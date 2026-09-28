#!/usr/bin/env python3
"""Build the control map for ParaBank's loan-request screen.

Driven directly rather than through the goal loop: `extract_control_locators`
is the same perception discovery uses, and the loan page is behind a login and
a nav click that the agent has no reason to make for this demo.

The loan form is the only place in ParaBank with TWO money fields and a
genuinely irreversible submit -- which is what
`docs/issues`-adjacent value-dependent risk needs to be demonstrated against
something real. See `capabilities.REQUEST_LOAN`.

    ./scripts/map_loan_screen.py        # ~20 model calls
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interfaceai.control_map_store import ControlMapStore, MapKey
from interfaceai.screenshot2controls import (
    ScreenInput,
    extract_control_locators,
)
from interfaceai.settings import get_settings
from interfaceai.surface import OffLoop, PlaywrightSurface
from interfaceai.vision_llm import call_vision_llm


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
        surface.wait(1.0)

        control_map = off.run(
            extract_control_locators(
                ScreenInput(screenshot_png=surface.screenshot()), vision=call_vision_llm
            )
        )

    # ⚠️ DISCOVERY CANNOT KNOW THIS, and that is the point. Nothing on screen
    # distinguishes "Apply Now" from "Search" -- both are a button with a label.
    # Irreversibility is a fact about the BUSINESS, so a person declares it, and
    # it lives on the control so every capability touching that button inherits
    # it rather than each author remembering.
    controls = [
        c.model_copy(update={"policy": c.policy.model_copy(update={"irreversible": True})})
        if c.id == "apply_now_button"
        else c
        for c in control_map.controls
    ]
    control_map = control_map.model_copy(update={"controls": controls})

    ready = [c for c in control_map.controls if c.status == "ready"]
    store.put(MapKey(app="parabank", tenant="baseline", screen="requestloan"), control_map)
    print(f"requestloan: {len(ready)}/{len(control_map.controls)} grounded")
    for c in ready:
        print(f"   {c.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
