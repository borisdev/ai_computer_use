#!/usr/bin/env python3
"""Re-locate `from_account_select` against a FILLED loan form.

    uv run python3 scripts/remap_filled_loan_form.py

⛔ A control's landmark patch catches its NEIGHBOURS, so a locator measured on
an empty form stops matching once the fields above it hold digits -- issue
0002. `request_loan` fills two money fields and then selects an account, so
the select must be located against the form in that state.

Reordering does not escape it: putting the select first broke
`loan_amount_textbox` instead. Whichever field is touched first contaminates
the next one's anchor. The fix is to measure each control in the state the
capability actually reaches it in, which is what a discovery run would do
naturally and what this script does by hand for one control.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interfaceai.control_map_store import ControlMapStore, MapKey
from interfaceai.screenshot2controls import ScreenInput, extract_control_locators
from interfaceai.settings import get_settings
from interfaceai.surface import OffLoop, PlaywrightSurface
from interfaceai.vision_llm import call_vision_llm

TARGET = "from_account_select"


def main() -> int:
    settings = get_settings()
    store = ControlMapStore(ROOT / "control_maps")
    with PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface, OffLoop() as off:
        page = surface.page
        surface.navigate(f"{settings.parabank_base_url}/index.htm")
        page.fill("input[name='username']", settings.parabank_demo_username)
        page.fill("input[name='password']", settings.parabank_demo_password.get_secret_value())
        page.click("input[value='Log In']")
        page.wait_for_load_state("networkidle")
        page.goto(f"{settings.parabank_base_url}/requestloan.htm")
        page.wait_for_load_state("networkidle")
        # THE STATE THAT MATTERS: both money fields already filled.
        page.fill("input#amount", "500")
        page.fill("input#downPayment", "100")
        surface.wait(0.5)

        located = off.run(
            extract_control_locators(
                ScreenInput(screenshot_png=surface.screenshot()),
                vision=call_vision_llm,
                only=[TARGET],
            )
        )

    fresh = next((c for c in located.controls if c.id == TARGET), None)
    if fresh is None or fresh.status != "ready":
        print(f"  {TARGET}: {fresh.status if fresh else 'absent'} -- nothing written")
        return 1

    for tenant in store.tenants("parabank"):
        key = MapKey(app="parabank", tenant=tenant, screen="requestloan")
        control_map = store.get(key)
        controls = [c for c in control_map.controls if c.id != TARGET] + [fresh]
        store.put(key, control_map.model_copy(update={"controls": controls}))
        print(f"  {tenant}/requestloan: {TARGET} re-located on a filled form")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
