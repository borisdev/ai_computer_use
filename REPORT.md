# Design write-up

> **The end-to-end thread runs.** A goal drives a real LLM against the live app,
> the run is recorded as a typed artifact, a human approves it, and it replays
> deterministically to a typed outcome — including the failure and handoff
> branches, and on a second tenant it was never recorded against. Capabilities
> compose, a lost session is re-established, and a payment over a threshold
> stops and asks a person. Every number below came from a run.
>
> ```
> 247 tests — 216 offline, 31 live · ruff clean
> ```

Detail lives elsewhere so this stays short:
[evidence/](evidence/README.md) (six committed runs, one per outcome) ·
[findings.md](docs/findings.md) (every measurement) ·
[adr/](docs/adr/README.md) · [issues/](docs/issues/README.md) ·
[parabank.md](docs/parabank.md) (the target) ·
[STILL-OPEN.md](STILL-OPEN.md) (what was cut, and why).

---

## 1. Architecture

One Python package, one process, a CLI. No services, no queue, no supervisor —
§7 says scaling infrastructure is not rewarded.

```
goal ──► discover ──► capability (draft) ──► human approves ──► replay ──► outcome
           LLM                artifact           gate            NO LLM      typed
```

**The load-bearing seam is perception/action versus the recorded flow.** Below
it, `Surface` captures a frame and dispatches a click; above it, an artifact
knows the ordered steps of a banking task and what "done" looks like. A desktop
backend implements `Surface` and nothing above changes
([ADR 0002](docs/adr/0002-playwright-screenshot-control.md)).

Three decisions a reviewer would otherwise reverse-engineer:

- **Screenshots and coordinates, never the DOM.** `page.locator()` in the agent
  or replay path is a defect, not a shortcut: a DOM recording cannot replay
  against a desktop app, which is the point of the seam. Tests may use the DOM
  as an oracle; the system may not.
- **Discovery and replay share one chain** — `locate_control → validate_decision
  → use_control` — so the path discovery proved is the path production takes.
- **Control maps are separate from artifacts.** An artifact names `(screen,
  control_id)`; the pixels live in a per-tenant store. That is what makes §4
  work, and why a capability is not welded to the institution it was recorded
  at.

**The system describes itself**, because §3.2 asks that *both a human reviewer
and a calling agent* understand a capability. `interfaceai status` lists each
with signature, approval, composition and fault count;
`interfaceai diagram <name>` draws one **from its artifact**, so a diagram
cannot claim a step the system will not take
([status.md](docs/status.md), [flows.md](docs/flows.md)).

## 2. Artifact schema

`src/interfaceai/capability.py`; reasoning in
[ADR 0005](docs/adr/0005-capability-artifact-shape.md). Each constraint is in
the type system rather than a style guide, because each was measured failing
first:

1. **No coordinates, and no locators either.** A step names `(screen,
   control_id)`. Raw `(x, y)` scored **1/10** clicks inside the target; only a
   context patch plus a click offset replayed at drift `(0,0)`. A template is
   the *least* portable locator there is, so keeping it out is what lets one
   artifact serve two tenants.
2. **A checkpoint may only compare an extracted VALUE.** So *"did I reach
   account 13344"* is not expressible. ParaBank's CLEAN state is why: 13344
   still resolves, as `CHECKING $5,022.93` instead of `SAVINGS $1,231.10`. A
   presence checkpoint passes there and hands a bank **a different record's
   balance**.
3. **A sensitive slot cannot hold a literal** — only an `input_ref` resolved at
   replay, enforced in the validator and again by a test reading the committed
   JSON off disk, because a hand-edited file is the case that matters.
4. **`draft → approved` is one function**, so there is exactly one place to
   route around.

**Typed both ways:** `params` in, `returns` out, both checked against a 34-term
controlled vocabulary carrying a `sensitive` flag. `requires` holds
preconditions, re-checked on resume.

