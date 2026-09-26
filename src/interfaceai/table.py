"""Finding a row in a table without grounding each row, and without reading it.

Tables defeat everything else in this codebase. A landmark around row 7 looks
exactly like a landmark around row 8 — `docs/findings.md` §3 measured that in
miniature, where a control's own bbox matched *Username and Password*. And the
coarse pass assigns a cell number per control, which on eleven near-identical
rows it gets wrong ([issue 0009](../../docs/issues/0009-wrong-row-grounding-is-silent.md):
1 of 4 grounded account links landed on their own row).

The way out, and it needs no per-row perception at all:

    anchor    template-match the table HEADER -- unique, unlike every row
    rhythm    autocorrelation of a column's brightness -> the row pitch
    order     read the key column from a CLEAN screenshot (11/11 measured)
    row N     anchor_y + N * pitch

This module is the `rhythm` step. It is pure numpy: no model call, no network,
deterministic, and it refuses rather than guesses.

## Why autocorrelation and not edge detection

Edge detection was tried first and returned **9px** — the height of a digit. It
finds features locally, so a glyph edge and a row boundary are indistinguishable
and you are left classifying 38 candidates.

Autocorrelation asks one global question per candidate shift: how much does this
column resemble itself moved down by N pixels? Glyphs are not periodic, so they
average toward nothing; the row striping is, so it survives. Measured on
ParaBank's overview:

    lag 28   0.899     the pitch
    lag 56   0.805     its harmonic -- a real period always echoes at 2x
    lag 30   0.385     neighbours, less than half
    lag 26   0.383

⚠️ **What comes back is the image's visual period, which is not always the row
height.** Shade every other row and the true period is 2x the pitch — row i and
row i+1 genuinely do not look alike. ParaBank's overview is zebra-striped and
still reports 28, because its per-row content (an account number and two
amounts) is the stronger signal: 28 at 0.899 against 56 at 0.805. A table with
weak per-row content would report double. `tests/test_table.py` pins both
behaviours. The anchor step settles it — if the recorded header-to-row-1 offset
disagrees with the detected pitch, the pitch is a harmonic.

**The peak height is a confidence, and that is the point.** A table with
variable row heights produces a weak or split peak, so the caller learns the
assumption does not hold instead of receiving a plausible wrong number. Edge
detection offered no such signal, which is how it returned 9 with no warning.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from pydantic import BaseModel

from interfaceai.screenshot2controls import (
    ClickPoint,
    CropBox,
    ResolveInput,
    VisionCall,
    VisualLocator,
    locate_control,
)

# Measured on real regions, 2026-09-26. Real table columns score 0.899 and
# 0.818; the strongest non-table region scores 0.364 (an empty margin), with
# prose at 0.324 and a login form at 0.216. 0.6 sits in open space between
# them -- above every observed negative, below every observed positive.
MIN_CONFIDENCE = 0.6

# Below this lag we are measuring glyph height, not row pitch; above it, a
# "row" taller than this is not the repeating structure we are looking for.
MIN_PITCH_PX = 8
MAX_PITCH_PX = 60

# A column of uniform colour autocorrelates to 1.0 at every lag, the same way a
# constant template matches everywhere (`screenshot2controls._is_effectively_constant`).
# Refusing it is a correctness guard, not hygiene.
_MIN_SIGNAL_STD = 0.5


@dataclass(frozen=True)
class RowRhythm:
    """A table's vertical period, with the evidence for it."""

    pitch: int
    confidence: float

    def row_y(self, first_row_y: int, index: int) -> int:
        """The y of row `index`, counting the first row as 0.

        `first_row_y` is the phase, which autocorrelation cannot supply — it
        finds the period, not where the sequence starts. It comes from the
        anchor: the header is template-matched, and the first row sits a
        recorded offset below it.
        """
        if index < 0:
            raise ValueError("row index must be >= 0")
        return first_row_y + index * self.pitch


