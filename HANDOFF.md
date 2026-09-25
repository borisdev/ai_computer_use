# Handoff

Read this first. It says where the project is, what is proven, what is not, and
what to do next. Everything it claims is measured unless it says otherwise.

**Repo:** `github.com/borisdev/ai_computer_use` · 6 commits · 49 tests green · ruff clean

---

## 1. What this project is, in one paragraph

An LLM drives a legacy bank UI **once** to learn how a task is done; that run is
recorded as a typed capability artifact; the artifact is then replayed
**deterministically, with no model in the decision loop**. The target is
ParaBank, running locally in Docker. The brief is
[`Assignment-A-Computer-Use-Automation.md`](Assignment-A-Computer-Use-Automation.md).

---

## 2. Scope — settled, and quoted

The single most useful thing established in the last session. The brief draws
the line itself:

> §1: "the agent-facing product decides **what** to do; this system is **how** it
> reliably and safely does it inside legacy bank software"

```
  1. user utterance                ─┐
  2. triage / is this legitimate?   ├── the agent-facing product — OUT OF SCOPE
  3. match utterance -> capability  │
     + typed arguments            ─┘
  ────────────────────────────────────────────────────────────────────────
  4. run the capability             ─── OURS
```

### In scope

| | Brief |
|---|---|
| Accept a **goal** (natural language) + a target, and learn a capability | §3.1 |
| Emit a typed, versioned, **reviewable** capability artifact | §3.2 |
| Replay it deterministically, **no LLM in the decision loop** | §3.3 |
| Allowlist, risky-vs-reversible actions, redaction | §3.4 |
| Evidence for both runs | §3.5 |
| Pause, hand the **same live session** to a human, resume, record | §3.6 |

### Out of scope, and why

| | Brief |
|---|---|
| The chat box, triage, clarification dialogue | §1 — "the agent-facing product decides what to do" |
| Matching an utterance to a capability | same |
| A real co-browsing operator console | §3.6 — "out of scope… mock the operator UI if needed" |
| Queues, clusters, process supervision, multi-tenant plumbing | §7 — "we **do not reward**… building scaling infrastructure" |
| Desktop surface, multi-tenant implementation | §3.7 — "design, not necessarily build" |

Three different treatments, easily conflated:

- **Mocked** — a stand-in that actually runs. Only the `Operator` seam.
- **Designed, not built** — desktop, multi-tenant. Abstractions must not preclude them.
- **Not ours at all** — triage, utterance matching.

### Goal vs capability

> §3.1 "Accept a **goal** + a target as input" · §3.2 "a **capability** an AI agent can call… **typed input parameters**"

```
  goal        natural language, input to DISCOVERY, once
              "log in as john and read the balance of savings account 13344"
                     │  LLM in the loop, ~25 calls, 30s
                     ▼
  capability  typed artifact, invoked at REPLAY, many times
              read_savings_balance(account_id: str) -> balance: Money
```

A goal is a sentence. A capability is a function. **Discovery is the compiler.**

### Two phases

> §1: "figure out how to accomplish a task **the first time**, then turns what it
> learned into deterministic, replayable automation… a reusable, **reviewable**,
> parameterized capability" · §8: "gate unattended replay on an **approval state
> (draft → approved)**"

```
  PHASE 1  AUTHORING   developer, supervised, offline
  goal ─► discover ─► capability (draft) ─► human review ─► approved ─► registry

  PHASE 2  RUNTIME     user, unattended, cheap
  [agent-facing product] ─► capability + args ─► invoke ─► result | HITL
```

**Discovery must never run automatically at runtime.** An unreviewed artifact
acting on a bank is exactly what "reviewable" and "draft → approved" prevent.

---

## 3. The central finding

**Vision models read a screen accurately and locate it badly.** Measured against
DOM ground truth on ParaBank's login screen:

| Model | Mean error | Landed inside the control | Latency |
|---|---|---|---|
| gpt-4o | 143px | 0/5 | 13s |
| gpt-4.1 | 160px | 1/5 | 16s |
| gpt-5.2-chat | 155px | 0/5 | 34s |

The inputs are 15–22px tall, so 45–80px of vertical error is **3–5 control
heights** — not "near the field", a *different field*. Everything came back at
0.98 confidence, so the failure was silent. **The newest, slowest, most expensive
model scored worst: model tier is not a lever.**

