"""Offline tests for the two core functions. No model, no browser, no key.

A fake VisionCall makes discovery testable: these exercise the geometry, the
id scheme, the concurrency ordering and the failure paths. They say nothing
about how well a real model picks dots -- that is measured against ParaBank.
"""

import asyncio

import pytest
from PIL import Image, ImageDraw

from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    CropBox,
    DiscoveryConfig,
    DiscoveryError,
    ImageSize,
    ResolveInput,
    ScreenInput,
    VisualLocator,
    _choose_landmark,
    _CoarseControl,
    _CoarseInventory,
    _context_patch,
    _make_locator,
    _png_bytes,
    _Refinement,
    _slug,
    extract_control_locators,
    locate_control,
)


def canvas() -> Image.Image:
    """A tiny screen with one labelled field and one button."""
    img = Image.new("RGB", (320, 180), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 25), "Username", fill="black")
    d.rectangle((20, 45, 119, 64), outline="orange", width=2)
    d.text((22, 90), "Log In", fill="black")
    d.rectangle((20, 85, 80, 105), outline="blue", width=2)
    return img


# --------------------------------------------------------------------------
# locate_control -- the spec's section 7 acceptance cases
# --------------------------------------------------------------------------


class TestLocateControl:
    def locator(self) -> VisualLocator:
        screen = ScreenInput(screenshot_png=_png_bytes(canvas()))
        return _make_locator(
            screen, CropBox(x=10, y=15, width=120, height=65), ClickPoint(x=70, y=55)
        )

    def test_click_offset_is_the_point_minus_the_crop_origin(self) -> None:
        assert self.locator().click_offset.model_dump() == {"x": 60, "y": 40}

    def test_locator_survives_a_json_round_trip(self) -> None:
        loc = self.locator()
        assert (
            VisualLocator.model_validate_json(loc.model_dump_json()).template_png
            == loc.template_png
        )

    def test_translated_patch_is_found_and_the_point_follows(self) -> None:
        patch = canvas().crop((10, 15, 130, 80))
        moved = Image.new("RGB", (320, 180), "white")
        moved.paste(patch, (75, 50))
        r = locate_control(ResolveInput(screenshot_png=_png_bytes(moved), locator=self.locator()))
        assert (r.status, r.point.model_dump()) == ("matched", {"x": 135, "y": 90})

    def test_absent_patch_is_not_found(self) -> None:
        blank = Image.new("RGB", (320, 180), "white")
        r = locate_control(ResolveInput(screenshot_png=_png_bytes(blank), locator=self.locator()))
        assert (r.status, r.point) == ("not_found", None)

    def test_duplicated_patch_is_ambiguous_not_a_guess(self) -> None:
        """Two plausible matches must never be silently resolved to one."""
        patch = canvas().crop((10, 15, 130, 80))
        dup = Image.new("RGB", (320, 180), "white")
        dup.paste(patch, (10, 10))
        dup.paste(patch, (180, 90))
        r = locate_control(ResolveInput(screenshot_png=_png_bytes(dup), locator=self.locator()))
        assert (r.status, r.point) == ("ambiguous", None)

    def test_different_viewport_is_incompatible(self) -> None:
        larger = Image.new("RGB", (640, 360), "white")
        r = locate_control(ResolveInput(screenshot_png=_png_bytes(larger), locator=self.locator()))
        assert (r.status, r.point) == ("incompatible", None)

    def test_featureless_template_is_refused_not_matched_everywhere(self) -> None:
        """Measured: a blank patch scores 1.0 at 1,103,249 positions."""
        flat = Image.new("RGB", (40, 12), "white")
        loc = self.locator().model_copy(
            update={
                "template_png": _png_bytes(flat),
                "reference_crop": CropBox(x=0, y=0, width=40, height=12),
                "click_offset": ClickPoint(x=20, y=6),
            }
        )
        r = locate_control(ResolveInput(screenshot_png=_png_bytes(canvas()), locator=loc))
        assert r.status == "incompatible"
        assert "constant" in r.reason


