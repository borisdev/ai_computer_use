# 0004 — Our own tool vocabulary, not Anthropic's computer toolset

**Status:** Accepted · 2026-09-22

## Context

Anthropic ships a first-class computer-use toolset (`computer_toolset_20260801`,
GA, supported on Claude Opus 5). It defines seventeen member actions —
`screenshot`, `zoom`, `left_click`, `type`, `key`, `scroll` and so on — with
coordinates in screenshot pixel space. It is the obvious thing to reach for
given [ADR 0002](0002-playwright-screenshot-control.md), and the first
implementation used it.

## Decision

Define our own tools instead, one per method on the `Surface` protocol:
`screenshot`, `zoom`, `click`, `type_text`, `press_key`, `scroll`, `drag`,
`wait`, and `finish`.

## Why

- **The artifact's step vocabulary has to be ours.** A recorded capability is a
  list of steps. If those steps mirror a vendor's tool schema, then a change to
  that schema upstream is a change to our capability format — and the artifact
  schema is the load-bearing piece of this project. The indirection costs one
  `match` statement.
- **`finish` gives a typed result.** A custom tool with `strict: true` returns
  `{status, outputs, evidence}` validated against a schema, where `status`
  distinguishes `success` from `business_outcome` from `blocked`. The built-in
  toolset ends a run with free text that we would have to parse — and the
  success/business-outcome distinction is precisely what the brief says must not
  be conflated. Better to have the model commit to it in a typed field than to
  infer it from prose.
- **The tool surface documents the seam.** Anthropic's toolset includes members
  our surface cannot perform (`hold_key`, `cursor_position`, `left_mouse_down`);
  using it meant maintaining a `configs` block disabling them. A one-to-one
  vocabulary makes "what a surface must implement" a single readable list.

## Consequences

- **Targeting accuracy is likely somewhat worse.** Claude is specifically
  trained on the built-in computer toolset, so its coordinate estimates there
  benefit from that training. With custom tools it is doing general vision plus
  tool calling. This is the real cost of the decision and it should be measured
  rather than assumed — if discovery runs show it missing controls, this ADR is
  the first thing to revisit.
- Mitigation already in place: `zoom` is prominent in the system prompt, so the
  model inspects a region at full resolution before reading any number.
- We own the prompt-side description of every action, which is also a lever —
  tool descriptions can encode surface-specific guidance the built-in toolset
  has no place for.

## Alternatives rejected

- **`computer_toolset_20260801`.** Better targeting, less code, and a schema we
  do not control leaking into the artifact format. Reconsider if measured
  accuracy is materially worse; the `Surface` protocol means swapping the tool
  layer touches `discover.py` only.
- **A single `execute(action, params)` tool with a free-form params object.**
  Fewer definitions, but no per-action schema, so nothing validates what the
  model sends and mistakes surface as runtime errors instead of 400s.