### What fixed it

Stop asking for coordinates. Code places numbered dots at known points; the model
picks a number; code maps number → pixel. Regression becomes classification.

| | Clicks landing inside the control |
|---|---|
| Raw coordinate estimation | **1/10** |
| Grid + dots, first cut | 2/3 |
| **Grid + dots + resolution rules** | **3/3**, stable across runs |

One principle, applied twice — **code owns the resolution decision, the model
only points**:

- **Too coarse → do not trust a `click`.** At round 1 dots are 30px apart and the
  field is 18px, so *zero* dots can be inside it. Its chosen dot still says which
  cell, so we zoom.
- **Fine enough → do not honour a `zoom`.** At round 2 (11px spacing, 16 dots
  inside the field) the model asked to zoom while pointing *inside*. Obeying it
  meant round 3 on a 33×33px fragment where it could no longer tell what it was
  looking at. Magnifying past recognition destroys the context.

---

## 4. What is built, and what is proven

| Module | Does | Proven by |
|---|---|---|
| `screenshot2controls.py` | `extract_control_locators`, `locate_control` | 17 tests + live 3/3 |
| `surface.py` | `PlaywrightSurface`, `use_control` | 8 tests, live |
| `vision_llm.py` | litellm dispatch, profiles, strict schema | 3 tests, live |
| `decisions.py` | `validate_decision`, role→action table | 7 tests |
| `parabank.py` | target facts, known states | 7 + 4 live |
| `evidence.py` | `EvidenceWriter` | smoke only |

**The three verbs:**

```
  extract_control_locators(screenshot) -> locators    LLM, ~25 calls, once
  locate_control(screenshot, locator)  -> point       pure, no model
  use_control(screen, x, y, action)    -> Acted       the ONLY side effects
```

Replay is exact: locators recorded once, re-found on a fresh page load at score
**1.0000**, drift **(0,0)**, fields filled correctly.

### Landmarks

A **landmark** is a saved patch of screen. At replay we find it and step back to
the control by a recorded offset. It is *not* a picture of the control — an empty
field has no identity, so the landmark reaches beyond it to catch a label.
Measured, same matcher:

| Cropped | std | Positions ≥0.95 |
|---|---|---|
| the control's own bbox | 74.8 | **3** — matches Username *and* Password |
| a patch inside the empty field | **0.0** | **1,103,249** |
| the context landmark | 39.6 | **1** ✓ |

A flat crop is not merely weak — normalised correlation of a zero-variance patch
scores a perfect **1.0 everywhere**. Rejecting constant templates is a
correctness guard.

---

## 5. What is NOT built

| § | | |
|---|---|---|
| 3.1 | goal-driven agent loop | nothing decides yet |
| 3.2 | **capability artifact** | the graded centrepiece — designed, not coded |
| 3.3 | step executor / `CapabilityResult` | `locate_control` exists; nothing runs a sequence |
| 3.6 | escalation | triggers exist (`unresolved`, `ambiguous`); no `Operator` |
| — | `REPORT.md` | skeleton |
| — | `/evidence/` | screenshots only |

---

## 6. The blocker

**[Issue 0001](docs/issues/0001-incomplete-inventory.md) — the inventory is
incomplete and different every run.** Same screenshot bytes, same config,
temperature 0:

```
one broad call   15 / 24 / 22   and   24 / 19 / 24     spread 5
tiled scan       27 / 27 / 26   and   26 / 26 / 26     spread 1
```

A run once dropped `log_in_button` entirely, which is what stops an end-to-end
login. Root cause: the coarse prompt asks for **exhaustive enumeration with no
goal in it**, so "Log In" and "Read More" have equal standing.

Diffing tiled runs by control rather than by count changed the reading: the count
was 26/26/26, and **six of the eight varying entries were three controls
described two different ways** — ParaBank's orange header icons, which carry no
text label. Nothing was dropped; the churn was in what things are *called*.

That separates two failure modes that looked identical:

- a control **with** a label going missing → an **omission**, which tiling addresses
- a control **without** one churning between names → a **naming** problem, which
  only a controlled vocabulary addresses

---

## 7. Where to go next, in order

