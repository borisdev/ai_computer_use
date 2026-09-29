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
- **What exists right now** (generated) — [`docs/status.md`](docs/status.md)
- **The two engine flows**, discovery and replay — [`docs/flows.md`](docs/flows.md)
- Capabilities and the vocabulary they imply — [`docs/capabilities-and-vocabulary.md`](docs/capabilities-and-vocabulary.md)
- Open issues — [`docs/issues/`](docs/issues/README.md)
- Decision records — [`docs/adr/`](docs/adr/README.md)

## Status

Everything the brief asks for runs: a real LLM discovery run, a typed
artifact, deterministic replay with typed outcomes, human handoff of the live
session, and one artifact serving two tenants.

```
247 tests — 216 offline, 31 live · ruff clean
```

| Piece | State |
|---|---|
| ParaBank target, both tenant variants | done |
| Seed fixtures, verified against the live app | done |
| Known-state / error-injection controls | done, round-trip verified |
| Perception — `extract_control_locators`, `locate_control`, `use_control` | done; grounding 3/3, replay drift (0,0) |
| **Capability artifact (§3.2)** — schema, validator, `draft → approved` gate | done; [ADR 0005](docs/adr/0005-capability-artifact-shape.md) |
| **Discovery (§3.1)** — goal-driven LLM loop against the live app | done; real run, evidence committed |
| **Deterministic replay (§3.3)** — typed outcome, no model deciding | done; success, business outcome and escalation all demonstrated |
| **Composition** — a capability invokes another, version pinned | done |
| **Escalation & handoff (§3.6)** — live session, ownership, verified resume | done; the handoff window is bracketed by before/after evidence |
| **Cross-tenant reuse (§3.7)** — one artifact, two tenants | done; adoption verifies and refuses on drift |
| **Recovery** — a lost session is re-established, once | done; `session_loss_probe` logs itself out and the run survives |
| **Value-dependent risk** — a payment over the tenant's threshold stops | done; and the tenant policy outranks `--confirm-risky` |
| **Tenant permissions** — which capabilities a tenant may run | done, and **make-believe**: ParaBank has no roles |
| **Generated docs** — `interfaceai status`, `interfaceai diagram` | done; [docs/status.md](docs/status.md), [docs/flows.md](docs/flows.md) |
| Controlled vocabulary, 34 terms | done in code; **not yet in the inventory prompt** |
| Persistence of runs / interventions | cut — see REPORT §7 |

Artifacts in `artifacts/` come from **both** routes, and which is which
matters: `log_in_discovered` and `read_savings_balance` were produced by a real
discovery run against the live app; the earliest `log_in` was hand-authored
before discovery existed. The contrast is measured and unflattering to the hand
— the hand-written ones carry **3 and 8** faults against a real control map,
the discovered one carries **0**, because a hand-written artifact can name
anything and a discovered one can only name what it recorded. `interfaceai
capability check` is that check, and `interfaceai status` prints the counts.

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

```bash
docker compose up -d --wait && uv run interfaceai env reset
```

### The headline: the assignment's own worked example

> *"look up member 12345 and read their current savings balance"*

```bash
uv run interfaceai replay artifacts/read_savings_balance.v3.approved.json \
  --param account_id=13344
```
```
SUCCESS read_savings_balance in 12 steps
  found_account_id = 13344
  balance = $1231.10
  account_type = SAVINGS
```

Four things are happening in that one command:

| | |
|---|---|
| **Composition** | step 0 is `invoke log_in v2` — written once, called by anything needing a session. The version is pinned, so a newer `log_in` cannot silently change what replays. Three of the twelve steps are its |
| **A typed parameter** | `--param account_id=…` — try `13122` ($1100.00) or `12345` (**-$2300.00**, negative on purpose) |
| **No model decides** | step order, controls, values and checkpoints all come from the artifact. One call reads the accounts table; the row is then selected **in code** |
| **Panel extraction** | the table is a `TABLE_CONTROL_PANEL`: anchor its header, crop it, one model call against a response schema, get typed rows |
| **A checkpoint with teeth** | `account_type = SAVINGS` is returned *and* checked. Proving the row says SAVINGS is the difference between reading the right record and reading a record |

### A business outcome is an answer, not a crash

```bash
uv run interfaceai replay artifacts/read_savings_balance.v3.approved.json \
  --param account_id=99999        # in no seed row
```
```
record_not_found no row where account_id is '99999'; the table holds 11
```

**Exit 0.** The caller asked a fair question and got a real answer. Conflating
this with a failure is the mistake the brief's glossary names by name.

