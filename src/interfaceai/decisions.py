"""What to do to a control, and whether that action is even legal for it.

Perception (screenshot2controls) answers WHERE to click. This answers WHAT the
action is and refuses it before Playwright runs -- typing into a link is a
decision error, not a click that misses.

The role->actions table is derived in code rather than invented by the model:
a model cannot claim a control does something its role does not.

Split out of the original controlmap.py. The fractional BoundingBox /
UIScreenControl / ScreenManualControlMap types that lived alongside it were
retired -- measured at 45-80px error, 1/10 clicks landing inside the control.
Grounded click points from screenshot2controls replace them.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from interfaceai.screenshot2controls import ControlRole, LocatedControl, ScreenOutput
from interfaceai.vocabulary import VOCABULARY, SlotType


class ManualActionKind(StrEnum):
    CLICK = "click"
    ENTER_TEXT = "enter_text"
    SELECT = "select"
    TOGGLE = "toggle"


ACTIONS_BY_ROLE: dict[ControlRole, list[ManualActionKind]] = {
    ControlRole.TEXTBOX: [ManualActionKind.ENTER_TEXT],
    ControlRole.BUTTON: [ManualActionKind.CLICK],
    ControlRole.LINK: [ManualActionKind.CLICK],
    ControlRole.SELECT: [ManualActionKind.SELECT],
    ControlRole.CHECKBOX: [ManualActionKind.TOGGLE],
    ControlRole.RADIO: [ManualActionKind.TOGGLE],
    ControlRole.UNKNOWN: [],
    # A panel is read, not clicked. Extraction is a StepVerb, not a
    # ManualActionKind, because it has no side effect -- so `validate_decision`
    # refuses every manual action on a panel for free.
    ControlRole.TABLE_CONTROL_PANEL: [],
}


class AgentDecision(BaseModel):
    """
    The next action selected using the structured goal and control map.
    """

    model_config = ConfigDict(extra="forbid")

    action: ManualActionKind
    control_id: str

    # Used by ENTER_TEXT or SELECT.
    value: str | None = None

    reason: str
    post_action_expectation: str
    confidence: float = Field(ge=0, le=1)


def supported_actions(role: ControlRole) -> list[ManualActionKind]:
    """Derived in code, never supplied by the model."""
    return ACTIONS_BY_ROLE[role]


def get_control(control_map: ScreenOutput, control_id: str) -> LocatedControl:
    matches = [c for c in control_map.controls if c.id == control_id]
    if not matches:
        raise KeyError(f"Unknown control id: {control_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate control id: {control_id}")
    return matches[0]


def validate_decision(
    decision: AgentDecision,
    control_map: ScreenOutput,
    *,
    confirmed: bool = False,
) -> LocatedControl:
    """Validate a model's decision before Playwright executes it.

    Every refusal here is a decision error caught at the boundary, not a click
    that silently lands somewhere wrong.
    """
    control = get_control(control_map, decision.control_id)

    # `unresolved` means discovery never grounded a click point for it. Acting
    # on one would mean clicking a coordinate we do not have.
    if control.status != "ready":
        raise ValueError(f"Control is not ready: {control.id} ({control.reason})")

    if decision.action not in supported_actions(control.role):
        raise ValueError(f"{decision.action} is not supported by {control.id} ({control.role})")

    needs_value = {ManualActionKind.ENTER_TEXT, ManualActionKind.SELECT}
    if decision.action in needs_value and decision.value is None:
        raise ValueError(f"{decision.action} requires a value")

    # Irreversibility is recorded on the CONTROL, so every caller inherits it
    # and none of them has to remember. `use_control` enforces the same pairing
    # at the action layer; this catches it one step earlier, with a name.
    if control.policy.irreversible and not confirmed:
        raise ValueError(f"{control.id} is irreversible and this action was not confirmed")

    return control


def needs_human_confirmation(
    slot: str | None, value: str | None, *, above: Decimal | None
) -> str | None:
    """Why this step needs a person, or None if it does not.

    Risk that depends on the VALUE rather than on the control. `ControlPolicy.
    irreversible` covers "this control moves money"; this covers "this amount
    is one a person should see". Both end at the same enforcement point --
    `use_control` refuses a risky action that nobody confirmed -- so there is
    still exactly one place that can act.

    Only MONEY slots are considered, read from the controlled vocabulary. An
    account number that happens to parse as a number is not an amount, and
    `account_id` is deliberately a STRING there for the same reason.

    An unparseable money value returns a reason rather than passing. A field
    the system cannot read is not a field it may decide is small.
    """
    if above is None or slot is None or value is None:
        return None
    if not VOCABULARY.has(slot) or VOCABULARY.qualifier(slot).type is not SlotType.MONEY:
        return None

    cleaned = value.strip().replace("$", "").replace(",", "").replace(" ", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return (
            f"{slot}={value!r} is a money field this system cannot read, so it "
            "cannot be judged against the confirmation threshold"
        )
    if abs(amount) >= above:
        return (
            f"{slot} is {amount}, at or above the {above} threshold for this tenant; "
            "a person has to confirm it"
        )
    return None
