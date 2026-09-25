# 0001 — Coarse inventory returns a different set of controls each run

**Severity:** high — currently the blocker for an end-to-end login.

## Observed

Three consecutive runs, **the same screenshot bytes**, same config, same model:

```
run 1: 15 inventoried, 14 ready
run 2: 24 inventoried, 23 ready
run 3: 22 inventoried, 18 ready
```

60% variance in what the model reports seeing. The three login controls were
grounded correctly every time (3/3 each run), so the *accuracy* of what it finds
is not in question — only *which things it bothers to report*.

A later run dropped `log_in_button` entirely, which is what stopped the login
flow completing.

## Why it matters

- A capability recorded against a control cannot assume rediscovery finds it.
- The unresolved rate (5–25%) rides on this: phantom entries like *"there is no
  visible left sidebar menu in this enlarged region"* are controls the coarse
  step reported that were not really there, and each one costs a refinement call.
- It is not an id problem. Content-derived ids (`log_in_button`) fixed identity
  *when a control is found*; they cannot make it get found.

## Candidate fixes, untested

1. **Ask for named controls instead of everything.** The `only` parameter already
   exists. "Find the controls for logging in" is a narrower question than "list
   every control", and narrower questions are usually more stable. This also cuts
   cost, which is the same lever.
2. **A canonical control vocabulary.** Give the model a known set of concepts to
   map onto (`username_input`, `submit_button`, `account_link`) rather than
   letting it invent an inventory each time.
3. **Ask more than once and take the union or the intersection.** Cheap to try,
   costs a call per repeat, and measures the instability directly.
4. **Lower the temperature further / raise effort.** Already at temperature 0.

## What to measure

Inventory the same screenshot N times and report: set size distribution, which
controls appear in all runs vs. some, and whether the three login controls are
ever missing. That last number is the one that matters.