**Capabilities compose.** `StepVerb.INVOKE` calls another **in the same browser
session** — a section of the same run, in the same evidence file. That is what
makes this a vocabulary rather than a macro: `log_in` is written once instead of
copied into twenty artifacts and re-fixed the day the login page moves. **The
version is pinned**, so a library holding a newer `log_in` is a validation
error, not a silent substitution. Five refusals are tested: missing, version
drift, an **unapproved child**, self-invocation, and a cycle.

**A capability that RETURNS something must check it.** Not "everything needs a
checkpoint", which is what this said first — `log_in` returns nothing and its
`wait_for` already asserts arrival. The danger ADR 0005 names is handing back a
*value* never proved to come from the right record. Composition exposed the
difference.

**`establishes` is a postcondition** — for `log_in`, the authenticated nav. When
a step fails because that ref is gone, the engine knows which capability puts it
back. ⚠️ A postcondition added *after* approval does nothing: the approved
`log_in` predated the field and recovery silently never fired until re-approval.
Version pinning is what made that visible rather than mysterious.

⚠️ **Hand-authored artifacts name controls that do not exist.** Measured against
real control maps: the hand-written ones carry **3 and 8** faults, the discovered
one **0**. A hand-written artifact can name anything; a discovered one can only
name what it recorded. `interfaceai capability check` is the check.

## 3. Determinism & error handling

Replay takes an approved artifact and typed inputs. **Nothing chooses an
action** — step order, control, value and checkpoint all come from the artifact.

```python
CapabilityResult = Success | BusinessOutcome | Failed | NeedsOperator
```

⚠️ **One model call survives, and only for reading.** An `extract` step must turn
pixels into a value and a DOM-less surface offers no other way. For a table it
is **one call for the whole panel**; the caller's parameter then picks the row
*in code*. That matters: asking a model where a row is lands on the wrong record
**3 times in 4**, silently
([issue 0009](docs/issues/0009-wrong-row-grounding-is-silent.md)). Reading is
the half models are good at — **11/11** on a clean crop against **6/11** when our
own grid overlay defaced the image. The reader gets a crop and a schema; never
the goal, never a choice. **A capability with no `extract` step replays with zero
model calls.**

| | instances | example |
|---|---|---|
| `Success` | many | `balance = $1231.10` for account 13344, read off the live screen |
| `BusinessOutcome` | 2 | account 99999 through the whole replay path; `Could not find account #54321` is HTTP **200** with plain text, so status codes cannot detect it |
| `Failed` | 6 | checkpoint read `5022.93` where the artifact said `1231.10` |
| `NeedsOperator` | several | a locator at 0.8654, below threshold — and a $25,000 loan over the tenant's threshold, a different trigger entirely |
| ~~`Recoverable`~~ | **0** | **no type exists**, and a test asserts its absence |

**Why there is still no `Recoverable`, now that we recover.**
`session_loss_probe` logs itself out mid-flow and comes back `SUCCESS`, with
`recovered accounts_overview_link gone -- log_in no longer holds`. **A recovered
condition is not a terminal state.** A fifth variant would make a caller branch
on something that is not an answer; `Success.recovered` names what a run
survived, and recovery is bounded to **once per condition** so a genuinely dead
session fails rather than loops.

