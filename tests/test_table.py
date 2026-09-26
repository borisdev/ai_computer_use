"""Row rhythm: the pitch of a table, from pixels, with no model in the loop.

These run offline against the screenshot committed from the 2026-09-26
discovery run, so the numbers in `docs/issues/0007` have a check under them
rather than a paragraph.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from interfaceai.screenshot2controls import CropBox, _png_bytes
from interfaceai.table import MIN_CONFIDENCE, RowRhythm, find_row_rhythm

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
