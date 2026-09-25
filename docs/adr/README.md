# Architecture Decision Records

One file per decision that would be expensive to reverse or that a reviewer
would otherwise have to reverse-engineer from the code.

Format: context, the decision, consequences, and the alternatives that were
actually considered. A decision with no rejected alternative was not a decision.

| # | Decision | Status |
|---|---|---|
| [0001](0001-parabank-as-target.md) | ParaBank as the proxy target | Accepted |
| [0002](0002-playwright-screenshot-control.md) | Playwright driving screenshots and coordinates, not the DOM | Accepted |
| [0003](0003-plain-docker-compose.md) | Plain `docker compose`, no Makefile | Accepted |
| [0004](0004-custom-tool-vocabulary.md) | Our own tool vocabulary, not Anthropic's computer toolset | Accepted |
