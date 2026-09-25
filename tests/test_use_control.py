"""use_control is the only function that touches the app, so it is the only
place the safety checks can be enforced -- and the only place worth testing them.
"""

import pytest

from interfaceai.decisions import ManualActionKind
from interfaceai.surface import Acted, ActionPolicy, NotAllowedError, Viewport, use_control


class FakeSurface:
    """Records what would have happened. No browser."""

    def __init__(self, width: int = 1280, height: int = 900) -> None:
        self.viewport = Viewport(width=width, height=height)
        self.calls: list[tuple] = []

    def left_click(self, x, y, modifiers=None):
        self.calls.append(("click", x, y))

    def type_text(self, text):
        self.calls.append(("type", text))

    def current_url(self):
        return "http://localhost:8080/parabank/index.htm"


def test_click_reaches_the_surface() -> None:
    s = FakeSurface()
    acted = use_control(s, 366, 314, ManualActionKind.CLICK)
    assert s.calls == [("click", 366, 314)]
    assert isinstance(acted, Acted)


def test_enter_text_clicks_then_types() -> None:
    s = FakeSurface()
    use_control(s, 366, 314, ManualActionKind.ENTER_TEXT, "john")
    assert s.calls == [("click", 366, 314), ("type", "john")]


def test_the_record_carries_a_length_never_the_value() -> None:
    """A run log that contains a typed password is a finding, not a log."""
    acted = use_control(FakeSurface(), 1, 1, ManualActionKind.ENTER_TEXT, "hunter2")
    assert acted.value_length == 7
    assert "hunter2" not in repr(acted)


def test_action_outside_the_policy_is_refused() -> None:
    policy = ActionPolicy(allowed_actions=frozenset({ManualActionKind.CLICK}))
    s = FakeSurface()
    with pytest.raises(NotAllowedError, match="not in the policy"):
        use_control(s, 1, 1, ManualActionKind.ENTER_TEXT, "x", policy=policy)
    assert s.calls == [], "nothing may reach the app after a refusal"


def test_forbidden_value_is_never_typed() -> None:
    policy = ActionPolicy(forbidden_values=frozenset({"622-11-9999"}))
    s = FakeSurface()
    with pytest.raises(NotAllowedError, match="forbidden"):
        use_control(s, 1, 1, ManualActionKind.ENTER_TEXT, "SSN 622-11-9999", policy=policy)
    assert s.calls == []


def test_irreversible_action_needs_confirmation() -> None:
    s = FakeSurface()
    with pytest.raises(NotAllowedError, match="not been confirmed"):
        use_control(s, 1, 1, ManualActionKind.CLICK, risky=True)
    assert s.calls == []
    use_control(s, 1, 1, ManualActionKind.CLICK, risky=True, confirmed=True)
    assert s.calls == [("click", 1, 1)]


@pytest.mark.parametrize("x,y", [(-1, 10), (10, -1), (1280, 10), (10, 900)])
def test_point_outside_the_viewport_is_refused(x: int, y: int) -> None:
    """A stale coordinate must not become a click somewhere arbitrary."""
    s = FakeSurface()
    with pytest.raises(NotAllowedError, match="outside the"):
        use_control(s, x, y, ManualActionKind.CLICK)
    assert s.calls == []


def test_enter_text_without_a_value_is_refused() -> None:
    s = FakeSurface()
    with pytest.raises(NotAllowedError, match="requires a value"):
        use_control(s, 1, 1, ManualActionKind.ENTER_TEXT)
    assert s.calls == []
