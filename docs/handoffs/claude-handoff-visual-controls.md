# Claude Code handoff: screenshot to reusable visual control locators

Implement this in **one Python module: `visual_controls.py`**. Keep the Pydantic models, prompts, numbered overlays, crop geometry, discovery orchestration, template matcher, and doctests together. Use the project's existing model client through the small injected interface below. Do not turn this into a package or introduce a new workflow framework.

This is an implementation specification. The function bodies in the contract are intentionally unfinished; the doctest is an acceptance test for the completed implementation.

## 1. Context and intended result

We are building the visual targeting part of the interface.ai Computer-Use Automation assignment. Discovery uses an LLM to operate a real UI and records a reusable capability. Replay executes the recorded actions without LLM decisions. We cannot assume a useful DOM.

Our experiments found that models recognized ParaBank controls but often predicted coordinates too inaccurately to click thin input fields. We want the model to **select a numbered point that code has already placed**, rather than estimate numerical coordinates.

The agreed pipeline is:

1. Read one frozen screenshot and inventory its visible controls in one coarse model call.
2. Refine each control's coarse region using numbered dots on enlarged crops. Run independent refinements concurrently, with a limit.
3. Translate selected dot IDs into exact coordinates in the original screenshot using code-owned mappings.
4. Crop an unmarked reference patch around each selected point, including distinctive nearby context where possible.
5. Return a typed control map containing the point and reusable visual locator for each successfully resolved control.
6. On a later screenshot, use deterministic image matching to locate the patch and recover the click point from its saved offset. No LLM call on this path.

**Business input: one screenshot. Business output: a control map with visual locators.** The model client and tuning configuration are dependencies, not additional user input. Discovery maps visible controls; it does not select the next workflow action, click anything, or map an entire application.

This is a design to implement and evaluate, not a claim of demonstrated reliability. A precise coordinate lookup does not guarantee that the model selected the right dot or identified every control.

## 2. Assignment mapping and limits

| Assignment requirement | This module contributes | The surrounding system still owns |
| --- | --- | --- |
| 3.1: LLM-driven observe, decide, act on a real UI | Screenshot observation and LLM-based target grounding | Goal selection, action planning, live execution, stopping conditions |
| 3.2: typed, versioned artifact and robust control identification | Serializable, versioned control map and visual locators | Ordered actions, typed invocation parameters and outputs, checkpoints |
| 3.3: stable targeting and replay without LLM decisions | Deterministic template matching with explicit match failures | Branches, waits/retries, business outcomes, success verification |
| 3.4: allowlist and sensitive-data handling | No browser actions; byte fields excluded from normal model repr | Action policy, approval, safe screenshot/template persistence |
| 3.5: evidence | Source screenshot hash, crop rectangles, dot selections, matcher scores | Redacted run logs and failure screenshots/traces |
| 3.6: human handoff | Explicit unresolved/ambiguous results that can trigger escalation | Pausing, transferring the live session, recording human actions, resuming |
| 3.7: surface abstraction | Image-based contracts independent of HTML selectors | Screenshot acquisition and coordinate conversion for other surfaces |

V1 assumes the same viewport size, zoom, and rendering scale. It tolerates translation of a sufficiently unchanged reference patch. It does not promise matching through arbitrary scaling, restyling, content changes, or rearrangement within the patch. A patch match does not establish the current workflow state or prove a control is enabled.

## 3. Public signature and Pydantic contract

Use Python 3.11+, Pydantic v2 with `val_json_bytes` support, Pillow, NumPy, and `opencv-python-headless`. Keep Playwright in the caller. Reuse the existing LLM SDK instead of adding a second client stack.

The main signature is:

`async build_control_map(inp: ScreenInput, *, vision: VisionCall, config: DiscoveryConfig | None = None) -> ScreenOutput`

The downstream replay signature is:

`resolve_control(inp: ResolveInput) -> ResolveOutput`

