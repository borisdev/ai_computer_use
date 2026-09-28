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
already exists and is tested; nothing calls it yet.

> **Decision:**

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

### A5 · The controlled vocabulary is not in the prompt
34 terms exist and type every artifact. `VOCABULARY.as_prompt_block()` is
written and **nothing calls it**, so the 15/24/22 inventory variance it was built
to fix has never been re-measured.

⚠️ Worth re-measuring *after* A4 regardless: the two-pass split may have moved
that number on its own, since the read pass is no longer fighting the overlay.

**Cost:** ~1h to wire, plus a measurement run.

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

| condition | status |
|---|---|
| **recoverable** | never observed one. **No type exists**, and a test asserts its absence so adding one is deliberate |
| **permission denial** | ParaBank has no roles. ⚠️ Our policy refusing is a §3.4 *guardrail*; the app denying an operator is §3.3. A per-tenant ACL gives more of the first and none of the second |
| **unexpected dialog** | ParaBank raises none. Seam named (`page.on("dialog")`), cut rather than mocked |
| **session timeout** | **reachable** — log out mid-flow. Untried. ~1h, and it would give `recoverable` its first real instance |
| **slow / failed load** | plausibly reachable via `jms.htm` queue shutdown. **Unverified** — nothing has ever POSTed to it |
| **`ambiguous`** | ours, not the brief's. Implemented, defensible, **zero instances** — `findings.md`'s cited example does not reproduce under the ambiguity margin |

> **Decision:**

---

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
2. **A3** — highest severity still open, and capability 2 would hit it
   immediately. The fix is the move capability 1 already proves works
3. **C · session timeout** — one hour, and it earns the `recoverable` type
   instead of guessing it
4. **A5** — worth re-measuring after A4 before deciding it is still needed
5. Everything else is defensible as-is and argued in REPORT §7

> **Your ranking:**
