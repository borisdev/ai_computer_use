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
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

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
    validate_invocations,
)
from interfaceai.control_map_store import ControlMapMiss, ControlMapStore, MapKey, check_capability
from interfaceai.decisions import (
    AgentDecision,
    ManualActionKind,
    money_entered,
    needs_human_confirmation,
    validate_decision,
)
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
    ClickPoint,
    CropBox,
    LocatedControl,
    ResolveInput,
    VisionCall,
    locate_control,
)
from interfaceai.surface import (
    ActionPolicy,
    NotAllowedError,
    OffLoop,
    PlaywrightSurface,  # named ONLY at the composition root below
    Surface,
    use_control,
)
from interfaceai.table import Offset, PanelNotFound, extract_panel
from interfaceai.vocabulary import VOCABULARY, SlotType

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
    # The PROTOCOL, not the implementation. REPORT S4 claims "none of them
    # names a browser"; this line named one, which made the claim false and
    # the seam one annotation leakier than advertised. replay only ever calls
    # screenshot / wait / navigate / location, all of which Surface has.
    surface: Surface
    evidence: EvidenceWriter
    off: OffLoop | None
    vision: VisionCall | None
    policy: ActionPolicy
    confirm_risky: bool
    outputs: dict[str, str]
    done: list[str]
    operator: Operator | None = None
    owner: Owner = Owner.WORKER
    # What this tenant permits. None means no restriction.
    permitted: frozenset[str] | None = None
    # Capabilities this run invoked that declared an `establishes`
    # postcondition, so a lost one can be re-established.
    established: dict[str, Capability] = field(default_factory=dict)
    # Conditions already recovered from, so recovery is bounded to once each.
    recovered: list[str] = field(default_factory=list)
    library: dict[str, Capability] = field(default_factory=dict)
    stack: tuple[str, ...] = ()
    # One panel read serves every field taken from it. Cleared by any step
    # with side effects, because a click can change the table underneath.
    panel_cache: dict[str, object] = field(default_factory=dict)
    # Money amounts typed onto the CURRENT form, so an irreversible step can
    # be judged on what is about to be submitted. Cleared when the page moves.
    money_on_form: dict[str, Decimal] = field(default_factory=dict)


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
    confirm_money_above: Decimal | None = None,
    permitted: frozenset[str] | None = None,
    confirm_risky: bool = False,
    headless: bool = True,
    operator: Operator | None = None,
    requested_by: str = "cli",
    library: Mapping[str, Capability] | None = None,
) -> CapabilityResult:
    """Run an APPROVED capability. The production path an agent would trigger."""
    assert_replayable(capability)
    if library:
        # An invoke naming something absent, unapproved, version-drifted or
        # cyclic is an authoring fault -- catch it before a browser opens.
        validate_invocations(capability, library)

    evidence = EvidenceWriter(
        evidence_root, goal=capability.goal, model="replay/none", requested_by=requested_by
    )
    evidence.event(
        "replay_started",
        capability=capability.name,
        version=capability.version,
        inputs=sorted(inputs),
        target=capability.target.model_dump(),
    )

    def early(result: CapabilityResult) -> CapabilityResult:
        evidence.event("replay_finished", outcome=type(result).__name__, capability=capability.name)
        return result

    if permitted is not None and capability.name not in permitted:
        # A refusal by US, not by the application. Reported as a pre-flight
        # failure rather than a `BusinessOutcome`, because a business outcome
        # is the BANK's answer -- "no such member" -- and conflating our
        # guardrail with the application's verdict is the distinction this
        # result contract exists to keep.
        evidence.event("not_permitted", capability=capability.name, tenant=capability.target.tenant)
        return early(
            Failed(
                step_index=-1,
                step="pre-flight",
                expected=f"{capability.name} to be permitted for {capability.target.tenant}",
                observed=f"this tenant permits {sorted(permitted)}",
                evidence_dir=evidence.dir,
            )
        )

    faults = check_capability(capability, store)
    if faults:
        evidence.event("artifact_unrunnable", faults=faults)
        return early(
            Failed(
                step_index=-1,
                step="pre-flight",
                expected="every control recorded and grounded",
                observed="; ".join(faults),
                evidence_dir=evidence.dir,
            )
        )

    missing = [p.name for p in capability.params if p.required and p.name not in inputs]
    if missing:
        return early(
            Failed(
                step_index=-1,
                step="pre-flight",
                expected=f"inputs for {missing}",
                observed="not supplied",
                evidence_dir=evidence.dir,
            )
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
            policy=ActionPolicy(
                forbidden_values=forbidden_values,
                confirm_money_above=confirm_money_above,
            ),
            confirm_risky=confirm_risky,
            outputs={},
            done=[],
            operator=operator,
            permitted=permitted,
            library=dict(library or {}),
            stack=(capability.name,),
        )
        return _finish(ctx, _run(ctx))


