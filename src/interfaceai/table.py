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
from pydantic import create_model

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

# A pixel this far from its region's median is CONTENT. Measured on ParaBank:
# glyphs ~100, white 255, zebra stripes 230/235/238, a shaded header bar 194.
# Lives here rather than in `screenshot2panels` because both the proposer and the
# reader ask the same question of the same pixels.
INK_DELTA = 40

# Ink within this many pixels of a crop's right edge is content being CUT, not
# content that happens to end there.
_EDGE_PX = 2


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


def _is_cut_off(
    image: Image.Image, box: CropBox, *, first_row_y: int, pitch: int | None, rows: int
) -> bool:
    """Does content CROSS the crop's right edge? Then a value is truncated.

    ⛔ **The quietest wrong answer this system can produce.** A crop two pixels
    too narrow does not fail: the model reads what is inside it and returns
    `SAVIN` for `SAVINGS`, `CHECKIN` for `CHECKING`, `$1231.1` for `$1231.10`.
    Measured on a real replay -- a panel's geometry was derived from a screenshot
    whose value read `SAVINGS`, and the same column held `CHECKING` after the
    database changed. Nothing about the ROWS was wrong, so the alignment
    cross-check passed and the fault surfaced two steps later.

    A panel's geometry is recorded once and its DATA changes afterwards, so this
    cannot be settled when the panel is proposed. It is asked of every read.

    ⚠️ **Ink AT the edge is not ink CUT BY it**, and the first version of this
    conflated them -- it went red on a hand-measured panel whose value ends
    exactly at its boundary, correctly read. From the crop alone the two are
    indistinguishable; from the SCREENSHOT they are not. So the question is
    whether a run of ink spans the boundary: present on the last column inside
    AND on the first columns outside.

    ⚠️ **And only over the rows that were READ.** A panel records the height it had
    when it was authored -- eleven rows for the accounts table -- and ParaBank's
    CLEAN state leaves ONE. The rest of that box is whatever the page puts below
    the table, and asking about it reported a menu 200px lower as a truncated
    value. Second false positive from the same check, same cause: a question asked
    of pixels that are not the panel's.
    """
    right = box.x + box.width
    bands = (
        [(first_row_y + n * pitch, pitch) for n in range(max(1, rows))]
        if pitch
        else [(box.y, box.height)]
    )
    for top, height in bands:
        top = max(box.y, min(top, box.y + box.height))
        bottom = min(top + height, box.y + box.height, image.height)
        if bottom <= top:
            continue
        band = np.asarray(
            image.crop((box.x, top, min(image.width, right + _EDGE_PX), bottom)).convert("L")
        ).astype(float)
        if band.size == 0 or band.shape[1] <= box.width:
            continue  # the crop already reaches the screenshot's edge
        ink = np.abs(band - np.median(band)) > INK_DELTA
        if (ink[:, box.width - 1] & ink[:, box.width :].any(axis=1)).any():
            return True
    return False


@dataclass(frozen=True)
class PanelRead[T]:
    """What a panel read returned, the geometry to act on it, and its disagreements.

    ⛔ **Drilling into a row ALWAYS depends on having extracted the panel first**
    (Boris, 2026-09-26), so there is no way to get a click point except through
    this object. That is deliberate: the alternative -- asking a model to find
    the row for account 13344 on screen -- is
    [issue 0009](../../docs/issues/0009-wrong-row-grounding-is-silent.md),
    measured landing on the wrong record 3 times in 4.
    """

    data: T
    first_row_y: int
    rhythm: RowRhythm | None = None
    # Rows where the marker WE drew did not line up with the row the model saw.
    # Empty when the cross-check passed or could not run.
    misaligned: tuple[str, ...] = ()
    # Set when content runs into the crop's right edge, so at least one value was
    # read TRUNCATED. Distinct from `misaligned` because it fails the other way
    # round: the positions are fine and the CONTENT is not.
    clipped: tuple[str, ...] = ()

    @property
    def cross_checked(self) -> bool:
        return self.rhythm is not None

    def point_for_row(self, index: int, x: int) -> ClickPoint:
        """Where to click to drill into row `index`. `x` picks the column."""
        if self.rhythm is None:
            raise PanelNotFound(
                "no measurable row rhythm, so a row position cannot be computed; "
                "the panel was read but cannot be drilled into"
            )
        y = self.rhythm.row_y(self.first_row_y, index) + self.rhythm.pitch // 2
        return ClickPoint(x=x, y=y)


