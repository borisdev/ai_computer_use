# Design write-up

> **Status: in progress.** The target environment is built and verified; the
> agent loop, artifact schema and replay engine are not written yet. Sections
> below marked *pending* are placeholders against the brief's mandated headings,
> not claims. What is stated as done has been checked against a running system.

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

*Pending.* The shape is settled to this extent:

A single Python package (`src/interfaceai/`), monolith rather than services. The brief
is explicit that building scaling infrastructure is not rewarded and that a
small, correct, well-argued system is the goal.

The load-bearing seam is **perception and action vs. the recorded flow**. One
side knows how to capture a frame of a surface and dispatch a click or a
keystroke at it; the other side knows the ordered steps of a banking task and
what "done" looks like. Artifacts live above that line, which is what lets the
same recorded flow reach a legacy web app or a desktop app later
([ADR 0002](docs/adr/0002-playwright-screenshot-control.md)).

Two execution paths share the artifact and nothing else: **discovery** (LLM in
the loop, writes an artifact) and **replay** (no LLM, reads one).

## 2. Artifact schema

*Pending.* The constraint already fixed by
[ADR 0002](docs/adr/0002-playwright-screenshot-control.md): because targeting is
visual rather than DOM-based, an artifact cannot store a frozen `(x, y)` — the
first window resize invalidates it. It must store a *description* of the target
that is re-resolved against the current screen at replay time. That re-resolution
contract is the centre of the schema and the main thing this section will argue.

Two concrete requirements the target has already imposed:

- Any recorded URL must be canonicalised — ParaBank rewrites
  `;jsessionid=<hex>` into every link, so a raw href is unreplayable by the next
  session ([parabank.md §7](docs/parabank.md#7--jsessionid-is-rewritten-into-every-url)).
- Checkpoints must assert **values**, not lookups — see §3.

## 3. Determinism & error handling

*Pending.* The error taxonomy is already grounded in observed behaviour rather
than invented, which is the part worth recording now.

The target supplies both classes the brief insists a replay contract must
separate, from a single lever — `POST db.htm` with `action=CLEAN`
([parabank.md §5](docs/parabank.md#5-the-two-database-states)):

| | Observed |
|---|---|
| **Expected business outcome** | Account 54321 genuinely stops existing. `Could not find account #54321`. The caller needs this as a result, not a crash. |
| **Violated checkpoint** | Account 13344 still resolves — as `CHECKING $5,022.93` instead of `SAVINGS $1,231.10`. A *different record under the same id*. |

The second case is the one that shapes the design. A replay whose checkpoint is
"did I find account 13344" passes and returns $5,022.93 to a bank as a savings
balance. So a checkpoint has to assert the values it expected, and the result
contract needs a verdict that is neither success nor "not found".

Determinism is also helped by the environment: the database lives inside the
container with no volume, so `docker compose down` is a factory reset and every
run starts from an identical seed
([ADR 0003](docs/adr/0003-plain-docker-compose.md)).

Two traps this target sets, both already hit:

- **Readiness is not liveness.** ParaBank serves HTTP 200 with no database
  schema behind it, and the container healthcheck stays green throughout
  ([parabank.md §4](docs/parabank.md#4--it-boots-with-no-database-schema)).
- **Not-found is HTTP 200 plus plain text**, not a 404. Status-code checks do
  not detect it ([parabank.md §8](docs/parabank.md#8-the-surface)).

## 4. Heterogeneity & multi-tenant

*Pending.* The design argument rests on the seam in §1: perception and action is
an interface, so a desktop backend is a new implementation of it rather than a
change to the artifact schema or the replay engine.

For multi-tenant, the environment provides a real rather than mocked test case.
The `parasoft/parabank` `baseline` and `feature` tags are different images of the
same product — two institutions running the same vendor package at different
versions ([parabank.md §3](docs/parabank.md#3-image-tags-two-tenants-for-free)).
Tenant B runs on :8081 behind a compose profile.

Honest gap: the behavioural delta between the two images has not been measured
yet, only the digests. Claiming a cross-tenant reuse story before diffing them
would be asserting what has not been checked.

## 5. Escalation & handoff

*Pending.* [ADR 0002](docs/adr/0002-playwright-screenshot-control.md) picked
Playwright partly for this: a persistent browser context can be paused and
handed to a person operating the same live session, rather than a fresh one.

## 6. Safety

*Pending.* Built so far: an origin allowlist in configuration
(`INTERFACEAI_ALLOWED_ORIGINS`), and the `.env` / `.secret` split that keeps credentials
out of the committed tree. Neither is yet enforced at the action layer, which is
where it has to happen to count.

Worth naming as a limit of the target rather than the design: ParaBank's
`admin.htm` requires no authentication. Convenient here, and exactly the sort of
thing that is normal in a demo app and catastrophic in a real one.

## 7. Cuts

*Pending.* Deliberate so far:

- **The computer-use driver was left unchosen until it could be argued**, rather
  than settled by quietly adding a dependency. Now recorded as
  [ADR 0002](docs/adr/0002-playwright-screenshot-control.md).
- **No desktop surface, no multi-tenant plumbing.** The brief asks for the
  abstractions not to preclude them, not for them to be built.
- **The accessibility tree was considered and deferred**, not dismissed — it is
  the strongest rival to screenshot-based perception and slots behind the same
  seam. Reasoning in ADR 0002.
- **No Makefile.** [ADR 0003](docs/adr/0003-plain-docker-compose.md).
