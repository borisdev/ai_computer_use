# 0003 — Plain `docker compose`, no Makefile

**Status:** Accepted · 2026-09-22 · supersedes the Makefile added the same day

## Context

The project briefly had a Makefile wrapping `docker compose`. It existed for one
real reason: ParaBank needs a readiness gate, and `docker compose up -d` returns
before Tomcat has deployed the webapp.

Two things then turned out to be true:

1. The image ships `/usr/bin/curl`, so the compose healthcheck works, and
   `docker compose up --wait` is supported — even by the 2021-era v2.1.1 on this
   machine. The hand-rolled wait script was redundant and was deleted.
2. The healthcheck is still not sufficient, because ParaBank boots with **no
   database schema** and serves HTTP 200 anyway
   ([parabank.md §4](../parabank.md#4--it-boots-with-no-database-schema)). A
   green container still fails every lookup.

So one step genuinely cannot be expressed in compose alone: seeding, and
verifying the seed landed.

## Decision

No Makefile. Starting the stack is two commands, both documented in `README.md`:

```bash
docker compose up -d --wait     # liveness: Tomcat has deployed the webapp
uv run interfaceai env reset            # readiness: seed the DB, verify it took
```

Everything else is plain `docker compose` (`ps`, `logs`, `down`) or plain
`uv run`.

## Why

- A Makefile whose targets are one-line aliases is indirection that has to be
  read before the real command can be known.
- `docker compose` and `uv run` are the tools a reviewer already knows. The
  brief is explicit that it is read alongside many other submissions.
- The one step that is not a compose command is not a compose command *for a
  reason worth reading* — so making it visible in the README is better than
  hiding it behind `make up`.
- `interfaceai env reset` seeds **and verifies**, which a Make recipe would not have.
  The lazy-init path reports success while the schema never appears, so a POST
  returning 200 is not evidence.

## Consequences

- Two commands to start, not one. Acceptable, and the second is explained where
  it appears.
- The readiness rule now lives in Python (`interfaceai.parabank.is_seeded`) where it is
  testable, rather than in shell.
- `docker compose down` removes the container and therefore the database, so the
  seed step is required again on the next start. This is deliberate — see
  [parabank.md §10](../parabank.md#10-gotchas-collected).

## Alternatives rejected

- **A seeder sidecar** — a one-shot `curl` service with
  `depends_on: {parabank: {condition: service_healthy}}` that POSTs `action=INIT`,
  making `docker compose up -d --wait` sufficient on its own. Genuinely
  tempting, and the closest to "one command". Rejected because it reimplements
  the seed-and-verify logic in inline compose shell, duplicating
  `interfaceai.parabank.is_seeded()` where the two copies can drift. Worth revisiting if
  the second command becomes a nuisance in CI.
- **Keeping the Makefile as thin aliases.** All of the indirection, none of the
  remaining benefit.
- **A shell script wrapper** (`./scripts/up.sh`). Same indirection as Make, with
  less discoverability than two documented commands.
