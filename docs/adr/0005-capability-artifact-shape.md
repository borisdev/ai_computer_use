# 0005 — What a capability artifact may and may not contain

**Status:** Accepted · 2026-09-25

## Context

Assignment §3.2 asks for "a reusable, **reviewable**, parameterized capability
an AI agent can call, with **typed input parameters**", and §8 asks that
unattended replay be gated on "an approval state (draft → approved)". The
artifact is the graded centrepiece: discovery's only output, replay's only
input, and the one thing a human actually reviews.

Four things were already measured going wrong, and each of them is a shape
decision rather than a coding convention. Recording them here because the
obvious artifact — a list of coordinates and strings — fails all four.

## Decision

`src/interfaceai/capability.py` defines the artifact. Four constraints are in
the type system rather than in a style guide:

### 1. No coordinates, and no locators either

A step names a control by `(screen, control_id)`. The pixel template that finds
it lives in a per-tenant control map, not in the artifact.

Raw `(x, y)` scored **1/10** clicks inside the target control, and a fractional
bbox scored the same; only a context patch plus a click offset replayed at
drift `(0,0)` — `docs/findings.md` §2–3. But a template is also the *least*
portable locator there is: a tenant that rebrands the CSS changes the pixels.
Keeping the payload out of the artifact is what lets one artifact serve two
tenants (§3.7). The artifact schema and the replay engine stay tenant-agnostic;
only what sits behind a control name is tenant-specific.

### 2. A checkpoint may only compare an extracted VALUE

`Checkpoint.output` must name a declared output, so "did I reach the account
details screen for 13344" is **not expressible**.

ParaBank's own CLEAN state is the reason. Account 13344 still resolves after
it — as `CHECKING $5,022.93` instead of `SAVINGS $1,231.10`. A checkpoint that
asserts the lookup succeeded passes there and returns a different record's
balance to a bank, reporting success. A test asserts that the capability
checks the field that differs, reading both values from `parabank.py` rather
than restating them.

Presence questions did not disappear; they moved to `Precondition`, which is
where they are answerable (see 4).

### 3. A sensitive slot cannot hold a literal

`username`, `password` and `ssn` are flagged `sensitive` in the vocabulary, and
validation refuses an artifact that gives one a `literal` — or a caller
`param`. They take a `SecretValue`, which carries an `input_ref` key resolved
at replay.

§3.4 forbids persisting them. This is the difference between an artifact that
can live in a public git repo and one that cannot, and it is enforced twice:
in the validator, and by a test that reads the committed JSON off disk rather
than the objects in memory, because a hand-edited file is the case that matters.

### 4. Preconditions are visual, and separate from steps

`require` is a capability-level list, not a position in the step sequence,
because it is checked **twice**: before the first step, and again after a human
handoff. Resume is never "continue from line N" — the operator may have logged
out or navigated anywhere, so resume re-observes and re-checks preconditions
before acting (§3.6).

A precondition asks whether a control is present or absent, which
`locate_control` answers with no model and no DOM. `authenticated` is "the Log
Out link is visible". That is the honest answer to logged-out `overview.htm`
returning HTTP 200 with the correct heading and an empty table — a checkpoint
cannot catch it, a precondition can.

### And: draft → approved is one function

`assert_replayable` validates and then refuses anything not `approved`. One
gate, so there is exactly one place to route around it, and a test that a draft
cannot pass. `approve()` returns a new artifact and requires an attribution;
an artifact that could approve itself would make the gate decoration.

## Alternatives considered

- **Embed the locator in the step.** Simplest, and it is what the first sketch
  did. Rejected because it welds the artifact to one tenant's pixels, which is
  exactly the §3.7 limit we already measured and documented.
- **Steps mirroring the executor's tool calls.** Rejected for the reason in
  [ADR 0004](0004-custom-tool-vocabulary.md): an artifact that mirrors a tool
  schema inherits that schema's churn.
- **`assert` and `require` as step verbs**, as `docs/capabilities-and-vocabulary.md`
  layer 2 lists them. Rejected once resume was thought through: a precondition
  that lives at a position in the list cannot be re-checked from a place the
  human left us in. `escalate` went the same way — it is what the executor does
  on failure, so its authored form is `Step.risky`, not a verb.
- **A checkpoint expression language** (`on_screen(x) and id == y`). Rejected:
  it makes the un-expressible expressible again, and a reviewer would have to
  learn a grammar to read a draft.

## Consequences

- Discovery must emit this shape. It does not exist yet, so the two committed
  artifacts are **hand-authored** — the target shape, not evidence.
- The executor needs a control-map store keyed by `(app, tenant, screen)`. Not
  built.
- One capability cannot yet be expressed end to end: selecting one of eleven
  near-identical account rows by a parameter. `ControlRef.discriminator` says
  which row; nothing honours it — [issue 0007](../issues/0007-parameterised-row-selection.md).
