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

from interfaceai.capability import Approval, Capability, StepVerb, load_capability
from interfaceai.vocabulary import VOCABULARY


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


def language_as_mermaid() -> str:
    """The controlled language, GENERATED from the types that enforce it.

    Boris asked whether the language should be shown explicitly. It should, and
    it should be drawn from `VOCABULARY`, `ControlRole`, `StepVerb` and
    `ACTIONS_BY_ROLE` rather than transcribed — a hand-drawn picture of a
    vocabulary is a claim that goes stale the first time someone adds a term.

    Three axes, and the interesting part is where they DO NOT connect:
    `table_control_panel` and `unknown` have no permitted action at all, which
    is the geometric guard and the grounding refusal expressed as a gap in the
    diagram rather than as a paragraph.
    """
    from interfaceai.capability import StepVerb
    from interfaceai.decisions import ACTIONS_BY_ROLE
    from interfaceai.screenshot2controls import ControlRole
    from interfaceai.vocabulary import VOCABULARY

    lines = [
        "flowchart LR",
        '  subgraph VERBS["what a STEP can do"]',
        "    direction TB",
    ]
    for verb in StepVerb:
        lines.append(f'    V_{verb.name}["{verb.value}"]')
    lines += ["  end", '  subgraph ROLES["what a CONTROL can be"]', "    direction TB"]
    for role in ControlRole:
        acts = ACTIONS_BY_ROLE.get(role, [])
        label = role.value if acts else f"{role.value}<br/><i>no action permitted</i>"
        lines.append(f'    R_{role.name}["{label}"]')
    lines += ["  end", '  subgraph SLOTS["what a VALUE can mean"]', "    direction TB"]
    for kind in sorted({str(q.type) for q in VOCABULARY.qualifiers}):
        names = [q.name for q in VOCABULARY.qualifiers if str(q.type) == kind]
        sensitive = [n for n in names if VOCABULARY.qualifier(n).sensitive]
        label = f"{kind} &middot; {len(names)}"
        if sensitive:
            label += f"<br/><i>sensitive: {', '.join(sensitive)}</i>"
        lines.append(f'    S_{kind.upper()}["{label}"]')
    lines.append("  end")

    for role, acts in ACTIONS_BY_ROLE.items():
        if not acts:
            continue
        for verb in StepVerb:
            if verb.name.lower() in {a.value.replace("enter_text", "enter") for a in acts}:
                lines.append(f"  V_{verb.name} --> R_{role.name}")
    lines.append("  V_EXTRACT --> R_TABLE_CONTROL_PANEL")
    lines.append("  V_ENTER --> S_STRING")
    lines.append("  V_EXTRACT --> S_MONEY")
    lines.append("  classDef dead stroke-dasharray: 4 3")
    dead = [f"R_{r.name}" for r in ControlRole if not ACTIONS_BY_ROLE.get(r)]
    if dead:
        lines.append(f"  class {','.join(dead)} dead")
    return "\n".join(lines)


