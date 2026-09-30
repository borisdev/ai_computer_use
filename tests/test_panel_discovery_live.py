"""Discovery proposes a panel, and the verifier accepts it.

`live` — needs ParaBank up and seeded, and spends model calls.

This is the acceptance test for issue #6. `tests/test_screenshot2panels.py`
checks the geometry offline against committed screenshots; what it cannot check
is the thing the panel exists for: that a model, shown the crop the derived
geometry produces, reads the rows AND agrees about where each one sits.

⚠️ The bar is deliberately *"the verifier accepts it"* rather than *"the numbers
match the hand-measured ones"*. `table._check_alignment` is what stands between
a proposed panel and a wrong row, so a proposal it accepts is safe to act on
even where it is a few pixels from what a person would have chosen. The
hand-measured numbers are compared in the offline test, where they cost nothing.
"""

from __future__ import annotations

import pytest

from interfaceai import parabank
from interfaceai.screenshot2controls import ControlRole, ScreenInput
from interfaceai.screenshot2panels import extract_panel_locators
from interfaceai.settings import get_settings
from interfaceai.surface import OffLoop, PlaywrightSurface
from interfaceai.table import MARKER_FIELD, Offset, extract_panel
from interfaceai.vision_llm import call_vision_llm

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def overview_screenshot() -> bytes:
    settings = get_settings()
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().init_db()
    with PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface:
        page = surface.page
        surface.navigate(f"{settings.parabank_base_url}/index.htm")
        page.fill("input[name='username']", settings.parabank_demo_username)
        page.fill("input[name='password']", settings.parabank_demo_password.get_secret_value())
        page.click("input[value='Log In']")
        page.wait_for_load_state("networkidle")
        page.goto(f"{settings.parabank_base_url}/overview.htm")
        page.wait_for_load_state("networkidle")
        surface.wait(1.0)
        return surface.screenshot()


@pytest.fixture(scope="module")
def proposed(overview_screenshot: bytes):
    with OffLoop() as off:
        return off.run(
            extract_panel_locators(
                ScreenInput(screenshot_png=overview_screenshot), vision=call_vision_llm
            )
        )


def _read(screenshot: bytes, panel):
    spec = panel.panel
    with OffLoop() as off:
        return off.run(
            extract_panel(
                screenshot,
                panel.locator,
                panel=Offset(dx=spec.dx, dy=spec.dy, width=spec.width, height=spec.height),
                key_column=Offset(
                    dx=spec.key_dx, dy=spec.key_dy, width=spec.key_width, height=spec.height
                ),
                columns=spec.columns,
                key_column_name=spec.key_column,
                vision=call_vision_llm,
                row_pitch=spec.row_pitch,
            )
        )


def test_discovery_emits_a_table_control_panel(proposed) -> None:
    ready = [p for p in proposed if p.status == "ready"]
    assert ready, [(p.id, p.reason) for p in proposed]
    assert all(p.role is ControlRole.TABLE_CONTROL_PANEL for p in ready)
    assert all(p.panel is not None and p.locator is not None for p in ready)


def test_the_accounts_table_is_one_of_them_with_the_pitch_the_oracle_gives(proposed) -> None:
    """11 accounts are seeded, 28px apart. No panel has to be the accounts table
    for discovery to be working — but on THIS screen one of them is, and a
    proposal that misses it has not replaced `scripts/add_panels.py`."""
    accounts = [p for p in proposed if p.status == "ready" and p.panel.row_pitch == 28]
    assert accounts, [(p.id, p.status, p.reason, p.description) for p in proposed]
    assert any("11 rows" in p.description for p in accounts), [p.description for p in accounts]


def test_every_panel_discovery_proposed_passes_the_alignment_check(
    overview_screenshot, proposed
) -> None:
    """The bar from the issue: the verifier accepts what geometry proposed.

    One model call per panel. A disagreement here means the pitch or the phase
    is wrong, which is exactly what `_check_alignment` was built to say out loud
    instead of returning a plausible wrong row.
    """
    ready = [p for p in proposed if p.status == "ready"]
    assert ready
    for panel in ready:
        read = _read(overview_screenshot, panel)
        assert read.data.rows, f"{panel.id} read no rows"
        assert read.misaligned == (), (panel.id, read.misaligned)
        # ⛔ `misaligned == ()` is ALSO what a bypassed verifier looks like:
        # `_check_alignment` SKIPS a row whose optional marker is missing, so a
        # model that returned no markers at all passes silently. Assert the
        # markers are there and each row reports its own band (Copilot, #13).
        markers = [getattr(row, MARKER_FIELD, None) for row in read.data.rows]
        assert markers == list(range(len(markers))), (panel.id, markers)


def test_the_discovered_accounts_panel_can_find_account_13344(
    overview_screenshot, proposed
) -> None:
    accounts = next(p for p in proposed if p.status == "ready" and p.panel.row_pitch == 28)
    read = _read(overview_screenshot, accounts)
    keys = [str(getattr(row, accounts.panel.key_column)) for row in read.data.rows]
    assert "13344" in keys, keys
    assert len(keys) == 11, keys
