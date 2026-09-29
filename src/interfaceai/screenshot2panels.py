"""Proposing a `TABLE_CONTROL_PANEL`, instead of measuring one by hand.

`screenshot2controls` inventories things you ACT on. It is told to ignore static
text and layout, which is correct for a control and is exactly what excludes a
table -- so every panel in this repo was measured by hand in
`scripts/add_panels.py`, and 4 of 5 capabilities read `hand-authored` because of
it ([issue #6](https://github.com/borisdev/ai_computer_use/issues/6)).

The division of labour here is the whole design:

    perception   proposes WHAT: a region of repeated rows, its columns, which
                 column identifies a row. One call, on a CLEAN screenshot.
    geometry     measures WHERE: the row pitch, the phase, how many rows, how
                 far the region reaches. Pure numpy, no model, refuses rather
                 than guesses.
    the verifier CHECKS: `table._check_alignment` draws one band per computed
                 row and asks the same read which band each row sits inside.

⚠️ **The model is never asked for a pixel.** It was asked for cell numbers once
(`docs/issues/0008`) and the annotation needed to ask corrupted the read it was
annotating. Here it is asked only what it is good at -- reading text and saying
what a region IS -- and every number in the emitted `PanelSpec` comes from
`find_row_rhythm` and from ink runs.

## Why ink runs and not just autocorrelation

`find_row_rhythm` answers *what is the period*. It cannot answer *where does the
first row start* (it finds the period, not the phase) or *how many rows are
there*, and both are needed: the phase places the markers, and the row count is
the region's height. Ink runs answer all three, and the autocorrelation then has
to AGREE with them -- a disagreement is a refusal, because the only way two
independent measurements of one period disagree is that one of them is wrong.

Measured on the four regions `scripts/add_panels.py` measured by hand:

    accounts table    11 runs, every gap 28px, then a 56px gap at the Total row
    account-services   8 runs, every gap 24px
    account detail     3 runs, every gap 23px
    loan result        3 runs, every gap 23px

⚠️ **Ink is measured against the region's OWN background, never against white.**
The loan result sits on a shaded table and the accounts table is zebra-striped:
`pixel < 250` reads both as solid content and finds ONE run where there are
three. `|pixel - median| > 40` finds the glyphs in both, and in a shaded column
header too, where the text is lighter than its bar.

## What it refuses, and why refusing is the point

A wrong panel is worse than no panel: it reads a region that is not a table and
hands back rows nobody can check. So every step that cannot be measured is a
refusal carried on `LocatedControl.status = "unresolved"` with a reason -- the
same shape discovery already uses for a control it could not ground, and the
decide prompt already shows unresolved entries as not actionable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel

from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    CropBox,
    DiscoveryConfig,
    DiscoveryError,
    ImageSize,
    LocatedControl,
    PanelSpec,
    ResolveInput,
    ScreenInput,
    ScreenOutput,
    VisionCall,
    VisualLocator,
    _decode,
    _grid_overlay,
    _make_locator,
    _rect,
    _refine,
    _slug,
    _unique,
    locate_control,
)
from interfaceai.table import MAX_PITCH_PX, MIN_PITCH_PX, find_row_rhythm

# A pixel this far from its region's median is content, not background. 40
# separates ParaBank's glyphs (~100) from white (255), from the zebra stripes
# (230/235/238) and from a column header's own bar.
_INK_DELTA = 40

# Vertical gap that ends a line of text. Rows of glyphs within one line are
# contiguous or a pixel apart; 4 keeps a link and its underline together.
_LINE_GAP_PX = 4

# Horizontal gap that ends a run of text. ParaBank's column gutters are 79 and
# 84px, and its widest within-label space is 8.
_TEXT_GAP_PX = 8

# `table._mark_rows` needs 16px left of the key column to draw its bands, and
# without bands the alignment cross-check silently does not run. A panel that
# cannot be verified is refused, so the margin is reserved here rather than
# hoped for.
MARKER_MARGIN_PX = 24

# Autocorrelation needs two full periods, so three runs is the minimum that can
# produce a pitch at all -- and a two-row "table" is not a repeated structure
# worth a panel. `docs/what-went-wrong.md`: a blank strip happily autocorrelated
# at 8px, and the real fault was a column too SHORT to hold two periods.
MIN_ROWS = 3

# Anti-aliasing moves a run boundary by a pixel; anything larger is a different
# period, not the same one measured twice.
_PITCH_TOLERANCE_PX = 1

# How far below the heading to look for rows. Longer than any region on
# ParaBank's screens, and a structure further down cannot join the sequence
# anyway -- the run gaps end it.
_PROBE_PX = 420

# Padding around the anchor's text, and around the region's content.
_PAD_PX = 4

# Narrower than this is a table border or a rule, not a column. ParaBank's are
# 2px; its narrowest real column is 34px wide.
_MIN_COLUMN_PX = 8

# How many lines below the heading may be tried as the source of the columns.
# See the comment at the loop -- the first line is sometimes a clipped descender
# or a rule, and never on every screen.
_CANDIDATE_LINES = 3

# The anchor must match itself where it was cropped. Same rule as
# `_choose_landmark`: a template that cannot find its own pixels will not find
# them on a later screenshot either.
_ANCHOR_DRIFT_PX = 2


# ---------------------------------------------------------------------------
# What perception returns
# ---------------------------------------------------------------------------


class _SeenPanel(BaseModel):
    """One repeated structure, as READ from a clean screenshot."""

    heading: str
    columns: list[str]
    key_column: str
    rows_are_links: bool = False
    description: str


class _SeenPanels(BaseModel):
    panels: list[_SeenPanel]


class _PanelPlacement(BaseModel):
    index: int
    cell_id: int | None = None


class _PanelPlacements(BaseModel):
    placements: list[_PanelPlacement]


_PANEL_READ_PROMPT = """\
This is a screenshot of a business application. Nothing has been drawn on it.

