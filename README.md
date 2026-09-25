# Computer-Use Automation

An LLM drives a legacy bank UI once to work out how a task is done, that run is
recorded as a typed capability artifact, and the artifact is then replayed
deterministically with no model in the decision loop.

- **Start here** — [`HANDOFF.md`](HANDOFF.md): scope, what is proven, what is next
- Assignment brief — [`Assignment-A-Computer-Use-Automation.md`](Assignment-A-Computer-Use-Automation.md)
- Design write-up — [`REPORT.md`](REPORT.md)
- Target application notes — [`docs/parabank.md`](docs/parabank.md)
- Screen map (29 screens + graph) — [`docs/parabank-screens.md`](docs/parabank-screens.md)
- **Findings, mapped to the assignment** — [`docs/findings.md`](docs/findings.md)
- Capabilities and the vocabulary they imply — [`docs/capabilities-and-vocabulary.md`](docs/capabilities-and-vocabulary.md)
- Open issues — [`docs/issues/`](docs/issues/README.md)
- Decision records — [`docs/adr/`](docs/adr/README.md)

## Status

Built so far: the **target environment**. The agent loop, artifact schema and
replay engine are not implemented yet.

| Piece | State |
|---|---|
| ParaBank target, both tenant variants | done |
| Seed fixtures, verified against the live app | done |
| Known-state / error-injection controls | done, round-trip verified |
| `uv` project, tests, lint | done |
| Agent loop / artifact schema / replay / escalation | not started |

## Requirements

- A Docker runtime with `docker compose` — Docker Desktop, OrbStack or Colima
- [`uv`](https://docs.astral.sh/uv/)
- Python 3.13 (uv fetches it)

## Getting started

```bash
uv sync                          # create .venv and install
cp .secret.example .secret       # then fill in ANTHROPIC_API_KEY

docker compose up -d --wait      # 1. start ParaBank, wait for Tomcat
uv run interfaceai env reset             # 2. seed the database, verify it took
```

Then open <http://localhost:8080/parabank> and log in as `john` / `demo`.

First run pulls `parasoft/parabank:baseline` (~250 MB, native arm64 on Apple
Silicon). After that a cold start is about 15 seconds.

### Why starting it is two commands

`docker compose up -d --wait` blocks on the container healthcheck, which proves
Tomcat has deployed the webapp. It does **not** prove the app works.

ParaBank boots with **no database schema** and serves HTTP 200 regardless. Its
lazy initialiser was observed logging `Database not yet initialized.
Initializing...` every 10 seconds for minutes without ever completing, while
`docker compose ps` reported `healthy` the whole time and every account lookup
failed.

So the second command is the readiness gate. `interfaceai env reset` posts
`action=INIT` to ParaBank's admin page and then blocks until account 13344 is
actually readable — it seeds *and verifies*, because a POST returning 200 is not
evidence the fixtures landed.

Full detail: [parabank.md §4](docs/parabank.md#4--it-boots-with-no-database-schema).
Why there is no `make up` wrapping this: [ADR 0003](docs/adr/0003-plain-docker-compose.md).

## Everyday commands

```bash
docker compose ps                # container state
docker compose logs -f parabank  # tail Tomcat
docker compose down              # stop; also wipes the DB (no volume)

uv run interfaceai env status            # ready / no data / down, per tenant
uv run interfaceai env reset             # reseed to the full fixtures
uv run interfaceai env break             # switch to the minimal dataset (see below)

uv run pytest -m "not live"      # offline tests
uv run pytest -m live            # live tests; needs the stack up
uv run ruff check . && uv run ruff format --check .
```

### Both tenants

```bash
docker compose --profile tenant-b up -d --wait
uv run interfaceai env reset
uv run interfaceai env reset --tenant-b
```

## The target

[ParaBank](https://github.com/parasoft/parabank) is Parasoft's demo bank: Spring
MVC + JSP on Tomcat 10, backed by an in-container HSQLDB.

It was chosen because it is legacy-shaped in the way the brief describes —
server-rendered `.htm` form posts, table layout, **zero `data-testid`
attributes**, and `;jsessionid=` rewritten into every URL. It does expose a REST
API, which the automation deliberately never uses; the premise of the exercise
is a bank app with no API worth integrating against. Tests use that API only as
an oracle, to check the automation read the right number off the screen.

Reasoning: [ADR 0001](docs/adr/0001-parabank-as-target.md).
Everything else known about it: [docs/parabank.md](docs/parabank.md).

Two services run the same vendor product at different builds:

| Service | Image tag | URL | Stands in for |
|---|---|---|---|
| `parabank` | `baseline` | <http://localhost:8080/parabank> | Tenant A, where capabilities are recorded |
| `parabank-b` | `feature` | <http://localhost:8081/parabank> | Tenant B, a drifted install of the same product |

Upstream, `baseline` and `latest` are the same digest and `feature` is a
distinct image — so tenant B is a genuinely different build, not a relabelling.
It is off by default, behind the `tenant-b` compose profile.

### Seed data

`src/interfaceai/parabank.py` holds the fixtures, read out of the app's own `insert.sql`
and confirmed against the running container. The ones that matter:

- `john` / `demo` — customer 12212, John Smith
- account **13344**, SAVINGS, **$1,231.10** — the balance a recorded lookup
  capability should return
- account **99999** — in no state, so a lookup legitimately finds nothing
- minimum balance **$100.00** — transferring below it trips ParaBank's own
  validation

Full table: [parabank.md §6](docs/parabank.md#6-seed-data-actioninit).

### Exercising error handling

Failures come from ParaBank's own admin page, so they are real app behaviour
rather than an injected stub. `uv run interfaceai env break` posts `action=CLEAN`, which
is **not** a wipe — it swaps in the app's minimal dataset:

| Account | After `env reset` | After `env break` |
|---|---|---|
| 13344 | SAVINGS $1,231.10 | **CHECKING $5,022.93** |
| 54321 | CHECKING $1,351.12 | `Could not find account #54321` |

One lever, both failure classes the replay contract has to tell apart: 54321
genuinely stopped existing (a business outcome the caller needs to hear), while
13344 still resolves as a *different record* (a violated checkpoint — a replay
that only checks "did I find it" hands a bank the wrong number).

Detail: [parabank.md §5](docs/parabank.md#5-the-two-database-states).

## Demo path

Not available yet — it needs the agent loop and replay engine. It will be:

```bash
docker compose up -d --wait && uv run interfaceai env reset
uv run interfaceai discover --goal "..." --target http://localhost:8080/parabank
uv run interfaceai replay artifacts/<capability>.json --param account_id=13344
```

## Layout

```
docker-compose.yml     ParaBank, both tenants
REPORT.md              design write-up (brief deliverable)
docs/parabank.md       everything learned about the target
docs/adr/              decision records
src/interfaceai/
  settings.py          config from .env + .secret
  parabank.py          surface facts, seed fixtures, known-state controls
  cli.py               `interfaceai` CLI
tests/                 offline fixture tests + live smoke tests
evidence/              discovery and replay run evidence (brief deliverable)
artifacts/             saved capability artifacts (brief deliverable)
```

## Config

`.env` is committed and holds URLs and flags. `.secret` is gitignored and holds
credentials; `.secret.example` shows the shape. Nothing that would fail a bank's
security review belongs in `.env`.
