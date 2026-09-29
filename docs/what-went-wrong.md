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

## And the fix for that was wrong, which took one hour to find

The obvious repair was to make the claim true: re-run `capability.requires`
after the operator hands back. It shipped, and `resume` broke for every
capability in the library.

`requires` holds **entry** preconditions — `at_the_login_page` for anything
that logs in. They describe where a run STARTS, so by the time a handoff
happens they are necessarily false: you are mid-flow, past the login screen.
The run came back *"username_textbox should be present"*, blaming the operator
for a page they were right to have left.

```
entry precondition   must hold when the run starts       NOT resume-checkable
invariant            must hold throughout                 resume-checkable
```

The schema cannot tell those apart, which is the actual gap ([#10]). The
correct repair was to fix the **sentence**, and to let resume keep verifying
what it already verified well: the stopped step's own footing, advance /
retry / stay-paused per verb, and an irreversible step never retried on a
guess.

⚠️ Found by running the demo the README tells a reader to run — one hour after
shipping the fix, and after the offline suite went green on a test that
asserted the broken behaviour. **A false sentence in a document is cheaper
than a true sentence bought with a broken resume.**

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

## A pitch that every gap agreed with, and that was 20px wrong by row 10

Deriving a panel's geometry (#6), the row pitch came from ink runs: take the gaps
between consecutive rows and keep the ones within a pixel of the first. Eleven
gaps all passed. The pitch it produced put marker band 10 **twenty pixels** off
the row it was meant to contain.

    gap 0    28        every gap within ±1 of the one before it
    gap 1    29        a systematic +1 is INSIDE the tolerance
    ...      ...       and it accumulates
    row 10   576..586  band 596..623

A tolerance chained pairwise measures agreement between neighbours and says
nothing about the fit. Predicting `first + i * pitch` and then refitting across
the whole stretch is the same three lines and cannot drift.

⚠️ **Nothing about the failure was subtle except where it was checked.**
`marker_bands_contain_every_row` caught it on the first live run, which is the
argument for having written the verifier before the producer — the handoff for #6
said so in as many words, and it was right.

## A header row is exactly one row pitch above row one

The same geometry, anchored on the page heading *Accounts Overview* rather than
the *Account* column header, measured **13 rows over 11 accounts**: the shaded
header row and the Total line both joined the rhythm, because a header sits one
pitch above row one and nothing about its POSITION says otherwise.

What distinguishes it is the shading — the one property a column header actually
has. `_is_a_header_bar` compares the line's median against what is under it;
zebra striping (230 and 238 against a median of 235) does not trip it and the bar
(194 against white) does.

⚠️ **And the model was right.** Asked for "the heading above the rows" it named
the page heading, which IS a heading above the rows. The bug was in what the
geometry did with a correct answer, and the test that pins it asserts that BOTH
anchors arrive at the same table to the pixel.

## A menu 68px from a table swallowed it, and no distance rule can help

The account-services menu on the loan-result screen came out **722px wide**
instead of 170, having absorbed the result table beside it. The gap between them
is 68px; the accounts table's own column gutters are **79 and 84px**. So there is
no threshold that keeps one and rejects the other — a fact worth knowing before
reaching for one.

The menu repeats every 24px and the table every 23, and containment was not
enough either: an 11px row inside a 24px band leaves 12px of slack, which absorbs
1px of drift for five rows. What gives it away is WHERE in its band each run
sits. A real column of this table puts its glyphs the same distance below every
row boundary; a foreign rhythm creeps — 5px, then 4, then 3.

## The approval gate could not see the artifacts it exists for

`interfaceai capability approve discovered_balance` answered *"no capability
named 'discovered_balance'; known: log_in, read_savings_balance, …"*. It resolved
names against the in-code registry only, so a draft a discovery run had just
emitted could not be promoted — the `draft → approved` gate was **unreachable for
every discovered artifact**, which is exactly the set it was built for.

`interfaceai diagram` already had the fallback, with a comment explaining why
("NOT EVERY CAPABILITY IS AUTHORED"). One command had learned the lesson and the
one next to it had not, which is the argument for the shared `_capability_named`
rather than a second copy of the fallback.
