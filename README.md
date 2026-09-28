# Computer-Use Automation

An LLM drives a legacy bank UI once to work out how a task is done, that run is
recorded as a typed capability artifact, and the artifact is then replayed
deterministically with no model in the decision loop.

- **Start here** — [`HANDOFF.md`](HANDOFF.md): scope, what is proven, what is next
- **What is still open**, with a decision line per item — [`STILL-OPEN.md`](STILL-OPEN.md)
- Assignment brief — [`Assignment-A-Computer-Use-Automation.md`](Assignment-A-Computer-Use-Automation.md)
- Design write-up — [`REPORT.md`](REPORT.md)
- Target application notes — [`docs/parabank.md`](docs/parabank.md)
- Screen map (29 screens + graph) — [`docs/parabank-screens.md`](docs/parabank-screens.md)
- **Findings, mapped to the assignment** — [`docs/findings.md`](docs/findings.md)
- **Failure modes we have observed**, each with a test — [`docs/failure-modes.md`](docs/failure-modes.md)
- Capabilities and the vocabulary they imply — [`docs/capabilities-and-vocabulary.md`](docs/capabilities-and-vocabulary.md)
- Open issues — [`docs/issues/`](docs/issues/README.md)
- Decision records — [`docs/adr/`](docs/adr/README.md)

## Status

The end-to-end thread runs: discovery, a typed artifact, and deterministic
replay with a typed outcome. Human handoff is the main gap.

| Piece | State |
|---|---|
| ParaBank target, both tenant variants | done |
| Seed fixtures, verified against the live app | done |
| Known-state / error-injection controls | done, round-trip verified |
| Perception — `extract_control_locators`, `locate_control`, `use_control` | done; grounding 3/3, replay drift (0,0) |
| **Capability artifact (§3.2)** — schema, validator, `draft → approved` gate | done; [ADR 0005](docs/adr/0005-capability-artifact-shape.md) |
| **Discovery (§3.1)** — goal-driven LLM loop against the live app | done; real run, evidence committed |
| **Deterministic replay (§3.3)** — typed outcome, no model deciding | done; success and escalation both demonstrated |
| Controlled vocabulary, 34 terms | done in code; **not yet in the inventory prompt** |
| Escalation handoff (§3.6) — `page.pause()`, ownership, resume | detection works; **handoff not built** |
| Persistence of runs / interventions | not started |

The two artifacts in `artifacts/` are **hand-authored**: discovery does not
exist yet, so they are the shape it has to emit rather than evidence that it
can. `HANDOFF.md` is the honest ledger of what is measured.

Setting up a fresh machine: [`docs/vm-setup.md`](docs/vm-setup.md)

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

First run pulls `parasoft/parabank:baseline` (~250 MB; multi-arch, native on
both amd64 and arm64). After that a cold start is about 15 seconds.

⚠️ The arches do not ship the same packages — the amd64 image has neither
`curl` nor `wget`, which is why the compose healthcheck probes over `bash`'s
`/dev/tcp` instead of shelling out to an HTTP client.

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

uv run interfaceai capability list       # signatures and approval state
uv run interfaceai capability show read_savings_balance
uv run interfaceai capability validate   # check every artifact against the vocabulary
uv run interfaceai capability export     # (re)write artifacts/*.draft.json
uv run interfaceai capability approve read_savings_balance --by "your name"

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

The full thread — goal, a real LLM run, a typed artifact, deterministic replay,
and a typed outcome:

```bash
docker compose up -d --wait && uv run interfaceai env reset

# 1. DISCOVERY -- an LLM drives the live UI and records what worked
uv run interfaceai discover \
  --goal "Log in to the bank as the seeded customer and reach the accounts overview." \
  --name log_in_discovered \
  --secret parabank_username=username --secret parabank_demo_password=password

# 2. REVIEW -- a human promotes the draft. Replay refuses anything unapproved.
uv run interfaceai capability check
uv run interfaceai capability approve log_in_discovered --by "your name"

# 3. REPLAY -- no model decides anything
uv run interfaceai replay artifacts/log_in_discovered.v1.approved.json
#    SUCCESS log_in_discovered in 5 steps
#      account_id = 12345

# 4. THE ERROR PATH -- same artifact, same command, different app state
uv run interfaceai env break
uv run interfaceai replay artifacts/log_in_discovered.v1.approved.json
#    NEEDS A HUMAN at step 4: cannot read 12345_link: not_found (0.8582)
#      completed: enter username_textbox, enter password_textbox, click log_in_button, observe
uv run interfaceai env reset
```

Step 4 is the one worth watching. Nothing was mocked — `env break` posts
`action=CLEAN` to ParaBank's own admin page, account 12345 stops existing, and
replay refuses to click something scoring 0.86 rather than guessing. It exits 1
and carries what it had already completed, so a human can resume.

Every failure mode we have observed, with the fixture or lever that reproduces
it: [`docs/failure-modes.md`](docs/failure-modes.md).

## Layout

```
docker-compose.yml     ParaBank, both tenants
REPORT.md              design write-up (brief deliverable)
docs/parabank.md       everything learned about the target
docs/adr/              decision records
src/interfaceai/
  settings.py          config from .env + .secret
  parabank.py          surface facts, seed fixtures, known-state controls
  surface.py           the perception/action seam; `use_control`
  screenshot2controls.py   `extract_control_locators`, `locate_control`
  vocabulary.py        the 34-term controlled vocabulary
  capability.py        the capability artifact: schema, validator, approval gate
  capabilities.py      the authored capabilities and the registry
  cli.py               `interfaceai` CLI
tests/                 offline fixture tests + live smoke tests
evidence/              discovery and replay run evidence (brief deliverable)
artifacts/             saved capability artifacts (brief deliverable)
```

## Config

`.env` is committed and holds URLs and flags. `.secret` is gitignored and holds
credentials; `.secret.example` shows the shape. Nothing that would fail a bank's
security review belongs in `.env`.
