# 0002 — Playwright driving screenshots and coordinates, not the DOM

**Status:** Accepted · 2026-09-22

## Context

The brief leaves the computer-use mechanism open and adds one steer: *"Bias
toward an approach that would still work when the surface has no clean DOM —
that's the common case in our environment."* The target surfaces include native
desktop applications, where there is no DOM at all.

The mechanism choice determines what a recorded artifact can even say about
"how each target element is identified", so it constrains the schema.

## Decision

Use **Playwright** as the driver, but treat it as a screen, not as a document.

- Perceive by **screenshot**. The model receives an image and builds a map of
  the controls it can see.
- Act by **coordinate** — `page.mouse.click(x, y)`, `page.keyboard.type(...)`.
- **Do not depend on the DOM** for perception or for targeting. No CSS
  selectors, no XPath, no `page.locator()` as the primary path.

Playwright is the transport: browser lifecycle, navigation, screenshots, input
dispatch, tracing. It is not the locator strategy.

## Why

- **The constraint is the point.** A DOM-based recording cannot be replayed
  against a desktop app, so building on the DOM paints the design into the
  corner §3.7 asks it to avoid. Screenshots and coordinates port to any surface
  that can be captured and clicked.
- **This target punishes DOM targeting anyway.** No test IDs, table layout,
  `;jsessionid=` in every href
  ([parabank.md §7](../parabank.md#7--jsessionid-is-rewritten-into-every-url)).
  The selectors available are the brittle kind.
- **Playwright without the DOM is still worth having**: one API across Chromium,
  Firefox and WebKit, reliable screenshots, real input dispatch, built-in
  tracing for the evidence deliverable, and a persistent context so a human can
  take over the same live session (§3.6).
- **The seam this forces is the right one.** "How we perceive and act on a
  surface" becomes an interface — capture a frame, click a point, type — and the
  recorded flow sits above it. That seam is the answer to §3.7, and taking the
  DOM shortcut would have hidden it.

## Consequences

- **Raw pixel coordinates are not a durable locator.** Window size, zoom and
  scroll position all move them. The artifact must record a target
  *description* that is re-resolved at replay time against the current
  screenshot, not a frozen `(x, y)`. Getting this right is the load-bearing part
  of the schema, and pixel coordinates in an artifact would be the design's
  first real bug.
- The viewport must be pinned, and it becomes part of the artifact's contract.
- Perception costs image tokens and is slower than reading a DOM. Acceptable:
  the model runs once, at discovery, and replay is the hot path.
- Reading extracted values off a screenshot is OCR-shaped and can misread. The
  REST oracle is used in tests to catch that — never by the automation itself.
- Rejecting the DOM is a discipline, not a mechanism. Playwright will happily
  offer `page.locator()`. Reviewers should treat its appearance in the agent or
  replay path as a defect.

## Alternatives rejected

- **DOM selectors via Playwright locators.** The obvious choice and the fastest
  to a green demo. Rejected because it cannot extend to desktop, which is
  explicitly in scope for the design.
- **Accessibility tree.** Genuinely attractive: more stable than markup and
  available on desktop too, which makes it the strongest rival. Rejected for now
  because a legacy JSP app with table layout and no ARIA exposes a thin and
  unhelpful tree — the case where it helps least. Worth revisiting as a second
  perception backend behind the same seam; that the seam makes this cheap is an
  argument for the seam.
- **Raw CDP.** Everything Playwright gives us, minus the ergonomics, plus
  Chromium lock-in.
- **OS-level automation** (PyAutoGUI and similar). Closest to the general
  computer-use case, but no browser lifecycle, no tracing, no clean way to run
  headless in CI.
