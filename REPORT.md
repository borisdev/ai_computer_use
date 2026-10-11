# Design write-up

> **The end-to-end thread runs.** A goal drives a real LLM against a live
> legacy bank UI; the run is recorded as a typed, versioned artifact; a human
> approves it; and it replays **deterministically with no model in the decision
> loop**, to a typed outcome, on a tenant it was never recorded against.
> Capabilities compose, a lost session is re-established, and a payment over a
> threshold stops and asks a person. Every number here came from a run.
>
> ```
> 331 tests — 293 offline, 38 live · ruff clean
> ```

Detail lives elsewhere: **[evidence/](evidence/README.md)** (committed runs,
one per outcome) · **[what-went-wrong.md](docs/what-went-wrong.md)** (every
defect, long form) · [findings.md](docs/findings.md) ·
[adr/](docs/adr/README.md) · [issues/](docs/issues/README.md) ·
[STILL-OPEN.md](STILL-OPEN.md).

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
  or replay path is a defect: a DOM recording cannot replay against a desktop
  app, which is the point of the seam. Tests may use the DOM as an oracle; the
  system may not.
- **Discovery and replay share one chain** — `locate_control → validate_decision
  → use_control` — so the path discovery proved is the path production takes.
- **Control maps are separate from artifacts**, which is what makes §4 work: an
  artifact names `(screen, control_id)`, the pixels live in a per-tenant store.

**The system describes itself**, because §3.2 asks that *both a human reviewer
and a calling agent* understand a capability: `interfaceai status` and
`interfaceai diagram`, the latter drawn **from the artifact** so it cannot
claim a step the system will not take ([status.md](docs/status.md)).

## 2. Artifact schema

Six capabilities are approved; **[CAPABILITIES.md](CAPABILITIES.md)** is the
generated table that cannot drift, with the evidence per row. Two were
**discovered end to end** — `discovered_balance`, where the read pass named the
accounts table, geometry measured it, and the row is picked by a `row_key`
parameter; and `log_in_discovered`. The rest are hand-written, and two of them
*must* be: `read_savings_balance` and `request_loan` need the account-detail
and loan-result panels, where the read pass still names a **neighbouring**
region. A gap, not a backlog item (§7).

`capability.py`; reasoning in
[ADR 0005](docs/adr/0005-capability-artifact-shape.md). Four constraints, each
in the type system rather than a style guide, each measured failing first:

1. **No coordinates, and no locators either** — a step names `(screen,
   control_id)`. Raw `(x, y)` scored **1/10** clicks inside the target, and a
   template is the least portable locator there is, so keeping it out of the
   artifact is what lets one recording serve two tenants.
2. **A checkpoint may only compare an extracted VALUE.** ParaBank's CLEAN state
   is why: account 13344 still *resolves*, as `CHECKING $5,022.93` instead of
   `SAVINGS $1,231.10`, so a presence check passes and hands a bank **a
   different record's balance**.
3. **A sensitive slot takes no literal and cannot be extracted back out.** The
   second half was missing; discovery proposed `EXTRACT username` on two runs
   of two, which would have handed a credential past every redaction.
4. **`draft → approved` is one function**, so there is one place to route
   around.

