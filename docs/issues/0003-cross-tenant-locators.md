# 0003 — Template matching cannot survive a tenant rebrand

**Severity:** by design, not a defect. Recorded so it is argued rather than
discovered.

## The problem

A visual locator is pixels. Two institutions running the same vendor product
differ in exactly the way that breaks pixels: colours, fonts, logo, spacing.
`TM_CCOEFF_NORMED` at a 0.95 threshold will not survive a CSS rebrand.

This is the direct cost of [ADR 0002](../adr/0002-playwright-screenshot-control.md):
refusing the DOM buys a design that extends to desktop surfaces, and gives up the
semantic stability a selector would have had.

## What the design does give

- **A clean failure.** A rebranded tenant yields `not_found`, not a confident
  click in the wrong place.
- **The blast radius is one field.** The artifact schema, the replay engine, the
  error taxonomy and the action policy are all tenant-agnostic. Only the
  `VisualLocator` payload is tenant-specific.
- **A store keyed by `(app, tenant, screen)`** turns a rebrand into a lookup miss
  and a re-discovery, rather than silent breakage.

So the answer to §3.7 is: **re-run discovery per tenant; everything else is
shared.** Discovery is the amortised cost, and it is bounded — one pass per
screen per tenant.

## Untested

`parasoft/parabank:baseline` and `:feature` are genuinely different images, so
this is measurable rather than hypothetical. Nobody has run discovery on tenant
A and replayed against tenant B yet. Worth doing before the claim goes in
REPORT.md.

## Alternative worth revisiting

The accessibility tree ([ADR 0002](../adr/0002-playwright-screenshot-control.md)
considered and deferred it) is more portable across a restyle *and* available on
desktop. It is thin and unhelpful on a table-layout JSP app, which is why it lost
— but it slots behind the same `Surface` seam, so it remains a cheap experiment.
