# Evidence

What §6.3 asks for: *"a saved example artifact plus logs from both a discovery
run and a replay run. Ideally include one replay that hits an error or
exceptional state."*

Every run below is against the live ParaBank container and reproducible with the
commands in the [README](../README.md#demo-path). Each directory holds
`trace.jsonl` (one JSON object per event) and `frames/` (what the model was
actually shown).

| run | what it shows |
|---|---|
| [`runs/20260929T042350Z`](runs/20260929T042350Z) | **Discovery.** A real LLM drives the live app — 3 steps, 4 model calls, 24s — and emits [`artifacts/evidence_discovery.v1.draft.json`](../artifacts/evidence_discovery.v1.draft.json) |
| [`runs/20260929T071443Z`](runs/20260929T071443Z) | **Success.** `read_savings_balance(13344)` → `$1231.10`, 12 steps, 3 of them `log_in` invoked |
| [`runs/20260929T071501Z`](runs/20260929T071501Z) | **Business outcome.** `record_not_found` for account 99999 — **exit 0**, because a fair question with a negative answer is not a crash |
| [`runs/20260929T071538Z`](runs/20260929T071538Z) | **Escalation.** A $25,000 loan against a $1,000 tenant threshold stops and asks a person, *even with `--confirm-risky`* |
| [`runs/20260929T071516Z`](runs/20260929T071516Z) | **Recovery.** The session is destroyed mid-flow; `recovering` → `log_in` re-invoked → `SUCCESS`. A recovered condition is not a terminal state |
| [`runs/20260929T051949Z`](runs/20260929T051949Z) | **A full handoff.** The run blocks, a person takes the live session, navigates, and hands it back — `handoff_requested` → `human_acted` → `handoff_returned`, a frame and URL on each edge, `url_changed: true`. The operator aborts, having established the record genuinely does not exist |
| [`runs/20260929T232850Z`](runs/20260929T232850Z) | **Discovery, with a panel.** The run that emitted [`artifacts/discovered_balance.v1.draft.json`](../artifacts/discovered_balance.v1.draft.json) — it proposed the accounts table as a `TABLE_CONTROL_PANEL`, measured it (11 rows, 28px), and finished by naming a ROW and a COLUMN of it rather than a coordinate. the overview's `control_map_built` carries `panels=1, panels_ready=1` (the login screen's carries 3), which is the whole of issue #6 in one event |
| [`runs/20260929T234307Z`](runs/20260929T234307Z) | **Replaying a discovered panel.** `discovered_balance(13344)` → `$1231.10`, 6 steps, the row selected in code from one panel read |
| [`runs/20260929T234409Z`](runs/20260929T234409Z) | **The same artifact on the other tenant.** A heading template discovery chose, matching a different ParaBank build unchanged |
| [`runs/20260929T042311Z`](runs/20260929T042311Z) | **A safety refusal, at discovery time.** The model tried to `extract` into the sensitive slot `username`; the run stops rather than emitting an artifact that would leak a credential through `returns` |

## ⛔ Two older runs are also committed, and they are LOAD-BEARING

`runs/20260926T022551Z` (the first real discovery run) and
`runs/20260927T220436Z` (an early replay) are kept because **their frames are
test fixtures**. `test_table.py`, `test_failure_modes.py`,
`test_savings_balance_live.py`, `scripts/add_panels.py` and
`scripts/experiment_grid_schemes.py` all read PNGs out of them.

Deleting them as "stale evidence" breaks **24 tests** with a `FileNotFoundError`
several layers from the cause. Measured 2026-09-29, by doing exactly that.

They are also honest history — the first run is what the write-up's grounding
numbers came from — but the reason they cannot go is the fixtures.

⚠️ `runs/20260927T220436Z` ends without a terminal event, because it predates
`replay_finished`. `interfaceai status` therefore reports it as *incomplete*,
which is correct: the run genuinely did not record its verdict. It is left as
it is rather than regenerated, since it is the evidence for why that event
exists.

## Reading a trace

```bash
jq -r '"\(.event)\t\(.step // "")\t\(.why // .outcome // .capability // "")"' \
  evidence/runs/20260929T071538Z/trace.jsonl
```

Two events worth knowing:

- **`replay_finished`** is the run's own verdict. Every run writes one, so a
  reader never has to infer an outcome from where the log stopped — an
  escalation with no operator attached used to write nothing at all and read as
  a crash.
- **`handoff_requested` / `handoff_returned`** bracket the window in which a
  human, not the worker, owned the page. Each carries a frame and a URL, plus
  `url_changed`. The per-action log is complete for actions taken *through* the
  operator surface and blind to a hand on the mouse, so the bracket is the claim
  that holds either way.

⚠️ **What is redacted, precisely.** Typed INPUTS record `value_length` and
never the value. Extracted OUTPUTS are masked when the vocabulary says the slot
is `sensitive` or typed MONEY — you will see `<money redacted, 8 chars>` where a
balance was read. `account_id` is deliberately NOT masked: evidence whose job is
proving *which* record was read has to name the record.

⛔ **This was wrong until 2026-09-29, and this file said so anyway.** Extracted
outputs were written verbatim, so committed traces carried `"value":
"$1231.10"`. Found by Copilot reading the committed evidence rather than the
code — which is why `test_a_committed_TRACE_carries_no_balance_or_secret` now
reads the evidence too.

⚠️ **Frames are still written unmasked** ([#7](https://github.com/borisdev/ai_computer_use/issues/7)). On a real system
those would need a masking pass before persistence. Everything here is against
synthetic fixtures in a throwaway container.

Five of them are the outcome types in
[REPORT §3](../REPORT.md#3-determinism--error-handling); the full catalogue of
failure modes, each with the lever that reproduces it, is
[docs/failure-modes.md](../docs/failure-modes.md).
