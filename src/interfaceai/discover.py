"""The goal-driven discovery loop (assignment 3.1), and what it emits (3.2).

An LLM drives the real surface once: observe the screen, decide one action, act,
repeat, until it says the goal is met or a stopping condition fires. The run is
recorded as a `Capability` draft plus the control maps it used, and those two
artifacts together are what replay consumes with no model deciding anything.

    goal + target
        -> navigate -> [ screenshot -> control map -> decide -> act ]*
        -> DiscoverySuccess(capability) | DiscoveryFailure | PassToOperator

The brief's own sketch names those three outcomes. `PassToOperator` is not an
error branch bolted on -- being stuck is a legitimate result (3.6), and the
model can return it directly.

## Two threads, and why

⛔ **Sync Playwright and `asyncio.run` cannot share a thread.** Measured again
2026-09-26: `asyncio.run() cannot be called from a running event loop` is raised
from inside a `PlaywrightSurface` block, because the sync API drives its own
loop in the calling thread.

The repo previously concluded from this that "capture and discovery must be
separate phases". **That conclusion was wrong** -- they only need separate
THREADS. Playwright stays on the main thread; every model call is submitted to a
one-worker pool that runs `asyncio.run` where no loop exists. Verified both
directions: the surface is still usable after a model call, and model calls
still work after a click. This is what lets the loop observe and decide in the
same pass instead of recording a trace and reasoning about it afterwards.

## Cost, and why a control map is built once per screen

Grounding every control on a screen costs ~20-25 model calls. Doing that per
STEP would be ruinous and pointless: the screen has not changed between two
actions on it. So a control map is built the first time a screen is seen, put
in the `ControlMapStore`, and reused -- by later steps, by later runs, and by
replay. After the first visit a step costs exactly one call: the decision.

The click point is still re-found with `locate_control` against the CURRENT
screenshot before every action, never read from the stored map. That is the
same path replay takes, so discovery exercises it rather than a shortcut.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field

from interfaceai.capability import (
    Capability,
    Checkpoint,
    ControlRef,
    LiteralValue,
    OutputSpec,
    ParamSpec,
    ParamValue,
    Precondition,
    SecretValue,
    Step,
    StepVerb,
    Target,
    Value,
)
from interfaceai.contracts import Contract
from interfaceai.control_map_store import (
    ControlMapMiss,
    ControlMapStore,
    MapKey,
    panel_containing,
    row_instead_of_panel,
)
from interfaceai.decisions import AgentDecision, ManualActionKind, validate_decision
from interfaceai.evidence import EvidenceWriter
from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    DiscoveryConfig,
    DiscoveryError,
    LocatedControl,
    ResolveInput,
    ScreenInput,
    ScreenOutput,
    VisionCall,
    extract_control_locators,
    locate_control,
)
from interfaceai.screenshot2panels import extract_panel_locators, merge_panels
from interfaceai.surface import (
    ActionPolicy,
    NotAllowedError,
    OffLoop,
    PlaywrightSurface,
    use_control,
)
from interfaceai.table import Offset, PanelNotFound, extract_panel, match_row
from interfaceai.vocabulary import VOCABULARY, SlotType

# TOGGLE is deliberately absent: ParaBank's flows need none, and `StepVerb` has
# no spelling for it, so admitting it would put an action in a run that the
# artifact cannot record. Add both together or neither.
DISCOVERY_ACTIONS = frozenset(
    {ManualActionKind.CLICK, ManualActionKind.ENTER_TEXT, ManualActionKind.SELECT}
)

# How many refusals the model may be handed back before the run ends. A refusal
# names what to fix, so one more attempt is worth a model call; a model that
# cannot fix it in two is not going to.
#
# ⚠️ Covers BOTH kinds: a draft the synthesiser refused, and a move the decision
# boundary refused. They fail at opposite ends of the run and the reasoning is
# identical -- the reason is in the model's hands, so give it the reason.
_MAX_MODEL_RETRIES = 2

_VERB_OF_ACTION = {
    ManualActionKind.CLICK: StepVerb.CLICK,
    ManualActionKind.ENTER_TEXT: StepVerb.ENTER,
    ManualActionKind.SELECT: StepVerb.SELECT,
}


# ---------------------------------------------------------------------------
# What the operator supplies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Parameter:
    """A value the operator declares as a PARAMETER before the run.

    ⚠️ A deliberate simplification. The brief's §8 stretch goal is inferring
    that `13344` in a goal is a parameter rather than a constant; we make the
    operator say so instead. That turns a guess into a fact, and the mechanism
    that replaces it later plugs in here without changing the artifact.
    """

    name: str
    slot: str
    value: str


@dataclass(frozen=True)
class SecretBinding:
    """A credential the model may USE and never SEE.

    The model is shown `input_ref` only and selects it by name. The value is
    substituted at the action layer, `use_control` records its length and not
    its content, and the artifact stores the ref. Assignment 3.4.
    """

    input_ref: str
    slot: str
    value: str


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


class Extracted(Contract):
    name: str
    value: str
    slot: str
    control_id: str
    # A TABLE_CONTROL_PANEL only. `row_key` is the value in the panel's key
    # column that identifies the row; `field` is the column to read from it. The
    # row is then selected IN CODE at replay -- nothing is ever asked where a row
    # is, which is what keeps `docs/issues/0009` off this path.
    row_key: str | None = None
    field: str | None = None


class NextMove(Contract):
    """One decision. Exactly one of act / finish / stuck."""

    kind: Literal["act", "finish", "stuck"]
    reason: str
    confidence: float = Field(ge=0, le=1)

    # kind == "act"
    control_id: str | None = None
    action: ManualActionKind | None = None
    value: str | None = None
    value_ref: str | None = None
    slot: str | None = None
    # A TABLE_CONTROL_PANEL only: open the ROW whose key column holds this value.
    # The position comes from a panel read and the measured pitch, so this is the
    # only way to reach a row -- nothing is ever asked where a row is.
    row_key: str | None = None
    # Risk is a property of the control: "Log In" and "Transfer" are both a
    # click. The model classifies; the loop refuses to execute without a
    # confirmation; the artifact carries it to replay.
    irreversible: bool = False

    # kind == "finish"
    outputs: list[Extracted] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# What the loop returns
# ---------------------------------------------------------------------------


@dataclass
class RecordedStep:
    screen: str
    control_id: str
    action: ManualActionKind
    slot: str | None
    value_source: Value | None
    risky: bool
    note: str
    # Set when the step opened a ROW of a panel. Becomes `Step.row_key`.
    row_key: Value | None = None


@dataclass
class DiscoverySuccess:
    capability: Capability
    steps: list[RecordedStep]
    evidence_dir: Path
    model_calls: int
    seconds: float


@dataclass
class DiscoveryFailure:
    reason: str
    step_index: int
    evidence_dir: Path
    steps: list[RecordedStep] = field(default_factory=list)


@dataclass
class PassToOperator:
    """3.6: the run stopped and a human is needed. Carries enough to act on.

    Not a failure. The distinction the brief draws is between an outcome the
    caller must hear about and a crash, and "a person has to look at this" is
    the former.
    """

    reason: str
    step_index: int
    screen: str
    screenshot: Path
    evidence_dir: Path
    steps: list[RecordedStep] = field(default_factory=list)


DiscoveryOutcome = DiscoverySuccess | DiscoveryFailure | PassToOperator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def screen_name(url: str) -> str:
    """`.../overview.htm` -> `overview`, `.../activity.htm?id=13344` -> `activity`.

    The record id is dropped on purpose: `activity.htm?id=:id` is ONE screen
    with many instances, and a control map keyed per account would be a map per
    account. This is §8's `/item/12345 -> /item/:id` in the one place it is
    cheap to do.
    """
    stem = Path(urlparse(url).path).stem or "index"
    safe = "".join(c if c.isalnum() else "_" for c in stem.lower()).strip("_")
    return safe or "index"


class _Caller:
    """Counts model calls and runs them off the Playwright thread (`OffLoop`)."""

    def __init__(self, vision: VisionCall, off: OffLoop) -> None:
        self._vision = vision
        self._off = off
        self.calls = 0

    def vision(self) -> VisionCall:
        async def counted(*, prompt: str, image_png: bytes, response_model):  # type: ignore[no-untyped-def]
            self.calls += 1
            return await self._vision(
                prompt=prompt, image_png=image_png, response_model=response_model
            )

        return counted  # type: ignore[return-value]

    def run(self, coro):  # type: ignore[no-untyped-def]
        return self._off.run(coro)


_DECIDE_PROMPT = """\
You are operating a legacy bank web application through screenshots. You cannot
see HTML. You act only by choosing one control from the list below.

