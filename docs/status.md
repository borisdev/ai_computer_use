# System status

> **Generated** by `interfaceai status --markdown docs/status.md`.
> Do not edit by hand. Last run 2026-09-30 18:29 UTC.

12 capabilities (8 approved) · 246 recorded runs.

## Capabilities

`invokes` is composition — a capability calling another, version pinned.

| capability | v | approval | signature | invokes | steps |
|---|---|---|---|---|---|
| `discovered_balance` | 1 | ✅ approved | `discovered_balance(account_id) -> account_id, balance` | — | 6 |
| `discovered_savings_check` | 1 | ✅ approved | `discovered_savings_check(account_id) -> account_id, account_type` | — | 7 |
| `evidence_discovery` | 1 | draft | `evidence_discovery() -> account_id` | — | 5 |
| `log_in` | 1 | draft | `log_in() -> customer_first_name` | — | 5 |
| `log_in` | 2 | ✅ approved | `log_in() -> nothing` | — | 4 |
| `log_in_discovered` | 1 | ✅ approved | `log_in_discovered() -> account_id` | — | 5 |
| `read_savings_balance` | 1 | draft | `read_savings_balance(account_id) -> found_account_id, account_type, balance` | — | 8 |
| `read_savings_balance` | 2 | draft | `read_savings_balance(account_id) -> found_account_id, balance` | `log_in` | 5 |
| `read_savings_balance` | 3 | ✅ approved | `read_savings_balance(account_id) -> found_account_id, balance, account_type` | `log_in` | 8 |
| `request_loan` | 1 | ✅ approved | `request_loan(amount, down_payment) -> nothing` | `log_in` | 6 |
| `request_loan` | 2 | ✅ approved | `request_loan(amount, down_payment) -> nothing` | `log_in` | 7 |
| `session_loss_probe` | 1 | ✅ approved | `session_loss_probe(account_id) -> found_account_id` | `log_in` | 3 |

## Runs (most recent 20)

Outcomes are the four of `outcomes.CapabilityResult`, read from each run's
own `replay_finished` event rather than inferred. `recovered` means the run
hit a condition and handled it — it succeeded, and it survived something.

| when | kind | capability | outcome | steps | model calls | worst match | detail |
|---|---|---|---|---|---|---|---|
| 2026-09-30 18:28:06 | replay | `discovered_savings_check` | **FAILED** | 6 | 5 | 0.9998 | account_type: wanted 'SAVINGS', saw 'CHECKING' |
| 2026-09-30 18:27:43 | replay | `discovered_savings_check` | **SUCCESS** | 6 | 5 | 0.9998 |  |
| 2026-09-30 18:27:23 | replay | `discovered_savings_check` | **SUCCESS** | 6 | 5 | 0.9998 |  |
| 2026-09-30 18:21:55 | discovery | `discovered_savings_check` | **discovered** | 4 | 10 | — | 7 steps, 2 checkpoints |
| 2026-09-30 18:20:46 | discovery | `discovered_savings_check` | **discovered** | 4 | 7 | — | 7 steps, 2 checkpoints |
| 2026-09-30 18:20:37 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-30 18:20:36 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-30 18:20:35 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-30 18:19:51 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-30 18:19:50 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-30 18:19:49 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-30 18:18:30 | discovery | `discovered_savings_check` | **discovered** | 4 | 5 | — | 7 steps, 2 checkpoints |
| 2026-09-30 18:18:11 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-30 18:18:10 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-30 18:18:09 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-30 18:17:44 | discovery | `discovered_savings_check` | **incomplete** | 0 | 1 | — | no terminal event -- the run did not finish |
| 2026-09-30 18:17:18 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-30 18:17:17 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-30 18:17:16 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-30 18:17:15 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