# ---------------------------------------------------------------------------


def _finish(ctx: _Ctx, result: CapabilityResult) -> CapabilityResult:
    """Record HOW the run ended, always.

    Without this a `NeedsOperator` with no operator attached wrote no terminal
    event at all, so the evidence said nothing about the outcome and anything
    reading the trace back had to guess -- `status` reported it as
    "incomplete", which reads like a crash.

    A run's own log should state its verdict rather than leave it inferable.

    It is also where an escalation picks up its screenshot. 3.6 asks that an
    intervention request carry "the current state or screenshot", and
    `NeedsOperator` has always had the field -- but only 2 of its 19
    construction sites filled it, so most escalations reached a human with no
    picture of what stopped them. Attaching it at the single exit point rather
    than at seventeen call sites is the same chokepoint argument `use_control`
    rests on: one place to get right, one place to test.
    """
    if isinstance(result, NeedsOperator) and result.frame is None:
        try:
            result = replace(
                result,
                frame=ctx.evidence.frame(
                    ctx.surface.screenshot(), f"{result.step_index:02d}-stuck"
                ),
            )
        except Exception as exc:  # noqa: BLE001 -- a dead page must not mask the real reason
            ctx.evidence.event("stuck_frame_failed", why=str(exc))
    ctx.evidence.event(
        "replay_finished",
        outcome=type(result).__name__,
        capability=ctx.capability.name,
        recovered=list(ctx.recovered),
        frame=str(result.frame) if isinstance(result, NeedsOperator) else None,
    )
    return result


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


def _check_preconditions(ctx: _Ctx, *, when: str, step_index: int = -1) -> NeedsOperator | None:
    """Walk `capability.requires` at run ENTRY. Returns `NeedsOperator` if unmet.

    ⚠️ Entry only, and the `when` parameter is a scar. This was briefly also
    called from `_hand_over`, because REPORT.md claimed preconditions were
    "re-checked on resume" and they were not. Making the claim true broke every
    resume: `requires` holds ENTRY conditions -- `at_the_login_page` -- which
    are necessarily false once a run is mid-flow. See the comment in
    `_hand_over` for the full reasoning and issue #10 for the schema gap.
    """
    for precondition in ctx.capability.requires:
        try:
            control = _resolve(ctx, precondition.control)
        except ControlMapMiss as exc:
            return NeedsOperator(
                why=f"precondition {precondition.name!r} ({when}): {exc}",
                step_index=step_index,
                screen=precondition.control.screen,
                evidence_dir=ctx.evidence.dir,
                completed_steps=tuple(ctx.done),
            )
        present = _find(ctx, control).status == "matched"
        want = precondition.must == "present"
        ctx.evidence.event(
            "precondition",
            name=precondition.name,
            want=precondition.must,
            present=present,
            when=when,
        )
        if present is not want:
            return NeedsOperator(
                why=(
                    f"precondition {precondition.name!r} not met ({when}): "
                    f"{precondition.control.control_id} should be {precondition.must}. "
                    f"{precondition.why}"
                ),
                step_index=step_index,
                screen=precondition.control.screen,
                evidence_dir=ctx.evidence.dir,
                completed_steps=tuple(ctx.done),
            )
    return None