Find every REPEATED STRUCTURE: a region of three or more near-identical rows --
a results table, an account list, a label/value block, a menu of links. A single
row is not one, and neither is a paragraph of prose.

For each one give:
- heading: the text of the column header or heading DIRECTLY ABOVE the rows,
  verbatim. It must NOT be one of the repeated rows: the rows look alike, so
  none of them can identify the region. If a region has no heading above it,
  leave the region out entirely rather than naming one of its rows.
- columns: one short lower-case name per column, LEFT TO RIGHT, as you would
  name a field -- account_id, balance, field, value, label
- key_column: which of those columns identifies a row (an id, a name, a label),
  never a column of amounts
- rows_are_links: true if the values in the FIRST column are links (underlined,
  or coloured differently from plain text), false if they are plain text
- description: enough to tell this region apart from anything else on screen

Return an empty list if the screen has no repeated structure. Do not invent one
that an application like this usually has but this screenshot does not show.
"""

_PANEL_LOCATE_PROMPT = """\
This is the same screenshot you were just shown, with a numbered grid drawn on
top by our tooling. The numbers and lines are annotation, not page content.

These HEADINGS were read from the clean image. For each one, give the number of
the grid cell containing the heading TEXT ITSELF -- not the centre of the rows
below it:

{headings}

Return one placement per heading, using the index shown above. If you cannot say
which cell a heading is in, set cell_id to null. Do not add, drop or rename
headings -- the list is fixed.
"""


# ---------------------------------------------------------------------------
# Geometry: pure numpy, no model
# ---------------------------------------------------------------------------


def _grey(png: bytes) -> np.ndarray:
    return np.asarray(_decode(png, "screenshot").convert("L")).astype(float)


def _runs(flags: np.ndarray, min_gap: int) -> list[tuple[int, int]]:
    """Contiguous True runs, merged across gaps narrower than `min_gap`.

    >>> _runs(np.array([0, 1, 1, 0, 1, 0, 0, 0, 1]).astype(bool), 2)
    [(1, 4), (8, 8)]
    """
    out: list[tuple[int, int]] = []
    index, size = 0, len(flags)
    while index < size:
        if not flags[index]:
            index += 1
            continue
        start = last = index
        while index < size:
            if flags[index]:
                last = index
            elif index - last >= min_gap:
                break
            index += 1
        out.append((start, last))
    return out


def _ink(region: np.ndarray) -> np.ndarray:
    """Content, measured against the region's OWN background. See module doc."""
    return np.abs(region - np.median(region)) > _INK_DELTA


