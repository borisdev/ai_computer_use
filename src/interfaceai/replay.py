"""Deterministic replay: run an approved capability with no model deciding.

Assignment 3.3. Given an artifact and typed inputs, walk the recorded steps and
return one of `outcomes.CapabilityResult`.

    approved artifact + inputs
        -> preconditions -> [ locate -> validate -> use ]* -> extract
        -> checkpoints -> Success | BusinessOutcome | Failed | NeedsOperator

## What "no LLM in the decision loop" means here, precisely

**Nothing chooses an action.** The step order, the control, the value and the
checkpoint all come from the artifact. No model is consulted about what to do,
in what order, or whether to continue.

⚠️ **One model call remains, and only for READING.** An `extract` step has to
turn pixels into a value, and on a surface with no DOM there is no other way.
That is perception, not decision — and it is the half models are measured good
at (`docs/issues/0008`: 11/11 on a clean crop, against 6/11 when our own grid
overlay defaced the image). The distinction matters enough to be enforced: the
reader is handed a crop and a schema, never the goal, never the step list, and
never a choice.

A capability with no `extract` step replays with **zero** model calls.

## Every refusal is typed

The same chain discovery uses -- `locate_control` -> `validate_decision` ->
`use_control` -- so replay exercises the path discovery proved rather than a
parallel one. Each link refuses rather than guessing, and each refusal maps to a
result: a locator that cannot be trusted, a control the role forbids, an
irreversible step nobody confirmed, and a policy violation all become
`NeedsOperator`, because a human can resolve every one of them. A checkpoint
that reads the wrong value becomes `Failed`, because nobody can.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, create_model

from interfaceai.capability import (
    Capability,
    ControlRef,
    LiteralValue,
    ParamValue,
    SecretValue,
    Step,
    StepVerb,
    Value,
    assert_replayable,
)
from interfaceai.control_map_store import ControlMapMiss, ControlMapStore, MapKey, check_capability
from interfaceai.decisions import AgentDecision, ManualActionKind, validate_decision
from interfaceai.evidence import EvidenceWriter
from interfaceai.handoff import (
    InterventionRequest,
    Operator,
    Owner,
    Resolution,
)
from interfaceai.outcomes import (
    BusinessOutcome,
    BusinessOutcomeKind,
    CapabilityResult,
    Failed,
    NeedsOperator,
    Success,
)
from interfaceai.screenshot2controls import (
    CropBox,
    LocatedControl,
    ResolveInput,
    VisionCall,
    locate_control,
)
from interfaceai.surface import ActionPolicy, NotAllowedError, OffLoop, PlaywrightSurface
from interfaceai.table import Offset, PanelNotFound, extract_panel

_VERB_ACTION = {
    StepVerb.ENTER: ManualActionKind.ENTER_TEXT,
    StepVerb.CLICK: ManualActionKind.CLICK,
    StepVerb.SELECT: ManualActionKind.SELECT,
}

# A WAIT_FOR polls rather than sleeping, so a fast page costs nothing and a slow
# one is not a race. Chosen to exceed ParaBank's observed worst page load.
_WAIT_TIMEOUT_S = 10.0
_WAIT_POLL_S = 0.5


class ReadValue(BaseModel):
    """The only thing a model is asked during replay: what does this crop say."""

    text: str


@dataclass
class _Ctx:
    capability: Capability
    inputs: dict[str, str]
    secrets: dict[str, str]
    store: ControlMapStore
    surface: PlaywrightSurface
    evidence: EvidenceWriter
    off: OffLoop | None
    vision: VisionCall | None
    policy: ActionPolicy
    confirm_risky: bool
    outputs: dict[str, str]
    done: list[str]
    operator: Operator | None = None
    owner: Owner = Owner.WORKER


def replay(
    capability: Capability,
    inputs: dict[str, str],
    *,
    store: ControlMapStore,
    evidence_root: Path,
    secrets: dict[str, str] | None = None,
    vision: VisionCall | None = None,
    allowed_origins: tuple[str, ...] = (),
    forbidden_values: frozenset[str] = frozenset(),
    confirm_risky: bool = False,
    headless: bool = True,
    operator: Operator | None = None,
) -> CapabilityResult:
    """Run an APPROVED capability. The production path an agent would trigger."""
    assert_replayable(capability)

    evidence = EvidenceWriter(evidence_root, goal=capability.goal, model="replay/none")
    evidence.event(
        "replay_started",
        capability=capability.name,
        version=capability.version,
        inputs=sorted(inputs),
        target=capability.target.model_dump(),
    )

    faults = check_capability(capability, store)
    if faults:
        evidence.event("artifact_unrunnable", faults=faults)
        return Failed(
            step_index=-1,
            step="pre-flight",
            expected="every control recorded and grounded",
            observed="; ".join(faults),
            evidence_dir=evidence.dir,
        )

    missing = [p.name for p in capability.params if p.required and p.name not in inputs]
    if missing:
        return Failed(
            step_index=-1,
            step="pre-flight",
            expected=f"inputs for {missing}",
            observed="not supplied",
            evidence_dir=evidence.dir,
        )

    with (
        PlaywrightSurface(
            allowed_origins=allowed_origins or (capability.target.base_url,),
            headless=headless,
        ) as surface,
        OffLoop() as off,
    ):
        surface.navigate(f"{capability.target.base_url}/index.htm")
        ctx = _Ctx(
            capability=capability,
            inputs=inputs,
            secrets=secrets or {},
            store=store,
            surface=surface,
            evidence=evidence,
            off=off,
            vision=vision,
            policy=ActionPolicy(forbidden_values=forbidden_values),
            confirm_risky=confirm_risky,
            outputs={},
            done=[],
            operator=operator,
        )
        return _run(ctx)


# ---------------------------------------------------------------------------


def _resolve(ctx: _Ctx, ref: ControlRef) -> LocatedControl:
    key = MapKey(
        app=ctx.capability.target.app, tenant=ctx.capability.target.tenant, screen=ref.screen
    )
    return ctx.store.control(key, ref.control_id)


def _find(ctx: _Ctx, control: LocatedControl):
    assert control.locator is not None
    return locate_control(
        ResolveInput(screenshot_png=ctx.surface.screenshot(), locator=control.locator)
    )


def _value(ctx: _Ctx, value: Value | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, LiteralValue):
        return value.value
    if isinstance(value, ParamValue):
        return ctx.inputs[value.param]
    if isinstance(value, SecretValue):
        if value.input_ref not in ctx.secrets:
            raise KeyError(f"no secret bound for {value.input_ref!r}")
        return ctx.secrets[value.input_ref]
    raise TypeError(f"unhandled value kind {value!r}")  # pragma: no cover


def _run(ctx: _Ctx) -> CapabilityResult:
    for precondition in ctx.capability.requires:
        try:
            control = _resolve(ctx, precondition.control)
        except ControlMapMiss as exc:
            return NeedsOperator(
                why=f"precondition {precondition.name!r}: {exc}",
                step_index=-1,
                screen=precondition.control.screen,
                evidence_dir=ctx.evidence.dir,
            )
        present = _find(ctx, control).status == "matched"
        want = precondition.must == "present"
        ctx.evidence.event(
            "precondition", name=precondition.name, want=precondition.must, present=present
        )
        if present is not want:
            return NeedsOperator(
                why=(
                    f"precondition {precondition.name!r} not met: "
                    f"{precondition.control.control_id} should be {precondition.must}. "
                    f"{precondition.why}"
                ),
                step_index=-1,
                screen=precondition.control.screen,
                evidence_dir=ctx.evidence.dir,
            )

    n = 0
    while n < len(ctx.capability.steps):
        step = ctx.capability.steps[n]
        result = _step(ctx, n, step)
        if result is None:
            n += 1
            continue
        if not isinstance(result, NeedsOperator) or ctx.operator is None:
            return result

        verdict = _hand_over(ctx, n, step, result)
        if isinstance(verdict, NeedsOperator):
            return verdict
        if verdict == "advance":
            ctx.done.append(f"{step.verb} (completed by the operator)")
            n += 1
            continue
        # "retry": the precondition still holds and the action was safe to
        # repeat, so run the SAME step again rather than assuming it happened.
        continue

    return _checkpoints(ctx)


def _hand_over(ctx: _Ctx, n: int, step: Step, blocked: NeedsOperator) -> str | NeedsOperator:
    """Pause, give the human the live session, then VERIFY before resuming.

    Returns "advance", "retry", or a `NeedsOperator` meaning stay paused.

    The resume rule, and the order matters:

        the step's own target is now satisfied     -> advance past it
        the step is still safe to perform          -> retry it
        anything uncertain                         -> stay paused

    An irreversible step is never retried on the strength of "it looks like it
    did not happen" -- a submission that silently succeeded and a submission
    that failed can look identical, and repeating one moves money twice.
    """
    assert ctx.operator is not None
    ctx.owner = Owner.HUMAN
    ctx.evidence.event("handoff_requested", step=n, why=blocked.why, owner=str(ctx.owner))

    resolution = ctx.operator.resolve(
        InterventionRequest(
            why=blocked.why,
            capability=ctx.capability.name,
            step_index=n,
            screen=blocked.screen,
            url=ctx.surface.current_url(),
            completed_steps=tuple(ctx.done),
            frame=blocked.frame,
        ),
        ctx.surface,
    )
    for action in resolution.actions:
        ctx.evidence.event(
            "human_acted",
            step=n,
            action=str(action.action),
            x=action.x,
            y=action.y,
            url=action.url,
            value_length=action.value_length,
        )
    ctx.owner = Owner.WORKER
    ctx.evidence.event(
        "handoff_returned",
        step=n,
        resolution=str(resolution.resolution),
        human_actions=len(resolution.actions),
        owner=str(ctx.owner),
    )

    if resolution.resolution is Resolution.ABORTED:
        return NeedsOperator(
            why=f"operator aborted at step {n}: {resolution.note or blocked.why}",
            step_index=n,
            screen=blocked.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    if step.control is None:
        return "advance"

    try:
        control = _resolve(ctx, step.control)
    except ControlMapMiss:
        return NeedsOperator(
            why=f"after handoff, {step.control.control_id} is not in the control map",
            step_index=n,
            screen=blocked.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    reachable = _find(ctx, control).status == "matched"
    ctx.evidence.event("resume_check", step=n, control=control.id, reachable=reachable)

    if step.verb in (StepVerb.WAIT_FOR, StepVerb.EXTRACT):
        # These have no side effect, so "the target is there now" is the whole
        # question and repeating is free.
        if reachable:
            return "retry"
        return NeedsOperator(
            why=f"resumed, but {control.id} is still not on screen",
            step_index=n,
            screen=blocked.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    if step.risky or control.policy.irreversible:
        # Never blindly repeat an uncertain submission.
        return NeedsOperator(
            why=(
                f"step {n} is irreversible; its effect cannot be confirmed from the "
                "screen, so it will not be retried automatically"
            ),
            step_index=n,
            screen=blocked.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    if reachable:
        return "retry"
    # The control is gone and the step was reversible -- the likeliest reading
    # is that the operator performed it and the page moved on.
    return "advance"


def _step(ctx: _Ctx, n: int, step: Step) -> CapabilityResult | None:
    label = f"{step.verb} {step.control.control_id if step.control else ''}".strip()

    if step.verb is StepVerb.OBSERVE:
        frame = ctx.evidence.frame(ctx.surface.screenshot(), f"{n:02d}-observe")
        ctx.evidence.event("observed", step=n, frame=str(frame))
        ctx.done.append(label)
        return None

    assert step.control is not None
    control = _resolve(ctx, step.control)

    if step.verb is StepVerb.WAIT_FOR:
        deadline = time.monotonic() + _WAIT_TIMEOUT_S
        while time.monotonic() < deadline:
            if _find(ctx, control).status == "matched":
                ctx.evidence.event("waited", step=n, control=control.id)
                ctx.done.append(label)
                return None
            ctx.surface.wait(_WAIT_POLL_S)
        return NeedsOperator(
            why=f"{control.id} never appeared within {_WAIT_TIMEOUT_S}s",
            step_index=n,
            screen=step.control.screen,
            frame=ctx.evidence.frame(ctx.surface.screenshot(), f"{n:02d}-timeout"),
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    if step.verb is StepVerb.EXTRACT:
        return _extract(ctx, n, step, control, label)

    # ENTER / CLICK / SELECT -- the only verbs with side effects.
    try:
        typed = _value(ctx, step.value)
    except KeyError as exc:
        return NeedsOperator(
            why=str(exc), step_index=n, screen=step.control.screen, evidence_dir=ctx.evidence.dir
        )

    try:
        validate_decision(
            AgentDecision(
                action=_VERB_ACTION[step.verb],
                control_id=control.id,
                value=typed,
                reason=step.note,
                post_action_expectation="",
                confidence=1.0,
            ),
            ctx.store.get(
                MapKey(
                    app=ctx.capability.target.app,
                    tenant=ctx.capability.target.tenant,
                    screen=step.control.screen,
                )
            ),
            confirmed=ctx.confirm_risky,
        )
    except (KeyError, ValueError) as exc:
        return NeedsOperator(
            why=f"step {n} refused: {exc}",
            step_index=n,
            screen=step.control.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    if step.risky and not ctx.confirm_risky:
        return NeedsOperator(
            why=f"step {n} is marked irreversible and was not confirmed: {step.note}",
            step_index=n,
            screen=step.control.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    found = _find(ctx, control)
    if found.status != "matched" or found.point is None:
        return NeedsOperator(
            why=f"could not locate {control.id}: {found.status} ({found.reason})",
            step_index=n,
            screen=step.control.screen,
            frame=ctx.evidence.frame(ctx.surface.screenshot(), f"{n:02d}-{found.status}"),
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    from interfaceai.surface import use_control

    try:
        acted = use_control(
            ctx.surface,
            found.point.x,
            found.point.y,
            _VERB_ACTION[step.verb],
            typed,
            policy=ctx.policy,
            risky=step.risky,
            confirmed=ctx.confirm_risky,
        )
    except NotAllowedError as exc:
        return NeedsOperator(
            why=f"guardrail refused step {n}: {exc}",
            step_index=n,
            screen=step.control.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    ctx.evidence.event(
        "acted",
        step=n,
        control=control.id,
        action=str(acted.action),
        value_length=acted.value_length,
        score=found.score,
        url=acted.url,
    )
    ctx.done.append(label)
    ctx.surface.wait(1.0)
    return None


def _extract(
    ctx: _Ctx, n: int, step: Step, control: LocatedControl, label: str
) -> CapabilityResult | None:
    """Read one control's text off the LIVE screen. The only model call."""
    assert step.output is not None

    if control.panel is not None and step.row_key is not None:
        return _extract_from_panel(ctx, n, step, control, label)

    if ctx.vision is None or ctx.off is None:
        return Failed(
            step_index=n,
            step=label,
            expected=f"a reader for {step.output}",
            observed="no vision callable supplied to replay()",
            evidence_dir=ctx.evidence.dir,
        )

    found = _find(ctx, control)
    if found.status != "matched" or found.point is None or found.matched_crop is None:
        return NeedsOperator(
            why=f"cannot read {control.id}: {found.status} ({found.reason})",
            step_index=n,
            screen=step.control.screen if step.control else "?",
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    # Crop the control itself, not its landmark: the landmark deliberately
    # reaches beyond the control to stay unique, which would drag neighbouring
    # text into the read.
    box = CropBox(x=max(0, found.point.x - 60), y=max(0, found.point.y - 12), width=140, height=26)
    crop = _crop_png(ctx.surface.screenshot(), box)
    frame = ctx.evidence.frame(crop, f"{n:02d}-read-{step.output}")

    read = ctx.off.run(
        ctx.vision(
            prompt=(
                "This is a small crop of an application screen. Return the visible "
                "text exactly as printed. No commentary."
            ),
            image_png=crop,
            response_model=ReadValue,
        )
    )
    ctx.outputs[step.output] = read.text.strip()
    ctx.evidence.event(
        "extracted", step=n, output=step.output, value=read.text.strip(), frame=str(frame)
    )
    ctx.done.append(label)
    return None


def _extract_from_panel(
    ctx: _Ctx, n: int, step: Step, control: LocatedControl, label: str
) -> CapabilityResult | None:
    """Read a whole table in one call, then pick the row IN CODE.

    The parameter selects the row. No model is asked where account 13344 is --
    asking lands on the wrong record 3 times in 4 (`docs/issues/0009`), and the
    wrong record is indistinguishable from the right one.

    A row the caller asked for that simply is not in the table is a
    `BusinessOutcome`, not a failure. "No such member" is a legitimate answer
    and conflating it with a crash is the mistake the brief's glossary names.
    """
    assert control.panel is not None and step.row_key is not None and step.field is not None
    if ctx.vision is None or ctx.off is None:
        return Failed(
            step_index=n,
            step=label,
            expected=f"a reader for {step.output}",
            observed="no vision callable supplied to replay()",
            evidence_dir=ctx.evidence.dir,
        )

    spec = control.panel
    if step.field not in spec.columns:
        return Failed(
            step_index=n,
            step=label,
            expected=f"a column of {spec.columns}",
            observed=f"field={step.field!r}",
            evidence_dir=ctx.evidence.dir,
        )

    # The response schema is built from the panel's own declared columns, so a
    # panel that gains a column does not need code changed.
    row_model = create_model("PanelRow", **{c: (str, ...) for c in spec.columns})
    table_model = create_model("PanelRows", rows=(list[row_model], ...))

    try:
        read = ctx.off.run(
            extract_panel(
                ctx.surface.screenshot(),
                control.locator,
                panel=Offset(dx=spec.dx, dy=spec.dy, width=spec.width, height=spec.height),
                key_column=Offset(
                    dx=spec.key_dx, dy=spec.key_dy, width=spec.key_width, height=spec.height
                ),
                response_model=table_model,
                vision=ctx.vision,
                instruction=(
                    "This is a crop of a table from a banking application. Return every "
                    f"row with these fields, exactly as printed: {', '.join(spec.columns)}. "
                    "Do not invent rows."
                ),
            )
        )
    except PanelNotFound as exc:
        return NeedsOperator(
            why=f"panel {control.id}: {exc}",
            step_index=n,
            screen=step.control.screen if step.control else "?",
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    wanted = _value(ctx, step.row_key)
    rows = read.data.rows
    ctx.evidence.event("panel_read", step=n, control=control.id, rows=len(rows), wanted=wanted)

    matches = [
        r for r in rows if _normalise(getattr(r, spec.key_column)) == _normalise(str(wanted))
    ]
    if not matches:
        seen = [getattr(r, spec.key_column) for r in rows]
        ctx.evidence.event("row_not_found", step=n, wanted=wanted, seen=seen)
        return not_found_outcome(
            f"no row where {spec.key_column} is {wanted!r}; the table holds {len(rows)}",
            len(ctx.done),
            ctx.evidence.dir,
        )
    if len(matches) > 1:
        return Failed(
            step_index=n,
            step=label,
            expected=f"one row where {spec.key_column} is {wanted!r}",
            observed=f"{len(matches)} rows matched",
            evidence_dir=ctx.evidence.dir,
        )

    ctx.outputs[step.output] = getattr(matches[0], step.field)
    ctx.evidence.event(
        "extracted", step=n, output=step.output, value=ctx.outputs[step.output], via="panel"
    )
    ctx.done.append(label)
    return None


def _crop_png(png: bytes, box: CropBox) -> bytes:
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    crop = image.crop((box.x, box.y, box.x + box.width, box.y + box.height))
    buffer = io.BytesIO()
    crop.save(buffer, "PNG")
    return buffer.getvalue()


def _checkpoints(ctx: _Ctx) -> CapabilityResult:
    for checkpoint in ctx.capability.checkpoints:
        observed = ctx.outputs.get(checkpoint.output)
        expected = _value(ctx, checkpoint.expected)
        if observed is None:
            return Failed(
                step_index=-1,
                step=f"checkpoint on {checkpoint.output}",
                expected=str(expected),
                observed="the output was never extracted",
                evidence_dir=ctx.evidence.dir,
            )
        if _normalise(observed) != _normalise(str(expected)):
            ctx.evidence.event(
                "checkpoint_violated",
                output=checkpoint.output,
                expected=expected,
                observed=observed,
                why=checkpoint.why,
            )
            return Failed(
                step_index=-1,
                step=f"checkpoint on {checkpoint.output}",
                expected=str(expected),
                observed=observed,
                evidence_dir=ctx.evidence.dir,
            )

    ctx.evidence.event("replay_succeeded", outputs=ctx.outputs)
    return Success(
        outputs=dict(ctx.outputs), steps_run=len(ctx.done), evidence_dir=ctx.evidence.dir
    )


def _normalise(text: str) -> str:
    """Compare what a person would call the same value.

    A screen prints `$1,231.10` where an artifact recorded `1231.10`. Comparing
    raw strings would report a violated checkpoint for a correct read, which is
    the loudest possible false alarm.
    """
    return text.strip().lstrip("$").replace(",", "").rstrip(".").casefold()


def not_found_outcome(detail: str, steps: int, evidence_dir: Path | None) -> BusinessOutcome:
    """A legitimate negative answer, not an error. Assignment 3.3."""
    return BusinessOutcome(
        kind=BusinessOutcomeKind.RECORD_NOT_FOUND,
        detail=detail,
        steps_run=steps,
        evidence_dir=evidence_dir,
    )