The runnable transcripts are in the [README](README.md#demo-path); three things
they prove. The happy path takes **12 steps, three of them `log_in` invoked**.
The not-found path exits **0** — a fair question with a negative answer is not a
crash. And the injected-failure path **refuses to click something scoring
0.8654** and carries what it finished, so a human resumes rather than restarts.

**Determinism rests on** re-resolution against the current screenshot rather
than a stored coordinate (drift `(0,0)`); refusals rather than guesses
(`not_found`, `ambiguous`, `incompatible` all stop the run); a factory-reset
target; and value normalisation, since a screen prints `$1,231.10` where the
artifact recorded `1231.10`.

**Repeated structure needs a panel, not grounding.** Grid cell assignment was
never fixed — it was made *unreachable*. A table is a `TABLE_CONTROL_PANEL`: read
the region in one call, index the row in code, reach it by a **measured pitch**
(28px, autocorrelation 0.899), then verify by re-reading the row it landed on.
`check_capability` **refuses a direct click on any control inside a panel
region**, turning "we stopped doing that" into "that cannot be done". 11/11.
⚠️ It generalises — the site nav was **0/8** grounded, the same defect in
different clothes.

⚠️ **Two traps, both hit.** Readiness is not liveness: ParaBank serves 200 with
no schema behind it and the healthcheck stays green. And not-found is 200 plus
plain text.

## 4. Heterogeneity & multi-tenant

**`Surface` is a protocol** — screenshot, click, type, scroll, navigate. A
desktop backend implements it and the schema, engine and guardrails are
untouched, because none of them names a browser. `use_control` is
surface-independent: *what is permitted* is a property of the bank, *how to
click* a property of the surface.

**Demonstrated.** An artifact recorded on tenant A replays on tenant B:

```
TENANT A   SUCCESS log_in_discovered in 5 steps, account_id = 12345
TENANT B   SUCCESS log_in_discovered in 5 steps, account_id = 12345   (localhost:8081)
```

Structural, not a special case: the artifact names controls, the **control maps**
hold pixels keyed `(app, tenant, screen)`. **Drift detection is the adoption
step** — `maps adopt` re-runs every locator against the target tenant's live
screen and **writes nothing if any drifted**, because a partially adopted map
fails at replay far from the cause and reads like an application fault. A tenant
miss never falls back to another tenant's pixels.

⚠️ **The honest limit.** Both images ship the stock unbranded UI, which is why
every locator matches at `1.0000`. This proves the reuse *path*; it does not
prove the design survives a restyle. Template matching is the least portable
locator there is, and that is the trade this design accepts in exchange for
working without a DOM.

## 5. Escalation & handoff

**Detect.** Eight triggers, and **seven need no model judgement**: a guardrail
refusal, an `unresolved` control, a locate returning `not_found` or `ambiguous`,
an unconfirmed irreversible step, a money amount at or above the tenant's
threshold, an unknown secret ref, a malformed move. Only "the model says it is
stuck" needs a model.

**Route with context.** `InterventionRequest` carries why, which capability and
step, screen, URL, a frame, and **what was already completed**.

**Take the live session.** The same `PlaywrightSurface` mid-run — same page, same
cookies, automation genuinely stopped. `owner` flips `worker → human → worker`,
both transitions logged.

**Verify before resuming**, never "continue from line N":

```
the step's target is now satisfied  ->  advance past it
the step is still safe to perform   ->  retry it
anything uncertain                  ->  stay paused
```

An irreversible step is **never** retried on "it looks like it did not happen": a
submission that silently succeeded and one that failed look identical, and
repeating one moves money twice.

**The UI is minimal, not mocked**, and the loose word understates it.
`ScriptedOperator` is the mock (canned, tests only). `TerminalOperator` reads a
real person and drives the **real live page** through `use_control`, under the
same allowlist and redaction as the agent, recording `value_length` and never
the value. The axis is *fidelity of the interface*, not realness of the
implementation. ⚠️ Not `page.pause()`: it needs a headed browser and this
machine has no display.

⚠️ **It is a protocol plus a recorded state, not an interlock** — nothing
physically stops a person clicking during automation. So **the handoff window is
bracketed**: a frame, URL and `url_changed` at each edge. Not *"what the human
did"* but *"what the page looked like when we handed it over and got it back"* —
the action may be invisible, the effect is not.

⚠️ **A co-browsing console would not fix that, and §3.6 puts it out of scope.**
The design that would is a **headless mirror**: if the human's only window is a
screenshot they click, every action passes through `use_control` and the unlogged
path stops existing. Recorded rather than built, because it buys enforcement at
the cost of expressiveness at exactly the wrong moment — you escalate *because*
the system ran out of ideas, and a mirror only offers verbs someone anticipated.
The resolution is two modes with an audited break-glass.

## 6. Safety

**One chokepoint.** `use_control` is the only function that touches the
application, so it is the only place the checks can live and the only place
worth testing them. The human operator goes through the same gate.

**Risk is a property of the control, not the action.** Clicking "Log In" is
safe, clicking "Transfer" moves money, and both are `CLICK`. So `irreversible`
lives on the control and every capability touching it inherits that.

**Some risk depends on the VALUE.** A tenant policy carries
`confirm_money_above`; the engine tracks amounts typed onto the **current form**
and judges the irreversible step on what is about to be submitted. ⚠️ It has to
fire at the right step — checking at *typing* would also block a transaction
*search*, since `findtrans.htm` has an `amount` field too. Reading a number is
not spending it.

⚠️ **And the threshold was bypassable — the worst thing found here.** The gate
read `if irreversible and not confirm_risky:`, so a run started with
`--confirm-risky` skipped the value check **entirely**: a $25,000 loan against a
$1,000 threshold replayed `SUCCESS` and submitted, with no human. The threshold
was not misread — **it was never consulted.** These are different authorities:
the flag is the *caller* saying "this run may do irreversible things"; the
threshold is the *bank* saying "a person signs off above this amount", a question
never addressed to the caller. Tenant policy is now checked first and is not
bypassable. **Note the level:** `needs_human_confirmation` was correct throughout
and its unit test passed the whole time — the defect was the *branch*, and it was
found by running the demo, not by reading the code.

**Secrets never land.** A sensitive slot takes only an `input_ref`; the audit
record carries `value_length`. A run log containing a password is a finding, not
a log.

**Limits.** A current-URL check cannot prevent outbound navigation. ParaBank has
no roles, so our tenant permission gate demonstrates the enforcement point and
**not** integration with a real entitlement system — make-believe, and labelled
so. Redaction covers logs and artifacts, **not screenshots**.

## 7. Cuts

What was left out on purpose. Full reasoning per item in
[STILL-OPEN.md](STILL-OPEN.md).

- **Extraction cannot point at *unstructured* data**
  ([#4](https://github.com/borisdev/ai_computer_use/issues/4)). Values in tables
  and label/value pairs are reachable — both are panels. A lone value with no
  repeating structure is not. **Cut because nothing needs it:** every capability
  works without it, so building it now is an abstraction with no caller.
- **Constraining `control_id` to an enum — measured, and the premise was gone.**
  One screenshot, three draws: **62 ids over two screens, 0 churn.** An id is
  derived from label + role + position, not invented. We were one step from
  building a second fix for something already fixed. What survives is narrower —
  a later `NextMove` once named `13767_link`, which does not exist — and is
  already caught fail-closed, so an enum would buy enforcement, not correctness.
- **The operator console.** §3.6 puts a full co-browsing console out of scope;
  the headless mirror is designed and unbuilt (§5).
- **No persistence.** Evidence is files: `trace.jsonl` plus every frame. A
  SQLite `runs`/`events` schema adds durability across restarts; `jobs`/
  `attempts` adds queue semantics a single-worker CLI does not need.
- **Async `Surface`**, declined: it collides with sync Playwright and `OffLoop`,
  which exists *because* we measured `asyncio.run` failing inside it. And **a
  hand-authored YAML control catalogue**, declined in favour of the store
  discovery populates — placeholder image paths describe controls nobody has
  grounded.
- **Conditions with no instance.** Unexpected dialog and a *real* permission
  denial have never occurred here; no types were invented for them.
- **Not attempted:** capabilities 2–5, desktop surface, code generation,
  multi-run stability scoring.

### If I had another day

1. **A `TABLE_CONTROL_PANEL` producer in discovery.** Panels are hand-added by a
   committed script today; discovery has no notion of a region with structure.
   This is the largest gap between what discovery produces and what replay can
   use.
2. **A restyled tenant.** Both images ship the stock UI, so the reuse path is
   proven while the reuse *claim* is not. A CSS-only skin is the cheapest honest
   test of the decision with the most to lose.
3. **The headless mirror as a second operator mode**, so the trade in §5 is a
   decision rather than an excuse.
