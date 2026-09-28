# Design write-up

> **Status: the end-to-end thread runs.** A goal drives a real LLM against the
> live app, the run is recorded as a typed artifact, a human approves it, and it
> replays deterministically to a typed outcome — including the failure and
> human-handoff branches, and on a second tenant it was never recorded against.
> Capabilities **compose**, a lost session is **re-established**, a payment over
> a threshold **stops and asks a person**, and every one of those has a run
> behind it. Every number here came from a run; where something is inferred it
> says so.
>
> ```
> 246 tests — 215 offline, 31 live · ruff clean
> ```

Supporting documents:

- **[docs/parabank.md](docs/parabank.md)** — everything learned about the target
  application: how it fails, the two database states, the `;jsessionid=` problem,
  the seed fixtures, and the collected gotchas. The evidence behind most of the
  decisions below.
- **[docs/adr/](docs/adr/README.md)** — architecture decision records.
- **[docs/findings.md](docs/findings.md)** — every measurement behind the claims
  below, mapped section by section to this brief.
- **[docs/issues/](docs/issues/README.md)** — what is still open, with evidence.

---

## 1. Architecture

One Python package, one process, a CLI. No services, no queue, no supervisor —
§7 is explicit that scaling infrastructure is not rewarded.

```
  goal ──► discover ──► capability (draft) ──► human approves ──► replay ──► outcome
             LLM                  artifact          gate            NO LLM      typed
```

**The load-bearing seam is perception/action versus the recorded flow.** Below
it, `Surface` captures a frame and dispatches a click; above it, an artifact
knows the ordered steps of a banking task and what "done" looks like. A desktop
backend implements `Surface` and nothing above changes
([ADR 0002](docs/adr/0002-playwright-screenshot-control.md)).

Three decisions a reviewer would otherwise have to reverse-engineer:

**Screenshots and coordinates, never the DOM.** `page.locator()` in the agent or
replay path is a defect, not a shortcut: a DOM recording cannot replay against a
desktop app, which is the whole point of the seam. Tests may use the DOM as an
oracle; the system may not.

**Discovery and replay share one chain.** Both go `locate_control →
validate_decision → use_control`. Replay is not a parallel implementation, so
the path discovery proved is the path production takes.

**Control maps are separate from artifacts.** An artifact names
`(screen, control_id)`; the pixels live in a per-tenant store. That is what makes
§4 work, and it is why a capability is not welded to the institution it was
recorded at.

⚠️ **Sync Playwright and `asyncio.run` cannot share a thread** — measured, twice.
`OffLoop` runs model calls on a worker while Playwright keeps the main thread.
An earlier note in this repo concluded discovery and capture must be separate
*phases*; they only need separate *threads*.

**The system describes itself, and §3.2 is why.** The brief asks that *both a
human reviewer and a calling agent* understand what a capability does, needs and
returns. The agent half was typed and validated from the start; the human half
was a 200-line JSON file. `interfaceai status` now lists every capability with
its signature, approval state, composition and fault count, and `interfaceai
diagram <name>` draws one **from its artifact** — so a diagram cannot claim a
step the system will not take. [docs/status.md](docs/status.md) is that view
committed. [docs/flows.md](docs/flows.md) draws the two *engine* flows, a
different picture from a capability's own: those two are hand-drawn, and are
flagged as the only diagrams a reader must check against the code.

## 2. Artifact schema

`src/interfaceai/capability.py`. Reasoning in
[ADR 0005](docs/adr/0005-capability-artifact-shape.md). Four constraints are in
the type system rather than a style guide, because each was measured failing
first:

**1 · No coordinates, and no locators either.** A step names
`(screen, control_id)`. Raw `(x, y)` scored **1/10** clicks inside the target;
a fractional bbox the same; only a context patch plus a click offset replayed at
drift `(0,0)`. But a template is also the *least* portable locator there is, so
keeping it out of the artifact is what lets one artifact serve two tenants.

