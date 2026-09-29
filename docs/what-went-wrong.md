# What went wrong, and what each one cost

The long form of REPORT §3, §5 and §6's warnings. Kept out of the write-up so
it stays near its asked length, kept in the repo because a list of only what
worked is not evidence of judgement.

Ordered by what they teach, not by severity.

## A run-level flag answered a tenant-level policy

```
$ interfaceai replay …/request_loan.v1.approved.json --param amount=25000 --confirm-risky
SUCCESS request_loan in 10 steps                       ← submitted. $1,000 threshold.
```

The gate read `if irreversible and not ctx.confirm_risky:`, so confirming
irreversible steps skipped the value check **entirely**. The threshold was not
raised or misread — it was never consulted.

Two different authorities, collapsed into one condition, which inverted their
precedence. `--confirm-risky` is the **caller** saying *this run may do
irreversible things*. `confirm_money_above` is the **bank** saying *a person
signs off above this amount* — a question never addressed to the caller, so
the caller's blanket yes cannot answer it. Tenant policy is checked first now.

**The level is the lesson.** `needs_human_confirmation` was correct throughout
and its unit test passed the entire time the bypass existed. The defect was the
*branch*. Found by running the demo to capture real output for the write-up.

## The same bypass again, one page further along

`money_on_form` was cleared on URL change. So a two-step flow — enter $25,000
on page 1, confirm on page 2 — submits against an **empty form**, gated by
`--confirm-risky` alone. Found by `evals/grade.py` a commit after the fix
above, in the code that fix had just touched.

Three attempts at one rule:

```
cleared after every action   the form was empty at the submit; the rule never fired
cleared on URL change        a multi-page flow bypasses it
never cleared                over-escalates, which is the safe direction
```

All three were trying to avoid one false positive: Find Transactions has an
`amount` field and nobody wants a search to need a human. That was already
solved by judging at the **irreversible** step — a search has none, so it is
never judged. The clearing was defending against a problem that no longer
existed.

⚠️ Latent, never live: ParaBank's loan form is one page. Pinned by a
source-level test, because a behavioural one needs a multi-page money flow this
target does not have — which is exactly why nothing caught it.

## A secret could leave through `returns`

The schema refuses a literal in a sensitive slot — that is the way **in**.
Nothing covered the way **out**, so an `EXTRACT` into `password` would lift it
off the screen and hand it to the caller past every redaction we have.

Discovery proposed exactly that for `username`, on **two runs out of two**.
Refused now in `validate_capability` *and* at the point discovery produces it:
refusing only at the approval gate makes every draft unapprovable and leaves a
reviewer to work out why.

The disk test that should have caught it **crashed on a `None`** instead of
reporting. A check that errors is not a check that fails.

## "Preconditions are re-checked on resume" was false

REPORT.md and `Precondition`'s own docstring both said so. The sweep ran once
at `_run` entry; `_hand_over` re-checked only the stopped step's own control.
A person who navigated elsewhere during a handoff would be resumed onto footing
nobody verified.

Found by `evals/grade.py` reading the write-up against the code. **The claim
was in a graded document for as long as it was false** — which is the
uncomfortable part, and the reason that eval exists.

## Escalations reached a human with no screenshot

§3.6 asks the request to carry *"the current state or screenshot"*.
`NeedsOperator` has always had the field; **2 of its 19** construction sites
filled it. Attached at the single exit point rather than seventeen call sites.

## The grid overlay corrupted the labels it was there to help place

One model call did two jobs on one image: name the controls *and* assign cell
numbers. Measured, those want opposite images.

```
clean screenshot    11/11 account numbers read correctly
192-cell grid        8/11 — and the gridded run reproduced an exact wrong id
                          from a live failure
```

## Grounding a row in a uniform table is silently wrong 3 times in 4

A wrong cell in a uniform table looks exactly like a right one. Relabelling
does not fix it — three schemes measured, best 3/15. The answer was to stop
grounding rows: read the region in one call, index in code, reach it by a
**measured pitch** (28px, autocorrelation 0.899).

⚠️ It generalises past tables. The site nav was **0/8** grounded — the same
defect wearing different clothes. Repeated structure needs a panel.

⚠️ And fixed-interval markers do **not** work as a cross-check: at 7px the
deltas land in 14px bands. Matching it can do; counting it cannot. Numbered
*bands* work, because containment beats proximity.

## Two reader bugs that made a run look like something else

- An invoked capability writes into the **same evidence file**, so its
  `replay_succeeded` made `request_loan` — which always escalates — read as
  `SUCCESS`. Events now carry which capability they describe.
- A `NeedsOperator` with no operator attached emitted **no terminal event**, so
  the reader called the run "incomplete", which looks like a crash. Every run
  writes its own `replay_finished` now.

## Deleting "stale" evidence broke 24 tests

Two old runs in `evidence/runs/` are **test fixtures** — five files read PNGs
out of them. Removing them as housekeeping produced 24 `FileNotFoundError`s
several layers from the cause. Recorded in
[`evidence/README.md`](../evidence/README.md) where someone would look first.

## Two traps this target sets

- **Readiness is not liveness.** ParaBank serves HTTP 200 with no database
  schema behind it, and the healthcheck stays green throughout.
- **Not-found is HTTP 200 plus plain text.** Status codes cannot detect it.

## And the harness was wrong more often than the system

Recorded because it was the most expensive category and the least expected:

- A regression test **passed with the fix reverted** — wrong geometry; rebuilt
  with a 17px gap.
- A cross-check test painted bands over the whole table (0 rows), and a "blank
  strip" autocorrelated at 8px. The correct method was to notice the column was
  too **short** to hold two periods.
- A claimed guard against recovery re-invoking a forbidden capability had **no
  reachable path** — with a static allowlist the run dies at step 0.

`.claude/rules/checks.md`, in one line: a check must exercise the thing that can
break, and *"I measured it"* is not the same as *"I measured the right thing."*