# The marker column the cross-check adds to every panel schema. Named here so
# the schema, the instruction and the verification cannot disagree about it.
MARKER_FIELD = "row_marker"


def normalise_value(text: str) -> str:
    """Compare what a person would call the same value.

    A screen prints `$1,231.10` where an artifact recorded `1231.10`, and a field
    label printed `Account Type:` reads back as `Account Type`. Comparing raw
    strings would report a violated checkpoint -- or a missing row -- for a
    correct read, which is the loudest possible false alarm.

    Deliberately narrow: currency symbols, thousands separators, and trailing
    punctuation that is typography rather than content. It does NOT fold
    whitespace inside the value or strip letters, because two labels that differ
    by a word are two labels.

    >>> normalise_value("$1,231.10") == normalise_value("1231.10")
    True
    >>> normalise_value("Account Type:") == normalise_value("account type")
    True
    """
    return text.strip().lstrip("$").replace(",", "").rstrip(".:").strip().casefold()


@dataclass(frozen=True)
class RowMatch:
    """Which row a key names. `index` is set only when exactly one row matched.

    ⚠️ **One implementation, two callers, on purpose.** Replay drills into a row
    and discovery now does too, and both have to answer "which row is 13344" the
    same way -- including the near-misses: a key that names NO row is a fair
    negative answer about the data, and one that names TWO is a defect in the
    read. Callers map those to their own outcome types; what they must not do is
    each decide what "matches" means.
    """

    index: int | None
    matched: int
    total: int
    keys: tuple[str, ...]


def match_row(rows: list, key_column: str, wanted: object) -> RowMatch:
    """The single row whose key column equals `wanted`, compared as a person would."""
    keys = tuple(str(getattr(row, key_column)) for row in rows)
    target = normalise_value(str(wanted))
    hits = [n for n, key in enumerate(keys) if normalise_value(key) == target]
    return RowMatch(
        index=hits[0] if len(hits) == 1 else None,
        matched=len(hits),
        total=len(keys),
        keys=keys,
    )


async def extract_panel(
    screenshot_png: bytes,
    locator: VisualLocator,
    *,
    panel: Offset,
    key_column: Offset,
    columns: tuple[str, ...],
    key_column_name: str,
    vision: VisionCall,
    what: str = "a table from a banking application",
    row_pitch: int | None = None,
) -> PanelRead:
    """Locate a `TABLE_CONTROL_PANEL`, crop it, read it, and CHECK the geometry.

    One model call returns the whole panel as typed rows. The caller then
    selects a row IN CODE -- nothing is asked where a row is, which is what
    keeps `docs/issues/0009` off this path.

    ## Geometry proposes, perception verifies

    The rhythm is measured BEFORE the call, so one marker per row can be drawn
    at the computed positions and the SAME call asked which marker each row sits
    beside. Zero extra model calls, and margin markers are measured harmless
    (11/11 ids and balances, three runs -- `docs/issues/0011`).

    It catches the three ways the geometry goes wrong, all of which have
    happened here: a phase error (the first autocorrelation was a constant 7px
    out), a pitch HARMONIC (zebra striping returns twice the row pitch), and a
    table that changed between the read and the click.

    ⚠️ This is not a second position algorithm. One marker per row needs the
    pitch, so the marker pass is downstream of the autocorrelation -- what the
    model supplies is an independent CONFIRMATION of what we computed, which is
    stronger than recomputing it.

    A disagreement is reported on `PanelRead.misaligned` rather than raised:
    only the caller knows whether it is about to act on the row or merely read
    a value from it.
    """
    found = locate_control(ResolveInput(screenshot_png=screenshot_png, locator=locator))
    if found.status != "matched" or found.point is None:
        raise PanelNotFound(f"panel anchor {found.status}: {found.reason}")
    if key_column_name not in columns:
        raise PanelNotFound(f"key column {key_column_name!r} is not in {columns}")

    origin_x, origin_y = found.point.x, found.point.y
    absolute = key_column.at(origin_x, origin_y)
    measured = find_row_rhythm(screenshot_png, absolute)
    # A shrunken table has too few rows for a period; the pitch recorded when
    # the panel was authored is a measurement, not a guess.
    rhythm = measured or (RowRhythm(pitch=row_pitch, confidence=0.0) if row_pitch else None)

    image = Image.open(io.BytesIO(screenshot_png)).convert("RGB")
    box = panel.at(origin_x, origin_y)
    crop = image.crop((box.x, box.y, box.x + box.width, box.y + box.height))

    marker_of_index: dict[int, int] = {}
    if rhythm is not None:
        crop, marker_of_index = _mark_rows(crop, box, absolute, rhythm)

    fields: dict[str, object] = {c: (str, ...) for c in columns}
    if marker_of_index:
        fields[MARKER_FIELD] = (int | None, None)
    row_model = create_model("PanelRow", **fields)
    table_model = create_model("PanelRows", rows=(list[row_model], ...))

    instruction = (
        f"This is a crop of {what}. Return every row with these fields, exactly "
        f"as printed: {', '.join(columns)}. Do not invent rows."
    )
    if marker_of_index:
        instruction += (
            f" The left margin is divided into numbered bands by our tooling -- "
            f"annotation, not page content. Also return `{MARKER_FIELD}`: the "
            f"number of the band that this row sits INSIDE."
        )

    buffer = io.BytesIO()
    crop.save(buffer, "PNG")
    data = await vision(prompt=instruction, image_png=buffer.getvalue(), response_model=table_model)

    # Asked of the SCREENSHOT, not the crop, and only over the rows that came
    # back -- see `_is_cut_off` for why each of those matters.
    clipped: tuple[str, ...] = ()
    if _is_cut_off(
        image,
        box,
        first_row_y=absolute.y,
        pitch=rhythm.pitch if rhythm is not None else None,
        rows=len(data.rows),
    ):
        clipped = (
            (
                f"content runs past the right edge of the {box.width}px crop, so at "
                f"least one value is truncated rather than read"
            ),
        )

    misaligned = _check_alignment(data.rows, marker_of_index, key_column_name)
    return PanelRead(
        data=data,
        first_row_y=absolute.y,
        rhythm=rhythm,
        misaligned=misaligned,
        clipped=clipped,
    )