**2 · A checkpoint may only compare an extracted VALUE.** `Checkpoint.output`
must name a declared output, so *"did I reach account 13344"* is not
expressible. ParaBank's CLEAN state is why: 13344 still resolves, as
`CHECKING $5,022.93` instead of `SAVINGS $1,231.10`. A presence checkpoint
passes there and hands a bank a different record's balance.

**3 · A sensitive slot cannot hold a literal.** `username`, `password`, `ssn`
take an `input_ref` resolved at replay. Enforced in the validator and again by a
test that reads the committed JSON off disk, because a hand-edited file is the
case that matters.

**4 · `draft → approved` is one function.** `assert_replayable` is the only gate,
so there is exactly one place to route around, and a test proves a draft cannot
pass it.

**Typed both ways.** `params` are the caller's inputs, `returns` the typed
outputs, both checked against a 34-term controlled vocabulary carrying a
`sensitive` flag. `requires` holds preconditions — re-checked on resume, because
after a handoff the operator may be anywhere.

### 5 · Capabilities compose

`StepVerb.INVOKE` calls another capability **in the same browser session** — not
a subprocess, a section of the same run, in the same evidence file. That is what
makes this a vocabulary rather than a macro: `log_in` is written once and
everything needing a session calls it, instead of three steps copied into twenty
artifacts and re-fixed the day the login page moves.

**The version is pinned.** A library holding a newer `log_in` is a validation
error, not a silent substitution — a capability that quietly picked up a new
dependency would not be deterministic, which is the whole point of replay.

Five refusals, each tested: a missing capability, a version drift, an
**unapproved child** (an approved capability must not smuggle one in),
self-invocation, and a cycle.

Nested results map deliberately. `Success` merges its outputs and continues.
`BusinessOutcome` **propagates unchanged** — "no such member" is the caller's
answer however deep it was found. `Failed` and `NeedsOperator` propagate too,
the latter because a human resolves in the same live session.

### 6 · A capability that RETURNS something must check it

Not "every capability needs a checkpoint", which is what this said first.
`log_in` returns nothing; its success condition is reaching the authenticated
nav, which its final `wait_for` already asserts — and a `wait_for` that never
matches stops the run rather than passing silently. The danger ADR 0005 names is
a run handing back a *value* it never proved came from the right record, and a
capability returning nothing cannot do that. The narrower rule is the correct
one; composition is what exposed the difference.

### 7 · A capability can declare what it ESTABLISHES

`Capability.establishes` names a `ControlRef` that is true *after* the
capability succeeds — for `log_in`, the authenticated nav. It is a
**postcondition**, and it is what makes recovery possible without a model: when
a step fails because that ref is gone, the engine knows which capability
re-establishes it and re-invokes exactly that one.

⚠️ **A postcondition added after approval does nothing.** The approved `log_in`
predated the field, so recovery silently did not fire until it was re-approved.
Version pinning is what makes that visible rather than mysterious — and it is
the argument for pinning in one sentence.

⚠️ **Hand-authored artifacts name controls that do not exist.** Measured against
real control maps: the two written by hand carry 3 and 8 faults; the one
produced by discovery carries **0**. A hand-written artifact can name anything;
a discovered one can only name what it recorded. That contrast is the argument
for discovery, and `interfaceai capability check` is the check.

## 3. Determinism & error handling

Replay takes an approved artifact and typed inputs and returns one of four
things. **Nothing chooses an action** — step order, control, value and
checkpoint all come from the artifact.

```python
CapabilityResult = Success | BusinessOutcome | Failed | NeedsOperator
```

⚠️ **One model call survives, and only for reading.** An `extract` step must
turn pixels into a value and a DOM-less surface offers no other way. For a
table it is **one call for the whole panel** — the caller's parameter then picks
the row *in code*, so nothing is ever asked where a row is. That matters: asking
lands on the wrong record **3 times in 4**, silently
([issue 0009](docs/issues/0009-wrong-row-grounding-is-silent.md)). That is
perception, not decision, and it is the half models are measured *good* at —
**11/11** on a clean crop against **6/11** when our own grid overlay defaced the
image. The reader gets a crop and a schema; never the goal, never the step list,
never a choice. **A capability with no `extract` step replays with zero model
calls.**