# --------------------------------------------------------------------------
# extract_control_locators -- orchestration, via a fake model
# --------------------------------------------------------------------------


def fake_vision(inventory: list[_CoarseControl], refine: str = "click"):
    """A VisionCall that inventories `inventory` and then always picks dot 1."""
    calls = {"coarse": 0, "fine": 0}

    async def call(*, prompt, image_png, response_model):
        if response_model is _CoarseInventory:
            calls["coarse"] += 1
            return _CoarseInventory(controls=inventory)
        calls["fine"] += 1
        if refine == "unresolved":
            return _Refinement(action="unresolved", reason="cannot see it")
        return _Refinement(action=refine, number=1)

    call.calls = calls
    return call


def run(**kw):
    return asyncio.run(
        extract_control_locators(ScreenInput(screenshot_png=_png_bytes(canvas())), **kw)
    )


CONTROLS = [
    _CoarseControl(
        label="Username", role=ControlRole.TEXTBOX, description="the username field", cell_id=1
    ),
    _CoarseControl(
        label="Log In", role=ControlRole.BUTTON, description="the submit button", cell_id=1
    ),
]


class TestExtract:
    def test_ids_come_from_the_label_not_the_position(self) -> None:
        out = run(vision=fake_vision(CONTROLS))
        assert [c.id for c in out.controls] == ["username_textbox", "log_in_button"]

    def test_inventory_order_is_preserved_despite_concurrency(self) -> None:
        many = [
            _CoarseControl(label=f"L{i}", role=ControlRole.LINK, description=f"d{i}", cell_id=1)
            for i in range(8)
        ]
        out = run(vision=fake_vision(many), config=DiscoveryConfig(max_concurrency=4))
        assert [c.id for c in out.controls] == [f"l{i}_link" for i in range(8)]

    def test_duplicate_labels_get_distinct_ids(self) -> None:
        dupes = [
            _CoarseControl(label="Read More", role=ControlRole.LINK, description=f"d{i}", cell_id=1)
            for i in range(3)
        ]
        ids = [c.id for c in run(vision=fake_vision(dupes)).controls]
        assert ids == ["read_more_link", "read_more_link_2", "read_more_link_3"]
        assert len(set(ids)) == 3

    def test_a_control_with_no_cell_is_unresolved_never_dropped(self) -> None:
        out = run(
            vision=fake_vision(
                [
                    _CoarseControl(
                        label="Ghost", role=ControlRole.LINK, description="no cell", cell_id=None
                    )
                ]
            )
        )
        assert len(out.controls) == 1
        assert out.controls[0].status == "unresolved"
        assert "no cell" in out.controls[0].reason

    def test_model_reporting_unresolved_is_carried_through(self) -> None:
        out = run(vision=fake_vision(CONTROLS, refine="unresolved"))
        assert all(c.status == "unresolved" for c in out.controls)
        assert all("cannot see it" in c.reason for c in out.controls)

    def test_only_skips_refinement_but_keeps_the_entry(self) -> None:
        vision = fake_vision(CONTROLS)
        out = run(vision=vision, only=["log_in_button"])
        by_id = {c.id: c for c in out.controls}
        assert by_id["username_textbox"].status == "unresolved"
        assert by_id["username_textbox"].reason == "not requested"
        assert vision.calls["coarse"] == 1, "coarse inventory always runs"

    def test_a_failed_coarse_call_raises_rather_than_reporting_an_empty_screen(self) -> None:
        async def broken(*, prompt, image_png, response_model):
            raise RuntimeError("azure 500")

        with pytest.raises(DiscoveryError, match="coarse inventory failed"):
            run(vision=broken)

    def test_ready_controls_carry_a_point_and_a_locator(self) -> None:
        out = run(vision=fake_vision(CONTROLS))
        for c in out.controls:
            if c.status == "ready":
                assert c.click_point is not None and c.locator is not None
                assert c.reason is None
            else:
                assert c.click_point is None and c.locator is None and c.reason

    def test_screenshot_hash_is_recorded_for_provenance(self) -> None:
        out = run(vision=fake_vision(CONTROLS))
        assert len(out.screenshot_sha256) == 64
        assert out.image_size.model_dump() == {"width": 320, "height": 180}


