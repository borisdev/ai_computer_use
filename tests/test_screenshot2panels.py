"""Discovery proposing a panel: what geometry measures, and what it refuses.

Offline, against the real screenshots this repo already commits -- the one from
the 2026-09-26 discovery run, the account-detail and loan-result fixtures, and
the CLEAN one-account overview. Every number asserted here was measured by hand
in `scripts/add_panels.py` first, so the two can be compared.

⚠️ The strongest check on a proposed panel is `table._check_alignment`, which
asks a model which band each row sits inside. It needs a call and a container,
so it lives in `tests/test_panel_discovery_live.py`.
`marker_bands_contain_every_row` is the half that can run here, and the two
tests that CORRUPT a good proposal are what show it can go red.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest

from interfaceai import screenshot2panels
from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    DiscoveryError,
    ImageSize,
    LocatedControl,
    ScreenInput,
    ScreenOutput,
)
from interfaceai.screenshot2panels import (
    MIN_ROWS,
    _PanelPlacement,
    _PanelPlacements,
    _SeenPanel,
    _SeenPanels,
    _sequence,
    derive_panel,
    extract_panel_locators,
    geometry_faults,
    marker_bands_contain_every_row,
    merge_panels,
)

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "evidence" / "runs" / "20260926T022551Z" / "frames"
OVERVIEW = FRAMES / "004-03-overview.png"
LOGIN = FRAMES / "001-00-index.png"
ACTIVITY = ROOT / "tests" / "fixtures" / "activity-13344.png"
LOAN = ROOT / "tests" / "fixtures" / "loan-result.png"
ONE_ROW = ROOT / "tests" / "fixtures" / "overview-clean-1-row.png"

# The headings, at the points `scripts/add_panels.py` anchored on by hand.
ACCOUNTS_HEADING = ClickPoint(x=490, y=320)
NAV_HEADING = ClickPoint(x=300, y=287)
DETAILS_HEADING = ClickPoint(x=495, y=290)
LOAN_HEADING = ClickPoint(x=495, y=290)
# The account-services menu on the same screen, 68px left of the result table.
LOAN_NAV_HEADING = ClickPoint(x=339, y=289)
# A row of the detail table, which is what the hand-written panel anchors on.
DETAILS_ROW = ClickPoint(x=495, y=326)
# The PAGE heading above the accounts table. Live discovery names this one rather
# than the column header, and both have to arrive at the same table.
ACCOUNTS_PAGE_HEADING = ClickPoint(x=520, y=287)

# From the DOM oracle, 2026-09-26: the account links sit at x 492..525.
LINK_X = (492, 525)


def shot(path: Path) -> bytes:
    return path.read_bytes()


def propose(path: Path, point: ClickPoint, *, openable: bool = False, columns=("field", "value")):
    proposal, why = derive_panel(
        shot(path), point=point, columns=columns, key_column=columns[0], openable=openable
    )
    return proposal, why


# --------------------------------------------------------------------------
# The accounts table: the region every capability reads
# --------------------------------------------------------------------------


class TestTheAccountsTable:
    def proposal(self):
        proposal, why = propose(
            OVERVIEW,
            ACCOUNTS_HEADING,
            openable=True,
            columns=("account_id", "balance", "available"),
        )
        assert proposal is not None, why
        return proposal

    def test_the_pitch_matches_the_dom_oracle(self) -> None:
        proposal = self.proposal()
        assert proposal.spec.row_pitch == 28
        assert proposal.rows == 11

    def test_the_total_line_is_not_counted_as_a_row(self) -> None:
        # The Total sits 56px after a column of 28s, and eleven accounts are
        # seeded. Twelve rows here would mean the panel read one row that is not
        # a record.
        assert self.proposal().rows == 11

    def test_autocorrelation_confirms_the_pitch_it_was_measured_against(self) -> None:
        proposal = self.proposal()
        assert proposal.confidence is not None
        assert proposal.confidence > 0.85

    def test_the_measured_key_column_is_the_column_of_links(self) -> None:
        # Within a pixel of the DOM oracle either side: the band is the ink's
        # extent, and the last anti-aliased column of a glyph is a judgement
        # call. Exact equality here would go red on a font hinting change and
        # say nothing about whether the panel works.
        proposal = self.proposal()
        x0 = proposal.point.x + proposal.spec.key_dx
        x1 = x0 + proposal.spec.key_width - 1
        assert abs(x0 - LINK_X[0]) <= 1 and abs(x1 - LINK_X[1]) <= 1, (x0, x1)

    def test_the_drilldown_x_lands_inside_a_link(self) -> None:
        proposal = self.proposal()
        assert proposal.spec.key_click_dx is not None
        assert LINK_X[0] <= proposal.point.x + proposal.spec.key_click_dx <= LINK_X[1]

    def test_the_anchor_is_one_header_cell_not_the_whole_header_row(self) -> None:
        # Columns auto-size, so a patch spanning a boundary moves when the row
        # count changes -- measured 0.0000 against the one-row table. The header
        # BAR is 479px wide; the cell is not.
        assert self.proposal().anchor.width < 120

    def test_the_click_point_sits_inside_the_anchor(self) -> None:
        proposal = self.proposal()
        anchor, point = proposal.anchor, proposal.point
        assert anchor.x <= point.x < anchor.x + anchor.width
        assert anchor.y <= point.y < anchor.y + anchor.height


# --------------------------------------------------------------------------
# Every region measured by hand, measured again by geometry
# --------------------------------------------------------------------------

REGIONS = [
    pytest.param(OVERVIEW, ACCOUNTS_HEADING, 28, 11, id="accounts"),
    pytest.param(OVERVIEW, NAV_HEADING, 24, 8, id="account-services-nav"),
    pytest.param(ACTIVITY, DETAILS_HEADING, 23, 4, id="account-detail"),
    pytest.param(LOAN, LOAN_HEADING, 23, 3, id="loan-result"),
]


@pytest.mark.parametrize(("path", "point", "pitch", "rows"), REGIONS)
def test_the_hand_measured_pitch_and_row_count_are_reproduced(
    path: Path, point: ClickPoint, pitch: int, rows: int
) -> None:
    proposal, why = propose(path, point)
    assert proposal is not None, why
    assert (proposal.spec.row_pitch, proposal.rows) == (pitch, rows)


@pytest.mark.parametrize(("path", "point", "pitch", "rows"), REGIONS)
def test_every_row_sits_inside_the_marker_band_of_its_own_index(
    path: Path, point: ClickPoint, pitch: int, rows: int
) -> None:
    proposal, why = propose(path, point)
    assert proposal is not None, why
    assert marker_bands_contain_every_row(shot(path), proposal) == ()


# --------------------------------------------------------------------------
# The check can go red -- .claude/rules/checks.md
# --------------------------------------------------------------------------


class TestTheOfflineCheckFails:
    def good(self):
        proposal, why = propose(
            OVERVIEW, ACCOUNTS_HEADING, columns=("account_id", "balance", "available")
        )
        assert proposal is not None, why
        return proposal

    def corrupt(self, **update):
        good = self.good()
        return dataclasses.replace(good, spec=good.spec.model_copy(update=update))

    def test_a_pitch_two_pixels_out_is_caught(self) -> None:
        faults = marker_bands_contain_every_row(shot(OVERVIEW), self.corrupt(row_pitch=26))
        assert faults
        assert "not inside its band" in faults[0]

    def test_a_phase_error_is_caught(self) -> None:
        # The first autocorrelation in this repo was a constant 7px out of
        # phase, which is why the phase is checked separately from the pitch.
        good = self.good()
        faults = marker_bands_contain_every_row(
            shot(OVERVIEW), self.corrupt(key_dy=good.spec.key_dy + 9)
        )
        assert faults


# --------------------------------------------------------------------------
# A crop that cuts a value
# --------------------------------------------------------------------------


class TestClipping:
    """⛔ The defect a discovered CHECKPOINT caught, two steps downstream.

    The account-detail block's label and value are 2px apart, so they merge into
    one span — and the span was measured on row one, `Account Number: 13344`. Row
    two is `Account Type: SAVINGS`, which is wider. The crop cut it, the model
    read **`SAVIN`** and reported it without complaint, and `replay` failed on the
    `account_type == SAVINGS` checkpoint of the very capability that had just been
    discovered.

    Nothing about the rows was wrong, so the vertical check passed throughout.
    """

    def proposal(self):
        proposal, why = propose(ACTIVITY, DETAILS_HEADING)
        assert proposal is not None, why
        return proposal

    def test_the_widest_row_is_inside_the_crop(self) -> None:
        assert geometry_faults(shot(ACTIVITY), self.proposal()) == ()

    def narrowed(self, by: int):
        good = self.proposal()
        return dataclasses.replace(
            good, spec=good.spec.model_copy(update={"width": good.spec.width - by})
        )

    def test_a_crop_that_cuts_a_value_is_caught(self) -> None:
        # 30px in from the derived 211 lands inside the values; three of the four
        # rows report it.
        faults = geometry_faults(shot(ACTIVITY), self.narrowed(30))
        assert len(faults) == 3, faults
        assert "running past the crop's right edge" in faults[0]

    def test_a_value_that_ENDS_at_the_edge_is_not_a_fault(self) -> None:
        """⚠️ The distinction the first version of this check got wrong. Ink at the
        boundary is read correctly; ink CROSSING it is cut. Told apart by looking
        past the edge, which the screenshot can do and the crop cannot — and
        conflating them went red on a hand-measured panel that was working."""
        assert geometry_faults(shot(ACTIVITY), self.narrowed(25)) == ()

    def test_the_vertical_check_alone_does_not_notice(self) -> None:
        """Which is why the horizontal one had to be added rather than assumed."""
        assert marker_bands_contain_every_row(shot(ACTIVITY), self.narrowed(30)) == ()


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


class TestItRefuses:
    def test_a_screen_with_no_repeated_structure(self) -> None:
        proposal, why = propose(LOGIN, ClickPoint(x=300, y=300))
        assert proposal is None
        assert "evenly spaced" in (why or "")

    def test_a_point_on_nothing(self) -> None:
        proposal, why = propose(OVERVIEW, ClickPoint(x=1270, y=880))
        assert proposal is None
        assert why

    def test_a_one_row_table_cannot_be_opened(self) -> None:
        # ⛔ The measured behaviour, and it is the reason for the leftmost-column
        # rule. With one account left, the Total line and the footnote below it
        # are 28px apart, so a rhythm exists in the BALANCE column while the
        # account column has none. Geometry cannot tell those three lines from
        # three records -- but it can tell that the column it measured is not
        # the column of links, and it refuses to call the panel openable.
        proposal, why = propose(ONE_ROW, ACCOUNTS_HEADING, openable=True)
        assert proposal is not None, why
        assert proposal.spec.key_click_dx is None
        assert "read-only" in proposal.note


def test_either_heading_above_the_table_measures_the_same_table() -> None:
    """The column header and the page heading above it, to the same pixels.

    ⛔ This is the bug live discovery found on its first run. Asked for the
    heading above the rows, the model named *Accounts Overview* -- correct, and
    not the column header this repo measured by hand. Anchored there, the whole
    shaded header bar read as one column and the panel came back with THIRTEEN
    rows over eleven accounts. Both anchors now agree to the pixel, which is the
    property that matters: the anchor is where we measure FROM, not what we
    measure.
    """
    columns = ("account_id", "balance", "available")
    from_header, why_header = propose(OVERVIEW, ACCOUNTS_HEADING, openable=True, columns=columns)
    from_page, why_page = propose(OVERVIEW, ACCOUNTS_PAGE_HEADING, openable=True, columns=columns)
    assert from_header is not None, why_header
    assert from_page is not None, why_page

    def absolute(proposal):
        spec = proposal.spec
        return (
            proposal.rows,
            spec.row_pitch,
            proposal.point.x + spec.dx,
            proposal.point.y + spec.dy,
            spec.width,
            spec.height,
            proposal.point.x + spec.key_dx,
            proposal.point.x + (spec.key_click_dx or 0),
        )

    assert absolute(from_header) == absolute(from_page)
    assert from_page.rows == 11


def test_a_menu_does_not_swallow_a_table_beside_it() -> None:
    """A 24px menu next to a 23px table, which containment alone let through.

    ⛔ Measured on a live proposal: the account-services menu on the loan-result
    screen came out **722px wide** instead of ~170, having absorbed the result
    table 68px to its right -- closer than the accounts table's own 79 and 84px
    column gutters, so no distance rule can separate them. Every one of the
    table's five lines fell inside a menu band, because an 11px row inside a 24px
    band leaves 12px of slack and the 1px-per-row drift takes longer than that to
    show. The column's OWN rhythm is what tells them apart.
    """
    proposal, why = propose(LOAN, LOAN_NAV_HEADING, columns=("label",))
    assert proposal is not None, why
    assert proposal.spec.row_pitch == 24
    assert proposal.spec.width < 250, proposal.spec.width


def test_anchoring_on_a_row_measures_only_what_is_below_it() -> None:
    # The hand-written `account_details_panel` anchors on a ROW, which the
    # prompt now forbids: a row's value travels with the template, so the
    # locator stops matching the moment the record changes. Anchored there,
    # geometry sees three rows rather than four -- it never invents the row
    # above its anchor, and a row_key naming the missing one fails loudly at
    # replay rather than reading the wrong record.
    proposal, why = propose(ACTIVITY, DETAILS_ROW)
    assert proposal is not None, why
    assert proposal.rows == 3


# --------------------------------------------------------------------------
# The sequence rule
# --------------------------------------------------------------------------


class TestSequence:
    def runs(self, starts: list[int], height: int = 10):
        return [(s, s + height) for s in starts]

    def test_a_stray_run_before_the_first_row_is_skipped(self) -> None:
        # The loan heading's comma sits 40px above row one, in the same column.
        assert _sequence(self.runs([294, 334, 357, 380])) == (23, 3, 1)

    def test_a_stray_run_after_the_last_row_is_dropped(self) -> None:
        # The accounts table's Total line, 56px after a column of 28s.
        assert _sequence(self.runs([352, 380, 408, 464])) == (28, 3, 0)

    def test_two_rows_are_not_a_rhythm(self) -> None:
        # Autocorrelation needs two full periods; so does this.
        assert _sequence(self.runs([100, 128])) is None
        assert MIN_ROWS == 3

    def test_an_irregular_column_is_refused(self) -> None:
        assert _sequence(self.runs([100, 128, 170, 260])) is None


# --------------------------------------------------------------------------
# Orchestration: read, place, ground, measure
# --------------------------------------------------------------------------

ACCOUNTS_PANEL = _SeenPanel(
    heading="Account",
    columns=["account_id", "balance", "available amount"],
    key_column="account_id",
    rows_are_links=True,
    description="the accounts table, one row per account",
)


def fake_vision(panels: list[_SeenPanel], *, cell: int | None = 1):
    async def call(*, prompt, image_png, response_model):
        if response_model is _SeenPanels:
            return _SeenPanels(panels=panels)
        if response_model is _PanelPlacements:
            return _PanelPlacements(
                placements=[_PanelPlacement(index=n, cell_id=cell) for n in range(len(panels))]
            )
        raise AssertionError(f"unexpected call for {response_model}")

    return call


@pytest.fixture
def grounded(monkeypatch: pytest.MonkeyPatch):
    """`_refine` already has its own tests; here it always finds the heading."""

    async def refine(image, start, description, cfg, vision):
        return ACCOUNTS_HEADING, None

    monkeypatch.setattr(screenshot2panels, "_refine", refine)


def run(panels: list[_SeenPanel], **kw) -> list[LocatedControl]:
    return asyncio.run(
        extract_panel_locators(
            ScreenInput(screenshot_png=shot(OVERVIEW)), vision=fake_vision(panels, **kw)
        )
    )


class TestExtractPanelLocators:
    def test_a_measured_region_comes_back_ready_with_its_spec(self, grounded) -> None:
        (panel,) = run([ACCOUNTS_PANEL])
        assert panel.status == "ready"
        assert panel.role is ControlRole.TABLE_CONTROL_PANEL
        assert panel.panel is not None
        assert panel.panel.row_pitch == 28
        assert panel.panel.columns == ("account_id", "balance", "available_amount")
        assert panel.locator is not None
        assert "11 rows" in panel.description

    def test_the_id_comes_from_the_heading(self, grounded) -> None:
        (panel,) = run([ACCOUNTS_PANEL])
        assert panel.id == "account_table_control_panel"

    def test_a_key_column_that_is_not_a_column_is_unresolved_not_dropped(self, grounded) -> None:
        (panel,) = run([ACCOUNTS_PANEL.model_copy(update={"key_column": "iban"})])
        assert panel.status == "unresolved"
        assert "iban" in (panel.reason or "")

    def test_a_region_with_no_cell_is_unresolved_not_dropped(self, grounded) -> None:
        (panel,) = run([ACCOUNTS_PANEL], cell=None)
        assert panel.status == "unresolved"
        assert "no grid cell" in (panel.reason or "")

    def test_a_region_geometry_refuses_is_unresolved_with_the_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def refine(image, start, description, cfg, vision):
            return ClickPoint(x=1270, y=880), None

        monkeypatch.setattr(screenshot2panels, "_refine", refine)
        (panel,) = run([ACCOUNTS_PANEL])
        assert panel.status == "unresolved"
        assert panel.reason

    def test_a_failed_read_raises_rather_than_reporting_an_empty_screen(self) -> None:
        async def broken(*, prompt, image_png, response_model):
            raise RuntimeError("no model")

        with pytest.raises(DiscoveryError, match="panel read failed"):
            asyncio.run(
                extract_panel_locators(ScreenInput(screenshot_png=shot(OVERVIEW)), vision=broken)
            )

    def test_an_empty_read_places_nothing(self) -> None:
        calls = []

        async def counting(*, prompt, image_png, response_model):
            calls.append(response_model)
            return _SeenPanels(panels=[])

        panels = asyncio.run(
            extract_panel_locators(ScreenInput(screenshot_png=shot(OVERVIEW)), vision=counting)
        )
        assert panels == []
        assert calls == [_SeenPanels]


def test_merge_panels_renames_an_id_a_control_already_holds() -> None:
    control_map = ScreenOutput(
        screenshot_sha256="0" * 64,
        image_size=ImageSize(width=1280, height=900),
        controls=[
            LocatedControl(
                id="account_table_control_panel",
                label="Account",
                role=ControlRole.LINK,
                description="a link that happens to slug the same way",
                status="unresolved",
                reason="not requested",
            )
        ],
    )
    panel = LocatedControl(
        id="account_table_control_panel",
        label="Account",
        role=ControlRole.TABLE_CONTROL_PANEL,
        description="the accounts table",
        status="unresolved",
        reason="measured nothing",
    )
    merged = merge_panels(control_map, [panel])
    assert [c.id for c in merged.controls] == [
        "account_table_control_panel",
        "account_table_control_panel_2",
    ]
