# 0007 — A parameterised control has no stable name

**Severity: high.** It is the one step of capability 1 with no mechanism behind
it, and it generalises: every "act on the row for X" capability hits it.

## Observed

Control ids are slugs of the visible label, which is what made them stable
across runs where positional ids (`c007`) were not — `docs/findings.md` §3. The
docstring's own example says it plainly:

```
>>> _slug("Account #12345!", ControlRole.LINK)
'account_12345_link'
```

So discovery recording the accounts overview while looking up account 13344
produces `account_13344_link`. **The id contains the parameter.** Replay it with
`account_id=12456` and the control it names does not exist on the screen.

The failure is not subtle, and that is the only good thing about it: the lookup
misses and `locate_control` reports `not_found` rather than clicking a row at
random.

## Why the obvious fixes are worse

- **Record the row by position** — "the tenth link in the table". Positional
  identity is what §3 retired, and an account list reorders when an account is
  opened or closed.
- **Template-match the whole row.** The patch would contain the account number,
  so it is the same problem with more pixels.
- **Navigate by URL** — `activity.htm?id=:id`. The brief's §8 blesses exactly
  this shape of parameterisation, and `Surface.navigate` exists. It would work
  today. It is not written in because it answers a different question: it
  bypasses the screen rather than finding a control on it, so it would not
  generalise to a desktop surface, which is the whole argument of ADR 0002. Worth
  taking as a deliberate, recorded fallback; not worth taking silently.

## The shape of the fix

`ControlRef.discriminator` is in the schema already — a `Value` that says
*which* one by content rather than by name: "the account link whose text is
`<account_id>`". Honouring it needs, at replay:

1. find every candidate for the concept `account_link` on the screen, not just
   the best one. `locate_control` already computes the peak list and already
   reports `ambiguous` when a second candidate is within the margin, so the
   candidates exist — what is missing is returning them.
2. read the text of each candidate and match it against the bound parameter.

   ⛔ **That second step is now measured and it does not work.** It assumed
   reading is the half models are good at. On this exact screen the model reads
   **6 of 11** account numbers correctly —
   [issue 0008](0008-dense-numeric-text-is-misread.md) — so matching row text
   against a parameter would pick the wrong account about half the time, with no
   signal that it had. **0007 cannot be fixed until 0008 is**, and the most
   promising route (read from a zoomed crop rather than the full screenshot) is
   unmeasured.

Note what this does **not** reintroduce: the model is not choosing where to
click. Code enumerates candidates, the model reads them, code picks the one
whose text matches. Same principle as the dot grid: the model only points,
code owns the resolution.

## What to measure

The accounts overview has 11 near-identical rows and is the natural fixture:
bind each of the 11 account ids in turn, and count how often the click lands on
the right row. Anything less than 11/11 is a wrong record on a bank screen, so
the bar is not a ratio to improve — it is pass or fail.

## Related

- [0001](0001-incomplete-inventory.md) — the inventory's naming churn. Different
  problem, same root: identity is downstream of whatever the model called it.
- [ADR 0005](../adr/0005-capability-artifact-shape.md) — why the field exists in
  the schema before the code that reads it.

---

## ✅ A candidate that needs no per-row grounding at all (2026-09-26)

Boris's proposal, after the wrong-row measurements in
[0009](0009-wrong-row-grounding-is-silent.md): *rows in a table keep changing so
there is no neighbourhood landmark — landmark the TABLE instead, then work
inside it.*

The principle underneath it is one this repo already measured in miniature and
never generalised: **never template-match something that repeats.**
[findings.md §3](../findings.md) recorded that a control's own bbox matched
*Username and Password* — 3 positions. A table is that failure eleven times
over. But a table's **header** is unique and does not change with the data, so
it is an ideal anchor.

That decomposes row targeting into four steps, none of which is cell assignment:

| step | mechanism | measured |
|---|---|---|
| locate the table | template-match the header row | template matching is proven — replay drift (0,0), score 1.0000 |
| row pitch | autocorrelation of the column's brightness profile | **28px at 0.899**; next candidate 0.385. Pure CV, **no model call** |
| row order | read the account column from a **CLEAN** screenshot | **11/11**, three runs ([0008](0008-dense-numeric-text-is-misread.md)) |
| row for account X | `origin + index(X) * pitch` | arithmetic |

```
ParaBank overview, account column
row tops   350  378  406  434  462  490  518  546  574  602  630
diffs           28   28   28   28   28   28   28   28   28   28

13344 is index 9 in the clean read  ->  350 + 9*28 = 602
real 13344 row                      ->  602..616                   exact
```

**Phase needs one anchor.** Autocorrelation alone recovered the pitch perfectly
but put the origin a constant 7px out, because "brightest offset" finds the top
of the stripe rather than the text baseline. A constant offset is what a single
grounded anchor calibrates — and the header is exactly that anchor.

### Why this is better than the fix this issue originally proposed

The original plan was: enumerate candidate rows, have the model read each one,
pick the one matching the parameter. That needs eleven readings on an image we
now know is defaced by our own overlay. This needs **one** template match on a
non-repeating element, **one** clean read, and arithmetic.

It also sidesteps the malformed question I posed after 0008 — *"does the overlay
corrupt cell assignment too?"* There is no way to answer that: cell assignment
**requires** the overlay, so no clean baseline exists. The right question was
whether repeated structures need cell assignment at all. They do not.

### Not yet built, and the honest gaps

- **Untested on a second table.** ParaBank's overview has uniform 28px rows and
  alternating stripes. A table with variable-height rows, or grouped headers,
  breaks the pitch assumption — and the autocorrelation peak would say so
  (a weak or split peak is the signal to refuse rather than guess).
- **Order must come from the same render as the click.** If the app reorders
  rows between the read and the action, the index is stale. The read and the
  act have to share one screenshot, or the checkpoint has to catch it.
- **It still needs the clean-read split** from [0008](0008-dense-numeric-text-is-misread.md)
  to land first, since the 11/11 depends on an un-gridded image.
