# System status

> **Generated** by `interfaceai status --markdown docs/status.md`.
> Do not edit by hand. Last run 2026-09-29 00:02 UTC.

8 capabilities (5 approved) · 386 recorded runs.

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
| 2026-09-29 00:01:46 | replay | `request_loan` | **SUCCESS** | 9 | 1 | 0.9998 |  |
| 2026-09-29 00:01:34 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-29 00:01:23 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-29 00:01:12 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-29 00:01:01 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-29 00:00:50 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-29 00:00:39 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-29 00:00:24 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 |  |
| 2026-09-29 00:00:17 | replay | `log_in_discovered` | **SUCCESS** | 4 | 1 | 0.9998 |  |
| 2026-09-29 00:00:08 | replay | `session_loss_probe` | **needs_human** | 5 | 1 | 0.9998 |  |
| 2026-09-29 00:00:07 | replay | `session_loss_probe` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-28 23:59:48 | replay | `session_loss_probe` | **SUCCESS** | 10 | 3 | 0.9998 | recovered: accounts_overview_link gone -- log_in no longer holds |
| 2026-09-28 23:59:29 | replay | `request_loan` | **FAILED** | 10 | 3 | 0.9998 | log_in not permitted |
| 2026-09-28 23:59:28 | replay | `request_loan` | **needs_human** | 0 | 0 | — |  |
| 2026-09-28 23:59:27 | replay | `request_loan` | **FAILED** | 0 | 0 | — | request_loan not permitted |
| 2026-09-28 23:59:22 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-28 23:59:18 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-28 23:59:13 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-28 23:59:00 | replay | `log_in_discovered` | **SUCCESS** | 4 | 1 | 0.9998 |  |
| 2026-09-28 23:58:19 | replay | `read_savings_balance` | **SUCCESS** | 10 | 5 | 0.9998 |  |
