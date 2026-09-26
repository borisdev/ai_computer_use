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
