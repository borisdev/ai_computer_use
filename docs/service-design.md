# `CapabilityService`, and what is actually built

Boris sketched a service — `load`, `run`, `export`, `list` — over a class
`Capability` with `replay`/`run`, plus the question of how `discover` is
modelled. This records what exists, what the CLI looks like now, and which
parts are deliberately not built.

## What exists, and it is already those verbs

Every method on the sketch has a real implementation today. What is missing is
a **name** for the group, not behaviour:

| sketched | today | caller |
|---|---|---|
| `load(name)` | `capability.resolve_artifact(root, name, version=)` → `load_capability` | `interfaceai replay -c` |
| `run(**params, tenant)` | `replay.replay(capability, inputs, store, …)` | `interfaceai replay` |
| `export()` | `capability.dump_capability` | `interfaceai capability export` |
| `list()` | `status.read_artifacts` + `status.runnable_by` | `interfaceai status` |
| `approve()` | `capability.approve` / `assert_replayable` | `interfaceai capability approve` |
| `check()` | `control_map_store.check_capability` | `interfaceai capability check` |

## ⭐ `JobRunner` is implemented. `JobQueue` is declared and nothing implements it.

`src/interfaceai/jobs.py`. This is the seam §3.7 asks for — *"the core
abstractions not to paint you into a corner"* — expressed as a **type** rather
than as a class whose methods raise.

```python
@runtime_checkable
class JobRunner(Protocol):
    def run(self, request: JobRequest) -> CapabilityResult: ...   # InProcessRunner

class JobQueue(Protocol):            # ⛔ nothing implements this
    def submit(self, request: JobRequest) -> str: ...
    def status(self, job_id: str) -> JobStatus: ...
    def result(self, job_id: str) -> CapabilityResult | None: ...
    def cancel(self, job_id: str) -> None: ...
```

**Why a Protocol and not `raise NotImplementedError`.** Both say "not built."
A Protocol says it in the type system, where nothing can call it by accident;
a raising method is a call site waiting to happen. `project.md` has the scar —
three tuning constants shipped before the code ran once, each with a confident
docstring nobody could falsify. This repo already does it the right way twice:
`Surface` is a Protocol with no `DesktopSurface`, and `Operator` is a Protocol
whose console is mocked by `TerminalOperator` being *minimal*.

**What a queue would change: almost nothing.** `submit` returns a `JobId` that
later resolves to the same `CapabilityResult` `run` returns today. That is why
`JobRequest` carries only what a **caller asked for** — capability, params,
tenant, who asked — and none of the **wiring** a deployment provides. A request
holding a control-map store or a browser could never go on a wire, which is
exactly the corner to avoid. A test asserts that split.

⚠️ **`job` is not a new word.** The original schema had it: *a job is requested
work; a run is an attempt.* That distinction was cut with the SQLite layer and
is reintroduced as the CLI's noun. `JobStatus` deliberately does **not** reuse
the outcome words — a job is `queued` or `running`; a run `Succeeds` or
`NeedsOperator`. Collapsing them is how a caller ends up branching on
"pending" as though it were an answer.

⚠️ **And the CLI goes through it**, so the Protocol has a real caller. A
declared interface nothing calls is the speculation this section warns about.

## `banking-jobs`, the same app under a domain name

```toml
interfaceai  = "interfaceai.cli:app"
banking-jobs = "interfaceai.cli:app"
```

The engine is domain-agnostic — `Surface` is a protocol, artifacts are
tenant-agnostic — but the **vocabulary is retail banking**: 21 qualifiers,
`amount`, `balance`, `ssn`. `banking-jobs` names the domain this instance
speaks; a second domain would be a second entry point over the same engine.
Both names ship, because renaming 68 committed command references to prove a
point is churn.

⚠️ **So a `CapabilityService` class would be a facade over six functions that
already have callers.** It adds a place to hang them and a single import for an
agent. It does not add behaviour, and `project.md` says an abstraction with no
second implementation is speculation with tests. **Cut until there is a second
backend** — the moment artifacts stop being files, the facade earns its keep
immediately, because that is exactly the seam that changes.

## Why `Capability` has no `.run()`

A `Capability` is a **Pydantic document**, not an actor. `run` lives in
`replay.py` and takes the capability as an argument.

