"""Screenshot in, reusable visual control locators out.

Finds where to click on a screen that offers no DOM, and records the target so
it can be found again later without a model.

WHY THIS EXISTS
===============

We measured three vision models estimating pixel coordinates for ParaBank's
login controls, scored against DOM ground truth:

    gpt-4o         mean error 143px    0/5 landed inside the control
    gpt-4.1        mean error 160px    1/5
    gpt-5.2-chat   mean error 155px    0/5      (2x the latency of gpt-4.1)

ParaBank's inputs are 15-22px tall, so a 45-80px vertical error is 3-5 control
heights: the click meant for Password lands on Username. Every control was
reported at 0.98 confidence, so the failure is silent. Model tier did not help
-- the newest model scored worst. Coordinate regression from an image is a
structural weakness, not a capability gap.

So we stop asking for coordinates. Code places numbered dots at known points;
the model picks a number. Regression becomes classification, and the arithmetic
error becomes exactly zero because code owns the number -> pixel mapping.

Replay then uses no model at all: the recorded patch is found by template
matching, and the click point is recovered from a saved offset.

THE THREE RECTANGLES PEOPLE CONFUSE
===================================

Measured on ParaBank's real login screen. The username input is 146x18 at
(293,305); its centre -- the click point -- is (366,314).

                          THE SCREEN
              x=293                    x=439
                |                        |
      y=294     |  Username              |      <- the only distinctive text
                +========================+
      y=305     |                        |      the username INPUT
      y=314     |           *            |      * = click point (366,314)
      y=323     +========================+      146 x 18 px

      y=342        Password
                +========================+
      y=353     |                        |      the password INPUT
      y=362     |           .            |      PIXEL-IDENTICAL to the one above
      y=371     +========================+


A. The control's own bounding box -- the intuitive choice, and it fails
-----------------------------------------------------------------------

                +========================+
      CROP ->   |                        |   146 x 18 of empty white box
                +========================+

      Searching the screen for it:
                +==========+  username   MATCH
                +==========+  password   MATCH   <- identical pixels
                +==========+  (a third)  MATCH
                                       ---------
                                       3 matches -> AMBIGUOUS, unusable

An empty field has no identity. Two empty boxes are the same box.


B. A small patch inside the field -- catastrophically worse
------------------------------------------------------------

                +------------+
      CROP ->   |            |   40 x 12 of pure white,  std = 0.000
                +------------+

      Searching the screen for it:
                every blank region       MATCH ... 1,103,249 times at score 1.0

A constant template scores a PERFECT 1.0 against every position, because
normalised correlation of a zero-variance patch is degenerate. It sails past any
threshold. This is why `_reject_constant_template` is load-bearing and not
hygiene, and why the discovery step must never crop the blank interior of a
field. Cheap detector: standard deviation. Blank patch std=0.000, a usable
context patch std=39.6.


C. The context patch -- deliberately LARGER than the control
--------------------------------------------------------------

              +--------------------------------------+  <- y=250
              |                                      |
              |   Customer Login                     |    two thirds of the
              |                                      |    height sits ABOVE
              |   Username         <-- THIS is what  |    the click point,
              |  +====================+   makes it   |    on purpose
              |  |         *          |   unique     |  <- click point
              |  +====================+              |
              |                                      |
              +--------------------------------------+  <- y=346
               240 x 96                  1 match -> UNIQUE

The patch is not the control. It is the control plus enough surroundings to be
unmistakable -- here, the word "Username". The label carries the identity; the
field carries none. That is why the patch reaches upward rather than hugging
the control.

Measured, same screen, same matcher:

    A. exact control bbox          146x18   std=74.789   peaks>=0.95: 3
    B. patch inside empty field     40x12   std= 0.000   peaks>=0.95: 1103249
    C. context patch               240x96   std=39.603   peaks>=0.95: 1   OK

Consequence for implementation: the spec's "one bounded expansion if the patch
is featureless or ambiguous" is not an edge case on this application. It is the
normal path for every input field.

HOW THE CLICK POINT SURVIVES
============================

The patch is what you FIND. The offset tells you where to click inside it.

      AT DISCOVERY (once, with the model)

            +------------------------+  <- crop origin (246, 250)
            |                        |
            |  Username              |     click_offset
            |  +==================+  |     = click_point - crop_origin
            |  |        *         |  |     = (366,314) - (246,250)
            |  +==================+  |     = (120, 64)
            +------------------------+
                                          SAVE: patch pixels + (120, 64)

      AT REPLAY (no model -- deterministic image matching)

       The page has shifted down 20px. Find the saved patch:

            +------------------------+  <- found at (246, 270)
            |                        |
            |  Username              |     click_point
            |  +==================+  |     = matched_origin + click_offset
            |  |        *         |  |     = (246,270) + (120,64)
            |  +==================+  |     = (366, 334)   follows the page
            +------------------------+

The CENTRE of the patch is NOT the click point -- it lands 32px up, inside the
label. That is precisely why the offset is stored separately rather than
clicking the middle of whatever matched.

WHAT THIS MODULE DOES NOT DO
============================

It maps visible controls on one frozen screenshot. It does not choose the next
action, click anything, or map an application. A patch match does not establish
workflow state and does not prove a control is enabled -- a matching-looking
control on the wrong screen is not permission to act. State is the caller's.

It also does not measure a control's boundary. A known point inside the target
is enough to click; it implies nothing about where the control ends.

LIMITS
======

V1 assumes one viewport size, zoom and rendering scale. It tolerates translation
of a sufficiently unchanged patch. It does NOT promise matching through scaling,
restyling, content change, or rearrangement within the patch.

That last one is a real tension with cross-tenant reuse (assignment 3.7): a
tenant that rebrands the CSS changes the pixels, and template matching is the
least portable locator there is. This design buys within-tenant precision at the
cost of cross-tenant portability. Argue it in REPORT.md rather than hide it.

Scores need empirical tuning. 0.95 is a starting value, not a 95% probability
of correctness.

Spec: docs/handoffs/claude-handoff-visual-controls.md
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from enum import StrEnum
from typing import Literal, Protocol, TypeVar

import cv2
import numpy as np
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from interfaceai.contracts import Contract

# A patch flatter than this matches everything at 1.0 -- module docstring, B.
_CONSTANT_STD = 1.0
# Peak search bounds, so a pathological response map cannot spin.
_MAX_PEAKS = 16
_NMS_SLACK = 0.10
# Enlargement for refinement overlays: readable for the model, bounded for cost.
_TARGET_ZOOM_PX = 900
_MAX_ZOOM = 8
# A rebuilt locator must recover its own point this closely on its own image.
_SELF_MATCH_TOLERANCE_PX = 2
# (size factor, fraction of height above the point). Ordered: reach up for a
# label first, then down for a control below a form, then centred, then bigger.
_PATCH_PLACEMENTS = ((1.0, 2 / 3), (1.0, 1 / 3), (1.0, 1 / 2), (1.5, 2 / 3), (1.5, 1 / 3))
# Never accept a grounded point from a grid coarser than this. A dot cannot be
# inside a control shorter than the dot spacing, so at coarser resolutions a
# `click` is not a wrong answer by the model -- it is an answer we should not
# have asked for. Measured: ParaBank's inputs are 18px tall; round 1 spacing is
# 30px, and 0 dots landed inside the password field. See _refine.
_MIN_TRUSTED_DOT_SPACING_PX = 12


class ControlRole(StrEnum):
    TEXTBOX = "textbox"
    BUTTON = "button"
    LINK = "link"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    UNKNOWN = "unknown"


class ClickPoint(Contract):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class ImageSize(Contract):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CropBox(Contract):
    # Original screenshot pixels. Right/bottom are exclusive:
    # (x, y, x + width, y + height).
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ScreenInput(Contract):
    screenshot_png: bytes = Field(repr=False)
    coordinate_space: Literal["viewport_css_pixels"] = "viewport_css_pixels"


class VisualLocator(Contract):
    schema_version: Literal[1] = 1
    template_png: bytes = Field(repr=False)
    reference_size: ImageSize
    reference_crop: CropBox
    # Relative to the template's top-left, not the full screenshot.
    click_offset: ClickPoint
    # Starting values to evaluate, not calibrated probabilities.
    match_threshold: float = Field(default=0.95, gt=0, le=1)
    ambiguity_margin: float = Field(default=0.05, ge=0, le=1)


class LocatedControl(Contract):
    id: str = Field(min_length=1)  # Unique within this saved map.
    label: str | None
    role: ControlRole
    description: str = Field(min_length=1)
    status: Literal["ready", "unresolved"]
    click_point: ClickPoint | None = None
    locator: VisualLocator | None = None
    reason: str | None = None


class ScreenOutput(Contract):
    schema_version: Literal[1] = 1
    screenshot_sha256: str
    image_size: ImageSize
    controls: list[LocatedControl]


class DiscoveryConfig(Contract):
    coarse_cell_px: int = Field(default=80, ge=16)
    # DEVIATION FROM SPEC: 8, not 5. With the spec's defaults the dot spacing
    # per refinement round is 48 -> 28.8 -> 17.3 -> 10.4 px. The prompt tells
    # the model to click only when a dot is SAFELY inside, away from borders,
    # which on an 18px field needs spacing <= ~9px. So a correctly-behaving
    # model keeps returning `zoom`, exhausts max_refinements=4, and reports
    # `unresolved` -- failing on the login screen for exactly the right reason,
    # which is the worst kind of bug. At grid=8 the spacing runs
    # 30 -> 11.2 -> 4.2 px: safely inside by round 3, and fewer calls.
    fine_grid_size: int = Field(default=8, ge=2, le=10)
    max_refinements: int = Field(default=4, ge=1, le=6)
    max_concurrency: int = Field(default=4, ge=1, le=16)
    call_timeout_seconds: float = Field(default=30, gt=0)
    context_width: int = Field(default=240, ge=16)
    context_height: int = Field(default=96, ge=16)

    # --- Tiled inventory (prototype; see docs/issues/0001-incomplete-inventory.md)
    #
    # One broad "list every control" call over a 192-cell grid is the worst-shaped
    # task available, and it measures that way: 24/19/24 controls from identical
    # bytes. Tiling into a few narrow questions gave 27/27/26 -- spread 1 against
    # 5. Parameterised so the comparison can be replicated and swept rather than
    # re-derived from a scratchpad script.
    #
    # Report zones tile the screen EXACTLY (no overlap); only the context margin
    # overlaps. A control is reported by the one tile whose zone contains its
    # centre, so nothing is lost at a boundary and nothing is double-counted.
    tile_cols: int = Field(default=2, ge=1, le=8)
    tile_rows: int = Field(default=3, ge=1, le=8)
    # Context shown around each zone, as a fraction of the zone. Large enough
    # that a label just outside the zone is still readable.
    tile_margin: float = Field(default=0.35, ge=0, le=1)
    # Enlargement cap for a tile. Lower values trade legibility for cost, which
    # is the knob to sweep when tuning scan resolution.
    tile_max_zoom: int = Field(default=4, ge=1, le=8)
    tile_target_px: int = Field(default=900, ge=200, le=2000)


class ResolveInput(Contract):
    screenshot_png: bytes = Field(repr=False)
    locator: VisualLocator
    coordinate_space: Literal["viewport_css_pixels"] = "viewport_css_pixels"


class ResolveOutput(Contract):
    status: Literal["matched", "not_found", "ambiguous", "incompatible"]
    point: ClickPoint | None = None
    score: float | None = None  # Matching score, never a probability.
    matched_crop: CropBox | None = None
    reason: str | None = None


T = TypeVar("T", bound=BaseModel)


class VisionCall(Protocol):
    async def __call__(
        self,
        *,
        prompt: str,
        image_png: bytes,
        response_model: type[T],
    ) -> T:
        """Use the configured model and validate its structured response."""
        ...


class DiscoveryError(RuntimeError):
    """The coarse inventory call failed.

    Distinct from an empty screen: never report a failed call as "no controls
    are visible".
    """


# ---------------------------------------------------------------------------
# Private helpers: images and geometry
# ---------------------------------------------------------------------------


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _decode(png: bytes, what: str) -> Image.Image:
    if not png:
        raise ValueError(f"{what} is empty")
    try:
        image = Image.open(io.BytesIO(png))
        image.load()
    except Exception as exc:
        raise ValueError(f"{what} is not a decodable image: {exc}") from exc
    return image.convert("RGB")


def _rect(x: int, y: int, width: int, height: int, size: ImageSize) -> CropBox:
    """Build a CropBox from a possibly out-of-bounds rectangle, clipped to fit.

    Clamping happens on plain ints because CropBox validates `ge=0` at
    construction: a context patch wanted around a control near the top edge has
    a negative y BEFORE clipping, so building it first raises instead of
    clipping. That was a real crash on ParaBank's nav row.

    >>> size = ImageSize(width=100, height=100)
    >>> _rect(-20, -10, 40, 30, size).model_dump()
    {'x': 0, 'y': 0, 'width': 20, 'height': 20}
    >>> _rect(90, 90, 40, 30, size).model_dump()
    {'x': 90, 'y': 90, 'width': 10, 'height': 10}
    """
    right, bottom = x + width, y + height
    x, y = max(0, min(x, size.width - 1)), max(0, min(y, size.height - 1))
    return CropBox(
        x=x,
        y=y,
        width=max(1, min(right, size.width) - x),
        height=max(1, min(bottom, size.height) - y),
    )


def _clip(box: CropBox, size: ImageSize) -> CropBox:
    """Clamp an already-valid box to the image."""
    return _rect(box.x, box.y, box.width, box.height, size)


def _crop(image: Image.Image, box: CropBox) -> Image.Image:
    return image.crop((box.x, box.y, box.x + box.width, box.y + box.height))


def _is_effectively_constant(gray: np.ndarray) -> bool:
    """A flat patch matches EVERYTHING at score 1.0 -- see module docstring, B."""
    return float(gray.std()) < _CONSTANT_STD


def _make_locator(screen: ScreenInput, crop: CropBox, point: ClickPoint) -> VisualLocator:
    """Crop clean pixels and record the click point as an offset into them.

    >>> from PIL import Image
    >>> canvas = Image.new("RGB", (100, 80), "white")
    >>> screen = ScreenInput(screenshot_png=_png_bytes(canvas))
    >>> loc = _make_locator(screen, CropBox(x=10, y=20, width=40, height=30),
    ...                     ClickPoint(x=25, y=35))
    >>> loc.click_offset.model_dump()
    {'x': 15, 'y': 15}
    >>> loc.reference_size.model_dump()
    {'width': 100, 'height': 80}
    """
    image = _decode(screen.screenshot_png, "screenshot")
    size = ImageSize(width=image.width, height=image.height)

    if crop.x + crop.width > size.width or crop.y + crop.height > size.height:
        raise ValueError(f"crop {crop.model_dump()} exceeds image {size.model_dump()}")
    if not (crop.x <= point.x < crop.x + crop.width and crop.y <= point.y < crop.y + crop.height):
        raise ValueError(f"click point {point.model_dump()} is outside crop {crop.model_dump()}")

    return VisualLocator(
        template_png=_png_bytes(_crop(image, crop)),
        reference_size=size,
        reference_crop=crop,
        click_offset=ClickPoint(x=point.x - crop.x, y=point.y - crop.y),
    )


# ---------------------------------------------------------------------------
# Replay: deterministic, no model
# ---------------------------------------------------------------------------


def _fail(status: str, reason: str) -> ResolveOutput:
    return ResolveOutput(status=status, reason=reason)


def locate_control(inp: ResolveInput) -> ResolveOutput:
    """Find a saved template and its click point in the current screenshot.

    This function must not call a model or perform browser actions.
    """
    screen = _decode(inp.screenshot_png, "screenshot")
    template = _decode(inp.locator.template_png, "template")
    ref = inp.locator.reference_size

    if (screen.width, screen.height) != (ref.width, ref.height):
        return _fail(
            "incompatible",
            (
                f"viewport is {screen.width}x{screen.height}, locator was recorded at "
                f"{ref.width}x{ref.height}. Same dimensions would not prove equal zoom; "
                "different ones rule out a comparable render."
            ),
        )

    crop = inp.locator.reference_crop
    if (template.width, template.height) != (crop.width, crop.height):
        return _fail(
            "incompatible",
            (
                f"template is {template.width}x{template.height} but reference_crop is "
                f"{crop.width}x{crop.height} -- corrupt artifact"
            ),
        )
    if template.width > screen.width or template.height > screen.height:
        return _fail("incompatible", "template is larger than the screenshot")

    haystack = np.asarray(screen.convert("L"))
    needle = np.asarray(template.convert("L"))

    # Before normalisation, not after: a flat template correlates perfectly with
    # every position, so it would be accepted everywhere rather than rejected.
    if _is_effectively_constant(needle):
        return _fail(
            "incompatible",
            (
                f"template is effectively constant (std={needle.std():.3f}); it would "
                "match every uniform region at score 1.0. Re-record with more context."
            ),
        )

    with np.errstate(all="ignore"):
        scores = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    scores = np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)

    peaks = _peaks(scores, needle.shape[1], needle.shape[0], inp.locator.match_threshold)
    if not peaks:
        return _fail(
            "not_found",
            (
                f"best score {float(scores.max()):.4f} is below threshold "
                f"{inp.locator.match_threshold}"
            ),
        )

    best_score, (bx, by) = peaks[0]
    if len(peaks) > 1:
        runner_up = peaks[1][0]
        if (
            runner_up >= inp.locator.match_threshold
            or (best_score - runner_up) < inp.locator.ambiguity_margin
        ):
            return _fail(
                "ambiguous",
                (
                    f"{len(peaks)} distinct candidates; best {best_score:.4f}, "
                    f"next {runner_up:.4f} (margin {inp.locator.ambiguity_margin})"
                ),
            )

    point = ClickPoint(x=bx + inp.locator.click_offset.x, y=by + inp.locator.click_offset.y)
    if not (0 <= point.x < screen.width and 0 <= point.y < screen.height):
        return _fail(
            "not_found", f"recovered point {point.model_dump()} falls outside the viewport"
        )

    return ResolveOutput(
        status="matched",
        point=point,
        score=best_score,
        matched_crop=CropBox(x=bx, y=by, width=needle.shape[1], height=needle.shape[0]),
    )


def _peaks(
    scores: np.ndarray, tw: int, th: int, threshold: float
) -> list[tuple[float, tuple[int, int]]]:
    """Distinct match locations, best first.

    Non-maximum suppression: one real match lights up a cluster of neighbouring
    response pixels, so take the best, blank a template-sized box around it, and
    repeat. That keeps two genuinely duplicated controls apart while collapsing
    the halo around a single one.
    """
    work = scores.copy()
    found: list[tuple[float, tuple[int, int]]] = []
    for _ in range(_MAX_PEAKS):
        best = float(work.max())
        if best < threshold - _NMS_SLACK:
            break
        y, x = np.unravel_index(int(work.argmax()), work.shape)
        found.append((best, (int(x), int(y))))
        y0, y1 = max(0, y - th // 2), min(work.shape[0], y + th // 2 + 1)
        x0, x1 = max(0, x - tw // 2), min(work.shape[1], x + tw // 2 + 1)
        work[y0:y1, x0:x1] = -1.0
    return [p for p in found if p[0] >= threshold]


# ---------------------------------------------------------------------------
# Discovery: overlays, prompts, refinement
# ---------------------------------------------------------------------------


class _CoarseControl(BaseModel):
    label: str | None = None
    role: ControlRole = ControlRole.UNKNOWN
    description: str
    # None means "identified but not located" -- returned as unresolved, never dropped.
    cell_id: int | None = None


class _CoarseInventory(BaseModel):
    controls: list[_CoarseControl]


class _Refinement(BaseModel):
    action: Literal["click", "zoom", "unresolved"]
    number: int | None = None
    reason: str | None = None


_COARSE_PROMPT = """\
This image is a screenshot of a business application with a numbered grid drawn
on top of it by our tooling. The numbers are an annotation, not page content.

