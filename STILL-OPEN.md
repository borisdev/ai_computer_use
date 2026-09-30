# Still open

Everything REPORT §7 cuts or defers, in one editable page. Each item says what
it is, why it is open, what proves it, and what it would cost.

**Fill in the `Decision:` lines.** They are the only thing here I will not
change without you.

---

## A · Would make the submission stronger

### A1 · ~~Capability 1 does not replay~~ — **DONE 2026-09-28**

```
$ interfaceai replay artifacts/read_savings_balance.v2.approved.json --param account_id=13344
SUCCESS read_savings_balance in 7 steps
  found_account_id = 13344
  balance = $1231.10

  13122  -> $1100.00     12345 -> -$2300.00     both match the seed fixtures
  99999  -> record_not_found, exit 0            a BUSINESS OUTCOME, not a failure
```

`interfaceai capability check` went **8 faults → ok**. What it took:

- `PanelSpec` on a control — the anchor's offsets, the columns, the key column
- `Step.row_key` + `Step.field` — "the row where key = param, read this column"
- the executor builds the response schema from the panel's own columns, reads
  the table in ONE call, and selects the row **in code**
- `scripts/add_panels.py` — stood in for the discovery step, committed so the
  geometry is reviewable. ⛔ **No longer the only route: `screenshot2panels`
  proposes panels and `scripts/discover_panels.py` stores them (#6).** These four
  ids stay hand-measured because these artifacts name them

**Two things this bought beyond capability 1:** the first real
`BusinessOutcome` instance we have ever produced (99999), and issue 0009 is now
off this path entirely — no row is ever grounded.

⚠️ **One thing it cost.** v1 drilled into `activity.htm` to read `Account Type`,
so after `env break` it caught 13344 coming back as CHECKING. v2 reads the
overview, where there is no type column, so it reports the balance of whatever
13344 now is. Restoring the stronger checkpoint needs the drilldown, which needs
A3. Recorded in `capabilities.py`.

> **Decision:**

---

### A2 · Extraction of a single value still needs a control
[issue 0010](docs/issues/0010-extraction-cannot-point-at-data.md)

**Half solved.** A value inside a TABLE is now reachable — that is what
`TABLE_CONTROL_PANEL` does, and capability 1 uses it. A value that is *not* in a
table still is not: `EXTRACT` names a control, the inventory is told to ignore
static text, so a lone `Balance: $1,231.10` on a detail page has no id.

**Fix:** a region locator — landmark + offset **+ size**, reusing the matcher
that already exists. `locate_control` already returns `matched_crop`.

**Cost:** ~2h, plus an ADR amendment (it changes the artifact schema).

> **Decision:** CUT — filed as [#4](https://github.com/borisdev/ai_computer_use/issues/4).
> Nothing needs it: every capability in `LIBRARY` works without it, so it is an
> abstraction with no caller. Both instances we actually hit had structure and
> a panel was the better answer. §7 Cuts.

---

### A3 · ~~Row drilldown by grounding~~ — **DONE 2026-09-28**

```
$ replay read_savings_balance.v3 --param account_id=13344
SUCCESS in 12 steps
  found_account_id = 13344
  balance          = $1231.10
  account_type     = SAVINGS          <- the checkpoint v2 gave up

$ replay read_savings_balance.v3 --param account_id=12345      # a CHECKING account
FAILED at checkpoint on account_type
  expected  SAVINGS
  observed  CHECKING                                            exit 1
```

**A capability that promises a savings balance now refuses to hand back a
checking one** — on seeded data, no database manipulation.

The drilldown lands by arithmetic, not by grounding. From the run trace:

```
row_resolved   key=13344  index=9  pitch=28  x=508  y=614
```

Index 9 comes from the panel read; y comes from the measured rhythm; 614 is
inside 13344's link box (602..616). **No model is asked where a row is**, which
is what keeps issue 0009 off this path.

**What it took:** `PanelSpec.key_click_dx` (18px, measured), `CLICK + row_key`
in the schema, a `_read_panel` helper so extraction and drilldown share ONE
cached call, and `account_details_panel` — the detail page is itself a
label/value table, so it needed no new mechanism.

⚠️ **A panel is not clickable at its anchor.** `check_capability` refuses a
bare click on a panel and requires a `row_key` plus a declared `key_click_dx`.
Widening `ACTIONS_BY_ROLE` instead would have permitted a meaningless click at
the header.

⚠️ **A one-row table cannot be drilled** — autocorrelation has no period to
find, so it refuses (`NeedsOperator`, exit 1) rather than guessing a position.
Reading a one-row table still works. Pinned by a live test against `env break`.

⚠️ **Issue 0009 itself is NOT fixed** — grounding a row visually still lands
wrong 3 times in 4. It is now *off the path* rather than repaired, which is the
better outcome: the defect has no caller.

> **Decision:** DONE

---

### A4 · ~~The read/locate split~~ — **DONE 2026-09-28**

The coarse pass made one call do two jobs on one image: name the controls AND
assign cell numbers. Those want opposite images. Now it is two calls — read from
the clean screenshot, place using the grid.

Verified by a fresh discovery run against the live app:

```
                        account ids    invented    13344         map grounded
before (one call)       6/11           4           unresolved    22/34
after  (read + locate)  11/11          0           ready         27/34
```

`log_out_link`, which the single pass never found at all, now appears.

⚠️ **The grid did not go away and did not change.** It is still what the locate
pass and the refinement dots use — it simply stopped sitting on top of the text
while we read it. (The A/B/C margin-label idea was tested separately and
rejected: 0/15 against the current grid's 3/15, recorded in issue 0009.)

Three tests had to change because they were pinned to the old broken data,
including one asserting `13344_link` was ungrounded. A mechanism test should not
depend on a defect persisting, so it builds its own unresolved control now — and
a new test pins the improvement so a regression is loud.

> **Decision:**

---

### A5 · Constrain the RESPONSE SCHEMA, not just the prompt

Reframed 2026-09-28 by Boris: *"every single LLM extraction step uses a pydantic
model … and the values are typed and constrained by our controlled language
wherever feasible."*

**The first half is already structurally true.** `VisionCall` requires
`response_model: type[T]` bound to `BaseModel`. Seven call sites, seven models,
**no unstructured call path exists.**

**The second half is half true.** Audited:

| | field | |
|---|---|---|
| closed | `role` · `_Refinement.action` · `NextMove.kind` · `NextMove.action` | enums / Literals |
| **free** | `NextMove.slot` · `Extracted.slot` | should be the 21 vocabulary qualifiers |
| **free** | `NextMove.control_id` · `Extracted.control_id` | **the valid ids are known at call time** |
| **free** | `NextMove.value_ref` | **the offered secret refs are known at call time** |
| free | `label`, `description`, `ReadValue.text` | genuinely open — this is transcription |

### The better fix: make it unrepresentable

A prompt is advisory. A schema is **enforced by the provider** — Azure strict
mode rejects an out-of-enum value before it reaches us. And we already do this:
`extract_panel` builds its row schema from `PanelSpec.columns` with
`create_model` at call time.

**Two failures from today it would have made impossible:**

- the model naming `13767_link`, an account that does not exist
- the model naming an **ungrounded** control as an extraction source — patched
  with a fail-closed check after the fact; a closed enum of READY ids removes
  the need for the check entirely

**Work:** a `SlotName` StrEnum generated from `VOCABULARY.qualifiers`; per-call
`Literal` types for `control_id` and `value_ref` built with `create_model` from
what is actually on the screen and actually bound. ~1.5h.

### ⛔ MEASURED 2026-09-28: the naming churn is GONE. Half of A5 dies here.

`scripts/measure_naming_churn.py` — one screenshot, three draws, so the only
variable is the model. Two screens:

```
overview      36 ids   3 draws   0 churned
requestloan   26 ids   3 draws   0 churned
```

**62 ids, 6 draws, not one disagreement** — including the unlabelled controls
(`button`, `button_2`, `button_3`) that were the original complaint.

The reason is structural, which is what makes it trustworthy rather than a
lucky sample: an id is `_slug(label, role)` plus `_unique`'s positional
suffix. It is **derived, not invented**, and only moves if the model misreads a
*label* — and on a server-rendered bank page the labels are crisp text. The old
measurement was taken while the READ pass fought the grid overlay; **A4 fixed
this, and we were one step from building a second fix for it.**

### What SURVIVES the measurement, and it is narrower

The churn argument is dead. The *unrepresentable* argument is not, because it
was never about the same call. The inventory does not invent names — a LATER
call does:

```
the inventory   names controls from what is on screen   MEASURED STABLE
NextMove        names a control_id to ACT on            13767_link, which
                                                        does not exist
```

So the fix is not a global `SlotName` enum. It is a per-call `Literal` on
`NextMove.control_id` and `value_ref`, built with `create_model` from the ids
actually in the map and the refs actually bound — the trick `extract_panel`
already uses for its row schema. Smaller than the original ~1.5h.

### One vocabulary across apps and tenants

Cross-**tenant**: not even a question. Same vendor product, same concepts, and
the artifact is already tenant-agnostic — only the control map is tenant-specific.

Cross-**app**: the weaker claim. These 34 terms are retail banking; a back-office
tool needs holds, memo posting, maker-checker. But *keep one until something
concretely conflicts* is the right default, and it is the same argument as the
vocabulary itself — **fixed beats perfect**, and drifting early gives you a
synonym list.

> **Decision:** SPLIT. The churn half is **closed by measurement** — no fix,
> because there is nothing left to fix, and that is a better outcome than
> building one. The unrepresentable half is **cut**: the failure it prevents is
> already caught fail-closed, so the enum buys enforcement rather than
> correctness, and `project.md` says add the guard when the failing case
> justifies it. Recorded with the number so the next person inherits a
> measurement and not a hunch.

---

### A6 · ~~Capabilities do not compose~~ — **DONE 2026-09-28**

Boris: *"they should be composable. that is the point of the language. a small
canonical subset can express lots, efficiently."* Correct — a capability that
cannot call another is a macro, not a language.

```
read_savings_balance
  step 0  invoke log_in v2      <-- written once, called by anything needing a session
  step 1  wait_for accounts_table_panel
  ...
SUCCESS read_savings_balance in 9 steps   (its 5 + log_in's 4)
```

`StepVerb.INVOKE` + `Step.bind`. The invoked capability runs **in the same
browser session** — not a subprocess, a section of the same run, in the same
evidence file. Its preconditions are checked, because that is what they are for.

Five refusals, each with a test: a missing capability, a **version drift**
(the step pins the version, so a newer library entry is an error rather than a
silent substitution), an **unapproved child** (an approved capability cannot
smuggle one in), self-invocation, and a cycle.

Nested results map deliberately: `Success` merges its outputs and continues;
`BusinessOutcome` **propagates unchanged**, because "no such member" is the
caller's answer however deep it was found; `Failed` and `NeedsOperator`
propagate, the latter because a human resolves in the same live session.

**Two things it forced, both improvements:**

- **The checkpoint rule got narrower and more correct.** It was "every
  capability needs one". `log_in` returns nothing, so it has nothing to compare
  — its success condition is reaching the authenticated nav, which its final
  `wait_for` already asserts. Now: *a capability that RETURNS something must
  check it.* That is the danger ADR 0005 actually names.
- **One panel read now serves every field from it.** Capability 1 takes two
  fields from one row and was reading the table twice — two model calls, and
  two readings of one screen that could disagree. Cached per control, cleared
  by any step with side effects.

> **Decision:**

---

### A7a · ~~Value-dependent risk, the policy rule~~ — **DONE 2026-09-28**

Boris's idea. Today `irreversible` is a property of the **control** — "clicking
Transfer moves money". This is a property of the **control plus the value** —
"moving $1,500 moves money somebody should look at". Two axes, and a bank needs
both.

**It is the gap the handoff bundle named:**

> a click's risk depends on the operation. The reference gate covers basic
> allowlists; **context-dependent risk** … remain integration work.

**Classified where the slot is known, enforced where it always was.**
`needs_human_confirmation(slot, value, above=…)` lives in `decisions.py` and
reads the slot's TYPE from the vocabulary; `use_control` still refuses a risky
action nobody confirmed. One place can act, as before.

**Per tenant, which makes it §3.7 as well** — `INTERFACEAI_CONFIRM_MONEY_ABOVE=
baseline=1000,feature=250`. One institution's routine transfer is another's
exception, so it is configuration rather than a constant. An unlisted tenant
has no threshold and falls back to control-level risk.

Three decisions worth knowing, each with a test:

- **An account number is not an amount.** `13344` parses as a number; the rule
  reads the slot's *type*, and `account_id` is a STRING in the vocabulary
  exactly so identifiers are never arithmetic.
- **A large withdrawal counts.** Magnitude decides, not sign.
- **A money value the system cannot read needs a person**, rather than passing.
  A field we cannot read is not a field we may call small.

20 tests, all offline.

> **Decision:** DONE

---

### A7b · ~~The live demo~~ — **DONE 2026-09-28, via a loan rather than a transfer**

```
$ replay request_loan.v1 --param amount=1500 --param down_payment=200
NEEDS A HUMAN at step 5: this step is irreversible and amount=1500 is at or
above the 1000 threshold for this tenant; a person has to confirm it
  completed: invoke log_in (4 steps), ... enter loan_amount_textbox,
             enter down_payment_textbox
```

**No loan is ever submitted** — the run stops at the irreversible step, so the
fixtures stay clean and the demo is safe to repeat. That is the feature, not a
limitation of the test.

`requestloan.htm` was chosen over `transfer.htm` because it has **two** money
fields and no dropdown on the critical path. Boris's point was right: a PoC does
not need the canonical case, it needs a real one plus a rationale for what was
left.

### Three things it exposed, each a real defect

**1. The rule fired at the wrong step.** It checked when the amount was TYPED,
which is wrong twice: nothing has moved yet, and ParaBank's *Find Transactions*
page has an `amount` field too — so searching for £1,500 would have been
blocked as if it moved money. Now the amount is remembered and judged at the
**irreversible** step, which is also how a bank behaves.

**2. `money_on_form` was cleared after every action**, so it was empty by the
time the submit was reached and the generic "irreversible" message hid the
value rule entirely. Now it clears only when the URL changes.

**3. Cross-tenant replay and composition had never been exercised together.**
`--tenant feature` retargeted only the entry capability, so `validate_invocations`
refused the baseline `log_in` it invoked — **correctly**, since its control maps
are the wrong tenant's pixels. Retargeting now applies to the whole call tree.

> **Decision:** DONE

---

### A8 · ~~Cross-check the row position~~ — **DONE 2026-09-28**

Geometry proposes, perception verifies. `extract_panel` measures the rhythm
before the vision call, draws one numbered **band** per row at the computed
positions, and the same call reports which band each row sits inside. **Zero
extra model calls.**

Forced the failure and watched it fire:

```
true pitch 28 (measured)   11 rows read   0 misaligned
HARMONIC 56 (2x)           11 rows read   11 misaligned
   "row 1 (12456) reports marker 0: the markers we drew do not line up
    with the rows, so the row pitch or phase is wrong"
```

**Bands, not dots — containment beats proximity.** The first cut drew a dot at
the y we would click, which sits near the *bottom* of a row's text, and the
model consistently read row 0's dot as belonging to row 1 — a false alarm on a
correct run. "Which band is this row inside" has one answer; "which dot is level
with this row" is a judgement about distance. Same shape as
[0011](docs/issues/0011-control-panel-structured-read.md)'s finding: the model
**matches** reliably and **estimates** badly.

**A disagreement stops a click, not a read.** The values came from the model and
are still good; only the click point comes from the disputed geometry. So
extraction proceeds and drilling escalates — a second and qualitatively
different `NeedsOperator`: *"I could, and my two sources disagree, so I will not
guess."*

⚠️ **My test harness was wrong twice**, both times painting over the data or
picking a fixture that did not test the thing. The forced key column must keep
its x (moving it 420px right made the margin 440px and the bands covered the
whole table — 0 rows read, green for the wrong reason), and "a blank strip"
turned out to autocorrelate at 8px, so the deterministic way to refuse a
measurement is a column too SHORT to hold two periods.

> **Decision:** DONE

---

### S1 · ~~Generated docs and the status view~~ — **DONE 2026-09-28**

```
uv run interfaceai status                          capabilities + runs, at a glance
uv run interfaceai status --markdown docs/status.md   a committable page
uv run interfaceai diagram read_savings_balance    its flowchart, from the artifact
```

**§3.2's human half.** *"Both a human reviewer and a calling agent should be
able to understand what the capability does, what it needs, and what it
returns."* The agent half was typed and validated; the human half was a
200-line JSON file. Now it is a table with signature, approval, composition and
fault count — and a mermaid flowchart **generated from the artifact**, so it
cannot make a claim the system does not.

**§3.5's other end.** We were writing `trace.jsonl` and a frame per step and
reading none of it. No new storage: everything comes from `artifacts/` and
`evidence/runs/`.

**[`docs/flows.md`](docs/flows.md)** draws the two ENGINE flows — discovery's
loop and replay's walk — which are a different picture from a capability's own
diagram. Hand-drawn, and flagged as the only diagrams a reader must check
against the code.

### Two reader bugs it exposed, both making a run look like something else

- **An invoked capability writes into the same evidence file**, so its
  `replay_succeeded` made `request_loan` — which always escalates — read as
  SUCCESS. Events are now tagged with which capability they describe.
- **A `NeedsOperator` with no operator attached emitted no terminal event**, so
  the reader called it "incomplete", which looks like a crash. Every run now
  records its own verdict with `replay_finished` rather than leaving it
  inferable.

Both are pinned by tests, and both are the same shape as everything else here:
the reader was quietly wrong in a way that looked fine.

> **Decision:** DONE

---

### A9 · ~~The handoff window is unbracketed~~ — **DONE 2026-09-28**

**The question that produced it, from Boris:** *"'record what the human did'
denotes control the browser??"*

Re-read §3.6, and it says two things that pull apart:

> Let the human operate the same live session … **record what the human did.**

> A full real-time co-browsing operator console is **out of scope** … **mock
> the operator UI if needed**, but make the handoff mechanism and the
> control-transfer model **real**.

So the human must genuinely drive the browser, and must not be given a console
to do it with. The UI is the mockable part; the control transfer is the real
part. We already satisfy both — and **`TerminalOperator` is not a mock**, which
is a wording correction that makes the claim stronger, not weaker.

**The one real hole:** the human can reach past the terminal and click the
visible Chromium window, and we record nothing. The per-action log is complete
for one path and blind to the other.

**Fixed by bracketing, not by a recorder and not by a console.** A frame, a URL
and `url_changed` at each edge of the window. Not *"here is what the human
did"* but *"here is what the page looked like when we handed it over and when
we got it back"* — the action may be invisible, the effect is not.

> **Decision:** DONE

---

## B · Deliberate cuts — revisit if you disagree

### B1 · No persistence
Evidence is files: `trace.jsonl` plus every frame. A SQLite
`runs`/`events`/`interventions` schema would add durability across process
restarts; `jobs`/`attempts` would add queue semantics a single-worker CLI does
not need — §7 says that is unrewarded.

**Cut because:** the handoff happens in-process and the evidence is already
complete. Your bundle's `schema.sql` is ready if you want it back.

> **Decision:**

---

### B2 · Async `Surface` signatures
Your handoff proposed `async def observe/locate/act/read/verify`.

**Declined because:** it collides with sync Playwright, 8 passing tests, and
`OffLoop` — which exists *because* we measured `asyncio.run` failing inside a
`PlaywrightSurface` block. The rewrite buys nothing the brief rewards.

> **Decision:**

---

### B3 · Hand-authored YAML control catalogue
`shared-controls.yaml` + `locator_overrides` from your bundle.

**Declined because:** ours is populated by a real discovery run (54 controls
across 2 screens, with grounded click points); the YAML ships placeholder image
paths and no PNGs. I did adopt its `ControlPolicy` (`irreversible`,
`sensitive`) onto our controls — that part was better than what I had.

> **Decision:**

---

### B4 · `page.pause()` for handoff
**Replaced** by a terminal operator console. It needs a **headed** browser and
this machine has no display; a demo that works on one laptop is not a demo.

**Trade:** we get *better* recording (the human's actions go through the same
action layer, so they are captured exactly), and we lose the human's ability to
do anything the surface cannot express.

> **Decision:**

---

### B5 · The operator console (stage 2), and the headless mirror

**Cut, and the brief cuts it by name:** *"a full real-time co-browsing operator
console is out of scope."* Building one would spend the largest remaining
block of time on the thing §7 calls feature breadth, to upgrade a requirement
already met, and it would close no gap — a web page forwarding clicks records
the same action set as the terminal, through a prettier door.

**The design that WOULD close the gap is the headless mirror**, and it is worth
recording because it is not the same idea. If the human's only window onto the
page is a screenshot they click, then every action necessarily passes through
`use_control`: the unlogged path stops existing rather than being guarded
against. Same move as `check_not_inside_a_panel`.

The cost is the reason it is not obviously right:

```
visible Chromium   maximum expressiveness — native selects, file pickers,
                   hover menus, drag, anything a browser can do
                   ...and an ADVISORY audit log

headless mirror    complete, enforced audit — no second door
                   ...and the human is restricted to verbs we anticipated
```

⚠️ **And the objection that actually matters:** you escalate to a human
*because the system ran out of ideas.* A mirror can only express verbs someone
anticipated, so it narrows the human's vocabulary at precisely the moment ours
proved insufficient. The counter is real too — a regulated bank may well prefer
the restriction, since "the operator could do anything and we have no record"
is a finding, not a feature.

**The resolution, designed and unbuilt:** two modes, with break-glass from
mirrored to direct, and the takeover itself an audited event. Written into
REPORT §5 rather than built.

> **Decision:** CUT — out of scope by §3.6; the mirror is recorded as designed.

---

## C · Named by the brief, no instance — cannot honestly fix

`docs/failure-modes.md` has the full table.

### C1 · ~~Session timeout~~ — **DONE 2026-09-28**

```
$ replay session_loss_probe.v1 --param account_id=13344
SUCCESS session_loss_probe in 8 steps
  found_account_id = 13344
  recovered accounts_overview_link gone -- log_in no longer holds
```

The run threw its session away mid-capability, noticed, re-established it, and
finished. **Deterministic, and no LLM is involved** — which the handoff bundle
required of deterministic replay.

**Driven by a declared postcondition, not a guess.** `Capability.establishes`
says what a capability leaves behind; `log_in` declares the authenticated nav.
When a step fails, any established condition that no longer holds is
re-established by re-invoking the capability that set it. A test strips
`establishes` and shows the same failure becomes unrecoverable — the honest
behaviour, since nothing then says what that capability leaves behind.

**Four refusals, each deliberate:** once per condition (a second failure is not
a flake) · never for an irreversible step (a submission that silently succeeded
and one that failed look identical) · only when the postcondition is genuinely
unmet · only if the child is still permitted.

### ⛔ And it settled the `Recoverable` question properly

There is still **no `Recoverable` result variant**, and building one made the
reason sharper than "we have no instance":

> **A recovered condition is not a terminal state.** If recovery works the run
> ends `Success`; if it does not, it ends `NeedsOperator`. A third result would
> make every successful run ambiguous — *"did this succeed, or recover?"*

`Success.recovered` answers that without pretending the run ended there. And the
CLI prints it, because a run that survived something must not look like one that
had a clear path.

> **Decision:** DONE

---

### C2 · The rest, with no instance and no plan

| condition | why we have none |
|---|---|
| **permission denial** | ParaBank has no roles. ⚠️ Our own `ActionPolicy` refusing is a §3.4 *guardrail*; the app denying an operator is §3.3. A per-tenant ACL gives more of the first and none of the second |
| **unexpected dialog** | ParaBank raises none. Seam named (`page.on("dialog")`), cut rather than mocked |
| **slow / failed load** | plausibly reachable via `jms.htm` queue shutdown. **Unverified** — nothing has ever POSTed to it |
| **`ambiguous`** | ours, not the brief's. Implemented, defensible, **zero instances** — `findings.md`'s cited example does not reproduce under the ambiguity margin |

> **Decision:**

## D · Not attempted

| | note |
|---|---|
| Capabilities 2–5 | 5 (find transactions) genuinely needs the panel read — it *is* a result set |
| Desktop surface | designed only; §3.7 says design, not build |
| Approval workflow, code generation, multi-run stability | §8 stretch goals |

> **Decision:**

---

## My ranking, if you want one

1. ~~**A1**~~ · ~~**A6**~~ · ~~**A4**~~ — **all done.** A1 closed the
   `BusinessOutcome` gap, A6 made the checkpoint rule more correct, A4 took
   reading from 6/11 to 11/11
2. ~~**A3**~~ · ~~**A8**~~ — **done.** The savings capability refuses a checking
   account, and a disputed row position refuses to click at all
3. ~~**C1**~~ · ~~**A7a**~~ · ~~**A7b**~~ — **done.** A lost session recovers; a
   loan over the threshold stops; a forbidden capability never starts
4. ~~**A5**~~ — **measured, and the premise was already gone.** 62 ids, 6
   draws, 0 churn. The remaining half is cut: it is caught fail-closed, so an
   enum would buy enforcement rather than correctness
5. ~~**A9**~~ — **done.** The handoff window is bracketed by evidence
6. ~~**A2**~~ · ~~**B5**~~ — **cut**, with the reasoning filed:
   [#4](https://github.com/borisdev/ai_computer_use/issues/4) and §3.6's own
   scope note
7. Everything else is defensible as-is and argued in REPORT §7

### ⛔ And one thing found on the way out, which is why running the demo matters

Capturing real output for the write-up surfaced a live defect in the safety
layer: **`--confirm-risky` bypassed the money threshold entirely.** A $25,000
loan against a $1,000 threshold replayed `SUCCESS` and submitted, with no
human. A run-level flag was silently answering a tenant-level policy.

`needs_human_confirmation` was correct the whole time, and a unit test of it
passed throughout. The defect was the *branch*. Fixed, and pinned by two live
tests — one for each direction, because a guard that stops everything passes
the first one and is useless.

> **Your ranking:**