### Every variant has an observed instance

The brief names three classes. We implement the ones we have actually produced
and say so about the rest — `docs/failure-modes.md` is the catalogue, and every
row in it has a test.

| | instances | example |
|---|---|---|
| `Success` | many | `balance = $1231.10` for account 13344, read off the live screen |
| `BusinessOutcome` | 2 | **account 99999 through the whole replay path** — and `Could not find account #54321`, HTTP **200** with plain text, so status codes cannot detect it |
| `Failed` | 6 | checkpoint read `5022.93` where the artifact said `1231.10`; also `request_loan not permitted for this tenant` |
| `NeedsOperator` | several live | a locator at 0.8654, below threshold — and a **$25,000 loan over the tenant's threshold**, which is a different trigger entirely |
| ~~`Recoverable`~~ | **0** | **no type exists.** A test asserts its absence, so adding it is a conscious act |

### Why there is still no `Recoverable`, now that we recover

`session_loss_probe` logs itself out mid-flow, and the run comes back
**`SUCCESS`**, with `recovered accounts_overview_link gone -- log_in no longer
holds`.
That is the point: **a recovered condition is not a terminal state.** Adding a
fifth variant would make a caller branch on something that is not an answer —
the run succeeded, and what it survived belongs *on* the success, not instead of
it. `Success.recovered` names it, and recovery is bounded to **once per
condition** so a genuinely dead session fails rather than looping.

### Demonstrated, not argued

The assignment's own worked example, with a typed parameter:

```
$ interfaceai replay artifacts/read_savings_balance.v3.approved.json --param account_id=13344
SUCCESS read_savings_balance in 12 steps
  found_account_id = 13344
  balance = $1231.10
  account_type = SAVINGS                                          exit 0
```

Twelve steps, and three of them are `log_in` — this capability **invokes** it
rather than repeating it. The `account_type` output is what makes the checkpoint
strong: proving the row says `SAVINGS` is the difference between reading the
right record and reading a record.

A fair question with a negative answer — **exit 0**, because the caller can act
on it:

```
$ interfaceai replay artifacts/read_savings_balance.v3.approved.json --param account_id=99999
record_not_found no row where account_id is '99999'; the table holds 11    exit 0
```

And the failure branch, produced by the application rather than a stub:

```
$ interfaceai env break        # action=CLEAN — account 12345 stops existing
$ interfaceai replay artifacts/log_in_discovered.v1.approved.json
NEEDS A HUMAN at step 4: cannot read 12345_link: not_found
                        (best score 0.8654 is below threshold 0.95)
  completed: enter username_textbox, enter password_textbox,
             click log_in_button, observe                          exit 1
```

That last one is the one worth reading. It **refuses to click something scoring
0.86** and carries what it finished so a human can resume rather than restart.

### What determinism rests on

- **Re-resolution, never a stored coordinate.** Every step re-locates against
  the current screenshot. Replay drift measured `(0,0)` at score `1.0000`.
- **Refusals, not guesses.** `not_found`, `ambiguous` and `incompatible` all
  stop the run. `ambiguous` in particular means two candidates within the
  margin, which on an account list is two different records.
- **A factory-reset target.** The HSQLDB lives in the container with no volume,
  so `docker compose down` resets it and every run starts identical
  ([ADR 0003](docs/adr/0003-plain-docker-compose.md)).
- **Value normalisation.** A screen prints `$1,231.10` where an artifact
  recorded `1231.10`; comparing raw strings would report a violated checkpoint
  for a correct read — the loudest possible false alarm.

### Two traps this target sets, both hit

