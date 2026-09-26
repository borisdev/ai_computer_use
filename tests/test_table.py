"""Row rhythm: the pitch of a table, from pixels, with no model in the loop.

These run offline against the screenshot committed from the 2026-09-26
discovery run, so the numbers in `docs/issues/0007` have a check under them
rather than a paragraph.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from pydantic import BaseModel

from interfaceai.decisions import supported_actions
from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    CropBox,
    ScreenInput,
    VisualLocator,
    _make_locator,
    _png_bytes,
)
from interfaceai.table import (
    MIN_CONFIDENCE,
    Offset,
    PanelNotFound,
    PanelRead,
    RowRhythm,
    annotate_rows,
    extract_panel,
    find_row_rhythm,
)

RUN = Path(__file__).resolve().parents[1] / "evidence" / "runs" / "20260926T022551Z" / "frames"
OVERVIEW = RUN / "004-03-overview.png"
LOGIN = RUN / "001-00-index.png"

# From the DOM oracle, 2026-09-26. The account links sit at x 492..525 and the
# eleven row tops are 28px apart from y=350.
ACCOUNT_COLUMN = CropBox(x=490, y=340, width=40, height=320)
TRUE_PITCH = 28
TRUE_FIRST_ROW_Y = 350
TRUE_ROW_TOPS = [350, 378, 406, 434, 462, 490, 518, 546, 574, 602, 630]


def shot(path: Path) -> bytes:
    return path.read_bytes()


# --- the real table --------------------------------------------------------


def test_the_account_column_yields_the_real_row_pitch() -> None:
    rhythm = find_row_rhythm(shot(OVERVIEW), ACCOUNT_COLUMN)
    assert rhythm is not None
    assert rhythm.pitch == TRUE_PITCH
    assert rhythm.confidence > 0.8


def test_a_different_column_of_the_same_table_agrees() -> None:
    """Pitch is a property of the table, not of the column you sampled."""
    balance = CropBox(x=600, y=340, width=100, height=320)
    rhythm = find_row_rhythm(shot(OVERVIEW), balance)
    assert rhythm is not None
    assert rhythm.pitch == TRUE_PITCH


def test_the_pitch_reproduces_every_row_position() -> None:
    """The whole point: index -> y, with no per-row perception."""
    rhythm = find_row_rhythm(shot(OVERVIEW), ACCOUNT_COLUMN)
    assert rhythm is not None
    predicted = [rhythm.row_y(TRUE_FIRST_ROW_Y, i) for i in range(len(TRUE_ROW_TOPS))]
    assert predicted == TRUE_ROW_TOPS


def test_account_13344_lands_on_its_own_row() -> None:
    """The case issue 0009 gets wrong by grounding: 13344 is index 9."""
    rhythm = find_row_rhythm(shot(OVERVIEW), ACCOUNT_COLUMN)
    assert rhythm is not None
    y = rhythm.row_y(TRUE_FIRST_ROW_Y, 9)
    assert 602 <= y <= 616, f"y={y} is outside 13344's link box"


# --- it refuses rather than guessing ---------------------------------------


@pytest.mark.parametrize(
    ("name", "path", "column"),
    [
        ("left nav", OVERVIEW, CropBox(x=1, y=300, width=200, height=300)),
        ("empty margin", OVERVIEW, CropBox(x=900, y=300, width=200, height=300)),
        ("login form", LOGIN, CropBox(x=250, y=250, width=200, height=200)),
        ("prose", LOGIN, CropBox(x=700, y=300, width=400, height=200)),
    ],
)
def test_a_region_that_is_not_a_uniform_table_is_refused(
    name: str, path: Path, column: CropBox
) -> None:
    """Measured negatives: 0.364, 0.324, 0.216, and a flat region at 0.000."""
    assert find_row_rhythm(shot(path), column) is None, name


def test_a_flat_region_is_refused_rather_than_matching_everywhere() -> None:
    """A constant signal autocorrelates to 1.0 at every lag.

    Same shape as the constant-template guard in `screenshot2controls`: a
    featureless input must be a refusal, never a perfect score.
    """
    flat = _png_bytes(Image.new("RGB", (200, 400), "white"))
    assert find_row_rhythm(flat, CropBox(x=10, y=10, width=100, height=300)) is None


def test_a_region_shorter_than_two_periods_is_refused() -> None:
    rhythm = find_row_rhythm(shot(OVERVIEW), CropBox(x=490, y=340, width=40, height=12))
    assert rhythm is None


# --- it is not hardcoded to ParaBank ---------------------------------------


@pytest.mark.parametrize("pitch", [14, 21, 28, 35, 44])
def test_a_synthetic_table_of_any_pitch_is_measured_correctly(pitch: int) -> None:
    """Without this the tests above could pass on a constant that says 28."""
    img = Image.new("RGB", (200, 480), "white")
    d = ImageDraw.Draw(img)
    for i in range(480 // pitch):
        y = i * pitch
        d.line((0, y, 199, y), fill="#b0b8c8")
        d.text((12, y + 2), f"1{i:04d}", fill="black")

    rhythm = find_row_rhythm(_png_bytes(img), CropBox(x=5, y=0, width=120, height=480))
    assert rhythm is not None, f"pitch {pitch} not detected"
    assert rhythm.pitch == pitch


@pytest.mark.parametrize("pitch", [14, 21, 28])
def test_zebra_striping_reports_the_STRIPE_period_not_the_row_period(pitch: int) -> None:
    """A documented limitation, not a bug -- and the distinction matters.

    Shade every other row and the image's true visual period is 2x the row
    pitch: row i and row i+1 genuinely do not look alike. The detector is
    measuring the image correctly; what it returns is not the row height.

    ParaBank's overview is zebra-striped AND still reports 28, because its
    per-row content (an account number and two amounts) is a stronger periodic
    signal than the shading -- measured 28 at 0.899 against 56 at 0.805. A
    table with weak per-row content would not be so lucky.

    So a caller must not assume pitch == row height. The anchor step settles
    it: if the recorded offset from the header to row 1 does not match the
    detected pitch, the pitch is a harmonic.
    """
    img = Image.new("RGB", (200, 480), "white")
    d = ImageDraw.Draw(img)
    for i in range(480 // pitch):
        y = i * pitch
        if i % 2 == 0:
            d.rectangle((0, y, 199, y + pitch - 1), fill="#dde6f5")
        d.text((12, y + 2), f"1{i:04d}", fill="black")

    rhythm = find_row_rhythm(_png_bytes(img), CropBox(x=5, y=0, width=120, height=480))
    assert rhythm is not None
    assert rhythm.pitch == pitch * 2


def test_a_period_beyond_the_search_ceiling_is_refused() -> None:
    """Rows taller than MAX_PITCH_PX are out of scope, and say so."""
    img = Image.new("RGB", (200, 480), "white")
    d = ImageDraw.Draw(img)
    for i in range(480 // 80):
        d.line((0, i * 80, 199, i * 80), fill="#b0b8c8")
        d.text((12, i * 80 + 2), f"1{i:04d}", fill="black")
    assert find_row_rhythm(_png_bytes(img), CropBox(x=5, y=0, width=120, height=480)) is None


def test_the_confidence_threshold_is_honoured() -> None:
    """Raising it past the measured peak must turn a hit into a refusal."""
    assert find_row_rhythm(shot(OVERVIEW), ACCOUNT_COLUMN) is not None
    assert find_row_rhythm(shot(OVERVIEW), ACCOUNT_COLUMN, min_confidence=0.95) is None


def test_row_index_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="index must be"):
        RowRhythm(pitch=28, confidence=0.9).row_y(350, -1)


def test_the_default_threshold_sits_between_the_measured_populations() -> None:
    """0.818 is the weakest real table column; 0.364 the strongest non-table."""
    assert 0.364 < MIN_CONFIDENCE < 0.818


# --- marking rows for a structured read ------------------------------------

# The accounts table, widened LEFT so markers have clear margin. Content (the
# account links) starts at x=492 per the DOM oracle.
PANEL = CropBox(x=425, y=330, width=355, height=330)
CONTENT_X0 = 492


def _markers():
    rhythm = find_row_rhythm(shot(OVERVIEW), ACCOUNT_COLUMN)
    assert rhythm is not None
    return rhythm, annotate_rows(
        shot(OVERVIEW), PANEL, rhythm, TRUE_FIRST_ROW_Y, content_x0=CONTENT_X0
    )


def test_one_marker_per_visible_row() -> None:
    _, markers = _markers()
    assert len(markers.y_by_marker) == len(TRUE_ROW_TOPS)


def test_each_marker_maps_back_to_its_real_row() -> None:
    _, markers = _markers()
    assert [markers.y_of(i) for i in range(len(TRUE_ROW_TOPS))] == TRUE_ROW_TOPS


def test_marker_9_is_account_13344() -> None:
    """The end-to-end claim, in one assertion."""
    _, markers = _markers()
    assert 602 <= markers.y_of(9) <= 616


def test_markers_never_touch_the_content() -> None:
    """The bug that produced a 0/11 read, encoded so it cannot recur.

    A probe once drew markers at the column centre and `12345` rendered as
    `12<dot>45`. The model scored 0/11 and it looked like a model failure.
    """
    _, markers = _markers()
    before = (
        Image.open(io.BytesIO(shot(OVERVIEW)))
        .convert("RGB")
        .crop((PANEL.x, PANEL.y, PANEL.x + PANEL.width, PANEL.y + PANEL.height))
    )
    after = Image.open(io.BytesIO(markers.image_png)).convert("RGB")
    content_from = CONTENT_X0 - PANEL.x
    assert (
        np.asarray(before)[:, content_from:, :] == np.asarray(after)[:, content_from:, :]
    ).all(), "annotation altered pixels at or right of the content edge"


def test_a_panel_with_no_room_for_markers_raises() -> None:
    """Fail loudly rather than drawing over the data."""
    rhythm = find_row_rhythm(shot(OVERVIEW), ACCOUNT_COLUMN)
    assert rhythm is not None
    tight = CropBox(x=488, y=330, width=290, height=330)
    with pytest.raises(ValueError, match="Widen the panel"):
        annotate_rows(shot(OVERVIEW), tight, rhythm, TRUE_FIRST_ROW_Y, content_x0=CONTENT_X0)


def test_an_unknown_marker_raises_rather_than_returning_none() -> None:
    _, markers = _markers()
    with pytest.raises(KeyError, match="no marker"):
        markers.y_of(99)


def test_the_annotated_panel_is_written_for_a_human_to_look_at(tmp_path) -> None:
    """Not an assertion so much as a window.

    Everything else here is numbers. This writes the exact image a model would
    be sent, so a person can open it and see whether the markers sit where they
    should. Run with `--panel-out=<dir>` semantics via tmp_path, or read the
    copy committed under evidence/.
    """
    _, markers = _markers()
    out = tmp_path / "annotated-panel.png"
    out.write_bytes(markers.image_png)
    rendered = Image.open(out)
    assert rendered.size == (PANEL.width, PANEL.height)


# --- the panel: extract, then drill down -----------------------------------


class Row(BaseModel):
    account_id: str
    balance: str


class Accounts(BaseModel):
    rows: list[Row]


def _anchor() -> VisualLocator:
    """Anchor on the table HEADER -- unique, unlike every row below it."""
    return _make_locator(
        ScreenInput(screenshot_png=shot(OVERVIEW)),
        CropBox(x=470, y=322, width=280, height=26),
        ClickPoint(x=480, y=330),
    )


async def _fake_vision(*, prompt, image_png, response_model):
    """Stands in for the model. The real 11/11 read is measured in 0011."""
    return response_model(
        rows=[
            Row(account_id=a, balance="$0.00")
            for a in [
                "12345",
                "12456",
                "12567",
                "12678",
                "12789",
                "12900",
                "13011",
                "13122",
                "13233",
                "13344",
                "54321",
            ]
        ]
    )


def _read() -> PanelRead:
    return asyncio.run(
        extract_panel(
            shot(OVERVIEW),
            _anchor(),
            panel=Offset(dx=-10, dy=20, width=310, height=320),
            key_column=Offset(dx=10, dy=20, width=40, height=320),
            response_model=Accounts,
            vision=_fake_vision,
            instruction="read the table",
        )
    )


def test_a_panel_read_carries_the_rhythm_it_measured() -> None:
    read = _read()
    assert read.rhythm.pitch == TRUE_PITCH
    assert len(read.data.rows) == 11


def test_drilling_into_13344_goes_through_the_extract() -> None:
    """The index comes from the READ, never from asking where the row is."""
    read = _read()
    index = [r.account_id for r in read.data.rows].index("13344")
    assert index == 9
    point = read.point_for_row(index, x=508)
    assert 602 <= point.y <= 616, f"y={point.y} is outside 13344's link box"


def test_a_panel_whose_anchor_is_absent_refuses() -> None:
    blank = _png_bytes(Image.new("RGB", (1280, 900), "white"))
    with pytest.raises(PanelNotFound, match="anchor"):
        asyncio.run(
            extract_panel(
                blank,
                _anchor(),
                panel=Offset(dx=0, dy=0, width=100, height=100),
                key_column=Offset(dx=0, dy=0, width=40, height=200),
                response_model=Accounts,
                vision=_fake_vision,
                instruction="read the table",
            )
        )


def test_a_panel_with_no_rhythm_still_READS_but_cannot_be_drilled() -> None:
    """Reading a one-row table is fine. Drilling into it is what needs a period.

    The guard used to reject the whole extract, which made a legitimate
    one-row result look like a failure.
    """
    read = asyncio.run(
        extract_panel(
            shot(OVERVIEW),
            _anchor(),
            panel=Offset(dx=-10, dy=20, width=310, height=320),
            key_column=Offset(dx=420, dy=-20, width=200, height=260),  # blank margin
            response_model=Accounts,
            vision=_fake_vision,
            instruction="read the table",
        )
    )
    assert read.rhythm is None
    assert len(read.data.rows) == 11
    with pytest.raises(PanelNotFound, match="cannot be drilled"):
        read.point_for_row(0, x=508)


def test_a_table_panel_accepts_no_manual_action() -> None:
    """You read a panel; you never click it. Enforced by the role table."""
    assert supported_actions(ControlRole.TABLE_CONTROL_PANEL) == []
