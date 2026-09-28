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

### A3 · Grid cell assignment is still wrong 3 times in 4
[issue 0009](docs/issues/0009-wrong-row-grounding-is-silent.md) — **highest
severity open**, because it is *silent*.

```
12345_link   grounded (500,361)   INSIDE its own link      ok
12456_link   grounded (500,359)   that is 12345's row      WRONG
13122_link   grounded (511,466)   that is 12789's row      WRONG
```

`status: ready`, unique landmark, ~1.0 at replay — and it clicks another
customer's account. Relabelling the grid does not help: three schemes measured,
best 3/15.

⚠️ **Capability 1 no longer touches this** — the panel path grounds no rows. But
any capability that must *click* one of N identical rows still would, and
capability 2 (transfer funds) is exactly that shape.

**Fix:** the same move as capability 1 — extract the panel, select in code,
then use the row rhythm to turn an index into a click point. `PanelRead.point_for_row`
already exists and is tested; **nothing in the executor calls it.**

### Why it is worth doing — the rationale, corrected

My first framing was *"makes the product better, not the submission more
complete"*. That is wrong, and Boris's version is better. Re-read §7:

> **Robustness & error handling.** … sound **locator**, wait, and **checkpoint**
> strategy.

Both halves of A3 are in that one sentence. Wrong-row grounding **is** an
unsound locator strategy, silently. And v2's checkpoint is demonstrably weaker
than the v1 one it replaced.

> **Correctness of the core loop.** … the artifact replays deterministically
> **and verifies success**.

Today it verifies *"I answered about the account you named"*. It cannot verify
*"that account is what the recording said it was"* — the exact case `env break`
produces.

**Robustness is weighed THIRD. Feature breadth is weighed not at all.** §5 says
*"go deep where it matters — the artifact schema, deterministic replay plus
error handling"*. A3 is depth on a weighed criterion, achieved by REMOVING a
defect rather than adding a feature.

And it has a track record: building the next real thing has exposed a design
flaw twice today. Composition showed the checkpoint rule was too broad;
capability 1 showed a panel could not be named in an artifact. Neither was
visible from reading the code.

⚠️ **One claim to NOT make.** This is not "generality" in the brief's sense —
§7's *generalization* means heterogeneous **surfaces** and **tenant** reuse, both
already done and demonstrated. A drilldown does not touch that criterion.

**What it concretely restores:**

```
env break, then replay read_savings_balance --param account_id=13344
v1  ->  FAILED, account_type: expected SAVINGS, observed CHECKING   caught it
v2  ->  SUCCESS, balance = $5022.93                                 wrong record, reported fine
```

**The work:** `PanelSpec.key_click_dx` (measured: 18px from the anchor), a step
shape for "click the row where key = param", ~20 executor lines reusing the
CACHED panel read, capability 1 v3 with the drilldown, and a live test that is
self-proving in both DB states. **~2h.**

> **Decision:** DO IT — rationale above (Boris, 2026-09-28)

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
2. **A3** — **agreed, on the plan.** Depth on §7's third-weighed criterion
   (sound locator and checkpoint strategy), achieved by removing a defect
3. **C1 · session timeout** — **agreed, on the plan.** Earns the `recoverable`
   type instead of guessing it, and composition already supplies the mechanism
4. **A5** — reframed: constrain the SCHEMA, not the prompt. Measure the
   naming churn first (20 min) before building the rest
5. Everything else is defensible as-is and argued in REPORT §7

> **Your ranking:**
