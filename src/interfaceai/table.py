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
from PIL import Image

from interfaceai.screenshot2controls import CropBox

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
