# 0004 — Sync Playwright cannot nest `asyncio.run`

**Severity:** low — worked around, but it shapes the caller.

## Observed

```python
with PlaywrightSurface(...) as surf:              # Playwright's own loop is running
    asyncio.run(extract_control_locators(...))    # RuntimeError: asyncio.run()
                                                  # cannot be called from a
                                                  # running event loop
```

Sync Playwright drives its own event loop internally. `asyncio.run` starts a new
one, and loops do not nest.

## Consequence

Capture and discovery must be separate phases: screenshot, leave the browser
context, then run discovery. Every end-to-end script here is structured that way.

It is awkward for an agent loop, which naturally wants to observe → decide → act
inside one session — and holding one live session open is also what §3.6's human
handoff requires.

## Fix

Move `surface.py` to `async_playwright()` and make its methods awaitable. Then
one loop covers everything and `await extract_control_locators(...)` sits happily
beside `await page.screenshot()`. Mechanical; touches the driver and its callers.