GOAL: {goal}

CURRENT SCREEN: {screen}  ({url})

CONTROLS YOU MAY ACT ON (id | role | label -- description). Every control_id
you name, whether you are acting on it or reading a value from it, MUST be one
of these:
{controls}

{unusable}{panels}
WHAT HAS HAPPENED SO FAR:
{history}

PARAMETERS you may type (these are the caller's inputs):
{params}

SECRETS you may type. You are shown the NAME only and must never guess a value.
To use one, set `value_ref` to its name and leave `value` empty:
{secrets}

VOCABULARY -- when you type a value or extract one, name the slot it fills:
{vocabulary}

Choose ONE of:

  kind="act"     -- perform one action. Set control_id and action. For
                    enter_text/select also set `slot` and either `value` (a
                    literal or a parameter's value) or `value_ref` (a secret).
                    Set irreversible=true if the action moves money, submits an
                    application, or otherwise cannot be undone by navigating
                    away. Logging in is NOT irreversible.
  kind="finish"  -- the goal is met. `outputs` must be the FEWEST values that
                    prove it: the specific thing the goal asked to read, plus
                    at most one value identifying whose/which record you are
                    looking at. Do NOT enumerate everything on the screen -- a
                    capability that returns twenty values asserts twenty things
                    on every future replay. If the goal asks for no value at
                    all, return the single value that shows you arrived (a
                    name, a record id), not a list.
                    ⛔ If an output's control_id is a `table_control_panel` you
                    MUST also set `row_key` and `field` on that output. A panel
                    holds rows; without them there is no way to say WHICH row
                    and WHICH column the value came from, and the draft is
                    refused.
  kind="stuck"   -- you cannot proceed safely: the control you need is not
                    listed, the screen is unexpected, or you would be guessing.
                    Say so in `reason`. This is a legitimate answer and is
                    better than a wrong click.

Do not repeat an action already in the history unless the screen shows it did
not take effect.
"""


def _describe(control: LocatedControl) -> str:
    line = f"  {control.id} | {control.role} | {control.label or '(no label)'} -- {control.description}"
    if control.panel is None:
        return line
    spec = control.panel
    opens = "its rows can be opened" if spec.key_click_dx is not None else "read-only"
    return (
        f"{line}\n      columns: {', '.join(spec.columns)}"
        f" | key column: {spec.key_column} | {opens}"
        f"\n      to report a value from it, an output needs all three of: "
        f'control_id="{control.id}", row_key=<the {spec.key_column} of the row you mean>, '
        f"field=<one of {', '.join(spec.columns)}>"
    )


_PANEL_NOTE = """
A `table_control_panel` is a REGION OF REPEATED ROWS -- a table, a menu, a
label/value block -- and not something you click. You cannot act on one. To
report a value from one, use kind="finish" and give, for that output:
  control_id  the panel's id
  row_key     the value in its KEY COLUMN that picks the row you want
  field       which of that row's columns to read
The whole region is read in one pass and the row is then selected in code, so no
row is ever located by eye -- which is the only reason reading a table is safe
here.

An output that names a panel WITHOUT a row_key and a field is refused, so give
all three together: control_id, row_key, field.

To OPEN one of its rows -- only where the panel says its rows can be opened --
act with action="click", control_id=<the panel>, and row_key=<the value in its key
column>. Do not try to click a row any other way: the position is computed from
the panel read and the measured row spacing, and a row pointed at by eye lands on
the wrong record.
"""


def _render_controls(control_map: ScreenOutput) -> tuple[str, str, str]:
    ready = [c for c in control_map.controls if c.status == "ready"]
    blocked = [c for c in control_map.controls if c.status != "ready"]
    listed = "\n".join(_describe(c) for c in ready)
    note = ""
    if blocked:
        note = (
            "SEEN BUT NOT ACTIONABLE (discovery could not ground a click point; "
            "do not choose these):\n"
            + "\n".join(f"  {c.id} -- {c.reason}" for c in blocked)
            + "\n\n"
        )
    panels = _PANEL_NOTE if any(c.panel is not None for c in ready) else ""
    return listed or "  (none)", note, panels


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def discover(
    *,
    goal: str,
    name: str,
    target: Target,
    entry_point: str,
    vision: VisionCall,
    store: ControlMapStore,
    evidence_root: Path,
    params: tuple[Parameter, ...] = (),
    secrets: tuple[SecretBinding, ...] = (),
    max_steps: int = 12,
    timeout_seconds: float = 600,
    confirm_risky: bool = False,
    headless: bool = True,
    allowed_origins: tuple[str, ...] = (),
    requested_by: str = "cli",
    forbidden_values: frozenset[str] = frozenset(),
    config: DiscoveryConfig | None = None,
) -> DiscoveryOutcome:
    """Drive the surface until the goal is met, and record what worked."""
    started = time.monotonic()
    evidence = EvidenceWriter(evidence_root, goal=goal, requested_by=requested_by)
    evidence.event("discovery_config", target=target.model_dump(), max_steps=max_steps, name=name)

    policy = ActionPolicy(allowed_actions=DISCOVERY_ACTIONS, forbidden_values=forbidden_values)
    secret_by_ref = {s.input_ref: s for s in secrets}
    param_by_value = {p.value: p for p in params}
    recorded: list[RecordedStep] = []
    history: list[str] = []
    refusals = 0

    with OffLoop() as off:
        caller = _Caller(vision, off)
        counted_vision = caller.vision()

        with PlaywrightSurface(
            allowed_origins=allowed_origins or (entry_point,),
            headless=headless,
        ) as surface:
            surface.navigate(entry_point)

            for index in range(max_steps):
                if time.monotonic() - started > timeout_seconds:
                    evidence.event("stopped", why="timeout", step=index)
                    return DiscoveryFailure(
                        f"timed out after {timeout_seconds}s", index, evidence.dir, recorded
                    )

                png = surface.screenshot()
                url = surface.location()
                screen = screen_name(url)
                frame = evidence.frame(png, f"{index:02d}-{screen}")

                key = MapKey(app=target.app, tenant=target.tenant, screen=screen)
                try:
                    control_map = store.get(key)
                    evidence.event("control_map_reused", step=index, screen=screen)
                except ControlMapMiss:
                    evidence.event("control_map_building", step=index, screen=screen)
                    try:
                        control_map = caller.run(
                            extract_control_locators(
                                ScreenInput(screenshot_png=png),
                                vision=counted_vision,
                                config=config,
                            )
                        )
                    except DiscoveryError as exc:
                        evidence.event("control_map_failed", step=index, error=str(exc))
                        return DiscoveryFailure(
                            f"could not map screen {screen!r}: {exc}", index, evidence.dir, recorded
                        )
                    store.put(key, control_map)
                    evidence.event(
                        "control_map_built",
                        step=index,
                        screen=screen,
                        controls=len(control_map.controls),
                        ready=sum(1 for c in control_map.controls if c.status == "ready"),
                    )

                # ⛔ **Asked of every map, not only a fresh one.** Panels are
                # proposed on the SAME screenshot, by the same kind of pass, and
                # merged into the one map -- a panel IS a control
                # (`ControlRole.TABLE_CONTROL_PANEL`), so a second store would be a
                # second source of truth for one screen.
                #
                # `panels_scanned` is the fact this reads, and it exists because
                # `panels == []` cannot answer the question: a screen with no
                # repeated structure and a screen recorded BEFORE panel discovery
                # are spelled identically. Running the pass only on a cache MISS
                # meant every map already on disk stayed panel-less forever, so a
                # normal session on those screens could not produce a
                # panel-backed artifact at all (Copilot, #13).
                if not control_map.panels_scanned:
                    try:
                        panels = caller.run(
                            extract_panel_locators(
                                ScreenInput(screenshot_png=png),
                                vision=counted_vision,
                                config=config,
                            )
                        )
                    except DiscoveryError as exc:
                        evidence.event("panel_map_failed", step=index, error=str(exc))
                        return DiscoveryFailure(
                            f"could not read screen {screen!r} for panels: {exc}",
                            index,
                            evidence.dir,
                            recorded,
                        )
                    control_map = merge_panels(control_map, panels)
                    store.put(key, control_map)
                    evidence.event(
                        "panels_scanned",
                        step=index,
                        screen=screen,
                        panels=len(panels),
                        panels_ready=sum(1 for p in panels if p.status == "ready"),
                    )

                listed, unusable, panel_note = _render_controls(control_map)
                prompt = _DECIDE_PROMPT.format(
                    goal=goal,
                    screen=screen,
                    url=url,
                    controls=listed,
                    unusable=unusable,
                    panels=panel_note,
                    history="\n".join(f"  {h}" for h in history) or "  (nothing yet)",
                    params="\n".join(f"  {p.name} = {p.value}" for p in params) or "  (none)",
                    secrets="\n".join(f"  {s.input_ref}" for s in secrets) or "  (none)",
                    vocabulary=VOCABULARY.as_prompt_block(),
                )
                move = caller.run(
                    counted_vision(prompt=prompt, image_png=png, response_model=NextMove)
                )
                evidence.event(
                    "decided",
                    step=index,
                    # NOT `kind=` -- EvidenceWriter.event takes the event kind
                    # as its first positional parameter.
                    move=move.kind,
                    control_id=move.control_id,
                    action=move.action,
                    reason=move.reason,
                    confidence=move.confidence,
                    frame=str(frame),
                )

                if move.kind == "stuck":
                    return PassToOperator(move.reason, index, screen, frame, evidence.dir, recorded)

                if move.kind == "finish":
                    outcome = _synthesise(
                        name=name,
                        goal=goal,
                        target=target,
                        surface=surface,
                        recorded=recorded,
                        outputs=move.outputs,
                        params=params,
                        evidence=evidence,
                        store=store,
                    )
                    if isinstance(outcome, str):
                        # ⚠️ A refusal the model can act on is FEEDBACK, not a
                        # dead end. Measured twice: the first draft naming a
                        # panel omitted `row_key` and `field`, which is one line
                        # for the model to add and four wasted model calls to
                        # re-run. The refusal itself stays exactly as strict --
                        # it is handed back rather than relaxed, and a run that
                        # keeps producing unapprovable drafts still fails.
                        refusals += 1
                        evidence.event("draft_refused", step=index, why=outcome, attempt=refusals)
                        if refusals > _MAX_MODEL_RETRIES:
                            return DiscoveryFailure(outcome, index, evidence.dir, recorded)
                        history.append(f"finish was REFUSED and must be fixed: {outcome}")
                        continue
                    return DiscoverySuccess(
                        outcome, recorded, evidence.dir, caller.calls, time.monotonic() - started
                    )

                fault = _act(
                    move=move,
                    index=index,
                    screen=screen,
                    png=png,
                    control_map=control_map,
                    surface=surface,
                    caller=caller,
                    policy=policy,
                    secret_by_ref=secret_by_ref,
                    param_by_value=param_by_value,
                    confirm_risky=confirm_risky,
                    evidence=evidence,
                    recorded=recorded,
                    history=history,
                )
                if fault is not None:
                    # ⛔ Handed back rather than escalated, while the reason is
                    # something the model can act on. The case that forced this: the
                    # inventory grounds table rows as clickable controls, so a model
                    # offered `13344_link` takes it -- and ending the session there
                    # spends a full run to produce nothing, when the refusal names
                    # the panel to use instead.
                    refusals += 1
                    evidence.event("decision_refused", step=index, why=fault, attempt=refusals)
                    if refusals > _MAX_MODEL_RETRIES:
                        return PassToOperator(fault, index, screen, frame, evidence.dir, recorded)
                    history.append(f"that move was REFUSED and must be fixed: {fault}")
                    continue

            evidence.event("stopped", why="max_steps", step=max_steps)
            return DiscoveryFailure(
                f"reached max_steps={max_steps} without finishing",
                max_steps,
                evidence.dir,
                recorded,
            )


def _row_point(
    *,
    control: LocatedControl,
    wanted: str,
    png: bytes,
    anchor: ClickPoint,
    caller: _Caller,
    evidence: EvidenceWriter,
    index: int,
) -> tuple[ClickPoint | None, str | None]:
    """Where to click to open the row whose key is `wanted`, or why not.

    The same arithmetic `replay._drilldown_into_row` performs, and deliberately
    the same `table.match_row` underneath it: discovery and replay have to answer
    *which row is 13344* identically, or a recording means something different
    from its playback.

    ⛔ **Never grounded.** Asking a model where account 13344 is lands on the
    wrong row 3 times in 4, silently (`docs/issues/0009`). Here the index comes
    from the panel READ and the y from the measured pitch.

    ⚠️ A disputed geometry refuses to click. `misaligned` means the bands we drew
    did not line up with the rows the model saw, so the values are still
    trustworthy -- they came from the model -- and a position computed from that
    geometry is not. Reading is fine; clicking is not.
    """
    spec = control.panel
    assert spec is not None and control.locator is not None
    if not wanted:
        return None, f"{control.id} is a panel: opening a row needs a row_key"

    try:
        read = caller.run(
            extract_panel(
                png,
                control.locator,
                panel=Offset(dx=spec.dx, dy=spec.dy, width=spec.width, height=spec.height),
                key_column=Offset(
                    dx=spec.key_dx, dy=spec.key_dy, width=spec.key_width, height=spec.height
                ),
                columns=spec.columns,
                key_column_name=spec.key_column,
                vision=caller.vision(),
                row_pitch=spec.row_pitch,
            )
        )
    except PanelNotFound as exc:
        return None, f"panel {control.id}: {exc}"

    evidence.event(
        "panel_read",
        step=index,
        control=control.id,
        rows=len(read.data.rows),
        wanted=wanted,
        misaligned=list(read.misaligned),
    )
    if read.misaligned:
        return None, (
            f"the row positions computed for {control.id} do not match what the screen "
            f"shows, so this row will not be clicked: {read.misaligned[0]}"
        )

    match = match_row(read.data.rows, spec.key_column, wanted)
    if match.matched == 0:
        return None, (
            f"no row of {control.id} where {spec.key_column} is {wanted!r}; "
            f"the table holds {match.total}"
        )
    if match.index is None:
        return None, (
            f"{match.matched} rows of {control.id} have {spec.key_column} == {wanted!r}, "
            "so which one to open is not determined"
        )

    assert spec.key_click_dx is not None  # validate_decision refused a read-only panel
    try:
        point = read.point_for_row(match.index, anchor.x + spec.key_click_dx)
    except PanelNotFound as exc:
        return None, str(exc)
    evidence.event(
        "row_resolved",
        step=index,
        control=control.id,
        key=wanted,
        row=match.index,
        x=point.x,
        y=point.y,
    )
    return point, None


def _act(
    *,
    move: NextMove,
    index: int,
    screen: str,
    png: bytes,
    control_map: ScreenOutput,
    surface: PlaywrightSurface,
    caller: _Caller,
    policy: ActionPolicy,
    secret_by_ref: dict[str, SecretBinding],
    param_by_value: dict[str, Parameter],
    confirm_risky: bool,
    evidence: EvidenceWriter,
    recorded: list[RecordedStep],
    history: list[str],
) -> str | None:
    """Perform one action. Returns a reason to escalate, or None on success."""
    if move.control_id is None or move.action is None:
        return f"model chose kind=act without a control_id and action: {move.reason}"

    # The recorded value NEVER contains a secret; the typed one may.
    value_source: Value | None = None
    typed: str | None = None
    if move.value_ref is not None:
        secret = secret_by_ref.get(move.value_ref)
        if secret is None:
            return f"model asked for unknown secret {move.value_ref!r}"
        typed = secret.value
        value_source = SecretValue(input_ref=secret.input_ref)
    elif move.value is not None:
        typed = move.value
        param = param_by_value.get(move.value)
        value_source = ParamValue(param=param.name) if param else LiteralValue(value=move.value)

    try:
        control = validate_decision(
            AgentDecision(
                action=move.action,
                control_id=move.control_id,
                value=typed,
                row_key=move.row_key,
                reason=move.reason,
                post_action_expectation="",
                confidence=move.confidence,
            ),
            control_map,
        )
    except (KeyError, ValueError) as exc:
        return f"decision refused: {exc}"

    # ⛔ **A row is not a control you click, even when the map offers it as one.**
    # The inventory grounds `13344_link` and friends and they are `ready`, so the
    # model is shown them and will take one. `check_capability` refuses that in an
    # artifact; refusing it only THERE means a whole session ends in a draft nobody
    # can approve. Same geometry, same words, applied while it is still a decision
    # (Copilot, #13/#14).
    inside = panel_containing(control_map, control)
    if inside is not None:
        return f"decision refused: {row_instead_of_panel(inside, control)}"

    if move.irreversible and not confirm_risky:
        # 3.4: the risky class is handled conservatively. During a supervised
        # authoring run the conservative thing is to stop and ask a person,
        # which is also 3.6's escalation trigger.
        return (
            f"step {index} on {move.control_id!r} is irreversible and was not confirmed: "
            f"{move.reason}"
        )

    assert control.locator is not None  # `status == "ready"` guarantees it
    resolved = locate_control(ResolveInput(screenshot_png=png, locator=control.locator))
    if resolved.status != "matched" or resolved.point is None:
        # Never guess. `ambiguous` in particular means two candidates were
        # within the margin, which on an account list is two different records.
        return f"could not locate {move.control_id!r} on the live screen: {resolved.status} ({resolved.reason})"

    point = resolved.point
    row_key: Value | None = None
    if control.panel is not None:
        # The anchor is a HEADING. Clicking it would do nothing; the row is
        # reached by arithmetic from a panel read.
        point, why = _row_point(
            control=control,
            wanted=move.row_key or "",
            png=png,
            anchor=resolved.point,
            caller=caller,
            evidence=evidence,
            index=index,
        )
        if point is None:
            return why or f"could not resolve a row of {move.control_id!r}"
        param = param_by_value.get(move.row_key or "")
        row_key = ParamValue(param=param.name) if param else LiteralValue(value=move.row_key or "")

    try:
        acted = use_control(
            surface,
            point.x,
            point.y,
            move.action,
            typed,
            policy=policy,
            risky=move.irreversible,
            # Reaching here IS the confirmation: the loop refused above unless a
            # person passed --confirm-risky. `use_control` still enforces the
            # pairing, so the guard is not taken on trust from this call site.
            confirmed=confirm_risky,
        )
    except NotAllowedError as exc:
        evidence.event("refused", step=index, control=move.control_id, error=str(exc))
        return f"guardrail refused the action: {exc}"

    evidence.event(
        "acted",
        step=index,
        screen=screen,
        control=move.control_id,
        action=move.action,
        value_length=acted.value_length,
        x=acted.x,
        y=acted.y,
        location=acted.location,
        match_score=resolved.score,
        row_key=move.row_key,
    )
    recorded.append(
        RecordedStep(
            screen=screen,
            control_id=move.control_id,
            action=move.action,
            slot=move.slot,
            value_source=value_source,
            risky=move.irreversible,
            note=move.reason,
            row_key=row_key,
        )
    )
    history.append(f"{move.action} on {move.control_id} ({screen}) -- {move.reason}")
    surface.wait(1.0)
    return None


# ---------------------------------------------------------------------------
# Recording -> artifact
# ---------------------------------------------------------------------------


def _synthesise(
    *,
    name: str,
    goal: str,
    target: Target,
    surface: PlaywrightSurface,
    recorded: list[RecordedStep],
    outputs: list[Extracted],
    params: tuple[Parameter, ...],
    evidence: EvidenceWriter,
    store: ControlMapStore,
) -> Capability | str:
    """Turn the run into a draft artifact. Returns the reason on refusal.

    Refuses rather than emitting something unreviewable -- an artifact with no
    checkpoint would replay and report success without ever checking it reached
    the right record, which is the exact failure `docs/adr/0005` exists to stop.
    """
    if not recorded:
        return "the model finished without taking a single action"

    final_screen = screen_name(surface.location())
    steps: list[Step] = [
        Step(
            verb=_VERB_OF_ACTION[r.action],
            control=ControlRef(screen=r.screen, control_id=r.control_id),
            slot=r.slot,
            value=r.value_source,
            row_key=r.row_key,
            risky=r.risky,
            note=r.note or "recorded by discovery",
        )
        for r in recorded
    ]

    # One evidence frame of the screen every output is read from (3.5).
    steps.append(Step(verb=StepVerb.OBSERVE, note="evidence frame of the final screen"))

    # Refuse an output read from a control discovery never grounded. The model
    # sees the whole inventory and has named `unresolved` entries before, which
    # produces an artifact whose EXTRACT steps can never run. Failing closed is
    # affordable here: the control maps are already cached, so a re-run costs
    # decisions only, not another full mapping pass.
    final_key = MapKey(app=target.app, tenant=target.tenant, screen=final_screen)
    ungrounded = []
    read_from: dict[str, LocatedControl] = {}
    for out in outputs:
        try:
            control = store.control(final_key, out.control_id)
        except ControlMapMiss as exc:
            ungrounded.append(f"{out.name}: {exc}")
            continue
        if control.status != "ready":
            ungrounded.append(f"{out.name}: {out.control_id} is {control.status}")
        read_from[out.name] = control
    if ungrounded:
        return "outputs name controls that cannot be read: " + "; ".join(ungrounded)

    declared: list[OutputSpec] = []
    checkpoints: list[Checkpoint] = []
    by_value = {p.value: p for p in params}
    for out in outputs:
        if not VOCABULARY.has(out.slot):
            return f"model named output slot {out.slot!r}, which is not in the vocabulary"
        # A sensitive slot may be filled in from an input_ref and must never be
        # read back out. `validate_capability` refuses this too, but refusing it
        # only at the approval gate is the wrong place: discovery proposed
        # `extract username` on two runs out of two, so the draft would be
        # unapprovable every time and a reviewer would carry the diagnosis.
        # Refuse it where it is produced, and say what to do instead.
        if VOCABULARY.qualifier(out.slot).sensitive:
            return (
                f"model tried to extract into {out.slot!r}, which is sensitive; a secret "
                "can be filled in from an input_ref but never read back out"
            )
        # Reading from a panel is a different step shape, and refusing a
        # half-specified one HERE rather than at the approval gate is the same
        # rule as the sensitive-slot refusal above: a draft nobody can approve
        # leaves the diagnosis to a reviewer.
        row_key: Value | None = None
        control = read_from[out.name]
        if control.role is ControlRole.TABLE_CONTROL_PANEL:
            if control.panel is None or out.row_key is None or out.field is None:
                return (
                    f"{out.name} reads from the panel {out.control_id!r} without a row_key "
                    "and a field; a panel is read as rows, so which row and which column "
                    "have to be named"
                )
            if out.field not in control.panel.columns:
                return (
                    f"{out.name} reads column {out.field!r} of {out.control_id!r}, which "
                    f"holds {control.panel.columns}"
                )
            row_key = (
                ParamValue(param=by_value[out.row_key].name)
                if out.row_key in by_value
                else LiteralValue(value=out.row_key)
            )
        elif out.row_key is not None or out.field is not None:
            return (
                f"{out.name} names a row of {out.control_id!r}, which is not a panel; only "
                "a table_control_panel has rows"
            )

        declared.append(OutputSpec(name=out.name, slot=out.slot))
        steps.append(
            Step(
                verb=StepVerb.EXTRACT,
                control=ControlRef(screen=final_screen, control_id=out.control_id),
                slot=out.slot,
                output=out.name,
                row_key=row_key,
                field=out.field if row_key is not None else None,
                note=f"read {out.name} from the final screen (observed {out.value!r})",
            )
        )
        # The heuristic, and it is deliberately conservative:
        #   value equals a declared parameter -> assert it, every replay
        #   a MONEY slot                      -> never assert; it is the answer
        #   anything else                     -> assert the observed literal
        # A wrong checkpoint from the third case is caught by the human review
        # the draft state exists to force -- which is cheaper than a capability
        # that asserts nothing.
        if out.value in by_value:
            checkpoints.append(
                Checkpoint(
                    output=out.name,
                    expected=ParamValue(param=by_value[out.value].name),
                    why="the record the caller asked for, re-read from the screen",
                )
            )
        elif VOCABULARY.qualifier(out.slot).type is not SlotType.MONEY:
            checkpoints.append(
                Checkpoint(
                    output=out.name,
                    expected=LiteralValue(value=out.value),
                    why=f"observed {out.value!r} at discovery; REVIEW whether it is invariant",
                )
            )

    if not checkpoints:
        return (
            "no checkpoint could be derived: every output was a money value or "
            "unmatched to a parameter, so replay would have nothing to verify"
        )

    # ⚠️ **A row_key counts.** A parameter can be used NOWHERE else: read the
    # balance of the row where account_id = the caller's id, and check a different
    # output against a literal. Leaving row_keys out dropped that parameter from
    # `params` and the draft then failed its own validation, since `row_key` named
    # something undeclared. Found by Copilot on #13.
    used = (
        {s.value.param for s in steps if s.value is not None and isinstance(s.value, ParamValue)}
        | {s.row_key.param for s in steps if isinstance(s.row_key, ParamValue)}
        | {c.expected.param for c in checkpoints if isinstance(c.expected, ParamValue)}
    )

    # The one precondition discovery can honestly infer: we must be where the
    # recording started. Anything richer would be invented.
    first = recorded[0]
    requires = (
        Precondition(
            name="at_the_recorded_starting_point",
            control=ControlRef(screen=first.screen, control_id=first.control_id),
            must="present",
            why=(
                "The first control the run acted on. If it is not on screen we are "
                "not where this recording began -- re-checked on resume after a "
                "human handoff, since the operator may have navigated away."
            ),
        ),
    )

    capability = Capability(
        name=name,
        version=1,
        goal=goal,
        vocabulary_version=VOCABULARY.version,
        target=target,
        viewport_width=surface.viewport.width,
        viewport_height=surface.viewport.height,
        params=tuple(ParamSpec(name=p.name, slot=p.slot) for p in params if p.name in used),
        returns=tuple(declared),
        requires=requires,
        steps=tuple(steps),
        checkpoints=tuple(checkpoints),
    )
    evidence.event(
        "artifact_drafted",
        name=name,
        steps=len(capability.steps),
        params=len(capability.params),
        returns=len(capability.returns),
        checkpoints=len(capability.checkpoints),
    )
    return capability
