# Findings, mapped to the assignment

Everything measured so far, what it means for each requirement, and what is
still open. Every number here came from a run against the live target; where
something is inferred rather than measured, it says so.

Companions: [parabank.md](parabank.md) (the target), [parabank-screens.md](parabank-screens.md)
(its 29 screens), [adr/](adr/README.md) (decisions), [issues/](issues/README.md) (open problems).

---

## 1. Status against each requirement

| § | Requirement | State | Evidence |
|---|---|---|---|
| 3.1 | Goal-driven agent loop | **built** | real run 2026-09-26: 3 actions, logged in, artifact emitted |
| 3.2 | Typed, versioned artifact | **built** | `capability.py` + 35 tests; two authored artifacts, both hand-written |
| 3.3 | Deterministic replay | **partial** | `locate_control` exact (drift 0,0); no step executor, no control-map store |
| 3.4 | Safety guardrails | **partial** | single action chokepoint + 8 tests; no per-step risk classing |
| 3.5 | Evidence | **built** | wired: trace.jsonl + a frame per step, from a real run |
| 3.6 | Escalation & handoff | **not built** | triggers exist (`unresolved`, `ambiguous`); no routing |
| 3.7 | Heterogeneity & multi-tenant | **designed** | seam built and argued; limits measured |

---

## 2. The central finding

**Vision models read a screen accurately and locate it badly.**

⚠️ **Qualified 2026-09-26, and the qualification is load-bearing.** "Read
accurately" holds for **labelled controls** — the measurement below, five
well-spaced labels on a login screen, named verbatim on every run. It does
**not** hold for dense numeric data: on the Accounts Overview the model read
**6 of 11** account numbers correctly, inventing `13001` for `13011`, `13323`
for `13233` and `54221` for `54321`, each at full confidence. See
[issue 0008](issues/0008-dense-numeric-text-is-misread.md). The original claim
was true of what it measured and was generalised one step too far.

Asked to map ParaBank's login screen, every model named every control correctly
— labels verbatim, roles right, nothing hallucinated on the happy path. Asked
where those controls *are*, all three failed, scored against DOM ground truth:

| Model | Mean error | Landed inside the control | Latency |
|---|---|---|---|
| gpt-4o | 143px | 0/5 | 13s |
| gpt-4.1 | 160px | 1/5 | 16s |
| gpt-5.2-chat | 155px | 0/5 | 34s |

The inputs are 15–22px tall, so a 45–80px vertical error is **3–5 control
heights** — not "near the field", a different field. Everything was reported at
0.98 confidence, so the failure was silent. The newest, slowest, most expensive
model scored worst.

The error is also **asymmetric**: gpt-5.2 placed x within 10px and y 45–81px
out. Horizontal was nearly free; vertical was broken. That points at a
structural property of how a tall image is encoded, not a capability gap.

**Consequence:** model tier is not a lever. Changing *what you ask for* is.

⚠️ **And a second qualification, 2026-09-26, which cuts the other way.** The
grounding work below measured **3/3** on a login screen with five well-spaced
controls, and that stands. On a table of eleven rows 28px apart inside an 80px
coarse grid it is **1/4**, and — unlike every failure recorded here — it is
**silent**: the control reports `ready`, the landmark is genuine and unique, and
it sits around the wrong row. See
[issue 0009](issues/0009-wrong-row-grounding-is-silent.md). Control density, not
model tier, is the variable neither measurement controlled for.

### What fixed it

Stop asking for coordinates. Code places numbered dots at known points; the
model picks a number; code maps number → pixel. Regression becomes
classification and the arithmetic error becomes zero.

| Approach | Clicks landing inside the control |
|---|---|
| Raw coordinate estimation | **1/10** |
| Grid + dots, first implementation | 2/3 |
| Grid + dots + resolution rules | **3/3**, stable over 3 runs |

### The two resolution rules

Both measured, both counter-intuitive, and the second only appeared because the
first was implemented and observed:

**Too coarse → do not trust a `click`.** At round 1 dots are 30px apart and the
field is 18px, so *zero* dots can be inside it. A click there is not a wrong
answer by the model — it is an answer we should not have asked for. Its chosen
dot still says which cell, so we zoom.

**Fine enough → do not honour a `zoom`.** At round 2 (11px spacing, 16 dots
inside the field) the model asked to zoom while pointing at y=369, which *was*
inside. Obeying it meant round 3 on a 33×33px fragment where it could no longer
tell what it was looking at and returned `unresolved`. Magnifying past
recognition destroys the context the answer depends on.

One principle, twice: **code owns the resolution decision; the model only points.**

