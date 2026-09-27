# Design write-up

> **Status: the end-to-end thread runs.** A goal drives a real LLM against the
> live app, the run is recorded as a typed artifact, a human approves it, and it
> replays deterministically to a typed outcome — including the failure and
> human-handoff branches, and on a second tenant it was never recorded against.
> Every number here came from a run; where something is inferred it says so.
>
> ```
> 165 tests — 151 offline, 14 live · ruff clean
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
turn pixels into a value and a DOM-less surface offers no other way. That is
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
| `Success` | many | `account_id = 12345`, read off the live screen |
| `BusinessOutcome` | 1 | `Could not find account #54321` — HTTP **200** and plain text, so status codes cannot detect it |
| `Failed` | 6 | checkpoint read `5022.93` where the artifact said `1231.10` |
| `NeedsOperator` | 1 live + 6 forceable | a locator at 0.8582, below threshold |
| ~~`Recoverable`~~ | **0** | **no type exists.** A test asserts its absence, so adding it is a conscious act |

### Demonstrated, not argued

Same artifact, same command; only ParaBank's own admin page differs.

```
$ interfaceai replay artifacts/log_in_discovered.v1.approved.json
SUCCESS log_in_discovered in 5 steps
  account_id = 12345                                              exit 0

$ interfaceai env break        # action=CLEAN — account 12345 stops existing
$ interfaceai replay artifacts/log_in_discovered.v1.approved.json
NEEDS A HUMAN at step 4: cannot read 12345_link: not_found (0.8582)
  completed: enter username_textbox, enter password_textbox,
             click log_in_button, observe                          exit 1
```

The second is the one worth reading. It **refuses to click something scoring
0.86** and carries what it finished so a human can resume rather than restart.
Nothing is mocked — the failure is produced by the application.

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

**Detect.** Seven triggers, and **six need no model judgement**: a guardrail
refusal, a decision refused because the control is `unresolved`, a locate that
came back `not_found` or `ambiguous`, an unconfirmed irreversible step, an
unknown secret ref, a malformed move. Only "the model says it is stuck" depends
on a model.

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

### What is mocked, and what that costs

The operator drives the page through a **terminal console** rather than by
clicking in a window. The brief permits mocking the operator UI provided the
handoff mechanism and control-transfer model are real; they are.

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

**Capability 1 — "read a member's savings balance" — does not replay.** The
brief's own worked example. The *mechanism* works and is proven by a live test:
anchor the accounts table's header, crop it, one model call against a response
schema, and select the row **in code** by the caller's parameter — `$1,231.10`
for account 13344, and `5022.93` correctly caught as a violated checkpoint after
`env break`. What is missing is plumbing: nothing yet emits a
`TABLE_CONTROL_PANEL` into a control map, and `EXTRACT` targets one control
rather than a row set. **Next thing I would build.**

**Extraction cannot point at data** ([issue 0010](docs/issues/0010-extraction-cannot-point-at-data.md)).
`EXTRACT` names a control; the inventory prompt is told to ignore static text;
so a balance has no id. The fix is a region locator — a landmark plus an offset
*and a size* — reusing the matcher that already exists.

**Grid cell assignment is broken and is on the way out.** A grounded account
link lands on the wrong row **3 times in 4**
([issue 0009](docs/issues/0009-wrong-row-grounding-is-silent.md)), silently,
because a wrong cell in a uniform table looks exactly like a right one.
Relabelling the grid does not fix it — measured across three schemes, best
3/15. The answer is to remove cell assignment from the positioning path, which
is what the panel approach does.

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

**Conditions with no instance.** `Recoverable`, permission denial and
unexpected dialog are named by the brief and have never occurred here. No types
were invented for them; `docs/failure-modes.md` lists them as gaps. Session
timeout and slow-load are *reachable* and untried — those are the honest TODOs.

**The controlled vocabulary is not in the inventory prompt.** It exists and
types every artifact, but the 15/24/22 inventory variance it was meant to fix
has not been re-measured.

**Not attempted at all:** capabilities 2–5, desktop surface, an approval
workflow, code generation, multi-run stability scoring.

---

### If I had another day

1. A `TABLE_CONTROL_PANEL` producer, which lands capability 1 and closes 0009
   and 0010 together.
2. The vocabulary into the inventory prompt, then re-measure the variance.
3. A session-timeout capability, giving the recoverable class its first real
   instance instead of a guess.