def _line_at(grey: np.ndarray, point: ClickPoint) -> tuple[int, int] | None:
    """The vertical extent of the line of content the point sits on.

    A narrow window around the point's x, because the question is *how tall is
    this heading* and a full-width profile answers it about the whole page.
    """
    x0, x1 = max(0, point.x - 30), min(grey.shape[1], point.x + 30)
    column = _ink(grey[:, x0:x1]).sum(axis=1) > 0
    for start, end in _runs(column, _LINE_GAP_PX):
        if start - _LINE_GAP_PX <= point.y <= end + _LINE_GAP_PX:
            return start, end
    return None


def _spans(grey: np.ndarray, y0: int, y1: int) -> list[tuple[int, int]]:
    """Horizontal runs of content on the rows y0..y1 inclusive."""
    return _runs(_ink(grey[y0 : y1 + 1, :]).sum(axis=0) > 0, _TEXT_GAP_PX)


def _glyph_spans(
    grey: np.ndarray, y0: int, y1: int, frame: tuple[int, int]
) -> list[tuple[int, int]]:
    """Text runs INSIDE one line, measured against that line's own background.

    A column header on a shaded bar is invisible to a page-wide profile: the bar
    itself is content, so the whole header row reads as one run 479px wide.
    Restricting the median to the bar makes its glyphs the deviation instead.
    """
    band = grey[y0 : y1 + 1, frame[0] : frame[1] + 1]
    return [
        (frame[0] + s, frame[0] + e) for s, e in _runs(_ink(band).sum(axis=0) > 0, _TEXT_GAP_PX)
    ]


def _follows_the_rows(
    grey: np.ndarray, span: tuple[int, int], row_top: int, pitch: int, count: int
) -> bool:
    """Does this column's content sit inside the rows we measured?

    ⛔ **This is what decides which columns belong to the panel, and a gutter
    threshold cannot do it.** The account-services menu's rows end 68px left of
    the accounts table, while the accounts table's own column gutters are 79 and
    84px -- so any rule based on how far apart two columns are puts the whole
    accounts table inside the menu's panel.

    Sharing the RHYTHM is the property that distinguishes them: the menu repeats
    every 24px and the table every 28, so a few rows in, the table's content
    straddles the menu's row boundaries. Every run must sit inside a band, which
    is the same containment question `_check_alignment` asks a model.
    """
    band = grey[row_top : row_top + pitch * count, span[0] : span[1] + 1]
    runs = [(row_top + s, row_top + e) for s, e in _runs(_ink(band).sum(axis=1) > 0, _LINE_GAP_PX)]
    if len(runs) < 2:
        return False
    offsets = []
    for y0, y1 in runs:
        index = (y0 - row_top) // pitch
        if not (row_top + index * pitch <= y0 and y1 <= row_top + (index + 1) * pitch - 1):
            return False
        offsets.append(y0 - (row_top + index * pitch))
    # ⚠️ Containment ALONE is not enough, and a live proposal proved it. On the
    # loan-result screen the menu repeats every 24px and the result table beside
    # it every 23, and over five short rows every one of the table's lines still
    # landed inside a menu band -- an 11px row inside a 24px band leaves 12px of
    # slack, which absorbs 1px of drift for longer than you would guess. The panel
    # came out 722px wide instead of 170.
    #
    # What gives it away is WHERE in the band each run sits: a real column of
    # this table puts its glyphs the same distance below every row boundary, and
    # a foreign rhythm creeps -- 5px, then 4, then 3. Comparing the column's own
    # pitch does not catch it, because 23 against 24 is inside the tolerance that
    # exists for anti-aliasing.
    return max(offsets) - min(offsets) <= _PITCH_TOLERANCE_PX


