# Computer-Use Automation

Take-home build. The brief is `Assignment-A-Computer-Use-Automation.md` — read it
before making design decisions; it is explicit that under-specification is
deliberate and the judgment calls are what's being assessed.

Monolith, not a monorepo: one package at `src/interfaceai/`.

**Read [`HANDOFF.md`](HANDOFF.md) first.** It carries the settled scope
boundary, what is measured versus assumed, the current blocker, and the
decisions not to relitigate.

## Essential commands

- **python3** (not python) on this macOS system
- **uv** (not pip) — `uv add`, `uv sync`, `uv run`
- CLI: `uv run interfaceai <subcommand>`
- No Makefile, by decision — `docs/adr/0003-plain-docker-compose.md`

```bash
docker compose up -d --wait   # liveness only
uv run interfaceai env reset          # readiness: seed + verify. Both are needed.
```

## Tests

```bash
uv run pytest -m "not live"   # offline; no container needed
uv run pytest -m live         # live; needs the stack up and seeded
uv run ruff check . && uv run ruff format --check .
```

Live tests are marked `live` and deselected from the offline run. A live test
that skips when the container is down is fine; one that passes when the
container is down is not — it would be asserting nothing.

## Project map

- `src/interfaceai/settings.py` — config, loaded from `.env` + `.secret`
- `src/interfaceai/parabank.py` — everything about the target surface: seed fixtures,
  known-state controls, liveness
- `src/interfaceai/vocabulary.py` — the 34-term controlled vocabulary, versioned.
  Read by the artifact validator; **not yet in the inventory prompt**
- `src/interfaceai/capability.py` — **the capability artifact (§3.2)**: schema,
  validator, `draft → approved` gate. Shape decisions in `docs/adr/0005-*`
- `src/interfaceai/capabilities.py` — the authored capabilities and the registry.
  Hand-written, because discovery does not exist yet
- `src/interfaceai/cli.py` — `interfaceai` CLI: `env` and `capability` subcommands
- `docker-compose.yml` — ParaBank, both tenant variants
- `docs/findings.md` — **every measurement, mapped to the assignment sections.**
  Read before re-deriving anything; it records what was measured and what was
  only inferred.
- `docs/issues/` — open problems with their evidence
- `docs/capabilities-and-vocabulary.md` — the five capabilities the system must
  perform, and the 34-term straw-man vocabulary derived backwards from them
- `docs/parabank-screens.md` — the 29 screens, the navigation graph, and the
  hazards for an exploring agent (logout poisoning, POST-only screens)
- `docs/parabank.md` — **everything learned about the target.** Read this before
  touching anything that talks to ParaBank; it will save you the discoveries
  listed under Verified below.
- `docs/adr/` — decision records. Add one for any decision a reviewer would
  otherwise have to reverse-engineer.
- `REPORT.md` — the brief's design write-up deliverable, seven mandated headings
- `evidence/`, `artifacts/` — graded deliverables, see brief §6

Not written yet: the agent loop, the screen-map store, the replay engine, the
escalation path. `REPORT.md` exists but most sections are marked pending. Read
`HANDOFF.md` for what is actually done and measured.

## Conventions

- Secrets in `.secret` (gitignored), config in `.env` (committed)
- Local overrides in `docker-compose.override.yml` (gitignored; `.example` committed)
- Decisions go in `docs/adr/`, findings about the target go in `docs/parabank.md`
- Compose project name comes from `COMPOSE_PROJECT_NAME` in `.env`, not a
  top-level `name:` key — compose < 2.3 rejects that key

## Key decisions so far

- **ParaBank as the proxy target.** Server-rendered JSP, `.htm` form posts,
  table layout, zero test IDs. The brief asks for a surface where a clean DOM
  cannot be assumed, and a modern demo site would have made the locator problem
  artificially easy.
- **ParaBank's REST API is off limits to the automation.** It exists, and using
  it would dissolve the exercise. Tests may use it as an oracle; the agent and
  the replay engine may not.
- **Error states come from the app's own admin page**, not from a fault-injection
  proxy. `make break` posts `action=CLEAN` to `db.htm`, so both "no such
  account" and a changed-record checkpoint violation are genuine app behaviour.
- **Two tenants from two upstream image tags** (`baseline`, `feature`), which are
  genuinely different digests. Free stand-in for cross-tenant drift (brief §3.7).
- **No volumes.** The HSQLDB lives in the container, so `make down` is a factory
  reset and every replay run starts from identical state — determinism becomes
  measurable rather than assumed.
- **Playwright as the driver, screenshots and coordinates as the interface —
  NOT the DOM.** `docs/adr/0002-playwright-screenshot-control.md`. Playwright is
  the transport only. `page.locator()`, CSS selectors and XPath appearing in the
  agent or replay path are defects, not shortcuts: a DOM-based recording cannot
  replay against a desktop app, which is the whole point of the seam.
  ⚠️ Corollary: an artifact must never store raw `(x, y)`. It stores a target
  description that is re-resolved against the current screenshot at replay time.

## Verified against a running container (2026-09-22)

- Seed fixtures in `src/interfaceai/parabank.py` match the live app. The REST oracle
  returns `{"id":13344,"customerId":12212,"type":"SAVINGS","balance":1231.10}`,
  exactly what `insert.sql` says.
- The landing page has `name="username"` and **zero** `data-testid` attributes,
  which is the premise of choosing this target.
- ⛔ **Corrected 2026-09-25: the image does NOT ship `curl`, and this line cost
  the next session its start command.** Measured on **amd64**: no `curl`, no
  `wget`, so every healthcheck probe exited 127 and the container sat
  `unhealthy` indefinitely while happily serving 200s — `docker compose up -d
  --wait` could never return. The original reading was taken on **arm64**, and
  `parasoft/parabank` is multi-arch with different package sets. The check now
  uses `bash` + `/dev/tcp`, verified to exit 0 on `/parabank/index.htm` and 1 on
  a path Tomcat does not serve. `docker compose up -d --wait` returns Healthy in
  ~10s. **A verification is scoped to the machine it ran on**, and this note did
  not say which one.

- `db.htm` works and is the *only* dependable way to get a schema. `action=INIT`
  loads the full fixtures; `action=CLEAN` loads `reset.sql`, which is **not a
  wipe** — it leaves customer 12212 and account 13344 as CHECKING $5,022.93.
  Round-trip confirmed: 54321 is found after INIT, `Could not find account
  #54321` after CLEAN.

⚠️ ParaBank boots with NO SCHEMA, and serves HTTP 200 anyway. The lazy
`IndexController` init logged "Database not yet initialized. Initializing..."
every 10s for minutes and never completed, while `docker compose ps` said
`healthy` the whole time. Liveness is not readiness here. `make up` therefore
POSTs `action=INIT` after the healthcheck and blocks on `is_seeded()`. Do not
"simplify" that away.

Still unverified: `jms.htm` (loan-processor queue toggle). Nothing has POSTed
to it yet.