Use this contract in `visual_controls.py`, and implement the two bodies. Private helper models/functions belong in the same module. Add the cross-field and image validations specified after this block.

```python
from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


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
    fine_grid_size: int = Field(default=5, ge=2, le=10)
    max_refinements: int = Field(default=4, ge=1, le=6)
    max_concurrency: int = Field(default=4, ge=1, le=16)
    call_timeout_seconds: float = Field(default=30, gt=0)
    context_width: int = Field(default=240, ge=16)
    context_height: int = Field(default=96, ge=16)


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


async def build_control_map(
    inp: ScreenInput,
    *,
    vision: VisionCall,
    config: DiscoveryConfig | None = None,
) -> ScreenOutput:
    """Discover visible controls and construct reusable visual locators.

    LLM calls are allowed here. This function performs no browser actions.
    """
    raise NotImplementedError


def resolve_control(inp: ResolveInput) -> ResolveOutput:
    """Find a saved template and its click point in the current screenshot.

    This function must not call an LLM or perform browser actions.
    """
    raise NotImplementedError
```

Required validation:

- `ready` requires a click point and locator, and no failure reason. `unresolved` requires a reason and exposes neither a click point nor a locator. Preserve unresolved inventory entries rather than silently dropping them.
- `matched` requires a point, score, and matched crop. Every other replay status has a reason and no actionable point/crop.
- Decode PNGs, reject invalid/empty images, check every crop/point against actual dimensions, and require the template dimensions to equal the reference crop dimensions.
- Require `0 <= click_offset.x < crop.width` and the equivalent for y. For a ready control, `click_point == reference_crop.origin + click_offset`.
- Control IDs must be unique. Assign `c001`, `c002`, etc. in inventory order in code; these are references within an artifact, not universal IDs across discoveries.
- Use Pydantic model validators for cross-field rules. Invalid inputs/corrupt artifacts raise a clear validation error. A valid image with no usable match returns a typed replay status.
- Infer screenshot dimensions from the PNG. The coordinate-space field declares a caller precondition; image decoding cannot independently verify browser zoom or CSS scale.

## 4. Coordinates: one source of truth

The caller captures `await page.screenshot(type="png", scale="css", full_page=False)` at fixed viewport size and zoom. No browser toolbar, full-page capture, or external image resizing is allowed for V1 input.

All returned points refer to the original screenshot's top-left. With that capture contract they are also Playwright viewport CSS coordinates. Refinement zoom only enlarges an image for the model; it never changes browser zoom.

For each overlay, retain the exact mapping from its number to an original-image point and/or crop rectangle. Prefer generating integer points in source coordinates and projecting them onto the enlarged view. That makes selection a dictionary lookup instead of model-generated arithmetic. IDs are scoped to one overlay; never share a mutable mapping between concurrent refinements.

When conversion is needed, use the actual clipped crop origin and actual resize factors:

`original_x = crop_left + overlay_x / scale_x`

`original_y = crop_top + overlay_y / scale_y`

Avoid repeated rounding through nested crops: keep each crop in original-image coordinates. If rounding is needed, document it and test it. A known point inside the target is sufficient for a click; it does not imply a measured control boundary.

## 5. Discovery algorithm

### A. One coarse inventory call

Decode the original PNG once. Draw a numbered grid on a copy, with approximately `coarse_cell_px` spacing. Keep the original clean. Use readable labels and small dots; a dot is the coordinate anchor, not the printed number's bounding box. Place labels within image bounds.

Ask the LLM for a typed list of visible controls: label, role, distinguishing description, and the coarse cell containing the control's center or a useful interior region. Multiple controls may select the same coarse cell. Treat numbers as annotation, not webpage content. Return an empty list only if the successful model response actually reports no visible controls.

A coarse location need not be an accurate click yet. Do not ask for free-form pixel coordinates or percentages. Do not invent a confidence score or infer hidden controls.