- **Readiness is not liveness.** ParaBank serves HTTP 200 with no database
  schema behind it and the healthcheck stays green throughout.
- **Not-found is HTTP 200 plus plain text.** Status codes do not detect it.

## 4. Heterogeneity & multi-tenant

**Surface abstraction.** `Surface` is a protocol — screenshot, click, type,
scroll, navigate. A desktop backend implements it and the artifact schema,
the replay engine and the guardrails are untouched, because none of them names
a browser. `use_control` is surface-independent: *what is permitted* is a
property of the bank, *how to click* a property of the surface.

**Multi-tenant, demonstrated.** An artifact recorded on tenant A replays on
tenant B, which it was never recorded against:

```
TENANT A   SUCCESS log_in_discovered in 5 steps, account_id = 12345
TENANT B   cross-tenant replaying on feature (localhost:8081)
           SUCCESS log_in_discovered in 5 steps, account_id = 12345
```

This is structural, not a special case. The artifact names controls; the
**control maps** hold pixels and are keyed `(app, tenant, screen)`. Nothing in
the artifact is tenant-specific except which map it resolves against.

**Drift detection is the adoption step.** `interfaceai maps adopt <screen>
--from A --to B` re-runs every locator against the target tenant's live screen
and **writes nothing if any drifted** — a partially adopted map fails at replay
far from the cause and reads like an application fault.

```
baseline -> feature   index:    19/19 matched, adopted
baseline -> feature   overview: 22/22 matched, adopted
```

A restyled tenant shows up here as drift, and the answer is per-tenant
overrides or its own discovery run. **A tenant miss never falls back** to
another tenant's pixels — that would click confidently in the wrong place.

⚠️ **The honest limit.** `parabank:baseline` and `parabank:feature` are
different image digests but both ship the stock unbranded UI, which is why every
locator matches at `1.0000`. This proves the reuse *path*; it does not prove the
design survives a restyle. Template matching is the least portable locator
there is, and that is a real trade this design accepts in exchange for working
without a DOM.

## 5. Escalation & handoff

`src/interfaceai/handoff.py`. Four things, all real.

**Detect.** Eight triggers, and **seven need no model judgement**: a guardrail
refusal, a decision refused because the control is `unresolved`, a locate that
came back `not_found` or `ambiguous`, an unconfirmed irreversible step, **a
money amount at or above the tenant's threshold**, an unknown secret ref, a
malformed move. Only "the model says it is stuck" depends on a model.

**Route with context.** `InterventionRequest` carries why, which capability,
which step, the screen and URL, a frame, and **what was already completed** —
so a human resumes rather than restarts.

**Take the live session.** The same `PlaywrightSurface` mid-run: same page,
same cookies, automation genuinely stopped. `owner` flips `worker → human →
worker` and both transitions are in the run log.

**Verify before resuming.** Never "continue from line N" — the operator may
have navigated anywhere:

```
the step's target is now satisfied     ->  advance past it
the step is still safe to perform      ->  retry it
anything uncertain                     ->  stay paused
```

An irreversible step is **never** retried on the strength of "it looks like it
did not happen": a submission that silently succeeded and one that failed can
look identical, and repeating one moves money twice.

### What is MINIMAL, and what that costs — the UI is not mocked

Worth being precise, because the loose word understates what is here. The brief
says *"mock the operator UI if needed"*, and we did not need to. `ScriptedOperator`
is the mock — canned resolutions, tests only. `TerminalOperator` is a **real
operator surface with a minimal interface**: it reads a real person, drives the
**real live page** through `use_control`, is subject to the same allowlist and
the same redaction as the agent, and writes real `HumanAction` records. Nothing
about it pretends. The axis is *fidelity of the interface*, not realness of the
implementation:

```
ScriptedOperator    MOCKED     canned, tests only, no human
TerminalOperator    MINIMAL    real human, real page, terminal-grade affordances
a graphical console RICH       same mechanism, better affordances — not built
```