def as_mermaid(capability: Capability) -> str:
    """A capability as a flowchart, READ FROM THE ARTIFACT.

    A hand-drawn diagram is a claim about the artifact that stops being true the
    moment the artifact changes, and nothing tells you. This one cannot drift.

    ⚠️ This draws THE CAPABILITY, not the executor. The engine's own two flows —
    discovery's loop and replay's walk — are a different picture and live in
    `docs/flows.md`. Conflating them would produce a diagram that looks like a
    capability and is not one.

    SHAPE AND COLOUR ARE THE LANGUAGE, not decoration. A reader should be able
    to tell what a step does without reading its label:

        [[ invoke ]]     subroutine   another capability, in the same session
        [  enter   ]     rectangle    writes into the page
        (  click   )     rounded      acts on a control
        [/ extract /]    slanted      takes a value OUT
        >  wait_for      flag         looks, changes nothing
        {{ checkpoint }} hexagon      the only thing that turns Success into Failed

    ⛔ A RISKY STEP IS DRAWN RED AND THICK. It is the one thing in an artifact a
    reviewer must not miss, and "it says risky in the JSON" is not a reviewing
    strategy.

    Only the classes actually used are emitted — borrowed from nobsmed's causal
    map, where an unused `classDef` is a legend entry for a shape the reader
    will never find. The shape-per-kind idea is graph-builder-spec's.
    """
    palette = {
        # ⭐ COMPOSITION SHOULD LOOK LIKE COMPOSITION. An invoked capability is drawn
        # in the same green as the Success terminus, because it IS a capability --
        # a whole flow of its own, with its own checkpoint, running in this session.
        # Boris: "show off composition by using a green node capability within a
        # capability."
        "invoke": "fill:#bbf7d0,stroke:#15803d,stroke-width:3px,color:#14532d",
        "write": "fill:#fef3c7,stroke:#d97706,color:#92400e",
        "act": "fill:#fde68a,stroke:#d97706,stroke-width:2px,color:#92400e",
        "risky": "fill:#fee2e2,stroke:#dc2626,stroke-width:4px,color:#991b1b",
        "look": "fill:#f1f5f9,stroke:#94a3b8,color:#334155",
        "read": "fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#065f46",
        "check": "fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95",
        "good": "fill:#16a34a,stroke:#15803d,color:#ffffff",
        "stop": "fill:#f1f5f9,stroke:#94a3b8,color:#334155",
    }
    used: set[str] = set()

    def node(nid: str, shape: str, klass: str) -> str:
        used.add(klass)
        return f"    {nid}{shape}:::{klass}"

    sensitive = {q.name for q in VOCABULARY.qualifiers if q.sensitive}
    lines = [
        "```mermaid",
        "flowchart TD",
        node("start", f'(["<b>{capability.name}</b> v{capability.version}"])', "good"),
    ]
    previous = "start"
    for n, step in enumerate(capability.steps):
        nid = f"n{n}"
        verb = str(step.verb)
        target = step.control.control_id if step.control is not None else ""
        note = ""
        if step.slot in sensitive:
            note = "<br/><i>secret, input_ref only</i>"
        elif step.row_key is not None:
            note = "<br/><i>row picked in code</i>"

        if step.invokes:
            lines.append(
                node(nid, f'[["<b>invoke</b> {step.invokes} v{step.invokes_version}"]]', "invoke")
            )
        elif step.verb is StepVerb.EXTRACT:
            lines.append(
                node(nid, f'[/"<b>extract</b> {step.output}<br/>{target}{note}"/]', "read")
            )
        elif step.verb in (StepVerb.WAIT_FOR, StepVerb.OBSERVE):
            lines.append(node(nid, f'>"<b>{verb}</b> {target}"]', "look"))
        elif step.risky:
            lines.append(node(nid, f'("<b>{verb}</b> {target}<br/><i>irreversible</i>")', "risky"))
        elif step.verb is StepVerb.CLICK:
            lines.append(node(nid, f'("<b>click</b> {target}{note}")', "act"))
        else:
            lines.append(node(nid, f'["<b>{verb}</b> {target}{note}"]', "write"))
        lines.append(f"    {previous} --> {nid}")
        previous = nid

    for n, check in enumerate(capability.checkpoints):
        nid = f"chk{n}"
        lines.append(node(nid, f'{{{{"<b>checkpoint</b><br/>{check.output}"}}}}', "check"))
        lines.append(f"    {previous} --> {nid}")
        previous = nid

    lines.append(node("ok", '(["<b>Success</b>"])', "good"))
    if capability.checkpoints:
        lines.append(f"    {previous} -- holds --> ok")
        lines.append(node("bad", '(["Failed"])', "stop"))
        lines.append(f"    {previous} -- violated --> bad")
    else:
        lines.append(f"    {previous} --> ok")

    lines += [f"    classDef {k} {v};" for k, v in palette.items() if k in used]
    lines.append("```")
    return "\n".join(lines)
