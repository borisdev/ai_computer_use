# Evidence

What §6.3 asks for: *"a saved example artifact plus logs from both a discovery
run and a replay run. Ideally include one replay that hits an error or
exceptional state."*

Seven runs, all against the live ParaBank container, all reproducible with the
commands in the [README](../README.md#demo-path). Each directory holds
`trace.jsonl` (one JSON object per event) and `frames/` (what the model was
actually shown).

| run | what it shows |
|---|---|
| [`runs/20260929T042350Z`](runs/20260929T042350Z) | **Discovery.** A real LLM drives the live app — 3 steps, 4 model calls, 24s — and emits [`artifacts/evidence_discovery.v1.draft.json`](../artifacts/evidence_discovery.v1.draft.json) |
| [`runs/20260929T042505Z`](runs/20260929T042505Z) | **Success.** `read_savings_balance(13344)` → `$1231.10`, 12 steps, 3 of them `log_in` invoked |
| [`runs/20260929T042522Z`](runs/20260929T042522Z) | **Business outcome.** `record_not_found` for account 99999 — **exit 0**, because a fair question with a negative answer is not a crash |
| [`runs/20260929T042536Z`](runs/20260929T042536Z) | **Escalation.** A $25,000 loan against a $1,000 tenant threshold stops and asks a person, *even with `--confirm-risky`* |
| [`runs/20260929T042550Z`](runs/20260929T042550Z) | **Recovery.** The session is destroyed mid-flow; `recovering` → `log_in` re-invoked → `SUCCESS`. A recovered condition is not a terminal state |
| [`runs/20260929T051949Z`](runs/20260929T051949Z) | **A full handoff.** The run blocks, a person takes the live session, navigates, and hands it back — `handoff_requested` → `human_acted` → `handoff_returned`, a frame and URL on each edge, `url_changed: true`. The operator aborts, having established the record genuinely does not exist |
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
  evidence/runs/20260929T042536Z/trace.jsonl
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

⚠️ **Frames are written unmasked.** Redaction covers logs and artifacts —
`value_length`, never the value — and **not** screenshots. On a real system
those would need a masking pass before persistence. Everything here is against
synthetic fixtures in a throwaway container.

Five of them are the outcome types in
[REPORT §3](../REPORT.md#3-determinism--error-handling); the full catalogue of
failure modes, each with the lever that reproduces it, is
[docs/failure-modes.md](../docs/failure-modes.md).