⚠️ **Not `page.pause()`**, which was the earlier plan. Playwright documents it
opening Inspector with codegen controls, but it needs a **headed** browser and
the machine this runs on has no display. A demo that works on one laptop is not
a demo.

Two consequences, both deliberate:

- **Better evidence than Inspector.** The human's actions go through the same
  action layer the agent uses, so they are recorded exactly — with
  `value_length` and never the value. Inspector's export was flagged as
  unvalidated and would have needed its own redaction pass.
- **The human cannot exceed the surface.** A real console would let them do
  anything. That is the cost of the mock.

⚠️ **This is a protocol plus a recorded state, not an interlock.** With a headed
browser nothing physically stops a person clicking during automation. Stated
rather than implied.

**So the handoff window is bracketed.** The per-action log is complete for
actions taken *through* the operator surface and blind to a hand on the mouse,
and a log that is silently partial is worse than one that states its scope. Each
edge of the window therefore records a frame, a URL and `url_changed`. Not *"here
is what the human did"* but *"here is what the page looked like when we handed it
over and when we got it back"* — **the action may be invisible; the effect is
not.** Both edges are captured the same way on purpose: a before/after pair
sourced from two different moments is not a pair.

⚠️ **A co-browsing console would not fix this, and §3.6 puts it out of scope.**
The design that would is a *headless mirror* — the human sees only a screenshot
and clicks it, so every action necessarily passes through `use_control` and the
unlogged path stops existing. That is a real option and it is written down rather
than built, because it buys enforcement at the cost of expressiveness at exactly
the moment expressiveness matters: you escalate to a human *because* the system
ran out of ideas, and a mirror can only offer verbs you anticipated. The honest
resolution is two modes with the takeover itself audited, which §7 records as
designed-and-unbuilt.

## 6. Safety

**One chokepoint.** `use_control` is the only function that touches the
application, which makes it the only place the checks can live and the only
place worth testing them. Eight tests, each asserting nothing reached the app
after a refusal.

**Allowlist, explicit and configurable.** Permitted origins and permitted
action kinds, both denied by default. The human operator goes through the same
gate.

**Risk is a property of the control, not the action.** Clicking "Log In" is
safe; clicking "Transfer" moves money; both are `CLICK`. So `irreversible` is
recorded on the control in `ControlPolicy`, every capability touching it
inherits that, and `validate_decision` refuses without an explicit
confirmation — one layer earlier than the action gate, which enforces the same
pairing again.

**Some risk depends on the VALUE, not the control.** `irreversible` says *this
button moves money*; it cannot say *this one moves too much*. So a tenant policy
carries `confirm_money_above`, the engine tracks the money amounts typed onto
the **current form**, and the irreversible step is judged on what is about to be
submitted. The two reasons stay distinguishable, because *"this button always
does"* and *"this amount needs a look"* call for different responses:

```
   500   step 5 is irreversible and was not confirmed: Submits a loan application
 25000   this step is irreversible and amount=25000 is at or above the 1000
         threshold for this tenant; a person has to confirm it
```

⚠️ **And the threshold was bypassable, which is the worst thing found here.**
The gate read `if irreversible and not confirm_risky:` — so a run started with
`--confirm-risky` skipped the value check **entirely**:

```
$ interfaceai replay …/request_loan.v1.approved.json --param amount=25000 --confirm-risky
SUCCESS request_loan in 10 steps                                   ← submitted
```

A $25,000 loan, no human, against a $1,000 threshold. The threshold was not
raised or misread — **it was never consulted.** Collapsing the two into one
condition inverted their precedence, and they are different authorities:
`--confirm-risky` is the *caller* saying "this run may do irreversible things";
`confirm_money_above` is the *bank* saying "a person signs off above this
amount" — a question never addressed to the caller, so the caller's blanket yes
cannot answer it. The tenant policy is now checked first and is not bypassable;
$500 with the same flag still goes through, because a guard that stops
everything passes the regression test and is useless.

