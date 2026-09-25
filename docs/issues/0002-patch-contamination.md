# 0002 — Context patches capture fields whose contents change

**Severity:** high for any control below a form — which is every submit button.

## Observed

The Log In button's context patch spanned y 325..421. The password field sits at
y 353..371 — **inside it**. Measured with the same locator:

```
empty form   -> matched    score 1.0000
filled form  -> not_found  score 0.8150
```

We saved a picture containing two empty text boxes. Filling them changed the
picture. The button never moved; our reference did.

`locate_control` behaved correctly — it refused rather than clicking somewhere
wrong — but the login could not complete.

Not rare: ParaBank's Transfer, Bill Pay, Open Account and Request Loan forms all
put their submit button below their inputs.

## Why the first fix did not work

Patch placement was widened from "always reach upward" to five candidates (up,
down, centred, and two larger). It changed nothing, for an instructive reason:

**the self-check proves uniqueness on the discovery image, where the form is
empty.** The upward patch passes that check, so the downward one is never
reached. Uniqueness is not stability.

## Current state

Placements that self-match are now *scored* by how much they overlap regions
known to be volatile — controls the coarse inventory labelled `textbox` or
`select` — and the lowest-overlap placement wins.

**Unverified.** On the run that followed, `log_in_button` was never grounded
(see [0001](0001-coarse-inventory-instability.md)), so the patch stage was never
reached. There is no evidence either way yet.

## What to measure

Ground the Log In button, record the chosen patch rectangle, then re-run
`locate_control` against a screenshot with both fields filled. The patch should
sit below the button, over "Forgot login info?" and "Register", and should still
match.
