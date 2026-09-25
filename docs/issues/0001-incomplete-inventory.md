# 0001 — The inventory is incomplete and different every run

**Severity: highest.** This is the blocker for an end-to-end login, and every
other open item is downstream of it.

## Observed

Three consecutive runs, **the same screenshot bytes**, same config, same model,
temperature 0:

```
run 1: 15 inventoried, 14 ready
run 2: 24 inventoried, 23 ready
run 3: 22 inventoried, 18 ready
```

60% variance. A later run dropped `log_in_button` entirely — the single most
important control on a login screen — which is what stopped the flow completing.

**Accuracy is not the problem.** Whatever the model reports, it reports
correctly: labels verbatim, roles right, and the three login controls grounded
3/3 every run they appeared. The problem is *which things it bothers to report*.

## Root cause: we ask an open-ended enumeration question with no goal in it

The coarse prompt says, in full:

> "List every INTERACTIVE control you can see: links, buttons, text fields,
> checkboxes, radio buttons, dropdowns. Ignore static text, images and layout."

Nothing tells it what the screen is *for*. "Log In" and "Read More" have equal
standing. Exhaustive enumeration with no priority is close to the worst-shaped
task to hand a language model, and the variance is the direct result.

Two aggravating factors, both visible in the overlay the model receives
(`coarse_cell_px=80` on 1280x900):

- **192 numbered cells**, nearly all of them empty. The model must enumerate
  controls *and* map each to one of 192 numbers.
- **Grid lines cross controls.** The Log In button spans y 382..401 and the cell
  boundary is at y=400, so a red line is drawn through it. It is 66x19px.

## The fix has three parts, and they reinforce each other

### 1. A canonical vocabulary

Give the model a closed set of concepts to RESOLVE INTO rather than names to
invent: `username_input`, `password_input`, `submit_button`, `account_link`.

Today the id is a slug of whatever the model happened to call it, so identity is
downstream of a coin flip. Inverting that buys three things at once:

- stable identity across runs
- a searchable surface for "which controls help me change an address"
- a tenant-independent concept, so a locator recorded on tenant A is
  recognisably the same *concept* on tenant B even though the pixels differ

**The vocabulary does not need to be complete or correct. It needs to be
FIXED** — its only job is to stop the model inventing a new naming scheme each
run. A wrong-but-stable vocabulary fixes the variance; a perfect-but-regenerated
one does not.

Two vocabularies are easy to conflate and should not be:

| | Example | Where from |
|---|---|---|
| Control roles | `textbox`, `button`, `link` | exists: `ControlRole`, closed |
| **Domain slots** | `username`, `account_id`, `amount` | **this is what is missing** |

Seeding it: the labels already observed across the 29 mapped screens, plus the
nouns in ParaBank's own WADL (`accountId`, `amount`, `fromDate`, `billpay`),
curated by hand. Note the WADL is a bootstrap and not a method — the premise of
this project is applications with no API, so nothing may *depend* on one
existing. FIBO and the banking ontologies model the business domain, not UI
slots; wrong altitude.

### 2. Pass the goal down

"Find the controls needed to log in" is a narrower and more stable question than
"list everything". The `only` parameter already exists but operates *after* the
inventory, so it saves refinement calls without making the inventory itself more
reliable. The goal has to reach the coarse prompt.

### 3. A required-controls list

Controls that many capabilities depend on — login, the primary nav — are worth
naming explicitly and checking for. If the inventory comes back without one, ask
again specifically for it rather than proceeding with a hole. Turns a silent
omission into a retry.

## What to measure

Inventory the same screenshot N times and report: the size distribution, which
controls appear in every run versus some, and **how often a required control is
missing**. That last number is the one that matters, and it is the number the
three fixes above should move.

## Related

- [0002](0002-landmark-stability.md) — could not be verified because of this
- ADR 0004 — the tool vocabulary decision this sits under