def _is_a_header_bar(grey: np.ndarray, run: tuple[int, int], y0: int, y1: int) -> bool:
    """Is this line SHADED differently from what is under it?

    The one property that tells a column header from a record: ParaBank shades
    its header row. It matters because a header sits exactly one row pitch above
    row one, so nothing about its POSITION distinguishes it -- anchored on the
    page heading above the table, the header row joined the rhythm and the panel
    came out with twelve rows over eleven accounts.

    Zebra striping does not trip this: the stripes are 230 and 238 against a
    median of 235, and the bar is 194 against white.
    """
    height = y1 - y0 + 1
    band = grey[y0 : y1 + 1, run[0] : run[1] + 1]
    below = grey[y1 + 1 : y1 + 1 + 3 * height, run[0] : run[1] + 1]
    if below.size == 0:
        return False
    return abs(float(np.median(band)) - float(np.median(below))) > _INK_DELTA


def _containing(spans: list[tuple[int, int]], x: int) -> tuple[int, int] | None:
    for start, end in spans:
        if start - _TEXT_GAP_PX <= x <= end + _TEXT_GAP_PX:
            return start, end
    return None


def _sequence(runs: list[tuple[int, int]]) -> tuple[int, int, int] | None:
    """The LONGEST evenly spaced stretch of runs: (pitch, how many, where it starts).

    Each run has to land where the pitch PREDICTS it, not merely one pitch after
    the run before it.

    ⛔ **Chaining gaps was wrong, and it shipped a panel the verifier caught.**
    Allowing each gap to be within a pixel of the last lets a systematic +1
    accumulate: eleven gaps of 29 read as a pitch of 28, and by row 10 the band
    is 20px ahead of the row. Measured on a live overview -- every gap passed and
    `marker_bands_contain_every_row` refused the result, which is the check
    working and the measurement not.

    So: predict `first + i * pitch`, accept a run within `_PITCH_TOLERANCE_PX` of
    it, and then REFIT the pitch across the whole stretch -- which is what makes
    the phase right at row 10 as well as at row 1.

    Two more things it survives, both measured:

    - a stray run BEFORE the first row. The loan result's heading has a comma
      the narrow heading window clips off, 40px above row one, in the same
      column. Reading only the leading stretch found two rows and refused a
      table that is plainly there.
    - a stray run AFTER the last row. The accounts table's Total line is 56px
      after a column of 28s, and counting it would put twelve rows in an
      eleven-row panel.
    """
    if len(runs) < MIN_ROWS:
        return None
    best: tuple[int, int, int] | None = None
    for start in range(len(runs) - MIN_ROWS + 1):
        pitch = runs[start + 1][0] - runs[start][0]
        if pitch < MIN_PITCH_PX or pitch > MAX_PITCH_PX:
            continue
        matched = [runs[start][0], runs[start + 1][0]]
        for candidate, _ in runs[start + 2 :]:
            predicted = runs[start][0] + len(matched) * pitch
            if abs(candidate - predicted) > _PITCH_TOLERANCE_PX:
                break
            matched.append(candidate)
        if len(matched) < MIN_ROWS or (best is not None and len(matched) <= best[1]):
            continue
        refit = round((matched[-1] - matched[0]) / (len(matched) - 1))
        best = (refit, len(matched), start)
    return best


@dataclass(frozen=True)
class PanelProposal:
    """A measured panel, and the evidence for it."""

    anchor: CropBox
    point: ClickPoint
    spec: PanelSpec
    rows: int
    # None when autocorrelation could not run at all -- three rows is two
    # periods, which is the floor, and a short region can land under it.
    confidence: float | None
    note: str