def _run(ctx: _Ctx) -> CapabilityResult:
    unmet = _check_preconditions(ctx, when="entry")
    if unmet is not None:
        return unmet

    n = 0
    while n < len(ctx.capability.steps):
        step = ctx.capability.steps[n]
        result = _step(ctx, n, step)
        if result is None:
            n += 1
            continue
        if isinstance(result, NeedsOperator):
            recovered = _try_recover(ctx, n, step)
            if recovered is not None:
                ctx.recovered.append(recovered)
                continue  # run the SAME step again, once

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


def _for_evidence(capability: Capability, output: str | None, value: str) -> str:
    """Mask a value that regulated data protection would not let us keep.

    ⛔ `value_length, never the value` WAS ONLY TRUE OF INPUTS. Typed secrets
    were redacted from the first commit; EXTRACTED outputs were written
    verbatim, so committed traces carried `"value": "$1231.10"` and the
    `outputs` map repeated it. REPORT.md and evidence/README.md both claimed
    otherwise, and issue #7 described the gap as "screenshots only". Found by
    Copilot on PR #5, against the committed evidence rather than the code.

    The rule now follows the VOCABULARY rather than a guess: a slot that is
    `sensitive`, or typed MONEY, is a balance or a credential and is masked to
    its shape. Everything else -- notably `account_id` -- stays readable,
    because evidence whose whole job is proving WHICH record was read must
    still name the record.

    ⚠️ A mask is not encryption and this is not a compliance control. It keeps
    regulated VALUES out of a file that gets committed to a public repository,
    which is the specific hazard here.
    """
    slot = next((o.slot for o in capability.returns if o.name == output), None)
    if slot is None or not VOCABULARY.has(slot):
        return value
    qualifier = VOCABULARY.qualifier(slot)
    if not (qualifier.sensitive or qualifier.type is SlotType.MONEY):
        return value
    return f"<{qualifier.type} redacted, {len(value)} chars>"


