"""A control map's templates belong to the stack that rasterised them.

Issue 0012. A map built on Linux Chromium scored 0.6889 against macOS
Chromium on `username_textbox` -- the first control of the first screen --
and the failure said nothing about why, because nothing recorded the stack.
"""

from __future__ import annotations

from interfaceai.screenshot2controls import (
    ImageSize,
    RenderEnvironment,
    ScreenOutput,
    environment_mismatch,
)

LINUX = RenderEnvironment(
    platform="linux",
    browser="chromium 153.0.8010.12",
    viewport=ImageSize(width=1280, height=900),
)
MACOS = RenderEnvironment(
    platform="darwin",
    browser="chromium 141.0.7390.37",
    viewport=ImageSize(width=1280, height=900),
)


def _map(captured_on: RenderEnvironment | None) -> ScreenOutput:
    return ScreenOutput(
        screenshot_sha256="0" * 64,
        image_size=ImageSize(width=1280, height=900),
        controls=[],
        captured_on=captured_on,
    )


def test_a_map_from_another_stack_says_so_by_name() -> None:
    """The sentence a reader needed and did not get on 2026-10-07."""
    why = environment_mismatch(_map(LINUX), MACOS)
    assert why is not None
    assert "linux -> darwin" in why
    assert "chromium 153.0.8010.12 -> chromium 141.0.7390.37" in why


def test_the_same_stack_is_silent() -> None:
    """A warning that fires when nothing is wrong is one nobody reads."""
    assert environment_mismatch(_map(LINUX), LINUX) is None


def test_an_UNRECORDED_environment_must_not_read_as_a_match() -> None:
    """⛔ THE TRAP. Every map written before this field exists has
    `captured_on=None`, and `None` means "nobody recorded it" -- never "it
    matches yours". The caller gets None here too, so it must stay silent
    rather than print reassurance it has not earned.

    `checks.md`: a missing input must never read as a pass.
    """
    assert _map(None).captured_on is None
    assert environment_mismatch(_map(None), MACOS) is None


def test_viewport_alone_is_not_the_whole_environment() -> None:
    """`reference_size` already pinned 1280x900, and that is exactly what made
    the failure confusing: the one axis that WAS recorded matched."""
    assert LINUX.viewport == MACOS.viewport
    assert environment_mismatch(_map(LINUX), MACOS) is not None