1. **The capability artifact (§3.2).** The graded centrepiece and everything
   hangs off it. The design is settled in
   [`docs/capabilities-and-vocabulary.md`](docs/capabilities-and-vocabulary.md):
   five capabilities, and a 34-term straw-man vocabulary derived backwards from
   them. Capability 1 is self-checking — account 13344 is SAVINGS **$1,231.10**.
   Needs `requires` (preconditions) as well as a checkpoint.
2. **The step executor (§3.3).** `screenshot → locate → validate → use →
   screenshot → assert checkpoint → CapabilityResult`.
3. **Fix the inventory ([0001](docs/issues/0001-incomplete-inventory.md)).** Three
   reinforcing parts: the controlled vocabulary, the goal passed down to the
   coarse prompt, and a required-controls list that retries rather than
   proceeding with a hole.
4. **`Operator` seam (§3.6).** `page.pause()` gives pause, same session, resume
   and codegen capture in one line — see §8 below.
5. **`REPORT.md`.** Sections 2 and 3 of this document are most of it already.

---

## 8. Decisions already made — do not relitigate without evidence

- **ADR 0001** ParaBank as the target
- **ADR 0002** Playwright driving screenshots and coordinates, **not the DOM**.
  `page.locator()` in the agent or replay path is a defect.
- **ADR 0003** plain `docker compose`, no Makefile
- **ADR 0004** our own tool vocabulary, not Anthropic's computer toolset

Settled in discussion, not yet an ADR:

- **`page.pause()` is the HITL mechanism.** Verified in the installed library:
  requires headed mode, blocks, lets the human perform manual steps, resumes from
  the same place. Per the codegen docs the pause window carries **codegen
  controls**, so the human's clicks become real Playwright actions — which
  answers "record what the human did" and means **we do not have to mock the
  operator console; Playwright ships one**. Caveat: the generated code lands in a
  UI window, so capture into `/evidence/` is a paste plus our own state delta.
- **Resume is not "continue from line N".** The human may have gone anywhere, so
  resume must re-observe, re-check `requires`, re-locate, then continue. That is
  why preconditions matter.
- **We extract the signature; they extract the arguments.** Discovery must
  recognise that `13344` in a goal is a **parameter**, not bake it in. §3.2's
  "typed input parameters", §8's `/item/12345 → /item/:id`.
- **Sensitive slots.** `username`, `password`, `ssn` go through controls exactly
  like parameters do, and §3.4 forbids persisting them. The vocabulary needs a
  `sensitive` flag so they become `input_ref` placeholders. Build this in from
  the start — it is the difference between an artifact you can commit publicly
  and one you cannot.

---

## 9. Environment

```bash
docker compose up -d --wait          # liveness only
uv run interfaceai env reset         # readiness: seed the DB and verify
```

**Both are needed.** ParaBank boots with **no database schema** and serves HTTP
200 anyway; its lazy initialiser was observed logging "Database not yet
initialized" every 10s for minutes while `docker compose ps` said `healthy`.

Keys live in `.secret` (gitignored). `VISION_API_KEY` and `VISION_API_KEY_EASTUS2`
are copied from `~/workspace/nobsmed-v2/.secret`.

Setting up a fresh machine or VM: [`docs/vm-setup.md`](docs/vm-setup.md)

Full target notes: [`docs/parabank.md`](docs/parabank.md) ·
29 screens: [`docs/parabank-screens.md`](docs/parabank-screens.md)

---

## 10. Things that cost time — recorded so they cost it once

1. `docker compose down` **ignores profiled services**, leaving an orphan holding the network.
2. ParaBank **boots with no schema** and serves 200 anyway.
3. A crawler **clicks its own Log Out link** and silently continues unauthenticated.
4. `CropBox` validates `ge=0` **at construction**, so clipping must happen on plain ints.
5. **Sync Playwright cannot nest `asyncio.run`** — capture and discovery are separate phases.
6. Azure strict mode needs **every property in `required`** and `$ref` stripped of siblings.
7. A key in `.secret` **never reaches the SDK** — pydantic-settings loads it, the client reads `os.environ`.
8. gpt-4o rejects `max_tokens > 4096` on that deployment.
9. A module-level experiment **re-runs on import** — cost a duplicated 6-call batch.
10. `| tail -N` **buffers a whole pipeline**, so a background log looks empty until it exits.

Everything measured: [`docs/findings.md`](docs/findings.md) ·
Open problems: [`docs/issues/`](docs/issues/README.md)