def _mark_rows(
    crop: Image.Image, box: CropBox, key_column: CropBox, rhythm: RowRhythm
) -> tuple[Image.Image, dict[int, int]]:
    """Draw one numbered BAND per row, in the margin, at the computed positions.

    ⚠️ **Bands, not dots — containment beats proximity.** The first version drew
    a dot at the y we would click, which is near the BOTTOM of a row's text, and
    the model consistently read row 0's dot as belonging to row 1. "Which band
    is this row inside" has one answer; "which dot is level with this row" is a
    judgement about distance, and a 14px row inside a 28px pitch makes that
    judgement close.

    Same shape as the finding in `docs/issues/0011`: the model matches reliably
    and estimates badly.

    In the margin because a marker over a glyph destroys the read -- a probe
    once scored 0/11 that way. If there is no room the crop comes back unmarked
    and the cross-check simply does not run, because silently covering the data
    would be worse than not checking.
    """
    margin = key_column.x - box.x
    if margin < 16:
        return crop, {}

    marked = crop.copy()
    draw = ImageDraw.Draw(marked)
    marker_of_index: dict[int, int] = {}
    index = 0
    top = key_column.y
    while top + rhythm.pitch <= box.y + box.height:
        y0, y1 = top - box.y, top + rhythm.pitch - box.y
        shade = "#ffd0d0" if index % 2 == 0 else "#ffe8e8"
        draw.rectangle((0, y0, margin - 3, y1 - 1), fill=shade, outline="#e00000")
        draw.text((3, y0 + rhythm.pitch // 2 - 6), str(index), fill="#900000")
        # The y we would CLICK for this row -- the thing being verified.
        marker_of_index[index] = top + rhythm.pitch // 2
        index += 1
        top += rhythm.pitch
    return marked, marker_of_index


def _check_alignment(
    rows: list, marker_of_index: dict[int, int], key_column_name: str
) -> tuple[str, ...]:
    """Row `i` must sit beside marker `i`. Anything else means the geometry lied.

    Rows the model returned without a marker are not a disagreement -- it may
    simply not have answered that field -- but a marker that names a DIFFERENT
    row is, and so is a row count the markers cannot cover.
    """
    if not marker_of_index:
        return ()
    faults: list[str] = []
    for index, row in enumerate(rows):
        seen = getattr(row, MARKER_FIELD, None)
        if seen is None:
            continue
        if seen != index:
            key = getattr(row, key_column_name, "?")
            faults.append(
                f"row {index} ({key}) reports marker {seen}: the markers we drew do "
                f"not line up with the rows, so the row pitch or phase is wrong"
            )
    if len(rows) > len(marker_of_index):
        faults.append(
            f"the model read {len(rows)} rows but only {len(marker_of_index)} markers "
            "fit the panel, so the pitch is too large"
        )
    return tuple(faults)