List every INTERACTIVE control you can see: links, buttons, text fields,
checkboxes, radio buttons, dropdowns. Ignore static text, images and layout.

For each one give:
- label: the visible text on it, or the text immediately labelling it, verbatim
- role: what the control is
- description: enough to tell it apart from similar controls on this screen
- cell_id: the number of the grid cell containing the control's centre

Do not give pixel coordinates or percentages. If you can see a control but
cannot say which cell it is in, set cell_id to null. Do not invent controls that
an application like this usually has but this screenshot does not show.
"""

_FINE_PROMPT = """\
This is an enlarged region of a screenshot, with numbered dots drawn on it by
our tooling. The numbers are annotation, not page content.

Target: {description}

Return the number whose DOT is inside the target, not a number whose printed
text merely overlaps it. The dot must sit safely inside the control, away from
its borders -- we will click exactly there.

- click(number): a dot is safely inside the target.
- zoom(number):  no dot is safely inside, but the target is in or near that
                 cell. We will enlarge around it and ask again.
- unresolved(reason): the target is not visible here, or cannot be told apart
                 from something similar.
"""


def _grid_overlay(image: Image.Image, cell_px: int) -> tuple[bytes, dict[int, CropBox]]:
    """Number every cell of a coarse grid. Returns the overlay and the mapping.

    The mapping is code-owned, so turning a chosen number into pixels is a
    dictionary lookup rather than arithmetic the model performs.
    """
    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    cells: dict[int, CropBox] = {}
    n = 0
    for top in range(0, image.height, cell_px):
        for left in range(0, image.width, cell_px):
            n += 1
            box = _rect(
                left, top, cell_px, cell_px, ImageSize(width=image.width, height=image.height)
            )
            cells[n] = box
            draw.rectangle(
                [left, top, left + box.width - 1, top + box.height - 1],
                outline=(255, 0, 0),
            )
            label = str(n)
            draw.rectangle(
                [left + 1, top + 1, left + 8 * len(label) + 4, top + 14], fill=(255, 255, 0)
            )
            draw.text((left + 3, top + 2), label, fill=(0, 0, 0))
    return _png_bytes(marked), cells


def _dot_overlay(
    image: Image.Image, box: CropBox, grid_size: int
) -> tuple[bytes, dict[int, ClickPoint], dict[int, CropBox]]:
    """Enlarge a region and place numbered dots at cell centres.

    Points are generated in ORIGINAL screenshot coordinates first and then
    projected onto the enlarged view, so no rounding travels back the other way.
    """
    crop = _crop(image, box)
    scale = max(1, min(_MAX_ZOOM, _TARGET_ZOOM_PX // max(1, box.width)))
    view = crop.resize((box.width * scale, box.height * scale), Image.LANCZOS)
    draw = ImageDraw.Draw(view)

    points: dict[int, ClickPoint] = {}
    subcells: dict[int, CropBox] = {}
    n = 0
    cw, ch = box.width / grid_size, box.height / grid_size
    for row in range(grid_size):
        for col in range(grid_size):
            n += 1
            ox = box.x + int((col + 0.5) * cw)
            oy = box.y + int((row + 0.5) * ch)
            points[n] = ClickPoint(x=ox, y=oy)
            subcells[n] = _rect(
                box.x + int(col * cw),
                box.y + int(row * ch),
                max(1, int(cw)),
                max(1, int(ch)),
                ImageSize(width=image.width, height=image.height),
            )
            vx, vy = (ox - box.x) * scale, (oy - box.y) * scale
            draw.ellipse(
                [vx - 4, vy - 4, vx + 4, vy + 4], fill=(255, 0, 0), outline=(255, 255, 255)
            )
            draw.text(
                (vx + 6, vy - 6),
                str(n),
                fill=(255, 0, 0),
                stroke_width=2,
                stroke_fill=(255, 255, 255),
            )
    return _png_bytes(view), points, subcells


def _neighbourhood(box: CropBox, size: ImageSize) -> CropBox:
    """The cell plus its eight neighbours, clipped.

    Load-bearing: the coarse cell may be wrong by up to a cell, because that is
    the scale of error we measured in coordinate estimates. The 3x3 window is
    what absorbs it.

    >>> _neighbourhood(CropBox(x=0, y=0, width=80, height=80),
    ...                ImageSize(width=1280, height=900)).model_dump()
    {'x': 0, 'y': 0, 'width': 160, 'height': 160}
    """
    return _rect(box.x - box.width, box.y - box.height, box.width * 3, box.height * 3, size)


async def _refine(
    image: Image.Image,
    start: CropBox,
    description: str,
    cfg: DiscoveryConfig,
    vision: VisionCall,
) -> tuple[ClickPoint | None, str | None]:
    """Narrow a coarse region to one grounded point, or say why not."""
    size = ImageSize(width=image.width, height=image.height)
    box = _neighbourhood(start, size)

    for _attempt in range(cfg.max_refinements):
        overlay, points, subcells = _dot_overlay(image, box, cfg.fine_grid_size)
        spacing = max(1, box.height // cfg.fine_grid_size)
        try:
            async with asyncio.timeout(cfg.call_timeout_seconds):
                reply = await vision(
                    prompt=_FINE_PROMPT.format(description=description),
                    image_png=overlay,
                    response_model=_Refinement,
                )
        except TimeoutError:
            return None, f"refinement timed out after {cfg.call_timeout_seconds}s"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one control failing is not fatal
            return None, f"refinement call failed: {type(exc).__name__}: {exc}"

        if reply.action == "unresolved":
            return None, reply.reason or "model reported unresolved"
        if reply.number not in points:
            return None, f"model chose dot {reply.number!r}, not on this overlay"

        # Code owns the resolution decision in both directions; the model only
        # points. Two symmetric rules, both measured on ParaBank's 18px inputs:
        #
        #   too coarse -> do not trust a `click`. At round 1 the dots are 30px
        #     apart, so ZERO dots can be inside an 18px field. A click there is
        #     not a wrong answer by the model, it is an answer we should not
        #     have asked for. Its chosen dot still says which CELL, so we zoom.
        #
        #   fine enough -> do not honour a `zoom`. Measured: at round 2 (11px
        #     spacing, 16 dots inside the field) the model asked to zoom while
        #     pointing at y=369, which was inside. Obeying it meant round 3 on a
        #     33x33px fragment, where the model could no longer tell what it was
        #     looking at and returned unresolved. Magnifying past the point of
        #     recognition destroys the context the answer depends on.
        if spacing <= _MIN_TRUSTED_DOT_SPACING_PX:
            return points[reply.number], None

        nxt = _neighbourhood(subcells[reply.number], size)
        if nxt.width >= box.width and nxt.height >= box.height:
            return None, f"cannot narrow further than {box.width}x{box.height}px"
        box = nxt

    return None, (
        f"exhausted {cfg.max_refinements} refinements without reaching a dot "
        f"spacing of {_MIN_TRUSTED_DOT_SPACING_PX}px or finer"
    )


def _slug(label: str | None, role: ControlRole) -> str:
    """A stable id derived from what the control IS, not where it appeared.

    Positional ids were not stable across runs: the same screenshot inventoried
    15, 24 and 22 controls on three consecutive runs, so `c007` was a different
    control each time -- unique within a run and useless across them. A slug
    from the visible label survives that, and matches the naming a human would
    choose anyway.

    >>> _slug("Transfer Funds", ControlRole.LINK)
    'transfer_funds_link'
    >>> _slug("Log In", ControlRole.BUTTON)
    'log_in_button'
    >>> _slug(None, ControlRole.TEXTBOX)
    'textbox'
    >>> _slug("Account #12345!", ControlRole.LINK)
    'account_12345_link'
    """
    base = "".join(c if c.isalnum() else " " for c in (label or "")).split()
    stem = "_".join(w.lower() for w in base)[:40].strip("_")
    return f"{stem}_{role.value}" if stem else role.value


def _unique(slug: str, taken: set[str]) -> str:
    """Disambiguate genuine duplicates (two 'Read More' links) by position."""
    if slug not in taken:
        taken.add(slug)
        return slug
    n = 2
    while f"{slug}_{n}" in taken:
        n += 1
    taken.add(f"{slug}_{n}")
    return f"{slug}_{n}"


def _context_patch(
    point: ClickPoint, w: int, h: int, size: ImageSize, *, above: float = 2 / 3
) -> CropBox:
    """A patch around the point, with `above` of its height above the point.

    `above=2/3` reaches up for a label (an input field carries no identity of
    its own); `above=1/3` reaches down, for a control below a form whose fields
    will change; `above=1/2` is centred. See module docstring and _locator_for.

    >>> size = ImageSize(width=1000, height=1000)
    >>> _context_patch(ClickPoint(x=500, y=500), 240, 96, size).model_dump()
    {'x': 380, 'y': 436, 'width': 240, 'height': 96}
    >>> _context_patch(ClickPoint(x=500, y=500), 240, 96, size, above=1/3).model_dump()
    {'x': 380, 'y': 468, 'width': 240, 'height': 96}
    """
    return _rect(point.x - w // 2, point.y - int(h * above), w, h, size)


def _overlap(a: CropBox, b: CropBox) -> int:
    """Area shared by two boxes, in pixels.

    >>> _overlap(CropBox(x=0, y=0, width=10, height=10),
    ...          CropBox(x=5, y=5, width=10, height=10))
    25
    >>> _overlap(CropBox(x=0, y=0, width=10, height=10),
    ...          CropBox(x=50, y=50, width=10, height=10))
    0
    """
    w = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    h = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    return max(0, w) * max(0, h)


def _choose_landmark(
    screen: ScreenInput,
    point: ClickPoint,
    cfg: DiscoveryConfig,
    size: ImageSize,
    unstable_regions: list[CropBox] | None = None,
) -> tuple[VisualLocator | None, str | None]:
    """Choose the landmark that will be used to find this control again.

    A LANDMARK is a patch of the screen around the click point, saved as pixels.
    At replay we find the landmark and step back to the control by a recorded
    offset. It is not a picture of the control -- an empty text field has no
    identity of its own, so the landmark deliberately reaches beyond it to
    capture something distinctive nearby, usually a label.

    A good landmark is both UNIQUE (it appears once on the screen) and STABLE
    (its pixels will still look like that later). Uniqueness can be checked here;
    stability cannot, so it is inferred from which regions hold controls whose
    contents change.

    Five placements are tried. Measured on ParaBank, the click point is inside
    the Log In button and both candidates are unique:

          UP-reaching landmark                DOWN-reaching landmark
       +-----------------------+
       |  Password             |
       |  +-----------------+  |
       |  |                 |  |  <- contents change
       |  +-----------------+  |       +-----------------------+
       |    +----------+       |       |    +----------+       |
       |    |  LOG IN  |       |       |    |  LOG IN  |       |
       |    |    *     |       |       |    |    *     |       |
       |    +----------+       |       |    +----------+       |
       +-----------------------+       |  Forgot login info?   |
                                       |  Register             |
        unique?  YES                   +-----------------------+
        stable?  NO   rejected
                                        unique?  YES
                                        stable?  YES  chosen

       * = the click point, inside the button. The landmark surrounds it; the
           recorded offset is what steps from landmark corner back to the point.

    Uniqueness alone cannot choose between these -- both are unique on the
    discovery screenshot, where the form is empty. That is the whole trap: the
    upward landmark self-matched at 1.0000 and then scored 0.8150 once anything
    was typed, so the button became unfindable mid-login. Hence the second test.

    Verifying here is cheap; discovering at replay that a landmark was
    featureless or unstable is not.
    """
    unstable_regions = unstable_regions or []
    last = "no patch attempted"
    usable: list[tuple[int, VisualLocator]] = []

    for factor, bias in _PATCH_PLACEMENTS:
        w, h = int(cfg.context_width * factor), int(cfg.context_height * factor)
        crop = _context_patch(point, w, h, size, above=bias)
        try:
            locator = _make_locator(screen, crop, point)
        except ValueError as exc:
            last = str(exc)
            continue
        check = locate_control(ResolveInput(screenshot_png=screen.screenshot_png, locator=locator))
        if check.status != "matched" or check.point is None:
            last = f"self-match returned {check.status}: {check.reason}"
            continue
        drift = max(abs(check.point.x - point.x), abs(check.point.y - point.y))
        if drift > _SELF_MATCH_TOLERANCE_PX:
            last = f"self-match drifted {drift}px"
            continue
        usable.append((sum(_overlap(crop, r) for r in unstable_regions), locator))

    if usable:
        # Among placements that are unique, prefer the one overlapping the least
        # VOLATILE content. The self-check proves a patch is unambiguous on the
        # discovery image; it cannot know that an empty text field will not stay
        # empty. Measured on ParaBank: the Log In patch reached upward, swallowed
        # the password field, self-matched at 1.0000 on the empty form -- and
        # stopped matching (0.8150) the moment anything was typed, mid-login.
        usable.sort(key=lambda pair: pair[0])
        return usable[0][1], None

    return None, f"no distinctive patch around the point ({last})"


async def extract_control_locators(
    inp: ScreenInput,
    *,
    vision: VisionCall,
    config: DiscoveryConfig | None = None,
    only: list[str] | None = None,
) -> ScreenOutput:
    """Discover visible controls and construct reusable visual locators.

    Model calls are allowed here. This function performs no browser actions.

    `only` is a DEVIATION FROM SPEC, added for cost. The coarse inventory always
    runs -- it is one call and it is what names the controls. Refinement then
    runs only on the listed ids; the rest are returned `unresolved` with reason
    "not requested", which the spec's own rule already permits since unresolved
    entries must be preserved rather than dropped. Omit it for V1 behaviour.

    Measured motivation: ParaBank's overview screen inventories 19 controls at
    16-34s per vision call. Refining all of them costs ~20 calls per screen; a
    three-control goal needs three.
    """
    cfg = config or DiscoveryConfig()
    image = _decode(inp.screenshot_png, "screenshot")
    size = ImageSize(width=image.width, height=image.height)

    overlay, cells = _grid_overlay(image, cfg.coarse_cell_px)
    try:
        inventory = await vision(
            prompt=_COARSE_PROMPT, image_png=overlay, response_model=_CoarseInventory
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Never report a failed call as "this screen has no controls".
        raise DiscoveryError(f"coarse inventory failed: {type(exc).__name__}: {exc}") from exc

    wanted = set(only) if only is not None else None
    semaphore = asyncio.Semaphore(cfg.max_concurrency)

    taken: set[str] = set()
    ids = [_unique(_slug(c.label, c.role), taken) for c in inventory.controls]

    # Regions whose PIXELS change once the flow runs -- an empty field does not
    # stay empty. A landmark overlapping one is recorded blank at discovery and
    # stops matching the moment it is filled.
    unstable_regions = [
        cells[c.cell_id]
        for c in inventory.controls
        if c.cell_id in cells and c.role in (ControlRole.TEXTBOX, ControlRole.SELECT)
    ]

    async def resolve_one(control_id: str, found: _CoarseControl) -> LocatedControl:
        base = {
            "id": control_id,
            "label": found.label,
            "role": found.role,
            "description": found.description,
        }

        if wanted is not None and control_id not in wanted:
            return LocatedControl(**base, status="unresolved", reason="not requested")
        if found.cell_id is None:
            return LocatedControl(
                **base, status="unresolved", reason="model identified the control but gave no cell"
            )
        if found.cell_id not in cells:
            return LocatedControl(
                **base,
                status="unresolved",
                reason=f"cell {found.cell_id} is not on the coarse overlay",
            )

        async with semaphore:
            point, why = await _refine(image, cells[found.cell_id], found.description, cfg, vision)
        if point is None:
            return LocatedControl(**base, status="unresolved", reason=why)

        locator, why = _choose_landmark(inp, point, cfg, size, unstable_regions)
        if locator is None:
            return LocatedControl(**base, status="unresolved", reason=why)

        return LocatedControl(**base, status="ready", click_point=point, locator=locator)

    controls = await asyncio.gather(
        *(resolve_one(i, c) for i, c in zip(ids, inventory.controls, strict=True))
    )
    return ScreenOutput(
        screenshot_sha256=hashlib.sha256(inp.screenshot_png).hexdigest(),
        image_size=size,
        controls=list(controls),
    )
