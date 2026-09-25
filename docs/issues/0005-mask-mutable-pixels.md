# 0005 — Mask changing pixels instead of avoiding them

**Severity:** low — an idea, not a defect. Recorded so it is not re-derived.

## Now

[0002](0002-landmark-stability.md) avoids the problem: among landmark placements
that are unique, prefer the one overlapping the fewest input fields. Measured
working offline — the Log In landmark moves from covering the password field to
covering "Forgot login info?" / "Register".

## Better, maybe

`cv2.matchTemplate` accepts a `mask` argument. Instead of *avoiding* a text
field, a landmark could *include* it with its interior masked out, so "empty"
and "filled" produce the same match. That would fix the cause rather than route
around it, and would free landmark placement to always take the most distinctive
patch rather than the most stable one.

## Why it is not being built

The avoidance heuristic works and is cheap. Masking needs a mask per landmark,
which needs to know where the field interiors are — which is the information we
do not reliably have (that is [0001](0001-incomplete-inventory.md)). So it is
blocked behind the same problem, and buys less.

Revisit if a screen appears where no stable landmark exists at all.