def test_slug_is_stable_for_the_same_label() -> None:
    assert _slug("Transfer Funds", ControlRole.LINK) == _slug("Transfer  Funds", ControlRole.LINK)


class TestLandmarkSurvivesTypedInput:
    """A submit button's landmark must not swallow the field above it.

    Regression for the 2026-09-26 discovery run: every placement for ParaBank's
    Log In button reached up over the password field, self-matched at 1.0000 on
    the empty form, and scored 0.8365 once anything was typed -- so the run
    escalated mid-login. The failure is invisible on the discovery screenshot by
    construction, which is why the check has to fill the field and re-score.

    ⚠️ The geometry is not decorative. The gap between the field's bottom edge
    and the click point must be SMALLER than `context_height / 3`, or every
    stock placement clears the field on its own and the test passes without
    exercising anything. The first version of this test had a 33px gap against
    a 26px reach and stayed green with the fix reverted.

        field bottom   108
        click point    125     gap = 17
        context_height  80     bias 1/3 reaches 26px up -> top 98, INSIDE the field
                               bias 0.15 reaches 12px up -> top 113, clear
    """

    FIELD = (60, 70, 260, 108)
    CLICK = ClickPoint(x=150, y=125)
    CONFIG = DiscoveryConfig(context_width=200, context_height=80)

    def _form(self, *, typed: bool) -> Image.Image:
        img = Image.new("RGB", (320, 220), "white")
        d = ImageDraw.Draw(img)
        d.text((60, 50), "Password", fill="black")
        d.rectangle(self.FIELD, outline="gray", width=1)
        if typed:
            # A filled field differs across its whole height, which is what the
            # overlapping patch actually sees.
            d.rectangle((62, 72, 258, 106), fill="#404040")
        d.rectangle((110, 112, 190, 138), outline="blue", width=2)
        d.text((126, 119), "LOG IN", fill="black")
        d.text((60, 160), "Forgot login info?", fill="black")
        d.text((60, 180), "Register", fill="black")
        return img

    def _unstable(self) -> CropBox:
        x0, y0, x1, y1 = self.FIELD
        return CropBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0)

    def test_the_chosen_landmark_still_matches_once_the_field_is_filled(self) -> None:
        empty = _png_bytes(self._form(typed=False))
        filled = _png_bytes(self._form(typed=True))

        locator, why = _choose_landmark(
            ScreenInput(screenshot_png=empty),
            self.CLICK,
            self.CONFIG,
            ImageSize(width=320, height=220),
            [self._unstable()],
        )
        assert locator is not None, why
        assert locator.reference_crop.y >= self.FIELD[3], (
            f"chose a patch starting at y={locator.reference_crop.y}, inside the field "
            f"that ends at y={self.FIELD[3]}"
        )

        after = locate_control(ResolveInput(screenshot_png=filled, locator=locator))
        assert after.status == "matched", f"{after.status}: {after.reason}"
        assert after.point == self.CLICK

    def test_an_upward_landmark_is_what_this_avoids(self) -> None:
        """The control. Without it the test above could pass for the wrong reason.

        Forces the placement the chooser used to be stuck with and shows it
        self-matching perfectly on the empty form and failing on the filled one
        -- which is the whole shape of the bug.
        """
        empty = _png_bytes(self._form(typed=False))
        filled = _png_bytes(self._form(typed=True))

        upward = _context_patch(self.CLICK, 200, 80, ImageSize(width=320, height=220), above=1 / 3)
        assert upward.y < self.FIELD[3], "the control placement must actually overlap the field"
        locator = _make_locator(ScreenInput(screenshot_png=empty), upward, self.CLICK)

        assert (
            locate_control(ResolveInput(screenshot_png=empty, locator=locator)).status == "matched"
        )
        assert (
            locate_control(ResolveInput(screenshot_png=filled, locator=locator)).status != "matched"
        )
