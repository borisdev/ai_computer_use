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
    return rows


def _outcome_of(events: list[dict]) -> tuple[str, str]:
    """What happened, read off the trace rather than a status we wrote down.

    A run that crashed mid-way has no terminal event, and saying so is more
    honest than inferring success from the absence of a failure.
    """
    by_kind = {e["event"] for e in events}
    if "replay_succeeded" in by_kind:
        return "SUCCESS", ""
    if "row_not_found" in by_kind:
        e = next(x for x in events if x["event"] == "row_not_found")
        return "business_outcome", f"no row for {e.get('wanted')!r}"
    if "checkpoint_violated" in by_kind:
        e = next(x for x in events if x["event"] == "checkpoint_violated")
        return (
            "FAILED",
            f"{e.get('output')}: expected {e.get('expected')!r}, saw {e.get('observed')!r}",
        )
    if "handoff_requested" in by_kind:
        e = next(x for x in events if x["event"] == "handoff_requested")
        return "needs_human", str(e.get("why", ""))[:60]
    if "artifact_drafted" in by_kind:
        e = next(x for x in events if x["event"] == "artifact_drafted")
        return "discovered", f"{e.get('steps')} steps, {e.get('checkpoints')} checkpoints"
    if "stopped" in by_kind:
        e = next(x for x in events if x["event"] == "stopped")
        return "stopped", str(e.get("why", ""))
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
    """A committable page. Generated -- never hand-edited."""
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    out = [
        "# System status",
        "",
        f"Generated by `interfaceai status --markdown` at {now}. **Do not edit by hand.**",
        "",
        "## Capabilities",
        "",
        "| capability | v | approval | signature | steps | invokes |",
        "|---|---|---|---|---|---|",
    ]
    for a in artifacts:
        mark = "✅ approved" if a.approval is Approval.APPROVED else "draft"
        out.append(
            f"| `{a.name}` | {a.version} | {mark} | `{a.signature}` | {a.steps} | "
            f"{', '.join(f'`{i}`' for i in a.invokes) or '—'} |"
        )

    out += [
        "",
        f"## Runs (most recent {limit})",
        "",
        "| when | kind | capability | outcome | steps | model calls | worst score | detail |",
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
    """A capability's steps as a flowchart.

    Reads the artifact, so it cannot drift from what replays -- which is the
    whole reason not to hand-draw one (`docs/adr/0005`, and case-build's rule
    that a hand-written diagram is a claim that stops being true silently).
    """
    lines = ["```mermaid", "flowchart TD"]
    prior = "start([" + capability.name + "])"
    lines.append(f"    n0{prior}")
    for n, step in enumerate(capability.steps, start=1):
        if step.invokes:
            label = f"invoke {step.invokes} v{step.invokes_version}"
            shape = f'n{n}[["{label}"]]'
        elif step.control is not None:
            shape = f'n{n}["{step.verb} {step.control.control_id}"]'
        else:
            shape = f'n{n}["{step.verb}"]'
        lines.append(f"    {shape}")
        lines.append(f"    n{n - 1} --> n{n}")
    last = len(capability.steps)
    for c in capability.checkpoints:
        lines.append(f'    n{last} --> chk{c.output}{{"{c.output} == expected?"}}')
    lines.append("```")
    return "\n".join(lines)
