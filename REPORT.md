# Design write-up

> **The end-to-end thread runs.** A goal drives a real LLM against a live
> legacy bank UI; the run is recorded as a typed, versioned artifact; a human
> approves it; and it replays **deterministically with no model in the decision
> loop**, to a typed outcome, on a tenant it was never recorded against.
> Capabilities compose, a lost session is re-established, and a payment over a
> threshold stops and asks a person. Every number here came from a run.
>
> ```
> 275 tests — 244 offline, 31 live · ruff clean
> ```

Detail lives elsewhere so this stays short: **[evidence/](evidence/README.md)**
(committed runs, one per outcome) · **[what-went-wrong.md](docs/what-went-wrong.md)**
(every defect, long form) · [findings.md](docs/findings.md) (measurements) ·
[adr/](docs/adr/README.md) · [issues/](docs/issues/README.md) ·
[STILL-OPEN.md](STILL-OPEN.md) (what was cut, and why).

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
`interfaceai diagram`, the latter drawn **from the artifact** so it cannot claim
a step the system will not take ([status.md](docs/status.md)).

## 2. Artifact schema

Five capabilities are authored and tested (`interfaceai status` lists them):

| | exercises |
|---|---|
| `read_savings_balance` v3 | the brief's own worked example — panel read, row by index, a checkpoint on the account TYPE |
| `log_in` v2 | composition: invoked by three others, version pinned |
| `log_in_discovered` v1 | **produced by a real discovery run**; the cross-tenant and handoff subject |
| `request_loan` v2 | an irreversible step, a tenant money threshold, and a post-submit observation |
| `session_loss_probe` v1 | destroys its own session mid-flow, to earn recovery an instance |

`capability.py`; reasoning in [ADR 0005](docs/adr/0005-capability-artifact-shape.md).
Each constraint is in the type system rather than a style guide, because each
was measured failing first:

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
   replay — **and cannot be extracted back out.** The second half was missing;
   discovery proposed `EXTRACT username` on two runs of two, which would have
   handed a credential to the caller past every redaction.
4. **`draft → approved` is one function**, so there is exactly one place to
   route around.

