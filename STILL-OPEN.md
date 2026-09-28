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
- `scripts/add_accounts_panel.py` — stands in for the discovery step that does
  not exist yet, committed so the geometry is reviewable

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

> **Decision:**

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

⚠️ **Measure the naming churn first, separately.** The original A5 was about
unlabelled icons getting prose names that differ between runs. That was measured
with the read pass fighting the grid overlay, which A4 removed. Re-measuring is
20 minutes — run discovery 3x on one screen, diff the id sets — and it may show
the problem shrank or went.

### One vocabulary across apps and tenants

Cross-**tenant**: not even a question. Same vendor product, same concepts, and
the artifact is already tenant-agnostic — only the control map is tenant-specific.

Cross-**app**: the weaker claim. These 34 terms are retail banking; a back-office
tool needs holds, memo posting, maker-checker. But *keep one until something
concretely conflicts* is the right default, and it is the same argument as the
vocabulary itself — **fixed beats perfect**, and drifting early gives you a
synonym list.

> **Decision:**

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

### A7b · The live demo: capability 2, transfer funds — **LATER**

The policy rule above is tested but has never stopped a real transfer, because
there is no transfer capability. Building one needs a multi-field form, two
dropdowns (our `SELECT` is `click + type`, which is crude for a `<select>`), a
confirmation screen, and ParaBank's own minimum-balance validation error.

**~3h with real unknowns**, and it is the most impressive thing left in the
backlog: a $1,500 transfer stopping mid-flow and handing the session to a
person is the assignment's story in one command.

> **Decision:** later (Boris, 2026-09-28)

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

## C · Named by the brief, no instance — cannot honestly fix

`docs/failure-modes.md` has the full table.

### C1 · Session timeout → earns the `recoverable` type — **ON THE PLAN**

**The gap:** `Recoverable` is one of the brief's three result classes and we
have **zero** instances. Every run ends one of four ways — succeeds, business
outcome, fails, escalates. **Nothing ever recovers and continues.**

**What it looks like here:** the session dies mid-capability. `overview.htm`
starts serving the logged-out page — HTTP 200, right heading, empty table — and
the next step's control is not there. Today that is a `NeedsOperator`: a human
summoned to fix something the system could fix itself.

**Composition already handed us the mechanism.** Capability 1 declares:

```
requires:  at_the_login_page      a precondition
step 0:    invoke log_in v2       a capability that ESTABLISHES a session
```

So the rule falls out:

> If a step fails **and** a precondition that was satisfied is now unsatisfied,
> **and** the capability invoked something that establishes it — re-invoke that
> **once**, re-check, retry the step. Fail again and escalate.

Deterministic, bounded to one attempt, and **no LLM involved** — which the
handoff bundle was explicit about (*"No hidden LLM recovery in deterministic
replay"*).

**Forcing it for a test:** navigate to `logout.htm` mid-run, or clear the
session cookie. ParaBank hands us the lever.

**~1.5h**, and it earns the type honestly instead of declaring one and hoping.

> **Decision:** DO IT (Boris, 2026-09-28)

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
3. **C1 · session timeout** — **agreed, on the plan.** Earns the `recoverable`
   type instead of guessing it, and composition already supplies the mechanism
4. **A5** — reframed: constrain the SCHEMA, not the prompt. Measure the
   naming churn first (20 min) before building the rest
5. Everything else is defensible as-is and argued in REPORT §7

> **Your ranking:**