⚠️ **Note the level, because it is the transferable part.**
`needs_human_confirmation` was correct throughout, and a unit test of it passed
the entire time the bypass existed. The defect was in the *branch*. It was found
by running the demo to capture real output for this document — not by reading
the code, and not by any test that existed.

⚠️ **The rule has to fire at the right step, and my first cut did not.**
Checking at the moment of *typing* would also have blocked a transaction
*search*, because `findtrans.htm` has an `amount` field too. Reading a number is
not spending it. The check belongs at the irreversible step and nowhere else.

⚠️ **And the tracked amounts have to be cleared at the right moment.** Clearing
after every action left the set empty by the time submit was reached — the rule
present, configured, and silently never firing. They are cleared when the **URL
moves**, because that is what "a different form" means.

**A tenant permits a capability, or it does not.** A static allowlist checked
before step 0, so a forbidden capability produces `Failed` without touching the
app — and it is checked for **invoked children too**, so a permitted capability
cannot smuggle in a forbidden one. ⚠️ This one is **make-believe and labelled
as such**: ParaBank has no roles, so the permission is ours, not the
application's. It demonstrates the enforcement point; it does not demonstrate
integration with a real entitlement system.

**Secrets never land.** A sensitive slot cannot hold a literal or a caller
param, only an `input_ref` resolved at replay. The audit record carries
`value_length`, never the value — a run log containing a password is a finding,
not a log. Enforced by a test that reads the committed artifacts off disk.

### Limits, stated

- **A current-URL check cannot prevent outbound navigation.** A click can
  redirect anywhere; the allowlist catches the next action, not the redirect.
- **The application's own permission model is untested.** ParaBank has no
  roles, so we have no instance of a *permission denial* (§3.3) as distinct
  from our guardrail refusing (§3.4). Recorded as a gap, not mocked.
- **`admin.htm` needs no authentication.** Normal in a demo app, catastrophic
  in a real one, and it is the lever this project uses for error injection.
- **Redaction covers logs and artifacts, not screenshots.** Frames are written
  unmasked. On a real system they would need a masking pass before persistence.

## 7. Cuts

What was left out on purpose, and what I would do next.

**Grid cell assignment was never fixed. It was made unreachable.** A grounded
account link lands on the wrong row **3 times in 4**
([issue 0009](docs/issues/0009-wrong-row-grounding-is-silent.md)), silently,
because a wrong cell in a uniform table looks exactly like a right one.
Relabelling does not help — three schemes measured, best 3/15. So a repeated
structure is a `TABLE_CONTROL_PANEL`: read the whole region in one call, index
the row **in code**, and reach it by a **measured row pitch** (28px, found by
autocorrelation at 0.899) rather than by grounding. `check_capability` then
**refuses a direct click on any control whose click point falls inside a panel
region**, which is what turns "we stopped doing that" into "that cannot be
done". Verified over all 11 rows.

⚠️ **This generalises past tables, which is the part worth keeping.** The site
nav was **0/8** grounded — the same defect wearing different clothes. Repeated
structure needs a panel, not just a table.

**A8: geometry proposes, perception verifies.** A row reached by arithmetic is
checked by re-reading the row it landed on. An early cut drew a marker dot at
the click point and false-alarmed on a *correct* run; numbered **bands** work,
because containment beats proximity. ⚠️ And fixed-interval markers do **not**
work at all — at 7px the deltas land in 14px bands. Matching it can do;
counting it cannot.

**Discovery read labels through an overlay that corrupted them — fixed.** One
call was doing two jobs on one image: name the controls *and* assign cell
numbers. Those want opposite images — **11/11** reading a clean screenshot
against **8/11** through the 192-cell grid, the gridded run reproducing an exact
wrong id from a live failure. Split into read-clean / locate-gridded.

