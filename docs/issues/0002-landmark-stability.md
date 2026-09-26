# 0002 — Landmarks can capture pixels that change

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
(see [0001](0001-incomplete-inventory.md)), so the patch stage was never
reached. There is no evidence either way yet.

## What to measure

Ground the Log In button, record the chosen patch rectangle, then re-run
`locate_control` against a screenshot with both fields filled. The patch should
sit below the button, over "Forgot login info?" and "Register", and should still
match.

## ⛔ Reproduced live 2026-09-26, then fixed and measured

"Fixed, unverified live" was optimistic. The first real discovery run died on
it, mid-login, exactly as predicted:

```
step 0  username_textbox   matched 0.99999   (pristine form)
step 1  password_textbox   matched 0.9839    (username now filled -- degraded)
step 2  log_in_button      NOT FOUND 0.8365  (both filled)  -> escalated
```

The degradation is monotonic as the form fills, and the run **correctly refused
to click** and returned `PassToOperator` rather than guessing — so the failure
was loud, which is the one thing that went right.

**Root cause: the chooser had no survivable option.** `_choose_landmark` already
preferred the placement overlapping the least volatile content, but all five
entries in `_PATCH_PLACEMENTS` put the patch top at or above `click_y -
height/3`. For the Log In button at y=389 that is y=357, and the password field
runs to y≈370. Every candidate swallowed it; "least overlap" then picked the
least-bad contaminated patch.

Re-scored offline against that run's own before/after frames — no model calls,
real pixels:

```
bias  patch y      on the FILLED form
0.67  325..421     not_found
0.33  357..453     not_found
0.25  365..461     not_found
0.20  370..466     0.9572     <- the cliff is the field's bottom edge
0.15  375..471     0.9998
0.05  385..481     0.9998
```

Fix: two low-bias placements, `(1.0, 0.15)` and `(1.0, 0.05)`. The selection
rule was never wrong — it had nothing good to choose from. `0.20` is excluded
deliberately: clearing by 0.007 is one antialiasing change from failing.

Verified on the next run: password 1.0000, Log In **0.9998**, login completed.

⚠️ **The regression test had to be rebuilt to be worth anything.** Its first
version used a synthetic form with a 33px gap between field and button against a
26px upward reach, so every stock placement cleared the field on its own and the
test stayed green with the fix reverted. The geometry of a regression test for a
geometric bug is not decoration. The mutation check is what caught it: revert
the fix, confirm the test goes red, restore.
