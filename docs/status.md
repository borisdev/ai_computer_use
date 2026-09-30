# System status

> **Generated** by `interfaceai status --markdown docs/status.md`.
> Do not edit by hand. Last run 2026-09-30 18:12 UTC.

11 capabilities (7 approved) · 213 recorded runs.

## Capabilities

`invokes` is composition — a capability calling another, version pinned.

| capability | v | approval | signature | invokes | steps |
|---|---|---|---|---|---|
| `discovered_balance` | 1 | ✅ approved | `discovered_balance(account_id) -> account_id, balance` | — | 6 |
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
| 2026-09-30 18:11:13 | replay | `request_loan` | **needs_human** | 9 | 1 | 0.9998 |  |
| 2026-09-30 18:11:02 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-30 18:10:52 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-30 18:10:41 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-30 18:10:30 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-30 18:10:19 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-30 18:10:09 | replay | `request_loan` | **needs_human** | 8 | 1 | 0.9998 |  |
| 2026-09-30 18:09:56 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 |  |
| 2026-09-30 18:09:50 | replay | `log_in_discovered` | **SUCCESS** | 4 | 1 | 0.9998 |  |
| 2026-09-30 18:09:42 | replay | `session_loss_probe` | **needs_human** | 5 | 1 | 0.9998 |  |
| 2026-09-30 18:09:41 | replay | `session_loss_probe` | **FAILED** | 0 | 0 | — | log_in not permitted |
| 2026-09-30 18:09:23 | replay | `session_loss_probe` | **SUCCESS** | 10 | 3 | 0.9998 | recovered: accounts_overview_link gone -- log_in no longer holds |
| 2026-09-30 18:09:06 | replay | `session_loss_probe` | **SUCCESS** | 10 | 3 | 0.9998 | recovered: accounts_overview_link gone -- log_in no longer holds |
| 2026-09-30 18:08:32 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-30 18:08:27 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-30 18:08:23 | replay | `log_in_discovered` | **needs_human** | 3 | 0 | 0.9998 | cannot read 12345_link: not_found (best score 0.8654 is below threshol |
| 2026-09-30 18:08:11 | replay | `log_in_discovered` | **SUCCESS** | 4 | 1 | 0.9998 |  |
| 2026-09-30 18:07:18 | replay | `read_savings_balance` | **SUCCESS** | 10 | 5 | 0.9998 |  |
| 2026-09-30 18:07:07 | replay | `read_savings_balance` | **FAILED** | 10 | 5 | 0.9998 | account_type: wanted 'SAVINGS', saw 'CHECKING' |
| 2026-09-30 18:06:52 | replay | `read_savings_balance` | **FAILED** | 10 | 5 | 0.9998 | account_type: wanted 'SAVINGS', saw 'CHECKING' |