def find_row_rhythm(
    screenshot_png: bytes,
    column: CropBox,
    *,
    min_confidence: float = MIN_CONFIDENCE,
) -> RowRhythm | None:
    """The row pitch of a table, from one column's pixels. None = refuse.

    `column` should cover a single column over the table's vertical extent —
    the key column is the natural choice, since that is the one whose rows the
    caller wants to index.

    Returns None when the autocorrelation peak is too weak to trust, which is
    the honest answer for a region that is not a uniform table.
    """
    image = Image.open(io.BytesIO(screenshot_png)).convert("RGB")
    pixels = np.asarray(image).astype(float)

    band = pixels[
        column.y : column.y + column.height,
        column.x : column.x + column.width,
        :,
    ].mean(axis=(1, 2))

    if band.size <= MIN_PITCH_PX * 2 or band.std() < _MIN_SIGNAL_STD:
        return None

    centred = band - band.mean()
    correlation = np.correlate(centred, centred, mode="full")[len(centred) - 1 :]
    correlation /= correlation[0]

    lags = np.arange(len(correlation))
    window = (lags >= MIN_PITCH_PX) & (lags <= min(MAX_PITCH_PX, len(correlation) - 1))
    if not window.any():
        return None

    best = int(lags[window][np.argmax(correlation[window])])
    confidence = float(correlation[best])
    if confidence < min_confidence:
        return None
    return RowRhythm(pitch=best, confidence=confidence)


# ---------------------------------------------------------------------------
# Marking rows for a structured read
# ---------------------------------------------------------------------------
#
# Once the rhythm is known, one marker can be drawn per row and the panel handed
# to a model with a response schema: "return each row's fields AND its marker
# number". That gets the data and the click positions from a single call, with
# no cell assignment and no per-row grounding.
#
# ⚠️ **The marker must not touch the content.** Measured 2026-09-26 on the
# accounts table, three runs each:
#
#     clean crop                      ids 11/11   balances 11/11
#     markers drawn OVER the digits   ids  0/11   balances  0/11
#     markers drawn in the MARGIN     ids 11/11   balances 11/11, markers correct
#
# The middle row was an accident -- a probe placed dots at the column centre and
# `12345` rendered as `12<dot>45`. It is kept as the measurement because it is
# the whole rule: annotation is free in whitespace and destroys the read on top
# of a glyph. This is also the sharper form of
# `docs/issues/0008`: the 192-cell grid hurts because it draws ACROSS content,
# not because it is an overlay.


@dataclass(frozen=True)
class RowMarkers:
    """An annotated panel, and what each marker number means."""

    image_png: bytes
    y_by_marker: dict[int, int]

    def y_of(self, marker: int) -> int:
        if marker not in self.y_by_marker:
            raise KeyError(f"no marker {marker}; drew {sorted(self.y_by_marker)}")
        return self.y_by_marker[marker]


def annotate_rows(
    screenshot_png: bytes,
    panel: CropBox,
    rhythm: RowRhythm,
    first_row_y: int,
    *,
    content_x0: int,
    marker_radius: int = 5,
) -> RowMarkers:
    """Crop `panel` and draw one numbered marker per row, left of the content.

    `content_x0` is the leftmost pixel of anything that must stay legible. The
    markers are placed strictly left of it and the call raises if there is not
    room, because silently overlapping the data is the failure this exists to
    prevent -- and it is a failure that looks like a model error, not a drawing
    error.
    """
    image = Image.open(io.BytesIO(screenshot_png)).convert("RGB")
    crop = image.crop((panel.x, panel.y, panel.x + panel.width, panel.y + panel.height))

    margin = content_x0 - panel.x
    needed = 2 * marker_radius + 2
    if margin < needed:
        raise ValueError(
            f"only {margin}px between the panel edge and the content at x={content_x0}; "
            f"a marker needs {needed}px. Widen the panel to the left."
        )
    centre_x = margin // 2

    drawing = ImageDraw.Draw(crop)
    y_by_marker: dict[int, int] = {}
    marker = 0
    y = first_row_y
    while y < panel.y + panel.height:
        cy = y - panel.y + rhythm.pitch // 2
        if cy + marker_radius >= crop.height:
            break
        drawing.ellipse(
            (
                centre_x - marker_radius,
                cy - marker_radius,
                centre_x + marker_radius,
                cy + marker_radius,
            ),
            fill="#e00000",
        )
        drawing.text((centre_x + marker_radius + 1, cy - 6), str(marker), fill="#e00000")
        y_by_marker[marker] = y
        marker += 1
        y += rhythm.pitch

    buffer = io.BytesIO()
    crop.save(buffer, "PNG")
    return RowMarkers(image_png=buffer.getvalue(), y_by_marker=y_by_marker)


