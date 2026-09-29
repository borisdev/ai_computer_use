# System status

> **Generated** by `interfaceai status --markdown docs/status.md`.
> Do not edit by hand. Last run 2026-09-29 05:26 UTC.

9 capabilities (5 approved) · 471 recorded runs.

## Capabilities

`invokes` is composition — a capability calling another, version pinned.

| capability | v | approval | signature | invokes | steps |
|---|---|---|---|---|---|
| `evidence_discovery` | 1 | draft | `evidence_discovery() -> account_id` | — | 5 |
| `log_in` | 1 | draft | `log_in() -> customer_first_name` | — | 5 |
| `log_in` | 2 | ✅ approved | `log_in() -> nothing` | — | 4 |
| `log_in_discovered` | 1 | ✅ approved | `log_in_discovered() -> account_id` | — | 5 |
| `read_savings_balance` | 1 | draft | `read_savings_balance(account_id) -> found_account_id, account_type, balance` | — | 8 |
| `read_savings_balance` | 2 | draft | `read_savings_balance(account_id) -> found_account_id, balance` | `log_in` | 5 |
| `read_savings_balance` | 3 | ✅ approved | `read_savings_balance(account_id) -> found_account_id, balance, account_type` | `log_in` | 8 |
| `request_loan` | 1 | ✅ approved | `request_loan(amount, down_payment) -> nothing` | `log_in` | 6 |
| `session_loss_probe` | 1 | ✅ approved | `session_loss_probe(account_id) -> found_account_id` | `log_in` | 3 |

## Runs (most recent 20)

Outcomes are the four of `outcomes.CapabilityResult`, read from each run's
own `replay_finished` event rather than inferred. `recovered` means the run
hit a condition and handled it — it succeeded, and it survived something.

| when | kind | capability | outcome | steps | model calls | worst match | detail |
|---|---|---|---|---|---|---|---|
| 2026-09-29 05:26:14 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:26:13 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-29 05:26:12 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-29 05:26:11 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:23:54 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:23:53 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-29 05:23:52 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-29 05:23:51 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:19:49 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-29 05:19:04 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-29 05:18:55 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:18:54 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-29 05:18:53 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-29 05:18:52 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:17:49 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:17:48 | replay | `request_loan` | **needs_human** | 0 | 0 | — | log_in not permitted |
| 2026-09-29 05:17:47 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:16:50 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-29 05:16:49 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-29 05:16:48 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
