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

![wrong-row grounding](../../evidence/issue-0009-wrong-row-grounding.png)

Green boxes are the real links, read from the DOM oracle. Red crosshairs are
where discovery ground a click point and marked the control `ready`. Blue lines
are the 80px coarse grid the inventory pass works in.

The crosshairs bunch in the top three rows while the accounts they NAME are
spread down the whole table. `13122_link` is grounded 80px above its own row —
exactly one coarse cell — and `13344`, the account the assignment's worked
example needs, has no crosshair at all.

```
   80px coarse grid          real rows, 28px pitch        grounded point
 y=320 ├──────────────
                            12345  350..364   <--  12345_link (500,361)  ok
                            12456  378..392   <--  12456_link (500,359)  WRONG: 12345's row
 y=400 ├──────────────                        <--  13001_link (500,386)  WRONG: 12456's row
                            12567  406..420                              (+ no such account)
                            12678  434..448
                            12789  462..476   <--  13122_link (511,466)  WRONG: 12789's row
 y=480 ├──────────────
                            12900  490..504
                            13011  518..532
 y=560 ├──────────────
                            13122  546..560   <--  what 13122_link NAMES. nothing grounded here.
                            13233  574..588
                            13344  602..616   <--  capability 1 needs this. ungrounded.
 y=640 ├──────────────
                            54321  630..644
```

Three rows per cell, and the cell is the only positional information the
refinement step is given.

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

## Root cause — and the first answer here was wrong

⛔ **This section said "a coarse cell is 80px, a row is 28px, so three rows per
cell". That explains ONE of the three failures.** Boris asked whether `13001_link`
was wrong even allowing for the grid; it is, and checking properly changed the
diagnosis.

The refinement step can only ground *inside* the cell the coarse pass handed it,
so `cell(grounded_y)` **is** the assigned cell. That makes the question testable:
does the true row sit in that same cell?

```
control        ground y   assigned cell | true row   true cell | verdict
12345_link          361       320-400   |      357    320-400  | correct anyway
12456_link          359       320-400   |      385    320-400  | within-cell ambiguity
13122_link          466       400-480   |      553    480-560  | WRONG CELL by 1  (80px)
13001_link          386       320-400   |      525    480-560  | WRONG CELL by 2 (160px)
```

So the dominant failure is **not** resolution, it is **assignment**: the coarse
pass reports a cell number the control is not in. Only `12456_link` is the
three-rows-per-cell story.

That is the same defect [0001](0001-incomplete-inventory.md) already names as an
aggravating factor, arriving somewhere new:

> **192 numbered cells**, nearly all of them empty. The model must enumerate
> controls *and* map each to one of 192 numbers.

Enumerating is one task; mapping each result onto a number in a 192-cell overlay
is a second, and it is the one that fails here. The refinement then grounds
confidently inside whatever row happens to be in the cell it was given, and
nothing ever asks "is the thing I grounded the thing I was looking for?"

That is also the shared cause with [0008](0008-dense-numeric-text-is-misread.md)
— small, uniform, redundancy-free text in a dense table — but the mechanisms are
different and only one of them is loud:

```
0008   the LABEL is wrong          13011 read as 13001       visible: the id is bogus
0009   the CELL is wrong           13122 grounded on 12789   invisible: both are real
```

## Why coarse -> fine does not catch its own mistake

![what the coarse pass sees](../../evidence/issue-0009-what-the-coarse-pass-sees.png)

The overlay the coarse pass is given, cropped to the table. Cell 71 holds two
account links, cells 87 / 103 / 119 hold three each — and **every one of those
cells looks the same**: underlined blue numbers in the same column position.

```
COARSE   whole screenshot + 192 numbered cells
         "list the controls, and for each say which cell number it is in"
                     |
                     |  passes ONE NUMBER forward
                     v
FINE     crop that cell, enlarge, put dots on it
         "which dot is on the target?"
```

The fine pass never sees the whole screen again, so it cannot check the number
it was handed. For `13122`:

```
truth     13122 is in cell 103
coarse    says cell 87                       miscounted the grid rows
fine      crops 87, looks for "an account number link"
          finds 12567 / 12678 / 12789 -- three, all plausible
          grounds on 12789, returns click(n) at full confidence
result    status: ready, landmark unique, ~1.0 at every future replay
```

**The unstated assumption is that a wrong cell will look wrong.** It does when
controls are distinguishable — that is why the login screen scored 3/3 — and the
evidence shows it holding and failing on the same screen:

```
6 links   got a cell in the BALANCE column       nothing like an account link
                                                 -> unresolved. assumption HELD.
3 links   got a NEIGHBOURING ACCOUNT cell        something matching was there
                                                 -> clicked it. assumption FAILED.
```

And telling 12789 from 13122 means reading five small digits, which
[0008](0008-dense-numeric-text-is-misread.md) measures at 54% — so the check
that could catch this is unreliable at exactly this text size.

## What would catch it

Nothing in the pipeline does today. In rough order of cost:

- **Verify after grounding.** Zoom the grounded point and ask what is there;
  refuse if it does not match the control's own label. One extra call per
  control, and it closes the loop that is currently open — nothing ever checks
  the refinement's answer against the coarse pass's claim. ⚠️ It leans on
  reading, which 0008 measures at 54% on this exact text, so it must be
  measured, not assumed.
- ⛔ **A finer grid is the WRONG fix, and was proposed here before the
  measurement above.** It would help the one within-cell case and make the two
  dominant ones worse: halving the cell size quadruples the cell count, and
  picking the right number out of 192 is already what is failing. Recorded
  rather than deleted, because it is the intuitive answer and the next person
  will reach for it too.
- **Tile the scan** — the prototype in [0001](0001-incomplete-inventory.md),
  which is now the leading candidate for this issue as well. Each tile is shown
  with its zone marked and the model reports only controls centred inside it, so
  position comes from *which tile answered* rather than from the model mapping a
  control onto one of 192 numbers. It measured 27/27/26 against 24/19/24 for
  inventory stability; its effect on cell-assignment accuracy is **unmeasured**
  and is the experiment to run.
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