That is deliberate. A `.run()` method would give the document a reference to a
browser, a control-map store, a vision client, an operator and a policy — so the
thing that gets serialised to JSON, reviewed in a PR and approved by a person
would carry live infrastructure. The handoff bundle put it plainly: **keep
Playwright objects out of serialised artifacts.**

```
Capability      what to do          a value. Serialised, versioned, approved.
replay()        how to do it        a function. Holds the surface and the policy.
```

## How `discover` is modelled

The asymmetry is the point, and it follows from the through-line — *the model
discovers, the artifact becomes a reusable capability.*

```
discover(goal, surface)   →  a DRAFT capability + a full trace
replay(capability, inputs) →  a typed outcome
```

- **Discovery takes a goal and returns an artifact.** It is cyclic — look,
  decide, act, look again — and a model decides every move.
- **Replay takes an artifact and returns an outcome.** It is a linear walk and
  nothing decides anything.

They share the action chain (`locate_control → validate_decision →
use_control`) so the path discovery proved is the path production takes, and
they share nothing else. `docs/flows.md` draws both.

⚠️ **There is no `DiscoveryService`, and there should not be one yet.**
Discovery runs once per capability, by a person, from a CLI. A service implies
callers that do not exist.

## The CLI, now

**A name is the address. A filename is storage layout.**

```bash
# the shape a caller wants -- the capability is the SUBJECT, not a flag
uv run interfaceai replay read_savings_balance --param account_id=13344
uv run interfaceai replay log_in_discovered --tenant feature
uv run interfaceai replay request_loan --version 1 --param amount=500 ...

# a whole institution in one reviewable file
uv run interfaceai replay read_savings_balance \
  --tenant-config tenant_configs/bank_b.yaml --param account_id=13344

# what a tenant may run: capabilities(app) ∩ permitted(tenant)
uv run interfaceai status --tenant feature
uv run interfaceai status --app parabank

# the low-level form still works, for an arbitrary file or a draft in a test
uv run interfaceai replay artifacts/read_savings_balance.v3.approved.json --param account_id=13344
```

`--capability` resolves the **highest approved** version, and **refuses a
draft** with the command to approve it:

```
evidence_discovery has no APPROVED artifact (drafts: [...]).
Replay refuses a draft -- `interfaceai capability approve evidence_discovery --by <you>`
```

### ⚠️ A TENANT CONFIG is a path; a CAPABILITY is a name. Opposite cases.

A capability is an address in a registry, so a filename leaks storage layout.
A **tenant config carries permissions and a money threshold**, so the command
line naming the exact file that granted them is the point — auditable in a way
`--profile bank_b` is not.

```yaml
# tenant_configs/bank_b.yaml
tenant: feature
app: parabank
base_url: http://localhost:8081/parabank
confirm_money_above: 1000
permits: [log_in, log_in_discovered, read_savings_balance]   # request_loan absent ON PURPOSE
```

It is **additive** — `.env` stays the default, so every command in the README
still works. And it fails closed: an unparseable threshold stops the run, an
empty `permits` means *nothing* rather than everything, and `--tenant` that
contradicts the file is refused rather than silently resolved.

⚠️ `Typer` has `envvar=` but **no profile framework** — AWS's `--profile` is a
convention on top of exactly that. `INTERFACEAI_TENANT_CONFIG` gives the same
ergonomics with no dependency.

### ⚠️ `--app` is not on `replay`, and that is not an oversight

An artifact already names its app in `Target.app`; passing a second one would
let a caller claim a capability is for an app it was never recorded against.
`--tenant` is different — it selects **which control map** to resolve against,
which is the one axis a caller legitimately varies. `--app` exists on `status`,
where it is a filter rather than a claim.

## What a service would need before it is worth building

1. **A second storage backend.** Files in git are the registry today, and a
   directory scan is the index (16 artifacts, 2.4 ms). The facade matters when
   that stops being true.
2. **A caller that is not the CLI.** An HTTP surface, or an agent SDK importing
   this as a library. Right now every caller is `cli.py`.
3. **Per-tenant allowlists reachable from one place.** `capabilities(app)`
   travels with the registry; `permitted(tenant)` lives in the deployment and
   never leaves it — see [`layering.md`](layering.md). A central service cannot
   answer *"what may tenant B run"* without solving that first, and pretending
   otherwise would be the over-engineering §7 warns about.