**Typed both ways** — `params` in, `returns` out, against a 34-term vocabulary
carrying a `sensitive` flag. `requires` holds **entry** preconditions; entry
precondition versus invariant is a distinction the schema cannot express
([#10](https://github.com/borisdev/ai_computer_use/issues/10)).

**Capabilities compose.** `INVOKE` runs another **in the same browser session**
with its **version pinned**, so a library holding a newer `log_in` is a
validation error rather than a silent substitution; five refusals are tested,
including an unapproved child and a cycle. A capability that returns something
must check it — the danger is handing back a value never proved to come from
the right record — and **`establishes`** is the mirror, which is how recovery
knows what puts a lost session back.

⚠️ **A hand-authored artifact can name a control that does not exist.** The
first two drafts carried **3 and 8** faults against real control maps; the
discovered one carried **0 on first emission**. Both are at 0 now — the point
is which needed correcting.

## 3. Determinism & error handling

Replay takes an approved artifact and typed inputs. **Nothing chooses an
action** — step order, control, value and checkpoint all come from the artifact.

```python
CapabilityResult = Success | BusinessOutcome | Failed | NeedsOperator
```

⚠️ **One model call survives, and only for reading.** An `extract` step must
turn pixels into a value and a DOM-less surface offers no other way. For a
table it is **one call for the whole panel**; the caller's parameter picks the
row *in code*. Asking a model where a row is lands on the wrong record **3
times in 4**, silently
([0009](docs/issues/0009-wrong-row-grounding-is-silent.md)). Reading is the
half models are good at — **11/11** on a clean crop against **8/11** through
our own grid overlay. **A capability with no `extract` step replays with zero
model calls.**

| | instances | example |
|---|---|---|
| `Success` | many | `$1231.10` for account 13344, read off the live screen |
| `BusinessOutcome` | 2 | account 99999 through the whole path; ParaBank's not-found is HTTP **200** plus plain text, so status codes cannot detect it |
| `Failed` | 6 | checkpoint read `5022.93` where the artifact said `1231.10` |
| `NeedsOperator` | several | a locator at 0.8654; and a $25,000 loan over the tenant's threshold — a different trigger entirely |
| ~~`Recoverable`~~ | **0** | **no type exists**, and a test asserts its absence |

**Why there is still no `Recoverable`.** `session_loss_probe` logs itself out
mid-flow and comes back `SUCCESS`, with `recovered accounts_overview_link
gone`. **A recovered condition is not a terminal state.** A fifth variant would
make a caller branch on something that is not an answer; `Success.recovered`
names what a run survived, and recovery is bounded to **once per condition** so
a dead session fails rather than loops.

**Repeated structure needs a panel, not grounding.** Grid cell assignment was
never fixed — it was made *unreachable*. A table is a `TABLE_CONTROL_PANEL`:
read the region in one call, index the row in code by a **measured pitch**,
verify by re-reading the row it landed on. 11/11, where the same defect left
the site nav **0/8** grounded.

⭐ **No pixel is asked of a model.** A read pass names the repeated structure;
**geometry** measures it — ink runs cross-checked against autocorrelation,
which says what the period is and cannot say where the first row starts. It
reproduced all four hand-measured regions: pitch **28/24/23/23** over
**11/8/4/3** rows. And a row cannot be clicked *at the decision*:
`table_control_panel` has no permitted action in `ACTIONS_BY_ROLE`, so
`validate_decision` refuses before `use_control` is reached and
`check_capability` refuses it geometrically at authoring time.

**Determinism rests on** re-resolution against the current screenshot rather
than a stored coordinate; refusals rather than guesses; a factory-reset target;
and value normalisation, since a screen prints `$1,231.10` where the artifact
recorded `1231.10`.

## 4. Heterogeneity & multi-tenant

**`Surface` is a protocol** — screenshot, click, type, scroll, navigate. The
schema, engine and guardrails name the protocol, never a browser, except at
the composition root where `replay()` must construct something.

⚠️ **It did not used to be true, and §3.7 asks precisely this.** Two of
`Surface`'s fifteen methods named a browser — `current_url()` and
`navigate(url)` — and a desktop application has no URL. Both are renamed.
Every caller already treated the value as an **opaque token**: seven sites
compare or record it, none parses it, so a desktop surface answering with a
window title satisfies all of them.

An artifact recorded on tenant A replays on tenant B. **Drift detection is the
adoption step** — `maps adopt` re-runs every locator against the target's live
screen and **writes nothing if any drifted**, because a partially adopted map
fails at replay far from the cause and reads like an application fault. A
tenant miss never falls back to another tenant's pixels.

**Both images ship the stock UI**, so matching at `1.0000` proved the reuse
*path* and little else. So tenant B was reskinned — Bank B's colours and
typeface over the same product, same DOM. `maps adopt` matched **8/25 and
wrote nothing**; replay on the unadopted tenant refused at the precondition.
Both refusals are the design working against a failure it had never seen.

⚠️ **The 8 survivors say what a template locator is worth.** `about_us_link`
survived, `about_us_link_2` drifted — same words, same page, because ParaBank's
**top nav is a graphic** and its **footer repeats those words as styled text**.
A locator survived exactly when its landmark was an image. A mechanism, not a
score, and the honest trade for working without a DOM.

⛔ **Both measurements hold the RENDERING STACK constant, so neither tests the
axis that actually broke.** A reviewer ran the demo on an M1 Mac against maps
built on Linux. `username_textbox` — first control, first screen — scored
**0.6889**, and the run escalated rather than clicking at 69% confidence.

```
cross-tenant, same stack    1.0000     two ParaBank images
tightest case on record     0.9998     "one antialiasing change from failing"
reskinned tenant            8/25
macOS vs Linux              0.6889     a different rasteriser, nothing else changed
```

A template was never a picture of a control; it was a picture of a control *as
rendered by a particular browser on a particular OS*, and nothing recorded
that. `ScreenOutput.captured_on` now does — which makes the failure
diagnosable, not portable. The fix is to pin the stack: the agent ships as a
container, and every host then drives the Linux Chromium the templates came
from ([0012](docs/issues/0012-control-maps-are-rendering-stack-specific.md)).
**This is the strongest portability evidence here** — the only measurement
taken under conditions that could defeat the locator, and did, unstaged, on
hardware I do not own.

## 5. Escalation & handoff

**Detect.** Eight triggers, **seven needing no model judgement**: a guardrail
refusal, an `unresolved` control, a locate returning `not_found` or `ambiguous`,
an unconfirmed irreversible step, a money amount over the tenant's threshold, an
unknown secret ref, a malformed move. Only "the model says it is stuck" needs a
model.

**Route, take, verify.** `InterventionRequest` carries why, which capability and
step, screen, URL, a frame, and what was already completed. The human gets the
**same `PlaywrightSurface` mid-run** — same page, same cookies, automation
stopped — and `owner` flips `worker → human → worker`, both transitions logged.
Resume is never "continue from line N":

```
the capability's preconditions still hold, and
  the step's target is now satisfied  ->  advance past it
  the step is still safe to perform   ->  retry it
anything uncertain                    ->  stay paused
```

An irreversible step is **never** retried on "it looks like it did not happen":
a submission that silently succeeded and one that failed look identical.

**The UI is minimal, not mocked.** `TerminalOperator` reads a real person and
drives the **real live page** through `use_control`, under the same allowlist
and redaction as the agent, recording `value_length` and never the value.
⚠️ **No committed run has a human at the terminal** — the handoff evidence was
produced by `ScriptedOperator`, which feeds the same `resolve` through the same
gate, so the protocol is evidenced and a hand on the mouse is not.

⚠️ **It is a protocol plus a recorded state, not an interlock** — nothing stops
a person clicking the visible browser directly, and we would not see it. So the
window is **bracketed**: a frame, a location and `location_changed` at each
edge. Not *"what the human did"* but *"what the page looked like when we handed
it over and got it back"*. The design that would fix it is a **headless
mirror**, unbuilt because it restricts the human to verbs we anticipated at
exactly the moment ours proved insufficient.

## 6. Safety

**One chokepoint.** `use_control` is the only function that clicks or types, so
it is the only place the checks can live — and the human goes through it too.
⚠️ Precisely: `replay()` also calls `surface.navigate()` once at start-up,
outside it. That is the honest exception to "only".

**Risk is a property of the control, not the action.** Clicking "Log In" is
safe, clicking "Transfer" moves money, and both are `CLICK` — so `irreversible`
lives on the control and every capability touching it inherits it. **Some risk
depends on the VALUE:** a tenant policy carries `confirm_money_above`, judged
against the amounts entered during the run. ⚠️ **That rule has been bypassable
twice** (both in [what-went-wrong.md](docs/what-went-wrong.md)), and both times
`needs_human_confirmation` was correct while its *branch* was wrong — a
run-level `--confirm-risky` cannot answer a tenant-level policy.

**Secrets never land, and neither do balances.** A sensitive slot takes only an
`input_ref` and cannot be extracted back out. Typed inputs record
`value_length`; extracted outputs are masked when the vocabulary says the slot
is `sensitive` or MONEY. ⚠️ That second half was **false until Copilot checked
the committed traces**, which carried `"value": "$1231.10"` while this document
claimed redaction. `account_id` stays readable on purpose — evidence proving
*which* record was read must name it.

**Limits.** A current-URL check cannot prevent outbound navigation. ParaBank
has no roles, so the tenant permission gate demonstrates the enforcement point
and **not** integration with a real entitlement system. Redaction covers logs
and artifacts, **not screenshots**
([#7](https://github.com/borisdev/ai_computer_use/issues/7)). A tenant absent
from the policy is refused rather than run unrestricted, and an unparseable
threshold stops the run rather than silently disabling the money rule — both
were fail-open until Copilot found them.

## 7. Cuts

Reasoning per item in [STILL-OPEN.md](STILL-OPEN.md).

- **Extraction cannot point at *unstructured* data**
  ([#4](https://github.com/borisdev/ai_computer_use/issues/4)). Tables and
  label/value pairs are reachable; a lone value with no repeating structure is
  not. Cut because nothing needs it — an abstraction with no caller.
- **Closing `control_id` to an enum** — measured, and the premise was gone:
  one screenshot, three draws, **62 ids over two screens, 0 churn**, because an
  id is derived from label + role + position rather than invented.
- **The operator console** (§3.6 puts co-browsing out of scope), **persistence**
  (evidence is files; a queue adds semantics a single-worker CLI does not
  need), **async `Surface`** (collides with sync Playwright), and a
  hand-authored control catalogue.
- **Conditions with no instance:** unexpected dialog, a *real* permission
  denial, and — the one worth naming — **a validation error raised by the
  application**. §3.3 lists it and nothing here produces one, because ParaBank
  rejects a transfer for insufficient funds and no capability does transfers.
  A sixth capability would close it, and it is the best use of another day.
- **Not attempted:** a desktop `Surface`, code generation, multi-run stability
  scoring, and a real human at the handoff terminal (§5).
