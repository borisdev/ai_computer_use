# Open issues

Problems observed and not yet solved. ADRs record decisions made; these record
what is still wrong. Each carries the evidence, so nobody has to rediscover it.

| # | Issue | Blocks | Severity |
|---|---|---|---|
| [0001](0001-incomplete-inventory.md) | The inventory is incomplete and different every run (15/24/22) | **everything** | highest |
| [0002](0002-landmark-stability.md) | Landmarks can capture pixels that change | form submit buttons | fixed, unverified live |
| [0003](0003-cross-tenant-locators.md) | Template matching cannot survive a tenant rebrand | §3.7 reuse | by design |
| [0004](0004-sync-playwright-async.md) | Sync Playwright cannot nest `asyncio.run` | caller structure | low |
| [0005](0005-mask-mutable-pixels.md) | Mask changing pixels rather than avoiding them | — | idea |
| [0006](0006-controlled-vocabulary.md) | A straw-man controlled vocabulary for controls | part of 0001 | high |
| [0007](0007-parameterised-row-selection.md) | A parameterised control has no stable name (`account_13344_link`) | capability 1, end to end | high |
| [0008](0008-dense-numeric-text-is-misread.md) | The model misreads dense numeric text (6/11 account ids) | 0007's fix, extraction | high |
| [0009](0009-wrong-row-grounding-is-silent.md) | A grounded account link points at the WRONG ROW and says `ready` (1/4) | trusting any dense-table control | **highest** |
| [0010](0010-extraction-cannot-point-at-data.md) | Extraction can only target a control, and data is not a control | every capability that returns a value | **highest** |
| [0011](0011-control-panel-structured-read.md) | Control panels: locate a region, read it with a schema | — it UNBLOCKS 0007/0009/0010 | measured, partly built |