def derive_panel(
    screenshot_png: bytes,
    *,
    point: ClickPoint,
    columns: tuple[str, ...],
    key_column: str,
    openable: bool,
) -> tuple[PanelProposal | None, str | None]:
    """Measure the panel under `point`, or say why it cannot be measured.

    `point` is a grounded point inside the region's HEADING -- the one thing
    about a repeated structure that is unique, since its rows are not
    (`docs/issues/0009`, `0011`).

    Everything else is derived:

        the heading's line       the vertical extent of content under the point
        the heading's frame      the horizontal run it belongs to; the region
                                 cannot be wider than the heading spanning it
        the key column           the LEFTMOST column inside that frame whose
                                 pixels have a measurable rhythm -- leftmost
                                 because `_mark_rows` draws its bands to the
                                 left of it, and a band over column 1 would
                                 destroy the read it exists to check
        pitch, phase, row count  evenly spaced ink runs in that column
        the region's width       every column whose content STARTS inside the
                                 frame, out to its own right edge
    """
    grey = _grey(screenshot_png)
    height, width = grey.shape
    size = ImageSize(width=int(width), height=int(height))

    line = _line_at(grey, point)
    if line is None:
        return None, f"no line of content at {point.model_dump()} to anchor on"
    line_y0, line_y1 = line

    heading_run = _containing(_spans(grey, line_y0, line_y1), point.x)
    if heading_run is None:
        return None, f"no run of content at x={point.x} on the line y={line_y0}..{line_y1}"

    probe_y0 = line_y1 + 1
    probe_y1 = min(int(height), probe_y0 + _PROBE_PX)
    if probe_y1 - probe_y0 < MIN_ROWS * 2:
        return None, f"only {probe_y1 - probe_y0}px below the heading; nothing can repeat there"

    # ⚠️ Columns are read off ONE LINE at a time, never off the probe window. A
    # horizontal profile over 420 rows is one run 1280px wide -- every x holds ink
    # SOMEWHERE in a region that tall -- and the first version of this found one
    # column covering the whole page.
    lines = _runs(
        _ink(grey[probe_y0:probe_y1, heading_run[0] : heading_run[1] + 1]).sum(axis=1) > 0,
        _LINE_GAP_PX,
    )
    if not lines:
        return None, (f"no content below the heading inside x={heading_run[0]}..{heading_run[1]}")

    # ⚠️ And off the LINE's own run, not the heading's. A page heading can be
    # narrower than the table under it ("Accounts Overview" is 150px over a 479px
    # table) and a column header can be wider than any of its cells. Taking the
    # run that line makes around the heading's x is what lets either one be the
    # anchor and arrive at the same geometry -- measured: anchored on the page
    # heading this found 13 rows (eleven accounts, the Total line and a footnote)
    # because the whole shaded header bar read as one column.
    #
    # ⚠️ The first line below a heading is not always a row, either: a descender
    # the narrow heading window clipped off ("Loan Request Processed" ends at
    # y=293 in the window and its comma runs to 297), a rule, or a table border.
    # Trying the first few costs nothing, because the acceptance test is three
    # EVENLY SPACED rows and none of those can pass it.
    tried: list[tuple[int, int]] = []
    measured = None
    for line in lines[:_CANDIDATE_LINES]:
        ly0, ly1 = probe_y0 + line[0], probe_y0 + line[1]
        # Every run on this line that OVERLAPS the heading's own run, and then
        # the glyphs INSIDE each -- which is what makes a shaded header bar
        # legible (its own median is the bar, so its labels are the deviation)
        # while a plain row of separate cells stays separate.
        # Every column on this line, left to right, across every run of content
        # that overlaps the heading. A shaded run is a HEADER: its glyphs name the
        # columns and the rows start under it; an unshaded one is already row one.
        line_columns = [
            (column, ly1 + 1 if _is_a_header_bar(grey, run, ly0, ly1) else ly0)
            for run in _spans(grey, ly0, ly1)
            if run[1] >= heading_run[0] - _PAD_PX and run[0] <= heading_run[1] + _PAD_PX
            for column in _glyph_spans(grey, ly0, ly1, run)
        ]
        tried.extend(span for span, _ in line_columns)
        for span, rows_from in line_columns:
            found = _runs(
                _ink(grey[rows_from:probe_y1, span[0] : span[1] + 1]).sum(axis=1) > 0,
                _LINE_GAP_PX,
            )
            rows = [(rows_from + s, rows_from + e) for s, e in found]
            rhythm_of_runs = _sequence(rows)
            if rhythm_of_runs is not None:
                # Every column on the line, not just the winning one: the
                # leftmost-column rule below has to know what it beat.
                measured = (span, rows, rhythm_of_runs, [s for s, _ in line_columns])
                break
        if measured is not None:
            break
    if measured is None:
        return None, (
            f"no column below the heading repeats: tried x={[s for s, _ in tried]}, "
            f"none gave {MIN_ROWS} evenly spaced rows"
        )

    key_span, rows, (pitch, count, first), candidates = measured
    first_y0, first_y1 = rows[first]
    # Centre the ink in its band. A marker band is judged by CONTAINMENT, so the
    # phase that maximises the margin either side is the one that survives a row
    # whose glyphs sit high or low (`table._mark_rows`).
    row_top = max(line_y1 + 1, first_y0 - max(1, (pitch - (first_y1 - first_y0 + 1)) // 2))
    region_height = count * pitch

    left = key_span[0] - MARKER_MARGIN_PX
    if left < 0:
        return None, (
            f"the key column starts at x={key_span[0]}, leaving no room for the "
            f"{MARKER_MARGIN_PX}px marker margin the alignment check needs"
        )

    # The right edge: every column right of the key column that FOLLOWS THE SAME
    # ROWS. Gathered row by row, because a profile over the whole region reads as
    # one run, and a column whose values grow wider further down still has to be
    # inside the crop.
    right = key_span[1]
    seen: set[tuple[int, int]] = set()
    for index in range(count):
        top = row_top + index * pitch
        for span in _spans(grey, top, min(int(height) - 1, top + pitch - 1)):
            if span[0] <= key_span[1] or span[1] <= right or span in seen:
                continue
            seen.add(span)
            if _follows_the_rows(grey, span, row_top, pitch, count):
                right = max(right, span[1])

    key_box = _rect(key_span[0], row_top, key_span[1] - key_span[0] + 1, region_height, size)
    rhythm = find_row_rhythm(screenshot_png, key_box)
    if rhythm is not None and abs(rhythm.pitch - pitch) > _PITCH_TOLERANCE_PX:
        return None, (
            f"two measurements of one period disagree: {count} evenly spaced rows "
            f"{pitch}px apart, autocorrelation {rhythm.pitch}px at {rhythm.confidence:.3f}"
        )
    note = f"{count} rows, pitch {pitch}px" + (
        f", autocorrelation {rhythm.confidence:.3f}"
        if rhythm is not None
        else ", too short for autocorrelation to confirm"
    )

    # The anchor: the heading's own text, tight. NOT the whole header row --
    # columns auto-size, so a patch spanning a boundary moves when the row count
    # changes, measured 0.0000 against a one-row table (scripts/add_panels.py).
    glyphs = _containing(_glyph_spans(grey, line_y0, line_y1, heading_run), point.x) or heading_run
    anchor_top = max(0, line_y0 - 2)
    anchor = _rect(
        max(0, glyphs[0] - _PAD_PX),
        anchor_top,
        glyphs[1] - glyphs[0] + 1 + 2 * _PAD_PX,
        min(line_y1 + 2, row_top - 1) - anchor_top + 1,
        size,
    )
    inside = (
        anchor.x <= point.x < anchor.x + anchor.width
        and anchor.y <= point.y < anchor.y + anchor.height
    )
    origin = (
        point
        if inside
        else ClickPoint(x=anchor.x + anchor.width // 2, y=anchor.y + anchor.height // 2)
    )

    # ⛔ Only the LEFTMOST real column can be drilled into. Measured on
    # `tests/fixtures/overview-clean-1-row.png`: with one account left, the
    # account column holds no rhythm and the BALANCE column does, so the band
    # that wins is not the column of links. Clicking its centre would click an
    # amount. A 2px table border is not a column and does not count as leftmost
    # -- the loan result has one, 39px left of its first label.
    leftmost = next(
        (span for span in candidates if span[1] - span[0] + 1 >= _MIN_COLUMN_PX), key_span
    )
    if openable and key_span != leftmost:
        openable = False
        note += (
            f"; read-only: the rhythm is in the column at x={key_span[0]}, not the "
            f"leftmost column at x={leftmost[0]}, so a row cannot be opened by clicking it"
        )

    key_click_dx: int | None = None
    if openable:
        # The centre of the first row's ink in the KEY column. Clipped to that
        # column because two columns 2px apart merge into one span (ParaBank's
        # label/value blocks do), and the centre of a merged pair is the gutter
        # between them -- a click on nothing.
        cell = _containing(_spans(grey, row_top, row_top + pitch - 1), key_span[0]) or key_span
        cell = (max(cell[0], key_span[0]), min(cell[1], key_span[1]))
        key_click_dx = (cell[0] + cell[1]) // 2 - origin.x

    spec = PanelSpec(
        columns=columns,
        key_column=key_column,
        dx=left - origin.x,
        dy=row_top - origin.y,
        width=right + _PAD_PX - left,
        height=region_height,
        key_dx=key_span[0] - origin.x,
        key_dy=row_top - origin.y,
        key_width=key_span[1] - key_span[0] + 1,
        key_click_dx=key_click_dx,
        row_pitch=pitch,
    )
    proposal = PanelProposal(
        anchor=anchor,
        point=origin,
        spec=spec,
        rows=count,
        confidence=None if rhythm is None else rhythm.confidence,
        note=note,
    )
    return proposal, None


def marker_bands_contain_every_row(
    screenshot_png: bytes, proposal: PanelProposal
) -> tuple[str, ...]:
    """Every row's ink must sit inside the marker band of its own index.

    The offline half of the acceptance test. `table._check_alignment` asks a
    model the same question at replay and is the stronger check -- it sees rows,
    not just their ink -- but it costs a call and a running container, and it
    cannot run in the offline suite. This can, on a real screenshot.
    """
    grey = _grey(screenshot_png)
    spec = proposal.spec
    pitch = spec.row_pitch or 0
    key_x0 = proposal.point.x + spec.key_dx
    top = proposal.point.y + spec.key_dy
    band = grey[top : top + spec.height, key_x0 : key_x0 + spec.key_width]
    runs = [(top + s, top + e) for s, e in _runs(_ink(band).sum(axis=1) > 0, _LINE_GAP_PX)]

    faults: list[str] = []
    if len(runs) != proposal.rows:
        faults.append(f"{proposal.rows} rows were measured but the key column holds {len(runs)}")
    for index, (y0, y1) in enumerate(runs[: proposal.rows]):
        lo, hi = top + index * pitch, top + (index + 1) * pitch - 1
        if not (lo <= y0 and y1 <= hi):
            faults.append(f"row {index} ink y={y0}..{y1} is not inside its band y={lo}..{hi}")
    return tuple(faults)


# ---------------------------------------------------------------------------
# Discovery: read, place, ground, measure
# ---------------------------------------------------------------------------


def _identifier(text: str) -> str:
    """A column name a pydantic model can carry. `Available Amount` -> `available_amount`."""
    stem = "_".join("".join(c if c.isalnum() else " " for c in text).split()).lower()
    return stem.strip("_") or "column"


async def extract_panel_locators(
    inp: ScreenInput,
    *,
    vision: VisionCall,
    config: DiscoveryConfig | None = None,
) -> list[LocatedControl]:
    """Propose every `TABLE_CONTROL_PANEL` on this screen, measured not guessed.

    Model calls are allowed here; no browser action is. Mirrors
    `extract_control_locators`, and like it returns what it could not ground as
    `unresolved` with a reason rather than dropping it -- a region the model saw
    and geometry refused is a fact about the screen.
    """
    cfg = config or DiscoveryConfig()
    image = _decode(inp.screenshot_png, "screenshot")

    async def call[T: BaseModel](prompt: str, png: bytes, model: type[T], what: str) -> T:
        try:
            return await vision(prompt=prompt, image_png=png, response_model=model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise DiscoveryError(f"{what} failed: {type(exc).__name__}: {exc}") from exc

    seen = await call(_PANEL_READ_PROMPT, inp.screenshot_png, _SeenPanels, "panel read")
    if not seen.panels:
        return []

    overlay, cells = _grid_overlay(image, cfg.coarse_cell_px)
    listing = "\n".join(f"  {n}. {p.heading} -- {p.description}" for n, p in enumerate(seen.panels))
    placed = await call(
        _PANEL_LOCATE_PROMPT.format(headings=listing), overlay, _PanelPlacements, "panel placement"
    )
    cell_of = {p.index: p.cell_id for p in placed.placements}

    taken: set[str] = set()
    out: list[LocatedControl] = []
    for index, panel in enumerate(seen.panels):
        columns = tuple(dict.fromkeys(_identifier(c) for c in panel.columns))
        key = _identifier(panel.key_column)
        base = {
            "id": _unique(_slug(panel.heading, ControlRole.TABLE_CONTROL_PANEL), taken),
            "label": panel.heading,
            "role": ControlRole.TABLE_CONTROL_PANEL,
            "description": panel.description,
        }

        def refused(reason: str, base: dict = base) -> LocatedControl:
            return LocatedControl(**base, status="unresolved", reason=reason)

        if not columns or key not in columns:
            out.append(refused(f"key column {key!r} is not one of the columns read: {columns}"))
            continue

        cell = cell_of.get(index)
        if cell not in cells:
            out.append(
                refused(
                    "model read the region but gave no grid cell for its heading"
                    if cell is None
                    else f"cell {cell} is not on the coarse overlay"
                )
            )
            continue

        point, why = await _refine(
            image,
            cells[cell],
            f"the text {panel.heading!r} -- the heading of {panel.description}",
            cfg,
            vision,
        )
        if point is None:
            out.append(refused(why or "could not ground the heading"))
            continue

        proposal, why = derive_panel(
            inp.screenshot_png,
            point=point,
            columns=columns,
            key_column=key,
            openable=panel.rows_are_links,
        )
        if proposal is None:
            out.append(refused(why or "could not measure the region"))
            continue

        locator, why = _anchor_locator(inp, proposal)
        if locator is None:
            out.append(refused(why or "could not anchor on the heading"))
            continue

        faults = marker_bands_contain_every_row(inp.screenshot_png, proposal)
        if faults:
            out.append(
                refused("the measured geometry does not contain its own rows: " + "; ".join(faults))
            )
            continue

        out.append(
            LocatedControl(
                **{**base, "description": f"{panel.description} ({proposal.note})"},
                status="ready",
                click_point=proposal.point,
                locator=locator,
                panel=proposal.spec,
            )
        )
    return out


def _anchor_locator(
    inp: ScreenInput, proposal: PanelProposal
) -> tuple[VisualLocator | None, str | None]:
    """The heading, saved as pixels, and proved to find itself.

    Uniqueness is the check that matters: `ambiguous` on a repeated structure
    means the template matched more than one row, which is `docs/issues/0009`
    arriving through the anchor instead of through a grounded click.
    """
    try:
        locator = _make_locator(inp, proposal.anchor, proposal.point)
    except ValueError as exc:
        return None, f"cannot anchor on the heading: {exc}"
    check = locate_control(ResolveInput(screenshot_png=inp.screenshot_png, locator=locator))
    if check.status != "matched" or check.point is None:
        return None, f"the heading does not match its own pixels: {check.status} ({check.reason})"
    drift = max(abs(check.point.x - proposal.point.x), abs(check.point.y - proposal.point.y))
    if drift > _ANCHOR_DRIFT_PX:
        return None, f"the heading's self-match drifted {drift}px"
    return locator, None


def merge_panels(control_map: ScreenOutput, panels: list[LocatedControl]) -> ScreenOutput:
    """Add panels to a control map.

    A panel already in the map under the same id is REPLACED, so re-proposing a
    screen is idempotent rather than accumulating `..._2`, `..._3`. An id held by
    something that is not a panel is renamed instead -- two different controls
    cannot share an address.
    """
    replacing = {p.id for p in panels}
    surviving = [
        c
        for c in control_map.controls
        if not (c.id in replacing and c.role is ControlRole.TABLE_CONTROL_PANEL)
    ]
    taken = {c.id for c in surviving}
    merged: list[LocatedControl] = []
    for panel in panels:
        kept = (
            panel
            if panel.id not in taken
            else panel.model_copy(update={"id": _unique(panel.id, taken)})
        )
        taken.add(kept.id)
        merged.append(kept)
    return control_map.model_copy(update={"controls": [*surviving, *merged]})
