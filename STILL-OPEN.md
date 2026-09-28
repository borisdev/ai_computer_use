# Still open

Everything REPORT §7 cuts or defers, in one editable page. Each item says what
it is, why it is open, what proves it, and what it would cost.

**Fill in the `Decision:` lines.** They are the only thing here I will not
change without you.

---

## A · Would make the submission stronger

### A1 · Capability 1 does not replay
**The brief's own worked example** — "look up member 12345 and read their
current savings balance".

- **Mechanism: proven.** `tests/test_savings_balance_live.py` reads **$1,231.10**
  for account 13344 — anchor the table header, crop it, one model call against
  a response schema, select the row *in code* by the parameter. Flip to
  `env break` and it correctly catches `5022.93` as a violated checkpoint.
- **Plumbing: missing.** Nothing emits a `TABLE_CONTROL_PANEL` into a control
  map, and `EXTRACT` targets one control rather than a row set.
- **Also:** the hand-authored artifact names controls no inventory can produce
  (`global_nav`, `balance_value`, `account_link`) — 8 faults from
  `interfaceai capability check`.

**Cost:** ~half a day. Closes A2 and A3 as a side effect.
**Why it matters:** it is the example the reviewer will look for by name.

> **Decision:**

---

### A2 · Extraction cannot point at data
[issue 0010](docs/issues/0010-extraction-cannot-point-at-data.md)

```
capability.py      EXTRACT requires a ControlRef
control refs come from the inventory
the coarse prompt  "Ignore static text, images and layout."
```

A balance *is* static text, so it has no id, so nothing can extract it. This is
why the model named `13344_link` (a link) as an extraction source — it was the
only nearby thing with an id.

**Fix:** a region locator. A landmark + offset gives a *point* you click; a
landmark + offset + **size** gives a *region* you read. Same matcher, same
refusals. `locate_control` already returns `matched_crop`.

**Cost:** ~2h, plus an ADR amendment (it changes the artifact schema).

> **Decision:**

---

### A3 · Grid cell assignment is broken, 3 times in 4
[issue 0009](docs/issues/0009-wrong-row-grounding-is-silent.md) — **highest
severity open**, because it is *silent*.

```
12345_link   grounded (500,361)   INSIDE its own link      ok
12456_link   grounded (500,359)   that is 12345's row      WRONG
13122_link   grounded (511,466)   that is 12789's row      WRONG
13001_link   grounded (500,386)   no such account          WRONG
```

`status: ready`, unique landmark, ~1.0 match at replay — and it clicks another
customer's account. Relabelling the grid does **not** fix it: three schemes
measured, best **3/15**.

**Fix:** stop asking a model where things are. Panel + row rhythm + arithmetic
(A1's approach) removes cell assignment from the positioning path entirely.

> **Decision:**

---

### A4 · The read/locate split is diagnosed but not applied
[issue 0008](docs/issues/0008-dense-numeric-text-is-misread.md)

Our own 192-cell overlay corrupts reading:

```
full screenshot, NO grid     11/11  11/11  11/11
full screenshot, WITH grid    8/11   8/11   9/11    invented 13000, 54221, 5678
```

The gridded run reproduced `54221` — one of the exact wrong ids from the live
discovery run. **The instrument corrupts the measurement.**

**Fix:** one coarse call becomes two — read labels from a *clean* screenshot,
assign cells from the *gridded* one. One extra call per screen.

**Cost:** ~1h. **Not done.** Discovery still reads through the overlay.

> **Decision:**

---

### A5 · The controlled vocabulary is not in the prompt
34 terms exist and type every artifact. `VOCABULARY.as_prompt_block()` is
written and **nothing calls it**, so the 15/24/22 inventory variance it was
built to fix has never been re-measured.

**Cost:** ~1h to wire, plus a measurement run.

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

1. **A1** — the named example, and it drags A2 and A3 with it
2. **A4** — one hour, fixes a defect in our own instrument
3. **C · session timeout** — one hour, converts a guessed category into a measured one
4. Everything else is defensible as-is and argued in REPORT §7

> **Your ranking:**
