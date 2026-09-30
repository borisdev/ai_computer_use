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
    PanelSpec,
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
            LocatedControl(
                id="p001",
                label="Account",
                role=ControlRole.TABLE_CONTROL_PANEL,
                description="the accounts table; its rows are links",
                status="ready",
                click_point=ClickPoint(x=490, y=320),
                locator=_locator(),
                panel=_panel(key_click_dx=18),
            ),
            LocatedControl(
                id="p002",
                label="Account Details",
                role=ControlRole.TABLE_CONTROL_PANEL,
                description="a label/value block; its rows are text",
                status="ready",
                click_point=ClickPoint(x=495, y=290),
                locator=_locator(),
                panel=_panel(key_click_dx=None),
            ),
        ],
    )


def _panel(*, key_click_dx: int | None) -> PanelSpec:
    return PanelSpec(
        columns=("account_id", "balance"),
        key_column="account_id",
        dx=-22,
        dy=24,
        width=327,
        height=308,
        key_dx=2,
        key_dy=24,
        key_width=33,
        key_click_dx=key_click_dx,
        row_pitch=28,
    )


def _decide(control_id, action, value=None, row_key=None) -> AgentDecision:
    return AgentDecision(
        action=action,
        control_id=control_id,
        value=value,
        row_key=row_key,
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


# --------------------------------------------------------------------------
# A panel is read, or a ROW of it is opened by key. Nothing else.
# --------------------------------------------------------------------------


class TestPanel:
    def test_a_bare_click_on_a_panel_is_refused(self) -> None:
        """The anchor is a HEADING. Clicking it acts on nothing, and clicking a
        row by eye is `docs/issues/0009` — wrong record 3 times in 4."""
        with pytest.raises(ValueError, match="row_key"):
            validate_decision(_decide("p001", ManualActionKind.CLICK), _map())

    def test_typing_into_a_panel_is_refused(self) -> None:
        with pytest.raises(ValueError, match="never enter_text on the region"):
            validate_decision(_decide("p001", ManualActionKind.ENTER_TEXT, "x"), _map())

    def test_a_click_with_a_row_key_is_allowed(self) -> None:
        control = validate_decision(
            _decide("p001", ManualActionKind.CLICK, row_key="13344"), _map()
        )
        assert control.id == "p001"

    def test_a_read_only_panel_cannot_be_opened(self) -> None:
        """No `key_click_dx` means the cells are text, not links. Refusing here
        beats clicking a label and reporting success."""
        with pytest.raises(ValueError, match="read-only"):
            validate_decision(
                _decide("p002", ManualActionKind.CLICK, row_key="Account Type:"), _map()
            )

    def test_the_role_table_still_grants_a_panel_nothing(self) -> None:
        """The exception lives in `validate_decision`, not in `ACTIONS_BY_ROLE` —
        a panel supports no action on the REGION, and the table says so."""
        assert supported_actions(ControlRole.TABLE_CONTROL_PANEL) == []