Suggested private response types: `CoarseControl(label, role, description, cell_id)` and `CoarseInventory(controls)`. Allow a missing cell ID so an identified but unlocated control can be returned as unresolved. Validate every supplied ID against that overlay's mapping.

### B. Concurrent refinement

Refine every inventoried control for this requested V1; do not silently change the API to task-specific discovery. Bound concurrent calls with `asyncio.Semaphore(config.max_concurrency)` and preserve coarse inventory order in the final result.

For each control:

1. Crop its selected cell plus its eight neighboring cells, clipped to the original image. Use the original, unmarked pixels.
2. Enlarge the crop for readability. Overlay a `fine_grid_size` by `fine_grid_size` set of numbered dots at cell centers, and retain both dot and cell mappings.
3. Supply the control description. Ask for one of these typed replies: `click(number)`, `zoom(number)`, or `unresolved(reason)`.
4. `click(number)` means the dot itself is safely inside the intended control, away from borders. Accept only an ID from this overlay.
5. `zoom(number)` means no existing dot is safely inside but the target is in/near this cell. Crop that cell plus its neighbors from the original screenshot and repeat.
6. Stop at `max_refinements`, an invalid selection, or a crop that cannot shrink. Return unresolved with a specific reason rather than guessing.

Default to one call per control per refinement round. Reusing identical image crops is fine; batching multiple control decisions in one refinement call is a later optimization. No browser action may occur during the batch. The source screenshot is frozen even though the calls are concurrent.

Prompt wording must distinguish the printed label from the dot: "Return the number whose DOT is inside the target, not a number whose text overlaps it. Select zoom if the grid is too coarse. Return unresolved if the target is not visible or cannot be distinguished."

Treat per-control model timeout, schema/ID errors, and exhaustion as unresolved results. Coarse-call failure raises a module-local `DiscoveryError`; do not misreport that failure as an empty screen. Propagate cancellation and unexpected programmer errors. This module should not implement unbounded retries.

### C. Build a locator from the clean screenshot

Do not crop a tiny blank area inside a text field. Start with a context patch `context_width` by `context_height` around the grounded point, allocating about two-thirds of its height above the point to include a label such as Username. Clip it at the screenshot edges and record the actual rectangle.

This is a **context patch**, not an exact element bounding box. It may include the label, border, and part of the field. Compute `click_offset = click_point - actual_crop_origin`. Save original-resolution pixels with no numbers, dots, enlarged resampling, or browser chrome.

Before marking a control ready, run the same replay matcher against the original screenshot. Require a unique accepted match whose recovered click point agrees with the selected point within a small explicit tolerance (e.g. 2 CSS pixels). This checks repeatability on that image, not correctness of the LLM's semantic choice.

If the patch is featureless or matches ambiguously, try one bounded expansion (e.g. 1.5 times its width and height) to include more context. If it still fails, return unresolved. Do not silently fall back to a coordinate-only locator. A larger patch can also be more sensitive to neighboring content changes; record that trade-off.

Keep credentials and changing field values out of persistent templates. For the assignment use the safe sandbox fixture before values are entered. If no distinctive, stable, non-sensitive patch is available, expose unresolved; never assume image bytes are safe because `repr=False` hides them. The caller owns persistence policy.

## 6. Replay algorithm

`resolve_control` is a pure local image operation with no model client argument.

1. Decode the current screenshot and saved template. Reject malformed artifacts. Return `incompatible` if the viewport dimensions differ from `reference_size`. Same dimensions do not prove equal zoom; the caller maintains the rendering contract.
2. Convert both images consistently and compute OpenCV `matchTemplate` using `TM_CCOEFF_NORMED`. Reject an effectively constant template before normalization; handle non-finite scores explicitly.
3. Extract candidate peaks across the whole viewport. Deduplicate nearby response pixels belonging to one match using a documented non-maximum-suppression rule. Do not treat every neighboring high-score pixel as a separate match, and do not collapse spatially distinct duplicated controls into one.
4. If the best score is below the locator's threshold, return `not_found`. If another distinct candidate also meets the threshold, or is within `ambiguity_margin` of the best score, return `ambiguous`.
5. For an accepted unique match, return its top-left plus `click_offset`. Check the point remains inside the viewport. Include the matched patch rectangle and score.

