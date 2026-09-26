# 0008 — The model misreads dense numeric text. 6 of 11, measured.

**Severity: high.** It qualifies the project's headline finding, it puts wrong
account numbers into control ids today, and the fix proposed for
[0007](0007-parameterised-row-selection.md) depends on the thing that is broken.

## Measured

ParaBank's Accounts Overview, one real discovery run (2026-09-26), scored
against the REST oracle:

```
ground truth (11 accounts)  12345 12456 12567 12678 12789 12900 13011 13122 13233 13344 54321

read correctly   6   12345, 12456, 12678, 12789, 13122, 13344
WRONG            4   13001, 13323, 13767, 54221      <- no such account exists
missed           5   12567, 12900, 13011, 13233, 54321

                 6/11 = 54%
```

Three of the four wrong ones are **digit transpositions of a real account**:

```
  13011  ->  13001      a digit dropped and shifted
  13233  ->  13323      two digits swapped
  54321  ->  54221      one digit changed
```

The fourth, `13767`, matches nothing. None of the four announced any doubt.

## Why this matters more than it looks

**It contradicts the sentence this project has been building on.**
[findings.md §2](../findings.md) says, and has said since the first week:

> Vision models read a screen accurately and locate it badly.

That is still true **of labelled controls** — `Username`, `Password`, `Log In`
came back verbatim on every run, and that measurement stands. It is **not** true
of dense numeric data in a table. The original claim was measured on a login
screen with five well-spaced labelled controls, and generalised to "reading" as
a whole.

Three consequences, in order of how much they hurt:

1. **Control ids are slugs of read labels**, so `control_maps/.../overview.json`
   currently contains `13767_link` — an id for an account that does not exist.
   A capability naming it can never replay.
2. **[0007](0007-parameterised-row-selection.md)'s proposed fix is unsound as
   written.** It says: enumerate candidate rows, have the model read each one,
   pick the row whose text matches the bound parameter. At 54% that picks the
   wrong customer's account roughly half the time — and picks it *confidently*.
3. **Extraction is the same operation.** A capability whose declared output is a
   balance read off the screen is exposed to exactly this. Handing a bank the
   wrong number while reporting success is the failure this whole system exists
   to prevent.

## What it does NOT mean

Not "the model is unreliable, add retries". The failure is specific and its
shape suggests the mechanism: small glyphs, uniform digits, no linguistic
redundancy to constrain the guess. A word can be inferred from context; `13011`
cannot.

It also is not an argument against the dot-grid grounding work, which measured
3/3 and is unaffected — that asks the model to *point*, not to *read*.

## What to do instead

Untried, in rough order of preference:

- **Do not read the number at all.** ParaBank routes account details as
  `activity.htm?id=13344`, and §8 of the brief blesses `/item/12345 ->
  /item/:id` parameterisation explicitly. Navigating by a templated URL is
  deterministic and needs no reading. The cost is that it bypasses the screen,
  which cuts against [ADR 0002](../adr/0002-playwright-screenshot-control.md) —
  so it should be a recorded, deliberate fallback with its own provenance on the
  step, not a silent shortcut.
- **Zoom before reading.** Grounding already works by magnifying a cell; the
  same crop handed back for reading gives the model far larger glyphs. Cheap to
  test: re-read the 11 rows from crops rather than the full screenshot, and
  re-score against the oracle. **This is the next measurement to take.**
- **Read it twice and require agreement.** Turns a silent wrong answer into a
  detectable disagreement. Doubles the cost and does not fix a stable misread.

## The check

`/tmp` scratch is not a check. The comparison above should live in the repo as a
`live`-marked test that reads the overview map, pulls ground truth from the REST
oracle, and asserts the read rate — so that a change intended to improve it can
be shown to have improved it, and so this number cannot quietly rot.

## Related

- [0007](0007-parameterised-row-selection.md) — depends on this being fixed
- [0001](0001-incomplete-inventory.md) — naming churn; this is naming *error*,
  which is worse: churn is visible across runs, a wrong id looks fine
