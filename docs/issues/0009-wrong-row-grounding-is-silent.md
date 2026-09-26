# 0009 — A grounded account link points at the WRONG ROW, and says `ready`

**Severity: highest so far.** Every other open issue fails loudly. This one
produces a confident click on a different customer's record, which is the exact
failure the whole project exists to prevent.

## Measured

ParaBank's Accounts Overview, the control map from the 2026-09-26 discovery run,
scored against the DOM as an oracle (the agent and replay path never read the
DOM — [ADR 0002](../adr/0002-playwright-screenshot-control.md) — a diagnostic
may):

```
real account links, all of them   x = 492..525, rows 28px apart
  12345  y 350..364      12900  y 490..504
  12456  y 378..392      13011  y 518..532
  12567  y 406..420      13122  y 546..560
  12678  y 434..448      13233  y 574..588
  12789  y 462..476      13344  y 602..616
                         54321  y 630..644

what discovery marked `ready`
  12345_link   point (500, 361)   INSIDE its own link            ✅
  12456_link   point (500, 359)   that is 12345's row            ❌
  13122_link   point (511, 466)   that is 12789's row            ❌
  13001_link   point (500, 386)   no such account exists         ❌

                                  1 of 4 correct
```

The column is right every time. The **row** is wrong 3 times in 4.

## Why it is silent, which is the whole problem

`status: ready` means discovery ground a click point AND the landmark around it
self-matched uniquely. Both are true here — the landmark is a genuine, unique
patch of screen. It is simply a patch around **the wrong row**.

So at replay `locate_control` will find that landmark, score it near 1.0000,
and click it. Nothing downstream can tell. The capability says
`13122_link`, the artifact reviews cleanly, the click lands on 12789, and the
run reports success with another customer's balance.

Compare the six links that failed to ground (`13344_link` among them). Their
refinement zoomed a cell containing no account numbers at all and the model
said so, so they came back `unresolved` and the run escalates. **Those are the
benign half.** An honest `unresolved` costs a re-run; a wrong `ready` costs a
wrong record.

## Root cause

A coarse grid cell is **80px**. A table row is **28px**. Nearly three rows per
cell, and the rows are identical but for four digits.

The coarse pass names a control and assigns it one `cell_id`. For eleven
near-identical rows it cannot reliably say which cell holds which, and the
refinement that follows only ever sees the cell it was handed — so it grounds
confidently inside whatever row is there. There is no step that asks "is the
thing I grounded the thing I was looking for?"

That is also the shared cause with [0008](0008-dense-numeric-text-is-misread.md)
— small, uniform, redundancy-free text in a dense table — but the mechanisms are
different and only one of them is loud:

```
0008   the LABEL is wrong          13011 read as 13001       visible: the id is bogus
0009   the CELL is wrong           13122 grounded on 12789   invisible: both are real
```

## What would catch it

Nothing in the pipeline does today. In rough order of cost:

- **Verify after grounding.** Zoom the grounded point and ask what is there;
  refuse if it does not match the control's own label. One extra call per
  control, and it closes the loop that is currently open — nothing ever checks
  the refinement's answer against the coarse pass's claim. ⚠️ It leans on
  reading, which 0008 measures at 54% on this exact text, so it must be
  measured, not assumed.
- **Make the grid finer where controls are dense.** `coarse_cell_px=80` against
  a 28px row is the arithmetic of the bug. A cell smaller than the row pitch
  makes the assignment unambiguous, at the cost of more cells to enumerate —
  which [0001](0001-incomplete-inventory.md) already says is the thing that
  destabilises the inventory. The two pull against each other.
- **Do not target rows visually at all.** ParaBank routes account details as
  `activity.htm?id=13344`, and §8 of the brief blesses `/item/12345 ->
  /item/:id`. Deterministic, no reading, no grounding. It bypasses the screen,
  which cuts against ADR 0002 — a recorded, deliberate fallback with its own
  provenance on the step, never a silent shortcut.

## The check that should exist

The measurement above, as a `live`-marked test: log in, read the real link boxes
from the DOM oracle, and assert every `ready` control whose id looks like an
account number grounds inside that account's own link. It goes red today at
1/4, which is the right starting state for a check.

## Related

- [0008](0008-dense-numeric-text-is-misread.md) — same screen, same cause, loud
- [0007](0007-parameterised-row-selection.md) — wanted to pick a row by reading
  it; this says the row it lands on is not reliably the row it named
- [0001](0001-incomplete-inventory.md) — a finer grid trades against inventory
  stability