The original location is provenance, not a fallback click or an automatic tie-breaker between identical candidates. The matcher must recover translated targets and reject duplicate plausible matches. Scores and thresholds need empirical tuning; 0.95 is not a 95% probability of correctness.

Do not add an LLM fallback to this function. A caller may separately request rediscovery or human intervention, but that must be distinguishable from deterministic replay.

## 7. Required doctest in the same module

Put the following in the module docstring, adjusting indentation only. Implement `_png_bytes(image)` and `_make_locator(screen, crop, point)` as private helpers in the same file. The latter crops clean pixels, records reference dimensions/rectangle, validates the point, and calculates the offset; discovery adds the uniqueness check described above.

This doctest exercises the core promise: save a patch, serialize it, find it after translation, and reject missing/duplicate targets. It needs no model, browser, network, credentials, or image files.

```pycon
>>> from PIL import Image, ImageDraw
>>> canvas = Image.new("RGB", (320, 180), "white")
>>> draw = ImageDraw.Draw(canvas)
>>> draw.text((20, 25), "Username", fill="black")
>>> draw.rectangle((20, 45, 119, 64), outline="orange", width=2)
>>> screen = ScreenInput(screenshot_png=_png_bytes(canvas))
>>> crop = CropBox(x=10, y=15, width=120, height=65)
>>> locator = _make_locator(screen, crop, ClickPoint(x=70, y=55))
>>> locator.click_offset.model_dump()
{'x': 60, 'y': 40}

>>> restored = VisualLocator.model_validate_json(locator.model_dump_json())
>>> restored.template_png == locator.template_png
True

>>> patch = canvas.crop((10, 15, 130, 80))
>>> moved = Image.new("RGB", canvas.size, "white")
>>> moved.paste(patch, (75, 50))
>>> result = resolve_control(ResolveInput(screenshot_png=_png_bytes(moved), locator=restored))
>>> result.status, result.point.model_dump()
('matched', {'x': 135, 'y': 90})

>>> blank = Image.new("RGB", canvas.size, "white")
>>> result = resolve_control(ResolveInput(screenshot_png=_png_bytes(blank), locator=restored))
>>> result.status, result.point
('not_found', None)

>>> duplicates = Image.new("RGB", canvas.size, "white")
>>> duplicates.paste(patch, (10, 10))
>>> duplicates.paste(patch, (180, 90))
>>> result = resolve_control(ResolveInput(screenshot_png=_png_bytes(duplicates), locator=restored))
>>> result.status, result.point
('ambiguous', None)

>>> larger = Image.new("RGB", (640, 360), "white")
>>> result = resolve_control(ResolveInput(screenshot_png=_png_bytes(larger), locator=restored))
>>> result.status, result.point
('incompatible', None)
```

Run with `python -m doctest -v visual_controls.py`.

Also add small offline doctests in the relevant helper docstrings for: a zoomed crop mapping back to source pixels, a crop clipped at an image edge, rejection of a nonexistent dot ID, and a blank/constant template. Use a fake `VisionCall` in a builder doctest to exercise inventory plus refinement, preserving control order and returning one unresolved control. These test orchestration and geometry; they do not establish real-model accuracy.

## 8. How the caller uses the output

The following is integration usage, not a second implementation module. Adapt existing project names instead of inventing a new orchestrator.

