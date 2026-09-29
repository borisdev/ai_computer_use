# Open issues

Problems observed and not yet solved. ADRs record decisions made; these record
what is still wrong. Each carries the evidence, so nobody has to rediscover it.

⚠️ **The Severity column was stale for many commits** — it still read
"highest" for three issues that had been fixed. Re-read 2026-09-29 against the
code. A status table nothing regenerates goes quietly wrong; `interfaceai
status` is the one that cannot.

| # | Issue | Blocks | Severity |
|---|---|---|---|
| [0001](0001-incomplete-inventory.md) | The inventory is incomplete and different every run (15/24/22) | **everything** | **measured gone** — `scripts/measure_naming_churn.py`, one screenshot x3 draws, gave **36/36/36** on overview and **26/26/26** on requestloan. The variance was the grid overlay fighting the read pass (0008) |
| [0002](0002-landmark-stability.md) | Landmarks can capture pixels that change | form submit buttons | fixed, unverified live |
| [0003](0003-cross-tenant-locators.md) | Template matching cannot survive a tenant rebrand | §3.7 reuse | by design |
| [0004](0004-sync-playwright-async.md) | Sync Playwright cannot nest `asyncio.run` | caller structure | low |
| [0005](0005-mask-mutable-pixels.md) | Mask changing pixels rather than avoiding them | — | idea |
| [0006](0006-controlled-vocabulary.md) | A straw-man controlled vocabulary for controls | part of 0001 | high |
| [0007](0007-parameterised-row-selection.md) | A parameterised control has no stable name (`account_13344_link`) | capability 1, end to end | **fixed** — rows are not named at all now; a panel is read whole and the row picked in code |
| [0008](0008-dense-numeric-text-is-misread.md) | The model misreads dense numeric text (6/11 account ids) | 0007's fix, extraction | **fixed** — read on a clean screenshot, locate on the gridded one: 6/11 → **11/11** |
| [0009](0009-wrong-row-grounding-is-silent.md) | A grounded account link points at the WRONG ROW and says `ready` (1/4) | trusting any dense-table control | **unreachable** — `check_capability` refuses a direct click inside a panel region, so the bad path cannot be authored. Not fixed; removed |
| [0010](0010-extraction-cannot-point-at-data.md) | Extraction can only target a control, and data is not a control | every capability that returns a value | **half fixed, half cut** — tables and label/value pairs are panels; a lone unstructured value is [#4](https://github.com/borisdev/ai_computer_use/issues/4) |
| [0011](0011-control-panel-structured-read.md) | Control panels: locate a region, read it with a schema | — it UNBLOCKED 0007/0009/0010 | **built** — `TABLE_CONTROL_PANEL`, measured row pitch, cross-checked |