---

## 3. §3.2 — what an artifact may and may not store

Now built: `src/interfaceai/capability.py`, and
[ADR 0005](adr/0005-capability-artifact-shape.md) records the four constraints
that ended up in the type system rather than in a convention. The measurements
below are what put them there.

⚠️ The two committed artifacts in `artifacts/` are **hand-authored**. Discovery
does not exist, so they are the shape it must emit, not evidence that it can.

Three storage schemes were tried. Two were measured failing.

| Stored | Result |
|---|---|
| Raw `(x, y)` | invalid the moment anything reflows |
| Fractional bbox of the screenshot | **1/10** clicks inside — the measurement above |
| **Context patch + click offset** | **3/3**, replay drift `(0, 0)` |

The working scheme records a *picture of the neighbourhood* plus one number:

```
discovery:  click_offset = click_point − patch_origin
replay:     click_point  = matched_origin + click_offset
```

### The patch is not the control

Measured on the login screen, same matcher:

| Cropped | Size | std | Positions ≥0.95 |
|---|---|---|---|
| the control's exact bbox | 146×18 | 74.8 | **3** — matches Username *and* Password |
| a patch inside the empty field | 40×12 | **0.0** | **1,103,249** |
| the context patch | 240×96 | 39.6 | **1** ✓ |

An empty field has no identity; the label above it does. So the patch reaches
*beyond* the control deliberately. A flat crop is not merely weak — normalised
correlation of a zero-variance patch scores a perfect **1.0 everywhere**, so
rejecting constant templates is a correctness guard, not hygiene.

### Control identity must be content-derived

The same screenshot inventoried **15, 24 and 22** controls on three consecutive
runs. Positional ids (`c001`) are unique within a run and meaningless across
them — `c007` was a different control each time. Ids are now slugs from label +
role (`username_textbox`, `log_in_button`), with suffixes for genuine duplicates.

---

## 4. §3.3 — replay, and the error taxonomy

Replay is exact: locators recorded once, re-found on a fresh page load at score
**1.0000**, drift **(0, 0)**, fields filled correctly. No model, no network.

Four outcomes, each a deliberate refusal to guess:

| Status | Meaning |
|---|---|
| `matched` | one unique candidate above threshold |
| `not_found` | best score below threshold |
| `ambiguous` | a second candidate within the margin — **never silently pick one** |
| `incompatible` | wrong viewport, corrupt artifact, or a constant template |

`ambiguous` is not theoretical: the accounts overview has 11 near-identical rows.

### The taxonomy the brief demands, grounded in the target

ParaBank's own admin page supplies both classes from one lever
(`db.htm action=CLEAN`, which is **not** a wipe — it loads a minimal dataset):

| | Observed |
|---|---|
| **Business outcome** | account 54321 stops existing → `Could not find account #54321`. A result, not a crash. |
| **Violated checkpoint** | account 13344 still resolves — as `CHECKING $5,022.93` instead of `SAVINGS $1,231.10`. A *different record under the same id*. |

The second shapes the design: a checkpoint asserting "did I find account 13344"
passes here and hands a bank the wrong number. **Checkpoints must assert values,
not lookups.**

Two traps the target sets, both hit:

- **Readiness ≠ liveness.** ParaBank serves HTTP 200 with no database schema
  behind it, and the container healthcheck stays green throughout.
- **Not-found is HTTP 200 + plain text**, not 404. Status codes do not detect it.

---

## 5. §3.4 — safety

`use_control` is the only function that touches the application, which makes it
the only place the checks can live — and the only place worth testing them.
Eight tests, each asserting nothing reached the app after a refusal:

