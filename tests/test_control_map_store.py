"""The store, and the authoring-time check it makes possible.

The interesting assertions are the refusals: a tenant miss that does not fall
back, a control recorded at the wrong viewport, and a step whose verb the
control's role does not accept.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from interfaceai import capabilities
from interfaceai.capability import (
    Capability,
    Checkpoint,
    ControlRef,
    OutputSpec,
    ParamSpec,
    ParamValue,
    SecretValue,
    Step,
    StepVerb,
    Target,
)
from interfaceai.control_map_store import (
    ControlMapMiss,
    ControlMapStore,
    MapKey,
    check_capability,
)
from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    CropBox,
    ImageSize,
    LocatedControl,
    ScreenInput,
    ScreenOutput,
    _make_locator,
    _png_bytes,
)
from interfaceai.vocabulary import VOCABULARY_VERSION


def _canvas(width: int = 1280, height: int = 900) -> Image.Image:
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 25), "Account Number", fill="black")
    d.rectangle((20, 45, 119, 64), outline="orange", width=2)
    return img


def _control(control_id: str, role: ControlRole, size: tuple[int, int]) -> LocatedControl:
    screen = ScreenInput(screenshot_png=_png_bytes(_canvas(*size)))
    locator = _make_locator(
        screen, CropBox(x=10, y=15, width=120, height=65), ClickPoint(x=70, y=55)
    )
    return LocatedControl(
        id=control_id,
        label=control_id.replace("_", " ").title(),
        role=role,
        description=f"the {control_id}",
        status="ready",
        click_point=ClickPoint(x=70, y=55),
        locator=locator,
    )


def _map(*controls: LocatedControl, size: tuple[int, int] = (1280, 900)) -> ScreenOutput:
    return ScreenOutput(
        screenshot_sha256="0" * 64,
        image_size=ImageSize(width=size[0], height=size[1]),
        controls=list(controls),
    )


@pytest.fixture
def store(tmp_path: Path) -> ControlMapStore:
    return ControlMapStore(tmp_path)


# --- round trip ------------------------------------------------------------


def test_a_map_survives_the_round_trip_with_its_templates(store: ControlMapStore) -> None:
    key = MapKey(app="parabank", tenant="baseline", screen="activity")
    original = _map(_control("balance_value", ControlRole.LINK, (1280, 900)))
    store.put(key, original)
    assert store.get(key) == original


def test_the_path_is_browsable_by_a_human(store: ControlMapStore) -> None:
    key = MapKey(app="parabank", tenant="baseline", screen="overview")
    path = store.put(key, _map())
    assert path == store.root / "parabank" / "baseline" / "overview.json"


# --- misses ----------------------------------------------------------------


def test_a_missing_screen_says_what_was_recorded(store: ControlMapStore) -> None:
    store.put(MapKey(app="parabank", tenant="baseline", screen="overview"), _map())
    with pytest.raises(ControlMapMiss, match="recorded screens: overview"):
        store.get(MapKey(app="parabank", tenant="baseline", screen="activity"))


def test_a_missing_control_lists_the_ones_that_are_there(store: ControlMapStore) -> None:
    key = MapKey(app="parabank", tenant="baseline", screen="overview")
    store.put(key, _map(_control("log_out_link", ControlRole.LINK, (1280, 900))))
    with pytest.raises(ControlMapMiss, match="log_out_link"):
        store.control(key, "account_link")


def test_a_tenant_miss_does_NOT_fall_back_to_another_tenant(store: ControlMapStore) -> None:
    """The whole reason tenant is in the key.

    A rebranded tenant's pixels differ, so serving tenant A's template to
    tenant B would click confidently in the wrong place. A miss must stay a
    miss.
    """
    store.put(
        MapKey(app="parabank", tenant="baseline", screen="overview"),
        _map(_control("log_out_link", ControlRole.LINK, (1280, 900))),
    )
    with pytest.raises(ControlMapMiss):
        store.control(MapKey(app="parabank", tenant="feature", screen="overview"), "log_out_link")


def test_a_key_cannot_escape_the_store_root() -> None:
    with pytest.raises(ValueError, match="safe path segment"):
        MapKey(app="parabank", tenant="../../etc", screen="overview")


def test_browsing_an_empty_store_is_empty_not_an_error(store: ControlMapStore) -> None:
    assert store.screens("parabank", "baseline") == []
    assert store.tenants("parabank") == []


# --- checking a capability against what was recorded -----------------------


def _probe(**overrides: object) -> Capability:
    base: dict[str, object] = {
        "name": "probe",
        "version": 1,
        "goal": "a capability used to test the control-map check",
        "vocabulary_version": VOCABULARY_VERSION,
        "target": Target(app="parabank", tenant="baseline", base_url="http://localhost:8080"),
        "viewport_width": 1280,
        "viewport_height": 900,
        "params": (ParamSpec(name="account_id", slot="account_id"),),
        "returns": (OutputSpec(name="found_account_id", slot="account_id"),),
        "steps": (
            Step(
                verb=StepVerb.EXTRACT,
                control=ControlRef(screen="activity", control_id="account_number_value"),
                slot="account_id",
                output="found_account_id",
                note="read the id back",
            ),
        ),
        "checkpoints": (
            Checkpoint(
                output="found_account_id",
                expected=ParamValue(param="account_id"),
                why="the record we asked for",
            ),
        ),
    }
    base.update(overrides)
    return Capability(**base)  # type: ignore[arg-type]


def test_a_capability_whose_controls_were_all_recorded_has_no_faults(
    store: ControlMapStore,
) -> None:
    store.put(
        MapKey(app="parabank", tenant="baseline", screen="activity"),
        _map(_control("account_number_value", ControlRole.LINK, (1280, 900))),
    )
    assert check_capability(_probe(), store) == []


def test_an_unrecorded_control_is_a_fault_at_authoring_time(store: ControlMapStore) -> None:
    store.put(MapKey(app="parabank", tenant="baseline", screen="activity"), _map())
    faults = check_capability(_probe(), store)
    assert len(faults) == 1
    assert "account_number_value" in faults[0]


def test_a_map_recorded_at_another_viewport_is_a_fault(store: ControlMapStore) -> None:
    """A coordinate means nothing away from the viewport it was recorded at."""
    store.put(
        MapKey(app="parabank", tenant="baseline", screen="activity"),
        _map(_control("account_number_value", ControlRole.LINK, (1024, 768)), size=(1024, 768)),
    )
    faults = check_capability(_probe(), store)
    assert any("1024x768" in f and "1280x900" in f for f in faults)


def test_an_ungrounded_control_is_a_fault(store: ControlMapStore) -> None:
    ungrounded = LocatedControl(
        id="account_number_value",
        label="Account Number",
        role=ControlRole.LINK,
        description="never grounded",
        status="unresolved",
        reason="exhausted refinements",
    )
    store.put(MapKey(app="parabank", tenant="baseline", screen="activity"), _map(ungrounded))
    faults = check_capability(_probe(), store)
    assert any("unresolved" in f for f in faults)


def test_a_verb_the_control_role_refuses_is_a_fault(store: ControlMapStore) -> None:
    """Typing into a link, caught while authoring rather than at the bank."""
    store.put(
        MapKey(app="parabank", tenant="baseline", screen="index"),
        _map(_control("log_in_button", ControlRole.LINK, (1280, 900))),
    )
    typing_into_a_link = _probe(
        steps=(
            Step(
                verb=StepVerb.ENTER,
                control=ControlRef(screen="index", control_id="log_in_button"),
                slot="username",
                value=SecretValue(input_ref="parabank_username"),
                note="a link cannot be typed into",
            ),
            _probe().steps[0],
        )
    )
    faults = check_capability(typing_into_a_link, store)
    assert any("does not accept" in f for f in faults)


def test_every_fault_is_reported_not_just_the_first(store: ControlMapStore) -> None:
    """The caller is a person fixing a draft; one round trip per mistake is bad."""
    store.put(MapKey(app="parabank", tenant="baseline", screen="activity"), _map())
    many = _probe(
        steps=(
            Step(
                verb=StepVerb.CLICK,
                control=ControlRef(screen="activity", control_id="nope_one"),
                note="missing",
            ),
            Step(
                verb=StepVerb.CLICK,
                control=ControlRef(screen="activity", control_id="nope_two"),
                note="also missing",
            ),
            _probe().steps[0],
        )
    )
    assert len(check_capability(many, store)) == 3


def test_capability_one_does_not_check_out_against_an_empty_store(
    store: ControlMapStore,
) -> None:
    """The honest current state, asserted rather than described.

    Nothing has been recorded, so every control capability 1 names is a miss.
    When discovery runs and populates the store, this test should be inverted
    -- and issue 0007's `account_link` is expected to remain a fault until the
    discriminator has a mechanism, because discovery records that row as
    `account_13344_link`.
    """
    faults = check_capability(capabilities.READ_SAVINGS_BALANCE, store)
    assert faults, "an empty store must not read as a clean bill of health"
    assert all("nothing recorded" in f for f in faults)