**Extraction still cannot point at unstructured data**
([issue 0010](docs/issues/0010-extraction-cannot-point-at-data.md), backlog
[#4](https://github.com/borisdev/ai_computer_use/issues/4)). `EXTRACT` names a
control and the inventory ignores static text, so a lone `Balance: $1,231.10`
has no id. **Half solved:** a value inside a table is reachable, and the account
detail page is label/value pairs, which is a two-column table wearing different
clothes — both are panels. What remains is a value with *no* repeating structure
around it, whose one real victim is `log_in` wanting to return the customer
name. The fix is a region locator — landmark plus offset *and size* — reusing
the matcher that exists. **Cut because nothing needs it:** every capability in
the library works without it, so building it now is an abstraction with no
caller.

**A5: the naming churn was measured, and it was already gone.** The plan was to
close `control_id` to an enum because unlabelled controls got names that drifted
between runs. That measurement predated the read/locate split, so it was re-run
first — one screenshot, three draws, so the only variable is the model:
**62 ids over two screens, 6 draws, 0 churn.** The reason is structural: an id
is derived from label + role + position, not invented. **We were one step from
building a second fix for something already fixed.** What survives is narrower
and was never about the same call — the *inventory* does not invent names, but a
later `NextMove` once named `13767_link`, an account that does not exist. A
per-call `Literal` built from the ids actually in the map would make that
unrepresentable. Cut: it is already caught fail-closed, so the enum buys
enforcement rather than correctness.

**The operator console.** §3.6 puts a full co-browsing console out of scope and
permits a mocked UI; we built something better than a mock (above) and stopped
there. The *headless mirror* — the human sees a screenshot and clicks it — is
designed and unbuilt, with the trade recorded in §5.

**No persistence.** Evidence is files: `trace.jsonl` plus every frame. A SQLite
`runs`/`events`/`interventions` schema would add durability across process
restarts, and `jobs`/`attempts` would add queue semantics a single-worker CLI
does not need — §7 says that is unrewarded. Cut both; the handoff happens
in-process and the evidence is already complete.

**Async `Surface`.** Proposed and declined: it collides with sync Playwright,
eight passing tests and `OffLoop`, which exists *because* we measured
`asyncio.run` failing inside it. The rewrite buys nothing the brief rewards.

**A hand-authored YAML control catalogue.** Declined in favour of the store
discovery actually populates. A catalogue of placeholder image paths describes
controls nobody has grounded.

**Conditions with no instance.** Unexpected dialog and a *real* permission
denial are named by the brief and have never occurred here — ParaBank has no
roles, so our permission gate demonstrates the enforcement point and not the
integration. No types were invented for them; `docs/failure-modes.md` lists them
as gaps. **Session timeout is no longer on this list** — `session_loss_probe`
logs itself out mid-flow and the run recovers. Slow-load remains reachable and
untried.

**The controlled vocabulary is not in the inventory prompt.** It exists and
types every artifact, but the 15/24/22 inventory variance it was meant to fix
has not been re-measured.

**Not attempted at all:** capabilities 2–5 (5, *find transactions by amount*,
would reuse the panel read directly — its whole output is a result set),
desktop surface, code generation, multi-run stability scoring.

---

### If I had another day

1. **A `TABLE_CONTROL_PANEL` producer in discovery.** The panel is hand-added by
   a committed script today; discovery has no notion of a region with structure.
   This is the largest remaining gap between what discovery produces and what
   replay can use, and it is the reason capability 1's artifact needed a human
   step the recorder could not supply.
2. **A restyled tenant.** Both images ship the stock UI, so every locator
   matches at `1.0000` and the reuse path is proven while the reuse *claim* is
   not. A CSS-only skin would be the cheapest honest test of the one design
   decision with the most to lose.
3. **The headless mirror, as a second operator mode** — because it closes the
   unlogged-input path by construction rather than by protocol, and because
   having both modes is what makes the trade in §5 a decision rather than an
   excuse.

*Items 1 and 3 of the previous list — splitting the coarse pass and a
session-timeout capability — were done, and are written up above.*
