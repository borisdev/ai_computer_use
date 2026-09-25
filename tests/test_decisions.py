"""Offline tests for decision validation. No API key, no browser."""

import pytest

from interfaceai.decisions import (
    ACTIONS_BY_ROLE,
    AgentDecision,
    ManualActionKind,
    supported_actions,
    validate_decision,
)
from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    CropBox,
    ImageSize,
    LocatedControl,
    ScreenOutput,
    VisualLocator,
)

PNG = b"not-really-a-png"


def _locator() -> VisualLocator:
    return VisualLocator(
        template_png=PNG,
        reference_size=ImageSize(width=1280, height=900),
        reference_crop=CropBox(x=246, y=250, width=240, height=96),
        click_offset=ClickPoint(x=120, y=64),
    )


def _map() -> ScreenOutput:
    return ScreenOutput(
        screenshot_sha256="0" * 64,
        image_size=ImageSize(width=1280, height=900),
        controls=[
            LocatedControl(
                id="c001",
                label="Username",
                role=ControlRole.TEXTBOX,
                description="username field",
                status="ready",
                click_point=ClickPoint(x=366, y=314),
                locator=_locator(),
            ),
            LocatedControl(
                id="c002",
                label="Transfer Funds",
                role=ControlRole.LINK,
                description="nav link",
                status="ready",
                click_point=ClickPoint(x=183, y=335),
                locator=_locator(),
            ),
            LocatedControl(
                id="c003",
                label="Amount",
                role=ControlRole.TEXTBOX,
                description="never grounded",
                status="unresolved",
                reason="refinement exhausted",
            ),
        ],
    )


def _decide(control_id, action, value=None) -> AgentDecision:
    return AgentDecision(
        action=action,
        control_id=control_id,
        value=value,
        reason="test",
        post_action_expectation="test",
        confidence=1.0,
    )


def test_actions_are_derived_from_role_not_supplied() -> None:
    assert supported_actions(ControlRole.LINK) == [ManualActionKind.CLICK]
    assert supported_actions(ControlRole.TEXTBOX) == [ManualActionKind.ENTER_TEXT]
    assert supported_actions(ControlRole.UNKNOWN) == []


def test_every_role_has_an_entry() -> None:
    assert set(ACTIONS_BY_ROLE) == set(ControlRole)


def test_valid_decision_returns_the_control() -> None:
    control = validate_decision(_decide("c002", ManualActionKind.CLICK), _map())
    assert control.id == "c002"


def test_unknown_control_is_refused() -> None:
    with pytest.raises(KeyError):
        validate_decision(_decide("nope", ManualActionKind.CLICK), _map())


def test_unresolved_control_is_refused() -> None:
    """No grounded click point means there is no coordinate to act on."""
    with pytest.raises(ValueError, match="not ready"):
        validate_decision(_decide("c003", ManualActionKind.ENTER_TEXT, "x"), _map())


def test_action_not_supported_by_role_is_refused() -> None:
    """Typing into a link is a decision error, not a click that misses."""
    with pytest.raises(ValueError, match="not supported"):
        validate_decision(_decide("c002", ManualActionKind.ENTER_TEXT, "x"), _map())


def test_enter_text_without_a_value_is_refused() -> None:
    with pytest.raises(ValueError, match="requires a value"):
        validate_decision(_decide("c001", ManualActionKind.ENTER_TEXT), _map())