```python
# DISCOVERY: capture once; the module inventories and refines controls.
screen = ScreenInput(screenshot_png=await page.screenshot(type="png", scale="css", full_page=False))
control_map = await build_control_map(screen, vision=vision_adapter)

# The existing goal-driven planner selects a returned control ID.
control = next(c for c in control_map.controls if c.id == selected_control_id)
if control.status != "ready":
    raise RuntimeError(f"Discovery needs intervention: {control.reason}")
assert control.locator is not None

# Save this locator under the chosen control ID in the capability artifact.
# Record the action separately, for example:
# {"kind": "enter_text", "control_id": control.id,
#  "value": {"input_ref": "username"}}
# Store a parameter reference, not a literal credential.

# REPLAY: the saved step determines the target and action; no planner/LLM call.
result = resolve_control(
    ResolveInput(
        screenshot_png=await page.screenshot(type="png", scale="css", full_page=False),
        locator=control.locator,  # In replay this comes from the saved artifact.
    )
)
if result.status != "matched":
    # Route through the project's structured retry/escalation path.
    raise RuntimeError(f"Target resolution: {result.status}: {result.reason}")
assert result.point is not None

# Execute only after the caller checks its expected screen, action allowlist,
# session ownership, and readiness. Prevent concurrent session interaction.
await page.mouse.click(result.point.x, result.point.y)
await page.keyboard.insert_text(input_parameters["username"])
# The caller must verify the intended field/result after acting.
```

`insert_text` inserts into the focused field; it does not clear existing content. The saved action must specify whether it means append or replace. For replacement, the executor must perform its recorded select-all/clear sequence after verifying focus, then enter text. Input values remain runtime parameters.

Use fresh screenshots before each replay action. Do not reuse discovered coordinates after navigation or other layout changes. Template matching finds the present location; the caller still needs to establish the expected state, detect overlays/errors, and verify the outcome. A matching-looking control on the wrong screen is not permission to act.

For persistence, `control_map.model_dump_json()` serializes PNG bytes as base64 and `ScreenOutput.model_validate_json(...)` restores them. This compact implementation choice avoids a separate asset store. A later storage layer can replace embedded PNGs with asset references while keeping the locator semantics.

## 9. Evidence and completion criteria

1. Both public functions are implemented in `visual_controls.py`, with no unconditional provider initialization or network calls at import time.
2. Offline doctests pass; the replay tests cannot call an LLM by construction.
3. On ParaBank, run real screenshot-only inventory/refinement against the visible login controls. Record selected IDs, source coordinates, and bounded failures. Draw final points for review; do not rely on model confidence as proof of a hit.
4. Verify the Username click by actual entry of a safe synthetic value into the intended field. Verify Password and Log In localization without submitting real credentials. UI execution belongs to the existing caller.
5. Save the clean locator, return to the expected state, and replay without LLM calls. Include a translated-patch fixture and an ambiguous-patch fixture in evidence.
6. Report observed successes/failures, call count, and latency. State the tested viewport/zoom and limitations. A module doctest is not the handout's required genuine end-to-end discovery run.

Keep default logging free of screenshot bytes, template bytes, typed credentials, and full model responses. Optional annotated-image evidence must use the project's safe sandbox/redaction policy. Do not silently persist the input screenshot.

Complete the focused implementation before adding OCR, a universal rectangle detector, multi-scale template search, or a global application graph. The intended seam is stable: screenshot in, reusable visual control locators out; saved locator plus current screenshot in, current click point or explicit failure out.

## References

- Assignment: supplied **Assignment-A-Computer-Use-Automation.pdf**, sections 3.1-3.7. The grid algorithm is our implementation choice, not a prescribed requirement.
- [Pillow crop](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.crop) and [drawing overlays](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html).
- [OpenCV template matching](https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html). Peak suppression and ambiguity policy are application code.
- [Pydantic configuration](https://docs.pydantic.dev/latest/api/config/): `ser_json_bytes` and `val_json_bytes` support a base64 round trip.
- [Playwright screenshot](https://playwright.dev/python/docs/api/class-page#page-screenshot) and [mouse coordinates](https://playwright.dev/python/docs/api/class-mouse).
