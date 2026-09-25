"""The perception/action seam.

Everything above this line knows about banking tasks; everything below knows how
to look at a screen and touch it. A desktop backend would implement `Surface`
and change nothing in the agent loop, the artifact schema or the replay engine
-- that is the whole argument of ADR 0002.

Deliberately no DOM. No selectors, no XPath, no `page.locator()`. The only
perception channel is a screenshot, and the only targeting channel is a
coordinate in that screenshot's pixel space.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Literal, Protocol, Self, runtime_checkable

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from interfaceai.decisions import ManualActionKind

log = logging.getLogger(__name__)

ScrollDirection = Literal["up", "down", "left", "right"]


class NotAllowedError(RuntimeError):
    """An action was refused by the guardrails (assignment 3.4)."""


@dataclass(frozen=True)
class Viewport:
    """Pinned, and part of an artifact's contract.

    Coordinates only mean anything relative to a viewport, so a capability
    recorded at one size cannot be replayed at another without rescaling.
    """

    width: int = 1280
    height: int = 900


@runtime_checkable
class Surface(Protocol):
    """What a computer-use surface must be able to do."""

    def screenshot(self) -> bytes: ...
    def zoom(self, x0: int, y0: int, x1: int, y1: int) -> bytes: ...
    def left_click(self, x: int, y: int, modifiers: str | None = None) -> None: ...
    def right_click(self, x: int, y: int, modifiers: str | None = None) -> None: ...
    def double_click(self, x: int, y: int, modifiers: str | None = None) -> None: ...
    def triple_click(self, x: int, y: int, modifiers: str | None = None) -> None: ...
    def mouse_move(self, x: int, y: int) -> None: ...
    def drag(self, x0: int, y0: int, x1: int, y1: int) -> None: ...
    def scroll(self, x: int, y: int, direction: ScrollDirection, amount: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def press_key(self, key: str, repeat: int = 1) -> None: ...
    def wait(self, seconds: float) -> None: ...
    def navigate(self, url: str) -> None: ...
    def current_url(self) -> str: ...


# Claude emits X11-style key names; Playwright wants its own spelling.
_KEY_ALIASES = {
    "Return": "Enter",
    "KP_Enter": "Enter",
    "Escape": "Escape",
    "BackSpace": "Backspace",
    "Tab": "Tab",
    "space": " ",
    "Page_Up": "PageUp",
    "Page_Down": "PageDown",
    "Up": "ArrowUp",
    "Down": "ArrowDown",
    "Left": "ArrowLeft",
    "Right": "ArrowRight",
    "super": "Meta",
    "ctrl": "Control",
    "alt": "Alt",
    "shift": "Shift",
}


def _translate_key(combo: str) -> str:
    """'ctrl+s' -> 'Control+s', 'Return' -> 'Enter'."""
    return "+".join(
        _KEY_ALIASES.get(part, _KEY_ALIASES.get(part.lower(), part)) for part in combo.split("+")
    )


class PlaywrightSurface:
    """A browser treated as a screen.

    Playwright supplies the browser lifecycle, screenshots and input dispatch.
    It is the transport; it is not the locator strategy.
    """

    def __init__(
        self,
        allowed_origins: tuple[str, ...],
        viewport: Viewport | None = None,
        headless: bool = True,
    ) -> None:
        self.allowed_origins = tuple(o.rstrip("/") for o in allowed_origins)
        self.viewport = viewport or Viewport()
        self._headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    # --- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Self:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        context = self._browser.new_context(
            viewport={"width": self.viewport.width, "height": self.viewport.height},
            # One context for the whole run, so a human can later be handed the
            # same live session rather than a fresh one (assignment 3.6).
        )
        context.set_default_timeout(15_000)
        self._page = context.new_page()
        return self

    def __exit__(self, *exc: object) -> None:
        # Teardown must not mask whatever is already propagating, but a
        # swallowed error here means a leaked browser process -- so it is
        # logged rather than dropped.
        for closer, close in ((self._browser, "close"), (self._pw, "stop")):
            if closer is None:
                continue
            try:
                getattr(closer, close)()
            except Exception as exc_info:  # noqa: BLE001
                log.warning("surface teardown failed on %s: %s", close, exc_info)

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Surface used outside its context manager")
        return self._page

    # --- guardrails --------------------------------------------------------

    def _check_origin(self, url: str) -> None:
        if not any(url.startswith(origin) for origin in self.allowed_origins):
            raise NotAllowedError(
                f"navigation to {url!r} is outside the allowlist {self.allowed_origins}"
            )

    # --- perception --------------------------------------------------------

    def screenshot(self) -> bytes:
        return self.page.screenshot(type="png")

    def zoom(self, x0: int, y0: int, x1: int, y1: int) -> bytes:
        """Crop at full resolution -- how small print like a balance gets read."""
        return self.page.screenshot(
            type="png",
            clip={"x": x0, "y": y0, "width": max(1, x1 - x0), "height": max(1, y1 - y0)},
        )

    def current_url(self) -> str:
        return self.page.url

    # --- action ------------------------------------------------------------

    def _click(self, x: int, y: int, button: str, count: int, modifiers: str | None) -> None:
        # Playwright's Mouse.click takes no `modifiers` -- they are held on the
        # keyboard around the click.
        keys = [_translate_key(m) for m in modifiers.split("+")] if modifiers else []
        for key in keys:
            self.page.keyboard.down(key)
        try:
            self.page.mouse.click(x, y, button=button, click_count=count)
        finally:
            for key in reversed(keys):
                self.page.keyboard.up(key)

    def left_click(self, x: int, y: int, modifiers: str | None = None) -> None:
        self._click(x, y, "left", 1, modifiers)

    def right_click(self, x: int, y: int, modifiers: str | None = None) -> None:
        self._click(x, y, "right", 1, modifiers)

    def double_click(self, x: int, y: int, modifiers: str | None = None) -> None:
        self._click(x, y, "left", 2, modifiers)

    def triple_click(self, x: int, y: int, modifiers: str | None = None) -> None:
        self._click(x, y, "left", 3, modifiers)

    def mouse_move(self, x: int, y: int) -> None:
        self.page.mouse.move(x, y)

    def drag(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.page.mouse.move(x0, y0)
        self.page.mouse.down()
        self.page.mouse.move(x1, y1)
        self.page.mouse.up()

    def scroll(self, x: int, y: int, direction: ScrollDirection, amount: int) -> None:
        self.page.mouse.move(x, y)
        step = amount * 100
        dx, dy = {
            "up": (0, -step),
            "down": (0, step),
            "left": (-step, 0),
            "right": (step, 0),
        }[direction]
        self.page.mouse.wheel(dx, dy)

    def type_text(self, text: str) -> None:
        self.page.keyboard.type(text, delay=20)

    def press_key(self, key: str, repeat: int = 1) -> None:
        for _ in range(max(1, repeat)):
            self.page.keyboard.press(_translate_key(key))

    def wait(self, seconds: float) -> None:
        self.page.wait_for_timeout(min(seconds, 30) * 1000)

    def navigate(self, url: str) -> None:
        self._check_origin(url)
        self.page.goto(url, wait_until="domcontentloaded")


def png_to_base64(png: bytes) -> str:
    return base64.standard_b64encode(png).decode("ascii")


# ---------------------------------------------------------------------------
# use_control -- the ONLY function that acts on the application
# ---------------------------------------------------------------------------
#
# The third of the three verbs:
#
#   extract_control_locators(llm, screenshot, ...) -> locators   learn   (model)
#   locate_control(screenshot, locator)            -> point      find    (pure)
#   use_control(surface, point, action, value)     -> Acted      act     (effects)
#
# Keeping the effects in one function is what makes the safety model tractable:
# nothing else can touch the app, so nothing else can route around the checks
# here (assignment 3.4). It is deliberately dumb -- it does not decide what to
# do, does not verify that it worked, and does not know what a capability is.
# Verification against a checkpoint belongs to whatever replays a step, because
# only that layer knows which state was expected.


@dataclass(frozen=True)
class ActionPolicy:
    """What the agent is permitted to do. Deny by default.

    Risk is a property of the CONTROL, not the action kind: clicking "Log In" is
    safe, clicking "Transfer" moves money, and both are ManualActionKind.CLICK.
    So irreversibility is classified per step by the capability layer, and
    arrives here as `confirmed` -- this function only enforces that something
    upstream made the decision, never guesses.
    """

    allowed_actions: frozenset[ManualActionKind] = frozenset(ManualActionKind)
    # Text that must never be typed into a page unredacted, matched case-
    # insensitively against the value. Empty means no restriction.
    forbidden_values: frozenset[str] = frozenset()

    def check(self, action: ManualActionKind, value: str | None) -> None:
        if action not in self.allowed_actions:
            raise NotAllowedError(
                f"action {action} is not in the policy's allowed set {sorted(self.allowed_actions)}"
            )
        if value and any(bad.lower() in value.lower() for bad in self.forbidden_values):
            raise NotAllowedError("value matches a forbidden pattern; refusing to type it")


@dataclass(frozen=True)
class Acted:
    """What was done, for the run log. Deliberately carries no value."""

    action: ManualActionKind
    x: int
    y: int
    url: str
    value_length: int | None = None  # length, never the value itself


def use_control(
    surface: PlaywrightSurface,
    x: int,
    y: int,
    action: ManualActionKind,
    value: str | None = None,
    *,
    policy: ActionPolicy | None = None,
    risky: bool = False,
    confirmed: bool = False,
) -> Acted:
    """Perform one action at a located point. The only function with effects.

    `x, y` come from `locate_control`, never from a recorded constant -- a saved
    coordinate is stale the moment anything reflows.

    Raises NotAllowedError if the policy refuses the action, if the point is
    outside the viewport, or if a step marked `risky` has not been `confirmed`
    by a human or an explicit policy decision upstream.
    """
    policy = policy or ActionPolicy()
    policy.check(action, value)

    if risky and not confirmed:
        raise NotAllowedError(
            f"{action} at ({x},{y}) is marked irreversible and has not been confirmed"
        )

    viewport = surface.viewport
    if not (0 <= x < viewport.width and 0 <= y < viewport.height):
        raise NotAllowedError(
            f"point ({x},{y}) is outside the {viewport.width}x{viewport.height} viewport"
        )

    if action is ManualActionKind.CLICK or action is ManualActionKind.TOGGLE:
        surface.left_click(x, y)
    elif action is ManualActionKind.ENTER_TEXT:
        if value is None:
            raise NotAllowedError("enter_text requires a value")
        surface.left_click(x, y)
        surface.type_text(value)
    elif action is ManualActionKind.SELECT:
        if value is None:
            raise NotAllowedError("select requires a value")
        surface.left_click(x, y)
        surface.type_text(value)
    else:  # pragma: no cover - StrEnum is closed, this is a guard not a branch
        raise NotAllowedError(f"unsupported action {action}")

    return Acted(
        action=action,
        x=x,
        y=y,
        url=surface.current_url(),
        value_length=None if value is None else len(value),
    )