- action outside the policy
- a forbidden value (john's seeded SSN) — never typed
- a step marked `risky` without `confirmed`
- a point outside the viewport (a stale coordinate must not become an arbitrary click)
- `enter_text` with no value

**Risk is a property of the control, not the action kind.** Clicking "Log In" is
safe; clicking "Transfer" moves money; both are `CLICK`. So `use_control`
enforces that something upstream decided, and never guesses.

The audit record carries `value_length`, never the value — a run log containing
a typed password is a finding, not a log.

Target weakness worth naming: **`admin.htm` requires no authentication**. Normal
in a demo app, catastrophic in a real one.

---

## 6. §3.7 — heterogeneity and multi-tenant

**The seam.** `Surface` is a protocol: screenshot, click, type, scroll. A
desktop backend implements it and nothing above changes. The recorded flow sits
above the seam; only the driver is surface-specific. `use_control` is
surface-independent — "what is permitted" is a property of the bank, "how to
click" a property of the surface.

**The honest limit.** Template matching is the *least* portable locator there
is. A tenant that rebrands the CSS changes the pixels, and the patch stops
matching. This design buys within-tenant precision at the cost of cross-tenant
portability.

That is a real trade, not a bug to hide. What it does give:

- a clean failure (`not_found`) rather than a confident wrong click
- a per-tenant store keyed by `(app, tenant, screen)`, so a miss is a lookup miss
- **the artifact schema and replay engine stay tenant-agnostic; only the locator payload is tenant-specific**

Discovery therefore re-runs per tenant. `parasoft/parabank:baseline` and
`:feature` are genuinely different images, so this is testable rather than
asserted — not yet measured.

---

## 7. Measurements index

| What | Value |
|---|---|
| Grounding, raw coordinates | 1/10 inside |
| Grounding, grid + dots + rules | **3/3**, three consecutive runs |
| Replay drift | **(0, 0)**, score 1.0000 |
| Discovery cost | 23–38s, ~20–25 model calls per screen, concurrency 8 |
| Coarse inventory stability | **15 / 24 / 22** controls, identical screenshot |
| Unresolved rate | 5–25%, varies with inventory |
| Constant template false match | 1.0 at **1,103,249** positions |
| Control bbox as template | 3 matches (ambiguous) |
| Context patch as template | 1 match (unique) |
| ParaBank cold start | ~15s to healthy, plus an explicit seed |
| ParaBank screens | 29 (9 public, 10 authenticated, 10 POST-only) |
| Account numbers read correctly | **6/11** on the overview table (issue 0008) |
| Account links grounded on their OWN row | **1/4** of those marked `ready` (issue 0009) |
| Discovery run, cold (maps unbuilt) | 2 screens mapped, ~100 calls |
| Discovery run, warm (maps cached) | 3 actions, **4 calls, 15s** |
| Landmark score as a form fills | 0.99999 -> 0.9839 -> **0.8365** (below threshold) |

---

## 8. Things that cost time, recorded so they cost it once

1. **`docker compose down` ignores profiled services** — leaves an orphan holding
   the network.
2. **ParaBank boots with no schema and serves 200 anyway.** Seed explicitly.
3. **A crawler clicks its own Log Out link** and silently continues unauthenticated.
4. **`CropBox` validates `ge=0` at construction**, so clipping had to happen on
   plain ints — building the box first crashed on any control near the top edge.
5. **Sync Playwright runs its own event loop**, so `asyncio.run()` cannot nest
   inside it. Capture and discovery must be separate phases.
6. **Azure strict mode requires every property in `required`** and `$ref` nodes
   stripped of siblings; Pydantic emits neither. (Solved by reusing nobsmed-v2's
   `_enforce_strict_schema`.)
7. **A key in `.secret` never reaches the SDK** — pydantic-settings loads it into
   `Settings`, the client reads `os.environ`.
8. **gpt-4o rejects `max_tokens > 4096`** on that deployment.
9. **The compose healthcheck shelled out to `curl || wget`, and the amd64 image
   has NEITHER.** Every probe exited 127, the container sat `unhealthy`
   indefinitely while serving 200s, and `docker compose up -d --wait` — the
   documented first command — could never return. `CLAUDE.md` recorded "the
   image ships `/usr/bin/curl`" under *Verified against a running container*;
   that reading was taken on arm64, and `parasoft/parabank` is multi-arch with
   different package sets. Replaced with a `bash` `/dev/tcp` probe that asks for
   the webapp path, so it still fails while Tomcat is listening but has not
   deployed the war. **A verification is scoped to the machine it ran on**, and
   nothing in the note said which one that was.

---

## 9. Open, in priority order

See [issues/](issues/README.md).

1. **Coarse inventory instability** (15/24/22) — currently blocks end-to-end login.
   The vocabulary that is one third of the fix now exists
   (`vocabulary.py`) and is **not in the prompt yet**, so the number has not moved.
2. **No control-map store** — a step names `(screen, control_id)` and nothing
   turns that into a `VisualLocator`. The executor's missing prerequisite.
3. **No agent loop** — §3.1.
4. **No step executor / `CapabilityResult`** — §3.3's result contract.
5. **A parameterised control has no stable name** —
   [issue 0007](issues/0007-parameterised-row-selection.md). One step of
   capability 1 is expressed and unimplemented.
6. **Patch contamination** — mechanically addressed, *unverified*: the last run
   never grounded the button, so there is no evidence either way.
7. **No escalation path** — §3.6.
8. **`REPORT.md` is a skeleton**, `/evidence/` holds screenshots only.
