# 0010 — Extraction can only target a control, and data is not a control

> **Severity: highest.** It is a hole through the middle of §3.2. Every
> capability that returns a value — which the brief says is most of them — has
> nowhere to point. It also makes two other issues irrelevant to the capability
> that motivated them.

Found 2026-09-26 by Boris asking the obvious question nobody had: *why are these
rows controls that need clicking? Is seeing the table sufficient?*

## The hole, in three lines of existing code

```
capability.py    _NEEDS_CONTROL includes StepVerb.EXTRACT   -> extraction targets a CONTROL
control_map_store.py  a ControlRef resolves through the inventory
screenshot2controls.py  the coarse prompt: "Ignore static text, images and layout."
```

A balance is static text. The inventory is told to skip it. So it has no id, so
no `EXTRACT` step can name it. **There is no way to express "read that table
cell."**

## What it caused

**The model reached for the nearest thing that had an id.** Asked to extract on
the overview, it named `13344_link` — a hyperlink — because a link is the only
object near the number that the inventory produces. That is not the model being
careless; it is the only vocabulary we gave it.

**The hand-authored capability 1 names ids that cannot exist.**
`capabilities.py` references `balance_value`, `account_type_value` and
`account_number_value` on the `activity` screen. Discovery can never emit those:
they are static text by definition. The artifact validates, reviews cleanly, and
is unbuildable.

**It sent us chasing the wrong bug for a day.** The measured route to a balance
was: find the account's row link, ground it, click it, read the detail page.
Steps 1–3 are where [0007](0007-parameterised-row-selection.md),
[0008](0008-dense-numeric-text-is-misread.md) and
[0009](0009-wrong-row-grounding-is-silent.md) all live. None of them needed to
be on the path.

## Measured: the click was never necessary

DOM oracle, both pages, 2026-09-26:

```
overview.htm              Account | Balance* | Available Amount
                          13344   | $1231.10 | $1231.10          <- the answer, already on screen

activity.htm?id=13344     Account Number:  13344
                          Account Type:    SAVINGS               <- the ONLY thing the click adds
                          Balance:         $1231.10
                          Available:       $1231.10
```

Reading the balance off the overview needs **no click, no row targeting, and no
navigation**. The entire account-row problem is off the critical path for the
assignment's own worked example.

⚠️ **One thing genuinely does require the detail page:** `Account Type`. Our
checkpoint asserts `SAVINGS`, and that is what catches ParaBank's CLEAN state
serving 13344 as `CHECKING $5,022.93` — the wrong-record failure the checkpoint
exists for. So the click is not useless; it is not needed to answer the
question, only to prove which record answered it. Whether that is worth
re-introducing the 0009 risk is a real trade, and it should be decided
deliberately rather than by which code happened to exist.

## The fix, from machinery that already exists

A locator today is *a landmark patch + a click offset* → resolves to a **point**.

Reading needs *a landmark patch + an offset + a size* → resolves to a **region**.

Same template matcher, same stability guarantees, same `not_found` / `ambiguous`
refusals. What differs is the verb applied at the end: click a point, or read a
region.

That implies three changes, in order:

1. **A `TextRegion` locator** alongside `VisualLocator`, or the same type with an
   extent. `locate_control` already returns `matched_crop`, so the region is
   half-built.
2. **The inventory must see data.** A second pass, or a widened prompt, that
   reports labelled READABLE regions (`Balance: $1231.10`) distinctly from
   interactive controls. They are different kinds and must not share a list —
   `role` already distinguishes them, and a `DATA` role would let one inventory
   carry both without the decision layer ever offering to click a number.
3. **`Step.EXTRACT` targets a region, not a `ControlRef`.** That is a schema
   change to the artifact and wants an ADR amendment, not a quiet edit.

### ⛔ It does NOT reuse `unstable_regions`, and the geometry says why

An earlier draft of this section said the landmark machinery "already does
exactly this bookkeeping — it just needs data regions added to the exclusion
set". Measured on `activity.htm?id=13344`, that is wrong three ways:

```
Account Number:  x 490..592  y 316..337   h=21
13344            x 594..653  y 316..337
Account Type:    x 490..592  y 339..360
SAVINGS          x 594..653  y 339..360
Balance:         x 490..592  y 362..383
$1231.10         x 594..653  y 362..383
Available:       x 490..592  y 385..406
$1231.10         x 594..653  y 385..406
```

1. **The whole block is 90px and a coarse cell is 80px.** Marking any value's
   cell unstable marks every label in the block — including the one anchor that
   says which number is being read. It would push the landmark off the details
   table entirely.
2. **It is not an exclusion set.** `usable.sort(key=overlap)` is a soft ranking;
   the minimum wins and nothing is ever refused. That is exactly how
   [0009](0009-wrong-row-grounding-is-silent.md)'s contaminated landmark got
   chosen.
3. **It is not a config change.** `_make_locator` yields
   `(template, click_offset)` → a point. A read needs
   `(template, offset, size)` → a region.

**The geometry hands over a simpler construction instead.** The label ends at
x=592 and the value starts at x=594 — 2px apart, same 21px row. So a read
locator is *anchor on the label, read immediately beside it*:

```
template      "Balance:"                 stable by definition -- it is the field name
read region   +2px right, same row, ~60px wide
```

The mutable-pixel problem then **disappears rather than needing machinery**: the
template contains only the label, so the value changing cannot degrade the
match. Reads do not reuse the unstable-region logic; they make it unnecessary.

What does carry over: `locate_control` itself, the constant-template rejection
guard, and the `not_found` / `ambiguous` / `incompatible` contract.

⚠️ This is measured on ParaBank's label-left/value-right detail table. A layout
with the label ABOVE the field, or no label at all, needs a different anchor —
and a column of eleven balances with one header has no per-row label, which is
the table case and is not solved by this.

⚠️ **Reading is the operation [0008](0008-dense-numeric-text-is-misread.md)
measures at 54% on this exact text.** A region read from a zoomed crop is the
untested hope — grounding already magnifies cells, so the machinery is there,
but nobody has scored it. **Measure before building on it.**

## What this does NOT mean

Not "0007 and 0009 are closed". A capability that must *act* on one of N
identical rows — transfer from a chosen account, open a specific record — still
needs exactly the row targeting those issues describe. What changed is that
**reading a value is no longer one of those capabilities**, so the assignment's
worked example stops being blocked by them.

## Related

- [0009](0009-wrong-row-grounding-is-silent.md) — wrong-row grounding. Still
  real, no longer on capability 1's path.
- [0008](0008-dense-numeric-text-is-misread.md) — the read accuracy the fix
  above depends on.
- [ADR 0005](../adr/0005-capability-artifact-shape.md) — declares a step names a
  control. That is the sentence this issue amends.
