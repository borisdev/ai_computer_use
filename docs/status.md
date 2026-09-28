# System status

> **Generated** by `interfaceai status --markdown docs/status.md`.
> Do not edit by hand. Last run 2026-09-28 23:56 UTC.

8 capabilities (5 approved) · 359 recorded runs.

## Capabilities

`invokes` is composition — a capability calling another, version pinned.

| capability | v | approval | signature | invokes | steps |
|---|---|---|---|---|---|
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
| 2026-09-28 23:55:40 | replay | `request_loan` | **SUCCESS** | 9 | 1 | 0.9998 |  |
| 2026-09-28 23:55:07 | replay | `session_loss_probe` | **SUCCESS** | 10 | 3 | 0.9998 | recovered: accounts_overview_link gone -- log_in no longer holds |
| 2026-09-28 23:53:09 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-28 23:53:08 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-28 23:53:07 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-28 23:52:31 | replay | `request_loan` | **SUCCESS** | 9 | 1 | 0.9998 |  |
| 2026-09-28 23:52:18 | replay | `request_loan` | **SUCCESS** | 9 | 1 | 0.9998 |  |
| 2026-09-28 23:51:54 | replay | `request_loan` | **SUCCESS** | 9 | 1 | 0.9998 |  |
| 2026-09-28 23:51:43 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-28 23:51:32 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-28 23:51:20 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-28 23:51:10 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-28 23:50:58 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-28 23:50:46 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-28 23:49:50 | replay | `request_loan` | **SUCCESS** | 9 | 1 | 0.9998 |  |
| 2026-09-28 23:49:35 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-28 23:49:17 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-28 23:49:16 | replay | `request_loan` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-28 23:49:15 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-28 23:49:14 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
