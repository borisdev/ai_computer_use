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

## Needs the live app

| what breaks | lever |
|---|---|
| checkpoint violated | `uv run interfaceai env break` → `pytest -m live` |
| record not found | `env break`, then look up account **54321** |

## ⛔ Named by the brief, NO observed instance

Listed so the gap is visible instead of quietly filled with a mock.

| condition | why we have none |
|---|---|
| **recoverable** (transient load, interstitial) | nothing has ever flaked and then succeeded. `surface.wait()` is a blind sleep, not a handled condition. **No type exists** — a test asserts `outcomes.Recoverable` is absent, so adding one is a conscious act |
| **permission denial** | ParaBank has no roles. ⚠️ Our own `ActionPolicy` refusing is a *guardrail* (§3.4), a different thing from the application denying an operator (§3.3). A per-tenant ACL would produce more of the first and still none of the second |
| **unexpected dialog** | ParaBank raises none. The seam is `page.on("dialog")` on the surface; cut rather than mocked |
| **session timeout** | reachable — log out mid-flow — **not tried** |
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
