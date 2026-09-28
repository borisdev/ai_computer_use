"""Read the evidence we already write, and say what it means.

## Why this exists, in the brief's own words

Two requirements name it, and the framing matters — the same code is on-brief
or off-brief depending on which one it answers.

**§3.2 — it is GENERATED DOCUMENTATION.**

    "The artifact should be versioned and REVIEWABLE -- both a human reviewer
     and a calling agent should be able to understand what the capability does,
     what it needs, and what it returns. Design the schema deliberately; it's a
     focal point of the evaluation."

The agent half was done: typed params, typed returns, validated. The human half
was a 200-line JSON file. This is the human half, and it is **generated from the
artifact** -- so it cannot drift from what actually replays, which is the whole
reason not to hand-draw one.

**§3.5 — it is the reading half of evidence.**

    "Produce enough evidence to understand and debug a run."

We were producing it and reading none of it: `trace.jsonl` plus a frame per
step, sitting on disk until something broke.

⚠️ **NOT a dashboard, and the distinction decides the scope.** Brief §7 does not
reward building infrastructure. A command that summarises files is generated
documentation; a web app with live updates is a dashboard. The operator console
(§3.6, where the brief itself says the operator UI may be mocked) is the only
part that serves a page, and it serves it to a *human taking control of a paused
run* -- not to a spectator.

**No new storage.** Everything here comes from `artifacts/*.json` and
`evidence/runs/*/trace.jsonl`, both of which exist already. If reading them
proves useful enough to want queries rather than a listing, SQLite is the next
step (issue #1) and this interface does not change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from interfaceai.capability import Approval, Capability, load_capability


@dataclass(frozen=True)
class ArtifactRow:
    name: str
    version: int
    approval: Approval
    params: tuple[str, ...]
    returns: tuple[str, ...]
    invokes: tuple[str, ...]
    steps: int
    path: Path

    @property
    def signature(self) -> str:
        args = ", ".join(self.params)
        out = ", ".join(self.returns) or "nothing"
        return f"{self.name}({args}) -> {out}"


@dataclass(frozen=True)
class RunRow:
    started: str
    kind: str  # discovery | replay
    capability: str
    outcome: str
    steps: int
    model_calls: int
    worst_score: float | None
    detail: str
    path: Path


def read_artifacts(root: Path) -> list[ArtifactRow]:
    """Every capability on disk. An approved copy hides the draft it came from.

    Both exist by design -- the draft is the reviewable deliverable, the
    approved one is what replay will run -- but listing both says nothing a
    reader needs and buries the ones that differ.
    """
    rows: list[ArtifactRow] = []
    for path in sorted(root.glob("*.json")):
        try:
            capability: Capability = load_capability(path)
        except (OSError, ValueError):
            continue  # a stale or hand-broken file is not a crash here
        rows.append(
            ArtifactRow(
                name=capability.name,
                version=capability.version,
                approval=capability.approval,
                params=tuple(p.name for p in capability.params),
                returns=tuple(o.name for o in capability.returns),
                invokes=tuple(s.invokes for s in capability.steps if s.invokes),
                steps=len(capability.steps),
                path=path,
            )
        )

    by_version: dict[tuple[str, int], ArtifactRow] = {}
    for row in rows:
        key = (row.name, row.version)
        if key not in by_version or row.approval is Approval.APPROVED:
            by_version[key] = row
    return [by_version[k] for k in sorted(by_version)]


# Read in order: the first match wins, so a terminal state beats the events
# that led to it. Written as data because the list grew three times while the
# executor did, and each time a missing entry showed as "incomplete" -- which is
# the worst reading, since it looks like a crash.
# How a replay ended, stated by the run itself. Preferred over every heuristic
# below, which exist for discovery runs and for traces written before this
# event did.
_OUTCOME_OF_RESULT = {
    "Success": "SUCCESS",
    "BusinessOutcome": "business_outcome",
    "Failed": "FAILED",
    "NeedsOperator": "needs_human",
}

_TERMINAL: tuple[tuple[str, str], ...] = (
    ("replay_succeeded", "SUCCESS"),
    ("row_not_found", "business_outcome"),
    ("checkpoint_violated", "FAILED"),
    ("not_permitted", "not_permitted"),
    ("artifact_unrunnable", "FAILED"),
    ("geometry_disputed", "needs_human"),
    ("handoff_requested", "needs_human"),
    ("artifact_drafted", "discovered"),
    ("control_map_failed", "FAILED"),
    ("stopped", "stopped"),
)


def _detail(event: dict) -> str:
    kind = event["event"]
    if kind == "row_not_found":
        return f"no row for {event.get('wanted')!r}"
    if kind == "checkpoint_violated":
        return f"{event.get('output')}: wanted {event.get('expected')!r}, saw {event.get('observed')!r}"
    if kind == "not_permitted":
        return f"{event.get('capability')} not permitted"
    if kind == "artifact_drafted":
        return f"{event.get('steps')} steps, {event.get('checkpoints')} checkpoints"
    if kind == "artifact_unrunnable":
        faults = event.get("faults") or []
        return f"{len(faults)} pre-flight fault(s)"
    for key in ("why", "reason", "faults"):
        if event.get(key):
            value = event[key]
            return str(value[0] if isinstance(value, list) else value)[:70]
    return ""


def _outcome_of(events: list[dict]) -> tuple[str, str]:
    """What happened, read off the trace rather than a status we wrote down.

    A run that crashed mid-way has no terminal event, and saying so is more
    honest than inferring success from the absence of a failure.
    """
    # ⚠️ An INVOKED capability writes into the same evidence file, so its
    # `replay_succeeded` would otherwise make a parent that failed look
    # successful. Only the outermost run's events describe the run.
    outer = next((e.get("capability") for e in events if e["event"] == "replay_started"), None)

    by_kind: dict[str, dict] = {}
    for event in events:
        if (
            event["event"] == "replay_succeeded"
            and outer is not None
            and event.get("capability") not in (None, outer)
        ):
            continue
        by_kind.setdefault(event["event"], event)

    finished = by_kind.get("replay_finished")
    if finished is not None:
        outcome = _OUTCOME_OF_RESULT.get(str(finished.get("outcome")), "incomplete")
        recovered = finished.get("recovered") or []
        if recovered:
            return outcome, f"recovered: {recovered[0]}"
        for kind, _ in _TERMINAL:
            if kind in by_kind and kind != "replay_succeeded":
                return outcome, _detail(by_kind[kind])
        return outcome, ""

    for kind, outcome in _TERMINAL:
        if kind in by_kind:
            detail = _detail(by_kind[kind])
            # A run that survived something must not read like one that had a
            # clear path -- the same rule the CLI follows.
            if outcome == "SUCCESS" and "recovered" in by_kind:
                detail = f"recovered: {by_kind['recovered'].get('condition', '')}"
            return outcome, detail
    return "incomplete", "no terminal event -- the run did not finish"


def read_runs(root: Path) -> list[RunRow]:
    rows: list[RunRow] = []
    for directory in sorted(root.glob("*/"), reverse=True):
        trace = directory / "trace.jsonl"
        if not trace.exists():
            continue
        events = []
        for line in trace.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        if not events:
            continue

        start = events[0]
        kind = "replay" if any(e["event"] == "replay_started" for e in events) else "discovery"
        capability = next(
            (
                e.get("capability") or e.get("name")
                for e in events
                if e["event"] in ("replay_started", "discovery_config", "artifact_drafted")
            ),
            "?",
        )
        outcome, detail = _outcome_of(events)
        scores = [
            e["score"]
            for e in events
            if e["event"] == "acted" and isinstance(e.get("score"), int | float)
        ]
        rows.append(
            RunRow(
                started=str(start.get("ts", ""))[:19].replace("T", " "),
                kind=kind,
                capability=str(capability),
                outcome=outcome,
                steps=sum(1 for e in events if e["event"] in ("acted", "extracted", "waited")),
                model_calls=sum(
                    1
                    for e in events
                    if e["event"] in ("control_map_built", "decided", "panel_read", "extracted")
                ),
                worst_score=min(scores) if scores else None,
                detail=detail,
                path=directory,
            )
        )
    return rows


def as_markdown(artifacts: list[ArtifactRow], runs: list[RunRow], limit: int = 20) -> str:
    """A committable page. GENERATED -- never hand-edited.

    Read from the artifacts and the evidence, so it cannot make a claim the
    system does not. A hand-written status page is a claim that stops being
    true the moment anything changes, and nothing tells you.
    """
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    approved = sum(1 for a in artifacts if a.approval is Approval.APPROVED)
    out = [
        "# System status",
        "",
        "> **Generated** by `interfaceai status --markdown docs/status.md`.",
        f"> Do not edit by hand. Last run {now}.",
        "",
        f"{len(artifacts)} capabilities ({approved} approved) · {len(runs)} recorded runs.",
        "",
        "## Capabilities",
        "",
        "`invokes` is composition — a capability calling another, version pinned.",
        "",
        "| capability | v | approval | signature | invokes | steps |",
        "|---|---|---|---|---|---|",
    ]
    for a in artifacts:
        mark = "✅ approved" if a.approval is Approval.APPROVED else "draft"
        out.append(
            f"| `{a.name}` | {a.version} | {mark} | `{a.signature}` | "
            f"{', '.join(f'`{i}`' for i in a.invokes) or '—'} | {a.steps} |"
        )

    out += [
        "",
        f"## Runs (most recent {limit})",
        "",
        "Outcomes are the four of `outcomes.CapabilityResult`, read from each run's",
        "own `replay_finished` event rather than inferred. `recovered` means the run",
        "hit a condition and handled it — it succeeded, and it survived something.",
        "",
        "| when | kind | capability | outcome | steps | model calls | worst match | detail |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in runs[:limit]:
        score = f"{r.worst_score:.4f}" if r.worst_score is not None else "—"
        out.append(
            f"| {r.started} | {r.kind} | `{r.capability}` | **{r.outcome}** | {r.steps} | "
            f"{r.model_calls} | {score} | {r.detail} |"
        )
    return "\n".join(out) + "\n"


def as_mermaid(capability: Capability) -> str:
    """A capability's steps as a flowchart, READ FROM THE ARTIFACT.

    A hand-drawn diagram is a claim about the artifact that stops being true the
    moment the artifact changes, and nothing tells you. This one cannot drift.

    ⚠️ This draws THE CAPABILITY, not the executor. The engine's own two flows —
    discovery's loop and replay's walk — are a different picture and live in
    `docs/flows.md`. Conflating them would produce a diagram that looks like a
    capability and is not one.
    """
    lines = [
        "```mermaid",
        "flowchart TD",
        f'    start(["{capability.name} v{capability.version}"])',
    ]
    previous = "start"
    for n, step in enumerate(capability.steps):
        node = f"n{n}"
        if step.invokes:
            shape = f'{node}[["invoke {step.invokes} v{step.invokes_version}"]]'
        elif step.control is not None:
            label = f"{step.verb} {step.control.control_id}"
            if step.row_key is not None:
                label += " (by row)"
            shape = f'{node}["{label}"]'
        else:
            shape = f'{node}["{step.verb}"]'
        lines.append(f"    {shape}")
        lines.append(f"    {previous} --> {node}")
        previous = node

    for n, check in enumerate(capability.checkpoints):
        node = f"chk{n}"
        lines.append(f'    {node}{{{{"{check.output} == expected?"}}}}')
        lines.append(f"    {previous} --> {node}")
        previous = node

    lines.append('    done(["Success"])')
    lines.append(f"    {previous} --> done")
    lines.append("```")
    return "\n".join(lines)
