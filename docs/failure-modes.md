# Failure modes: what we have actually observed

Every row below has a test that reproduces it —
[`tests/test_failure_modes.py`](../tests/test_failure_modes.py), 13 tests,
offline in half a second. **A mode with no test does not go in this table**,
which is what stops it becoming a list of things we imagine could happen.

The result contract these shape is [`src/interfaceai/outcomes.py`](../src/interfaceai/outcomes.py).

## Reproducible without a model, a network or a container

The inputs are committed: the frames from the 2026-09-26 discovery run, the
control maps it wrote, and one fixture captured from the CLEAN database.

| what breaks | observed | reproduced from | result |
|---|---|---|---|
| landmark swallows a field that gets typed into | **0.8365**, killed a run mid-login | that run's before/after frames | `Failed` |
| header anchor spans auto-sizing columns | **not_found** after 11 rows → 1 | `tests/fixtures/overview-clean-1-row.png` | `Failed` |
| checkpoint violated — same id, different record | read `5022.93`, recorded `1231.10` | `env break`, live | `Failed` |
| panel has no measurable row rhythm | 1-row table | blank key column | `Failed` (drilldown only) |
| acting on a control discovery never grounded | `13344_link` is `unresolved` | the committed control map | `NeedsOperator` |
| a forbidden value | john's SSN | `ActionPolicy` | `NeedsOperator` |
| an action outside the allowlist | `enter_text` when only `click` is allowed | `ActionPolicy` | `NeedsOperator` |
| typing into a link | role → action table | the committed control map | `NeedsOperator` |
| clicking a table panel | no action is legal on a panel | role → action table | `NeedsOperator` |
| an irreversible step over the tenant's money threshold | `amount=1500` vs a 1000 threshold | `request_loan`, live | `NeedsOperator` |
| a capability this tenant does not permit | `request_loan` on tenant `feature` | the allowlist | `Failed` at pre-flight |
| a permitted capability **invoking** a forbidden one | permit `request_loan`, forbid `log_in` | the allowlist, at every invoke | `Failed` |
| a session lost mid-capability | `session_loss_probe` | re-invoke what declared it, once | **`Success` with `recovered`** |

## Needs the live app

| what breaks | lever |
|---|---|
| checkpoint violated | `uv run interfaceai env break` → `pytest -m live` |
| record not found | `env break`, then look up account **54321** |

## ⛔ Named by the brief, NO observed instance

Listed so the gap is visible instead of quietly filled with a mock.

| condition | why we have none |
|---|---|
| ~~**recoverable**~~ | **Produced 2026-09-28.** A session lost mid-capability is re-established by re-invoking whatever declared it, once, and the run completes. ⚠️ Still **no `Recoverable` result variant**, and the reason sharpened by building one: a recovered condition is not a terminal state — if recovery works the run ends `Success`, if not it ends `NeedsOperator`. `Success.recovered` names what was survived |
| **permission denial** | ParaBank has no roles, so we still have **no instance**. ⚠️ We now DO have a per-tenant capability allowlist — and it produces exactly what was predicted here: more of the §3.4 guardrail and none of the §3.3 denial. It is labelled make-believe in `.env`, in `settings.py` and in its tests, because a fiction that forgets it is one is worse than no fiction |
| **unexpected dialog** | ParaBank raises none. The seam is `page.on("dialog")` on the surface; cut rather than mocked |
| ~~**session timeout**~~ | **done** — `session_loss_probe` logs out mid-capability. Logged-out `overview.htm` serves HTTP 200 with the same heading and an empty table, so neither a status code nor a checkpoint catches it |
| **slow / failed load** | plausibly reachable via `jms.htm` queue shutdown — **unverified**, nothing has ever POSTed to it |

## ⚠️ `ambiguous` is ours, and it has never fired

It appears **nowhere in the assignment**. It exists because we chose template
matching, and refusing two near-equal candidates is right for an account list.

`findings.md` §3 is cited as its instance — a control's own bbox "matches
Username *and* Password, 3 positions". That measurement is real, but it counts
**positions scoring ≥ 0.95**, which is not the ambiguity margin (a runner-up
within 0.05 of the best). Fed the real username bbox from the DOM oracle,
`locate_control` returns `matched`.

So it is implemented, defensible, and has **zero observed instances** — the same
standing as `Recoverable`, and recorded rather than dressed up with a synthetic
fixture.

## The three levers, for anyone adding a mode

```bash
uv run interfaceai env reset     # full fixtures: 11 accounts, 13344 SAVINGS $1,231.10
uv run interfaceai env break     # minimal:       1 account,  13344 CHECKING $5,022.93
                                 #                54321 gone -> "Could not find account #54321"
```

Plus the committed frames under `evidence/runs/` and the control maps under
`control_maps/`, which make most of the table above reproducible with no
container at all.