### The error path, produced by the application itself

```bash
uv run interfaceai env break     # posts action=CLEAN to ParaBank's own admin page
uv run interfaceai replay artifacts/log_in_discovered.v1.approved.json
```
```
NEEDS A HUMAN at step 4: cannot read 12345_link: not_found
                        (best score 0.8654 is below threshold 0.95)
  completed: enter username_textbox, enter password_textbox,
             click log_in_button, observe
```

**Exit 1.** It refuses to click something scoring 0.86, and carries what it
finished so a human can resume rather than restart. Add `--operator` to take
the live session at that point. Then `uv run interfaceai env reset`.

### Where the artifacts come from — a real LLM run

```bash
uv run interfaceai discover \
  --goal "Log in to the bank as the seeded customer and reach the accounts overview." \
  --name log_in_discovered \
  --secret parabank_username=username --secret parabank_demo_password=password

uv run interfaceai capability check      # does every control it names exist?
uv run interfaceai status                # capabilities, runs and outcomes at a glance
uv run interfaceai diagram read_savings_balance    # its flowchart, read from the artifact
uv run interfaceai capability approve log_in_discovered --by "your name"
```

Replay refuses anything unapproved. Evidence for both phases lands in
`evidence/runs/`, and **six curated runs are committed** — discovery, success,
business outcome, escalation, recovery, and a safety refusal — indexed with
what each one shows in [`evidence/README.md`](evidence/README.md).

### A payment large enough to need a person

```bash
uv run interfaceai replay artifacts/request_loan.v1.approved.json \
  --param amount=500 --param down_payment=100 --confirm-risky
```
```
SUCCESS request_loan in 10 steps
```
```bash
uv run interfaceai replay artifacts/request_loan.v1.approved.json \
  --param amount=25000 --param down_payment=5000 --confirm-risky
```
```
NEEDS A HUMAN at step 5: this step is irreversible and amount=25000,
  down_payment=5000 is at or above the 1000 threshold for this tenant;
  a person has to confirm it
```

Same artifact, same flag, different **value**. `--confirm-risky` is the caller
saying *this run may do irreversible things*; it cannot answer *this bank
requires a person above $1,000*, because that question was never addressed to
the caller. Drop the flag and both stop — but for different, distinguishable
reasons.

### A session that dies mid-flow

```bash
uv run interfaceai replay artifacts/session_loss_probe.v1.approved.json \
  --param account_id=13344
```
```
SUCCESS session_loss_probe in 8 steps
  found_account_id = 13344
  recovered accounts_overview_link gone -- log_in no longer holds
```

The capability logs itself out halfway through. `log_in` declares what it
`establishes`, so the engine knows which capability puts it back — and
re-invokes exactly that one, **once**. The run is a `SUCCESS` that says what it
survived: a recovered condition is not a terminal state, which is why there is
no `Recoverable` variant.

### One artifact, two institutions

```bash
docker compose --profile tenant-b up -d --wait && uv run interfaceai env reset --tenant-b
uv run interfaceai maps adopt index    --from baseline --to feature
uv run interfaceai maps adopt overview --from baseline --to feature --login
uv run interfaceai replay artifacts/log_in_discovered.v1.approved.json --tenant feature
```

`maps adopt` re-runs every locator against the target tenant's live screen and
**writes nothing if any drifted** — that check is the drift detector, not a
copy.

Every failure mode we have observed, with the fixture or lever that reproduces
it: [`docs/failure-modes.md`](docs/failure-modes.md). What is still open:
[`STILL-OPEN.md`](STILL-OPEN.md).

## Grading this submission against the client's own rubric

```bash
uv run python3 evals/grade.py                                  # 3 graders x 2 draws
uv run python3 evals/grade.py --critique-rubric gpt-5.2-codex  # audit the RUBRIC
```

[`evals/rubric.yaml`](evals/rubric.yaml) quotes §6 and §7 verbatim; results
land in [`evals/results/`](evals/results/). Mechanical checks (seven headings,
demo commands resolve, evidence present) run in code — asking a model whether a
heading exists is a worse grep. Judged criteria go to three graders, two draws
each, and every score must cite a quote from the submission and name the
strongest argument that it is too high.

⚠️ **An LLM grading work an LLM wrote.** The bias is not removed, only made
inspectable. It found four real defects the author missed — see
[what-went-wrong.md](docs/what-went-wrong.md) — and `--critique-rubric` exists
because a rubric written by the graded party is the weakest link in it.

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
