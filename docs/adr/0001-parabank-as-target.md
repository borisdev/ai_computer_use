# 0001 — ParaBank as the proxy target

**Status:** Accepted · 2026-09-22

## Context

The brief does not give access to a real bank system and says not to seek one.
We need a stand-in that exercises the interesting problems: a multi-step flow,
a surface where a clean DOM cannot be assumed, and real runtime error states.

The environment being simulated is back-office banking software: stable UIs that
change slowly, heterogeneous and often legacy, with the hard part being runtime
exceptional states rather than layout drift.

Candidates: a public demo/sandbox site; a local app built for the purpose; an
intentionally hostile surface written to be awkward; ParaBank.

## Decision

Use [ParaBank](https://github.com/parasoft/parabank), run locally from
`parasoft/parabank`, as the only concrete surface.

## Why

- **Legacy on its own terms.** Spring MVC + JSP, form POSTs to `.htm`, table
  layout, zero `data-testid`, `;jsessionid=` rewritten into every URL. None of
  that was arranged by us, which matters — a hostile surface we wrote ourselves
  would be a surface we knew the answers to.
- **It is a bank.** Accounts, balances, transfers, overdrafts, minimum-balance
  validation. The domain vocabulary in the artifacts is the real vocabulary.
- **Genuine error states, from the app's own admin page.** No fault-injection
  proxy, no monkeypatching. See [parabank.md §5](../parabank.md#5-the-two-database-states).
- **Two tenants for free.** The `baseline` and `feature` tags are different
  images of the same product — an honest stand-in for §3.7 rather than a mock.
- **Local, so no terms-of-service or rate-limit question**, and no temptation to
  point automation at someone else's site.

## Consequences

- ParaBank has a REST API, and using it would dissolve the exercise. The agent
  and replay engine are barred from it; tests may use it as an oracle. This is a
  discipline the code cannot enforce, so it is written down here and in
  `CLAUDE.md`.
- ParaBank boots with no database schema and serves HTTP 200 regardless, so
  startup needs an explicit seed step. See
  [parabank.md §4](../parabank.md#4--it-boots-with-no-database-schema).
- Findings are ParaBank-shaped. The multi-tenant and desktop story stays a
  design argument, as the brief permits.

## Alternatives rejected

- **A public demo site** (SauceDemo, the-internet, a shop). Modern DOM, clean
  selectors, nothing to be robust *against* — it would make the locator problem
  artificially easy and the whole exercise easier than it is.
- **A local app written for the purpose.** We would be marking our own homework:
  every locator difficulty would be one we chose to create or avoid.
- **A desktop app.** Closest to the hardest real case, but it costs the whole
  time budget on tooling and leaves nothing for the artifact schema and replay
  contract, which is where the brief says the marks are.