**Typed both ways:** `params` in, `returns` out, checked against a 34-term
vocabulary carrying a `sensitive` flag. `requires` holds **entry**
preconditions, checked once before step 0. ⚠️ This said "re-checked on resume"
and the code did not do it; making it true broke every resume, because
`at_the_login_page` is necessarily false mid-flow. Entry precondition versus
invariant is a distinction the schema cannot express
([#10](https://github.com/borisdev/ai_computer_use/issues/10)) — what resume
verifies is the stopped step's own footing (§5).

**Capabilities compose.** `INVOKE` calls another **in the same browser session**
— a section of the same run, in the same evidence file — so `log_in` is written
once instead of copied into twenty artifacts and re-fixed the day the login page
moves. **The version is pinned**, so a library holding a newer `log_in` is a
validation error, not a silent substitution. Five refusals are tested: missing,
version drift, an **unapproved child**, self-invocation, and a cycle.

**A capability that RETURNS something must check it** — not "everything needs a
checkpoint", which is what this said first. `log_in` returns nothing and its
`wait_for` already asserts arrival. The danger is handing back a *value* never
proved to come from the right record. **`establishes`** is the mirror: a
postcondition naming what is true afterwards, which is how recovery knows which
capability puts a lost session back.

⚠️ **A hand-authored artifact can name a control that does not exist.** The
first two drafts carried **3 and 8** faults against real control maps — they
referenced a screen called `global_nav` that I invented and never mapped. The
discovered artifact carried **0 on first emission**. Both are at 0 now; the
point is which needed correcting. `interfaceai capability check` is the check.

## 3. Determinism & error handling

Replay takes an approved artifact and typed inputs. **Nothing chooses an
action** — step order, control, value and checkpoint all come from the artifact.

```python
CapabilityResult = Success | BusinessOutcome | Failed | NeedsOperator
```

⚠️ **One model call survives, and only for reading.** An `extract` step must
turn pixels into a value and a DOM-less surface offers no other way. For a table
it is **one call for the whole panel**; the caller's parameter picks the row *in
code*. Asking a model where a row is lands on the wrong record **3 times in 4**,
silently ([0009](docs/issues/0009-wrong-row-grounding-is-silent.md)). Reading is
the half models are good at — **11/11** on a clean crop against **8/11** through
our own grid overlay. **A capability with no `extract` step replays with zero
model calls.**

| | instances | example |
|---|---|---|
| `Success` | many | `$1231.10` for account 13344, read off the live screen |
| `BusinessOutcome` | 2 | account 99999 through the whole path; ParaBank's not-found is HTTP **200** plus plain text, so status codes cannot detect it |
| `Failed` | 6 | checkpoint read `5022.93` where the artifact said `1231.10` |
| `NeedsOperator` | several | a locator at 0.8654; and a $25,000 loan over the tenant's threshold — a different trigger entirely |
| ~~`Recoverable`~~ | **0** | **no type exists**, and a test asserts its absence |

**Why there is still no `Recoverable`, now that we recover.**
`session_loss_probe` logs itself out mid-flow and comes back `SUCCESS`, with
`recovered accounts_overview_link gone`. **A recovered condition is not a
terminal state.** A fifth variant would make a caller branch on something that
is not an answer; `Success.recovered` names what a run survived, and recovery is
bounded to **once per condition** so a dead session fails rather than loops.

**Repeated structure needs a panel, not grounding.** Grid cell assignment was
never fixed — it was made *unreachable*. A table is a `TABLE_CONTROL_PANEL`:
read the region in one call, index the row in code, reach it by a **measured
pitch** (28px, autocorrelation 0.899), then verify by re-reading the row it
landed on. `check_capability` **refuses a direct click inside a panel region**,
turning "we stopped doing that" into "that cannot be done". 11/11 — and it
generalises: the site nav was **0/8** grounded, the same defect in different
clothes.

**Determinism rests on** re-resolution against the current screenshot rather
than a stored coordinate; refusals rather than guesses; a factory-reset target;
and value normalisation, since a screen prints `$1,231.10` where the artifact
recorded `1231.10`.

## 4. Heterogeneity & multi-tenant

**`Surface` is a protocol** — screenshot, click, type, scroll, navigate. The
schema, engine and guardrails name the protocol, never a browser, except at the
composition root where `replay()` constructs a `PlaywrightSurface` because
something must. `use_control` is surface-independent: *what is permitted* is a
property of the bank, *how to click* a property of the surface.

An artifact recorded on tenant A replays on tenant B. **Drift detection is the
adoption step** — `maps adopt` re-runs every locator against the target's live
screen and **writes nothing if any drifted**, because a partially adopted map
fails at replay far from the cause and reads like an application fault. A tenant
miss never falls back to another tenant's pixels.

**And it has now met a rebrand.** Both images ship the stock UI, so matching at
`1.0000` proved the reuse *path* and little else. So tenant B was reskinned —
Bank B's colours and typeface over the same product, same DOM, same layout
(`docker-compose.reskin.yml`). Measured:

```
maps adopt index   baseline -> reskinned feature    8/25 matched, NOTHING WRITTEN
replay             on the unadopted tenant          refused at the precondition
```

Both refusals are the design working. The adopter **wrote nothing** rather than
half a map, and replay stopped at `username_textbox should be present` — a
clean refusal, not a wrong click, against a failure the system had never seen.

⚠️ **And the 8 that survived say exactly what a template locator is worth.**

```
SURVIVED   about_us_link · services_link · products_link · locations_link
DRIFTED    about_us_link_2 · services_link_2 · products_link_2 · locations_link_2
```

Same words, same page. ParaBank's **top nav is a graphic**; its **footer
repeats those words as styled text**. A locator survived exactly when its
landmark was an image and drifted when the landmark was text — so a rebrand
costs you every text-anchored control and none of the image-anchored ones.
That is a mechanism, not a score, and it is the honest shape of the trade this
design accepts in exchange for working without a DOM: **template matching does
not survive a reskin, and the system's response to that is to refuse.**

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

**The UI is minimal, not mocked**, and the loose word understates it.
`ScriptedOperator` is the mock (tests only). `TerminalOperator` reads a real
person and drives the **real live page** through `use_control`, under the same
allowlist and redaction as the agent, recording `value_length` and never the
value.

⚠️ **It is a protocol plus a recorded state, not an interlock** — nothing stops
a person clicking the visible browser directly, and we would not see it. So the
handoff window is **bracketed**: a frame, URL and `url_changed` at each edge.
Not *"what the human did"* but *"what the page looked like when we handed it
over and got it back"*. A co-browsing console would not fix this and §3.6 puts
it out of scope; the design that would is a **headless mirror**, unbuilt because
it restricts the human to verbs we anticipated at exactly the moment ours proved
insufficient.

## 6. Safety

**One chokepoint for every action.** `use_control` is the only function that
clicks or types, so it is the only place the checks can live — and the human
goes through it too. ⚠️ Precisely: `replay()` also calls `surface.navigate()`
once at start-up, outside it. That is the honest exception to "only".

**Risk is a property of the control, not the action.** Clicking "Log In" is
safe, clicking "Transfer" moves money, and both are `CLICK`. So `irreversible`
lives on the control and every capability touching it inherits that.

**Some risk depends on the VALUE.** A tenant policy carries
`confirm_money_above`, and the irreversible step is judged on the amounts
entered during the run. ⚠️ **This rule has been bypassable twice** — both in
[what-went-wrong.md](docs/what-went-wrong.md) — and both times
`needs_human_confirmation` was correct while its *branch* was wrong. A
run-level `--confirm-risky` cannot answer a tenant-level policy, and an amount
entered anywhere in the run is still in play at an irreversible step.

**Secrets never land, and neither do balances.** A sensitive slot takes only an
`input_ref` and cannot be extracted back out. Typed inputs record
`value_length`; extracted outputs are masked when the vocabulary says the slot
is `sensitive` or MONEY. ⚠️ That second half was **false until Copilot checked
the committed traces**, which carried `"value": "$1231.10"` while this document
claimed redaction covered logs. `account_id` stays readable on purpose —
evidence proving *which* record was read must name it.

**Limits.** A current-URL check cannot prevent outbound navigation. ParaBank has
no roles, so our tenant permission gate demonstrates the enforcement point and
**not** integration with a real entitlement system — make-believe, and labelled
so. Redaction covers logs and artifacts, **not screenshots**
([#7](https://github.com/borisdev/ai_computer_use/issues/7)). A tenant name not
in the capability policy is refused rather than run unrestricted, and a
threshold that will not parse stops the run rather than silently disabling the
money rule — both were fail-open until Copilot found them.

## 7. Cuts

Reasoning per item in [STILL-OPEN.md](STILL-OPEN.md).

- **Extraction cannot point at *unstructured* data**
  ([#4](https://github.com/borisdev/ai_computer_use/issues/4)). Values in tables
  and label/value pairs are reachable; a lone value with no repeating structure
  is not. Cut because **nothing needs it** — an abstraction with no caller.
- **Closing `control_id` to an enum — measured, and the premise was gone.** One
  screenshot, three draws: **62 ids over two screens, 0 churn**, because an id
  is derived from label + role + position, not invented. We were one step from
  fixing something already fixed.
- **The operator console.** §3.6 puts a co-browsing console out of scope.
- **No persistence**, because evidence is files and `jobs`/`attempts` adds
  queue semantics a single-worker CLI does not need. **Async `Surface`**,
  because it collides with sync Playwright and `OffLoop` — which exists
  *because* we measured `asyncio.run` failing inside it. **A hand-authored YAML
  control catalogue**, in favour of the store discovery populates.
- **Conditions with no instance:** unexpected dialog, a *real* permission
  denial, and — the one worth naming — **a validation error raised by the
  application**. §3.3 lists it, and nothing here produces one: ParaBank rejects
  a transfer for insufficient funds, and no capability does transfers. That is
  the gap a sixth capability would close, and it is a better use of a day than
  any other flow.
- **Not attempted:** a desktop `Surface`, code generation, and multi-run
  stability scoring.

### If I had another day

1. **A `TABLE_CONTROL_PANEL` producer in discovery** — panels are hand-added by
   a script today, which is the largest gap between what discovery produces and
   what replay can use.
2. **A restyled tenant** — the cheapest honest test of the decision with the
   most to lose (§4).
3. **The headless mirror as a second operator mode**, so §5's trade is a
   decision rather than an excuse.