# ---------------------------------------------------------------------------
# Extracting from a panel
# ---------------------------------------------------------------------------


class PanelNotFound(RuntimeError):
    """The panel's anchor did not match. Never guess a region and read it."""


@dataclass(frozen=True)
class Offset:
    """A region expressed RELATIVE to a matched anchor. dx/dy may be negative.

    Not a `CropBox`: that validates `x >= 0` because it is an absolute region in
    image space, and a panel frequently starts left of or above its anchor. The
    repo already learned this once -- `docs/findings.md` records clipping having
    to happen on plain ints for the same reason.
    """

    dx: int
    dy: int
    width: int
    height: int

    def at(self, origin_x: int, origin_y: int) -> CropBox:
        """Resolve against a matched anchor, clipping to the image's origin."""
        x, y = max(0, origin_x + self.dx), max(0, origin_y + self.dy)
        return CropBox(x=x, y=y, width=self.width, height=self.height)


@dataclass(frozen=True)
class PanelRead[T]:
    """What a panel read returned, and the geometry to act on it.

    ⛔ **Drilling into a row ALWAYS depends on having extracted the panel first**
    (Boris, 2026-09-26), so there is no way to get a click point except through
    this object. That is deliberate: the alternative -- asking a model to find
    the row for account 13344 on screen -- is
    [issue 0009](../../docs/issues/0009-wrong-row-grounding-is-silent.md),
    measured landing on the wrong record 3 times in 4.

    The extract says 13344 is index 9. The rhythm turns index 9 into a y. No
    model is ever asked where a row is.
    """

    data: T
    rhythm: RowRhythm
    first_row_y: int

    def point_for_row(self, index: int, x: int) -> ClickPoint:
        """Where to click to drill into row `index`. `x` picks the column."""
        return ClickPoint(
            x=x, y=self.rhythm.row_y(self.first_row_y, index) + self.rhythm.pitch // 2
        )


async def extract_panel[T: BaseModel](
    screenshot_png: bytes,
    locator: VisualLocator,
    *,
    panel: Offset,
    key_column: Offset,
    response_model: type[T],
    vision: VisionCall,
    instruction: str,
) -> PanelRead[T]:
    """Locate a `TABLE_CONTROL_PANEL`, crop it, and read it against a schema.

    One model call returns the whole panel as typed rows. The parameter that
    selects a row is then applied in CODE to that list -- no per-row grounding,
    no cell assignment, and nothing asked to find a row on screen.

    `panel` and `key_column` are offsets from the MATCHED anchor, so the crop
    follows the anchor if the page reflows -- the same trick a click offset uses.

    Measured on ParaBank's accounts table, three runs: 11/11 account ids and
    11/11 balances. See `docs/issues/0011`.
    """
    found = locate_control(ResolveInput(screenshot_png=screenshot_png, locator=locator))
    if found.status != "matched" or found.point is None:
        raise PanelNotFound(f"panel anchor {found.status}: {found.reason}")

    origin_x, origin_y = found.point.x, found.point.y
    absolute = key_column.at(origin_x, origin_y)
    rhythm = find_row_rhythm(screenshot_png, absolute)
    if rhythm is None:
        raise PanelNotFound(
            "found the panel anchor but its rows have no measurable rhythm; "
            "refusing rather than assuming a row height"
        )

    image = Image.open(io.BytesIO(screenshot_png)).convert("RGB")
    box = panel.at(origin_x, origin_y)
    crop = image.crop((box.x, box.y, box.x + box.width, box.y + box.height))
    buffer = io.BytesIO()
    crop.save(buffer, "PNG")

    data = await vision(
        prompt=instruction, image_png=buffer.getvalue(), response_model=response_model
    )
    return PanelRead(data=data, rhythm=rhythm, first_row_y=absolute.y)