def _bracket(ctx: _Ctx, label: str) -> tuple[str, str]:
    """One edge of the window in which a human, not the worker, owns the page.

    Returns (url, frame path).

    WHY A BRACKET AND NOT A RECORDER. While the human has control they may act
    through the operator surface -- gated by `use_control`, recorded as
    `human_acted` -- or they may simply reach past it and click the visible
    browser, which we cannot see. So the per-action log is complete for one of
    those paths and blind to the other, and a log that is silently partial is
    worse than one that states its scope.

    Capturing both edges downgrades the claim to one that holds either way:
    not "here is what the human did" but "here is what the page looked like
    when we handed it over and when we got it back". `handoff_returned` also
    reports whether the URL moved, which is the cheapest evidence that
    something happened at all.

    Both edges are captured the same way, deliberately. `blocked.frame` already
    exists and is nearly identical to the opening shot, but it was taken when
    the step FAILED rather than when control transferred -- and a before/after
    pair sourced from two different moments is not a pair.
    """
    url = ctx.surface.location()
    frame = ctx.evidence.frame(ctx.surface.screenshot(), label)
    return url, str(frame)


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
    # The run's gate, not whatever the operator was constructed with. Imposed
    # here rather than trusted at construction, because the caller that builds
    # the operator (the CLI) does not know the policy -- replay does.
    ctx.operator.adopt_policy(ctx.policy)
    ctx.owner = Owner.HUMAN
    before_url, before_frame = _bracket(ctx, f"handoff-{n}-before")
    ctx.evidence.event(
        "handoff_requested",
        step=n,
        why=blocked.why,
        owner=str(ctx.owner),
        location=before_url,
        frame=before_frame,
    )

    resolution = ctx.operator.resolve(
        InterventionRequest(
            why=blocked.why,
            capability=ctx.capability.name,
            step_index=n,
            screen=blocked.screen,
            location=ctx.surface.location(),
            completed_steps=tuple(ctx.done),
            # ⛔ THIS WAS `blocked.frame`, WHICH IS None FOR 17 OF THE 19 PLACES
            # a NeedsOperator is built -- so the human arrived with no picture
            # of what stopped them, which is the one thing §3.6 names in its
            # list of context to carry.
            #
            # An earlier fix attached a frame in `_finish`. That is the EXIT,
            # reached long after the operator has already been handed this
            # request, so it fixed the trace and not the human. Found by
            # Copilot, PR #5. `before_frame` is the shot taken at the moment
            # control transferred, which is the one they want.
            frame=Path(before_frame) if before_frame else blocked.frame,
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
            location=action.location,
            value_length=action.value_length,
        )
    after_url, after_frame = _bracket(ctx, f"handoff-{n}-after")
    ctx.owner = Owner.WORKER
    ctx.evidence.event(
        "handoff_returned",
        step=n,
        resolution=str(resolution.resolution),
        human_actions=len(resolution.actions),
        owner=str(ctx.owner),
        location=after_url,
        frame=after_frame,
        location_changed=after_url != before_url,
    )

    if resolution.resolution is Resolution.ABORTED:
        return NeedsOperator(
            why=f"operator aborted at step {n}: {resolution.note or blocked.why}",
            step_index=n,
            screen=blocked.screen,
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    # ⛔ DO NOT RE-RUN `capability.requires` HERE. It was added on 2026-09-29
    # and reverted the same hour, because running it is what showed the idea
    # was wrong.
    #
    # `requires` holds ENTRY preconditions -- `at_the_login_page` for anything
    # that logs in. They are statements about where a run STARTS, so by the
    # time a handoff happens they are necessarily FALSE: you are mid-flow, past
    # the login screen. Re-checking them made `resume` impossible for every
    # capability in the library, always, with a message blaming the operator
    # for a page they were right to have left.
    #
    # The claim in REPORT.md -- "re-checked on resume" -- was false, and
    # evals/grade.py was right to catch it. The correct repair was to fix the
    # SENTENCE. What resume actually verifies is below, and it is the right
    # thing: the stopped step's own footing, with advance / retry / stay-paused
    # decided per verb, and an irreversible step never retried on a guess.
    #
    # The distinction the schema cannot express is ENTRY PRECONDITION versus
    # INVARIANT. Only an invariant is resume-checkable. Adding that flag is
    # issue #10; it is a real gap and not a wording problem.

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

    if step.verb is StepVerb.INVOKE:
        return _invoke(ctx, n, step)

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

    if step.verb is StepVerb.CLICK and step.row_key is not None and control.panel is not None:
        return _drill_into_row(ctx, n, step, control, label)

    # ENTER / CLICK / SELECT -- the only verbs with side effects.
    try:
        typed = _value(ctx, step.value)
    except KeyError as exc:
        return NeedsOperator(
            why=str(exc), step_index=n, screen=step.control.screen, evidence_dir=ctx.evidence.dir
        )

    # Remember what this step puts on the form. Typing an amount is harmless --
    # ParaBank's Find Transactions page has an `amount` field too -- so the
    # value is recorded and judged at the IRREVERSIBLE step, not here.
    amount = money_entered(step.slot, typed)
    if amount is not None:
        ctx.money_on_form[step.slot or "?"] = amount

    irreversible = step.risky or control.policy.irreversible
    if irreversible:
        # A TENANT policy outranks a RUN flag, and the order here is the whole
        # point. `--confirm-risky` is the caller saying "this run may do
        # irreversible things". It cannot answer "this bank requires a person
        # above $1,000", because that question was never addressed to the
        # caller -- so the threshold is checked FIRST and is not bypassable.
        #
        # Measured 2026-09-28: with the two collapsed into one condition, a
        # $25,000 loan against a $1,000 threshold replayed SUCCESS and
        # submitted, with no human. A blanket confirmation silently answered a
        # question about a specific amount.
        value_risk = needs_human_confirmation(
            ctx.money_on_form, above=ctx.policy.confirm_money_above
        )
        if value_risk or not ctx.confirm_risky:
            return NeedsOperator(
                why=value_risk or f"step {n} is irreversible and was not confirmed: {step.note}",
                step_index=n,
                screen=step.control.screen,
                evidence_dir=ctx.evidence.dir,
                completed_steps=tuple(ctx.done),
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

    try:
        acted = use_control(
            ctx.surface,
            found.point.x,
            found.point.y,
            _VERB_ACTION[step.verb],
            typed,
            policy=ctx.policy,
            risky=irreversible,
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
        location=acted.location,
    )
    ctx.done.append(label)
    ctx.panel_cache.clear()
    # ⛔ MONEY IS NOT CLEARED HERE, and the two deleted attempts say why.
    #
    #   cleared after every action   the form was empty by the time the submit
    #                                was judged, so the value rule never fired
    #   cleared on URL change        a multi-page flow -- enter the amount on
    #                                page 1, confirm on page 2 -- submits
    #                                against an empty form. The SAME bypass as
    #                                --confirm-risky, one page further along.
    #
    # Both were an attempt to avoid over-escalating: a Find Transactions
    # search types an `amount` too, and nobody wants a search to need a human.
    # But that was already solved by moving the check to the IRREVERSIBLE step
    # -- a search has none, so it is never judged at all.
    #
    # So an amount entered anywhere in this run is treated as still in play at
    # an irreversible step. The cost is over-escalation: search $5,000, then
    # do something irreversible, and a person is asked. That is the direction
    # to be wrong in. Under-escalating submitted $25,000 with nobody looking.
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
        "extracted",
        step=n,
        output=step.output,
        value=_for_evidence(ctx.capability, step.output, read.text.strip()),
        frame=str(frame),
    )
    ctx.done.append(label)
    return None


def _try_recover(ctx: _Ctx, n: int, step: Step) -> str | None:
    """Re-establish a lost postcondition, once, and only when it is safe.

    The brief asks that **recoverable conditions** be distinguished from
    business outcomes and hard failures. This is the one we can actually
    produce: a session dies mid-capability, and everything after it fails for a
    reason that has nothing to do with the step.

    Deterministic, and **no LLM is involved** -- the handoff bundle was explicit
    that deterministic replay must have no hidden model recovery. What decides
    is a declared postcondition and a locator:

        a capability was invoked and declared `establishes`
        that control is no longer on screen  -> what it established is gone
        re-invoke it ONCE, then retry the step

    Four refusals, each deliberate:

    - **Once per condition.** A second failure is not a flake.
    - **Never for an irreversible step.** A submission that silently succeeded
      and one that failed look identical; repeating one moves money twice.
    - **Only if the postcondition is genuinely unmet.** A step can fail for its
      own reasons, and re-logging-in would not help.
    - **Only if the child is still permitted** -- recovery must not reach a
      capability the tenant forbids. ⚠️ Defensive: with a STATIC allowlist
      this cannot fire, because a forbidden capability is refused at the
      first invoke and the run never reaches recovery. Kept because every
      other invoke applies the same check, and per-operator or time-boxed
      permissions would reach it.
    """
    if step.risky:
        return None
    for name, child in ctx.established.items():
        if name in ctx.recovered or child.establishes is None:
            continue
        if ctx.permitted is not None and name not in ctx.permitted:
            continue
        try:
            witness = _resolve(ctx, child.establishes)
        except ControlMapMiss:
            continue
        if _find(ctx, witness).status == "matched":
            continue  # still established; this failure is about something else

        condition = f"{child.establishes.control_id} gone -- {name} no longer holds"
        ctx.evidence.event("recovering", step=n, condition=condition, by=name)
        inner = replace(
            ctx,
            capability=child,
            inputs={},
            outputs={},
            done=[],
            stack=(*ctx.stack, child.name),
        )
        result = _run(inner)
        if not isinstance(result, Success):
            ctx.evidence.event("recovery_failed", step=n, by=name, result=type(result).__name__)
            return None
        if _find(ctx, witness).status != "matched":
            ctx.evidence.event("recovery_did_not_take", step=n, by=name)
            return None
        ctx.evidence.event("recovered", step=n, condition=condition, by=name)
        ctx.done.append(f"recover by re-invoking {name}")
        return condition
    return None


def _invoke(ctx: _Ctx, n: int, step: Step) -> CapabilityResult | None:
    """Run another capability in the SAME session, then carry its outputs up.

    Same surface, same browser, same evidence file — an invoked capability is
    not a subprocess, it is a section of this run. Its preconditions are
    checked, because that is what they are for.

    How a nested result maps, and each one is a deliberate choice:

        Success         its outputs merge into ours and we continue
        BusinessOutcome PROPAGATES unchanged. "No such member" is the caller's
                        answer whether it was discovered one level down or ten
        Failed          propagates, with the child's step named so the trace
                        does not dead-end at "invoke"
        NeedsOperator   propagates. A human resolves in the same live session,
                        so there is nothing to translate
    """
    assert step.invokes is not None
    child = ctx.library.get(step.invokes)
    if child is None:
        return Failed(
            step_index=n,
            step=f"invoke {step.invokes}",
            expected="a capability in the library",
            observed=f"library has {sorted(ctx.library)}",
            evidence_dir=ctx.evidence.dir,
        )
    if ctx.permitted is not None and step.invokes not in ctx.permitted:
        # ⛔ Checked at EVERY invoke, not only at the entry point. A permitted
        # capability must not be able to reach a forbidden one -- otherwise the
        # gate is a front door with the back door open.
        ctx.evidence.event("not_permitted", step=n, capability=step.invokes)
        return Failed(
            step_index=n,
            step=f"invoke {step.invokes}",
            expected=f"{step.invokes} to be permitted for {ctx.capability.target.tenant}",
            observed=f"this tenant permits {sorted(ctx.permitted)}",
            evidence_dir=ctx.evidence.dir,
        )
    if step.invokes in ctx.stack:
        return Failed(
            step_index=n,
            step=f"invoke {step.invokes}",
            expected="no cycle",
            observed=" -> ".join((*ctx.stack, step.invokes)),
            evidence_dir=ctx.evidence.dir,
        )

    try:
        bound = {b.param: _value(ctx, b.value) for b in step.bind}
    except KeyError as exc:
        return NeedsOperator(
            why=f"invoke {step.invokes}: {exc}",
            step_index=n,
            screen="-",
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    ctx.evidence.event(
        "invoke_started",
        step=n,
        capability=child.name,
        version=child.version,
        bound=sorted(bound),
    )
    inner = replace(
        ctx,
        capability=child,
        inputs={k: v for k, v in bound.items() if v is not None},
        outputs={},
        done=[],
        stack=(*ctx.stack, child.name),
    )
    result = _run(inner)
    ctx.evidence.event(
        "invoke_finished", step=n, capability=child.name, result=type(result).__name__
    )

    if not isinstance(result, Success):
        return result

    ctx.outputs.update(result.outputs)
    if child.establishes is not None:
        ctx.established[child.name] = child
    ctx.done.append(f"invoke {child.name} ({result.steps_run} steps)")
    ctx.done.extend(inner.done)
    return None


def _drill_into_row(
    ctx: _Ctx, n: int, step: Step, control: LocatedControl, label: str
) -> CapabilityResult | None:
    """Open the row whose key matches, by ARITHMETIC rather than by grounding.

    The defect this exists to avoid: grounding a row visually lands on the wrong
    one 3 times in 4, silently -- `status: ready`, a unique landmark, ~1.0 at
    replay, and a click on another customer's account
    (`docs/issues/0009`). Here the index comes from the panel read and the y
    from the measured row rhythm. No model is asked where the row is.

    The panel read is the SAME cached one the extract steps use, so opening a
    row after reading it costs no extra model call.
    """
    assert control.panel is not None and step.row_key is not None
    spec = control.panel
    if spec.key_click_dx is None:
        return Failed(
            step_index=n,
            step=label,
            expected=f"{control.id} to declare key_click_dx",
            observed="the panel is read-only; its rows cannot be opened",
            evidence_dir=ctx.evidence.dir,
        )

    found = _read_panel(ctx, n, step, control)
    if not isinstance(found, tuple):
        return found
    read, wanted = found

    pitch = read.rhythm.pitch if read.rhythm is not None else spec.row_pitch
    if pitch is None:
        return NeedsOperator(
            why=(
                f"{control.id} has no measurable row rhythm and declares no recorded "
                "row_pitch, so a row position cannot be computed"
            ),
            step_index=n,
            screen=step.control.screen if step.control else "?",
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )
    if read.rhythm is None:
        # A table that has shrunk to one row has no period to find. The
        # recorded pitch is a measurement, not a guess, and here it only
        # supplies the half-row centring -- index 0 sits at first_row_y
        # regardless.
        ctx.evidence.event(
            "pitch_from_record", step=n, control=control.id, pitch=pitch, rows=len(read.data.rows)
        )

    if read.misaligned:
        # Geometry and perception disagree about where the rows are. Reading a
        # value from the table is still fine -- the values came from the model.
        # CLICKING is not: the click point comes from the geometry, and the
        # geometry is what is in dispute.
        ctx.evidence.event(
            "geometry_disputed", step=n, control=control.id, faults=list(read.misaligned)
        )
        return NeedsOperator(
            why=(
                f"the row positions computed for {control.id} do not match what the "
                f"screen shows, so this row will not be clicked: {read.misaligned[0]}"
            ),
            step_index=n,
            screen=step.control.screen if step.control else "?",
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    keys = [_normalise(getattr(r, spec.key_column)) for r in read.data.rows]
    target = _normalise(str(wanted))
    if target not in keys:
        return not_found_outcome(
            f"no row where {spec.key_column} is {wanted!r}; the table holds {len(keys)}",
            len(ctx.done),
            ctx.evidence.dir,
        )
    if keys.count(target) > 1:
        return Failed(
            step_index=n,
            step=label,
            expected=f"one row where {spec.key_column} is {wanted!r}",
            observed=f"{keys.count(target)} rows matched",
            evidence_dir=ctx.evidence.dir,
        )

    index = keys.index(target)
    anchor = _find(ctx, control)
    if anchor.status != "matched" or anchor.point is None:
        return NeedsOperator(
            why=f"lost the panel anchor before clicking: {anchor.status}",
            step_index=n,
            screen=step.control.screen if step.control else "?",
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )
    y = read.first_row_y + index * pitch + pitch // 2
    point = ClickPoint(x=anchor.point.x + spec.key_click_dx, y=y)
    ctx.evidence.event(
        "row_resolved",
        step=n,
        control=control.id,
        key=wanted,
        index=index,
        pitch=pitch,
        x=point.x,
        y=point.y,
    )

    try:
        acted = use_control(
            ctx.surface,
            point.x,
            point.y,
            ManualActionKind.CLICK,
            None,
            policy=ctx.policy,
            risky=step.risky,
            confirmed=ctx.confirm_risky,
        )
    except NotAllowedError as exc:
        return NeedsOperator(
            why=f"guardrail refused the drilldown at step {n}: {exc}",
            step_index=n,
            screen=step.control.screen if step.control else "?",
            evidence_dir=ctx.evidence.dir,
            completed_steps=tuple(ctx.done),
        )

    ctx.evidence.event(
        "acted", step=n, control=control.id, action=str(acted.action), location=acted.location
    )
    ctx.done.append(label)
    # The page has changed, so any cached panel read is about the old screen.
    ctx.panel_cache.clear()
    ctx.surface.wait(1.0)
    return None


def _read_panel(
    ctx: _Ctx, n: int, step: Step, control: LocatedControl
) -> tuple[object, str | None] | CapabilityResult:
    """One panel read, shared by extraction and drilldown, cached per row key.

    Returns `(PanelRead, wanted)` or a result explaining why it could not.
    Reading the table twice would double the cost and -- worse -- could return
    two different readings of one screen, so a row can be extracted and then
    opened on the strength of a single call.
    """
    assert control.panel is not None and step.row_key is not None
    if ctx.vision is None or ctx.off is None:
        return Failed(
            step_index=n,
            step=f"{step.verb} {control.id}",
            expected="a reader for this panel",
            observed="no vision callable supplied to replay()",
            evidence_dir=ctx.evidence.dir,
        )

    spec = control.panel
    wanted = _value(ctx, step.row_key)
    cache_key = f"{control.id}:{wanted}"
    cached = ctx.panel_cache.get(cache_key)
    if cached is not None:
        ctx.evidence.event("panel_reused", step=n, control=control.id)
        return cached, wanted

    try:
        read = ctx.off.run(
            extract_panel(
                ctx.surface.screenshot(),
                control.locator,
                panel=Offset(dx=spec.dx, dy=spec.dy, width=spec.width, height=spec.height),
                key_column=Offset(
                    dx=spec.key_dx, dy=spec.key_dy, width=spec.key_width, height=spec.height
                ),
                columns=spec.columns,
                key_column_name=spec.key_column,
                vision=ctx.vision,
                row_pitch=spec.row_pitch,
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

    ctx.panel_cache[cache_key] = read
    ctx.evidence.event(
        "panel_read", step=n, control=control.id, rows=len(read.data.rows), wanted=wanted
    )
    return read, wanted


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
    assert control.panel is not None and step.field is not None
    spec = control.panel
    if step.field not in spec.columns:
        return Failed(
            step_index=n,
            step=label,
            expected=f"a column of {spec.columns}",
            observed=f"field={step.field!r}",
            evidence_dir=ctx.evidence.dir,
        )

    found = _read_panel(ctx, n, step, control)
    if not isinstance(found, tuple):
        return found
    read, wanted = found

    rows = read.data.rows

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
        "extracted",
        step=n,
        output=step.output,
        value=_for_evidence(ctx.capability, step.output, ctx.outputs[step.output]),
        via="panel",
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

    # Tagged with WHICH capability succeeded: an invoked one writes into the
    # same evidence file, so an untagged event makes a parent that failed
    # look successful to anything reading the trace back.
    ctx.evidence.event(
        "replay_succeeded",
        capability=ctx.capability.name,
        outputs={k: _for_evidence(ctx.capability, k, v) for k, v in ctx.outputs.items()},
    )
    return Success(
        outputs=dict(ctx.outputs),
        steps_run=len(ctx.done),
        evidence_dir=ctx.evidence.dir,
        recovered=tuple(ctx.recovered),
    )


def _normalise(text: str) -> str:
    """Compare what a person would call the same value.

    A screen prints `$1,231.10` where an artifact recorded `1231.10`, and a
    field label printed `Account Type:` reads back as `Account Type`. Comparing
    raw strings would report a violated checkpoint -- or a missing row -- for a
    correct read, which is the loudest possible false alarm.

    Deliberately narrow: currency symbols, thousands separators, and trailing
    punctuation that is typography rather than content. It does NOT fold
    whitespace inside the value or strip letters, because two labels that
    differ by a word are two labels.
    """
    return text.strip().lstrip("$").replace(",", "").rstrip(".:").strip().casefold()


def not_found_outcome(detail: str, steps: int, evidence_dir: Path | None) -> BusinessOutcome:
    """A legitimate negative answer, not an error. Assignment 3.3."""
    return BusinessOutcome(
        kind=BusinessOutcomeKind.RECORD_NOT_FOUND,
        detail=detail,
        steps_run=steps,
        evidence_dir=evidence_dir,
    )
