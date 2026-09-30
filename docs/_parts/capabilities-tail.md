---

## ⛔ THREE were discovered, and the reason the others were not is GONE

`log_in_discovered`, `discovered_balance` and `discovered_account_type` came out
of real LLM runs. The other four were **written by hand** in `capabilities.py`.

⭐ **`discovered_account_type` is the brief's own worked example, discovered.**
Two panels and a drilldown between them: open account 13344 from the accounts
table by `row_key`, then read `Account Type` out of a label/value block on the
detail page. It is the same shape as the hand-written `read_savings_balance` v3,
including the `account_type == SAVINGS` checkpoint — which discovery inferred from
the run, and which fails with **observed `CHECKING`** after `interfaceai env
break`. That is the honest state and
worth being precise about, because the brief's through-line is *"the model
discovers, the artifact becomes a reusable capability."*

⛔ **This section said "Only ONE of the five, and the reason is causal" until
2026-09-29,** the reason being that *"discovery cannot emit a
`TABLE_CONTROL_PANEL`"* — with a coarse prompt told to ignore static text and
layout, so it *"structurally cannot see the thing replay depends on"*. True when
written, and **closed** by [#6](https://github.com/borisdev/ai_computer_use/issues/6):
a second pass reads REPEATED STRUCTURES off the clean screenshot, and pure
geometry measures them — pitch by ink runs confirmed against
`find_row_rhythm`, phase and row count from the runs, and not one pixel asked of
a model.

`discovered_balance` is the artifact that closes the loop, and it is worth reading
as one line: **discovered → approved → replayed on both tenants**, reading a named
row out of an eleven-row table whose shape nobody told it.

⚠️ **Every region this repo measured by hand is now proposed AND measured**,
including the two that were missed at first:

```
accounts table        11 rows, pitch 28px, autocorrelation 0.899   proposed, measured, USED
account detail         4 rows, pitch 23px, 0.686                   proposed, measured, USED
account-services nav   8 rows, pitch 24px, 0.797                  proposed, measured
loan result            3 rows, pitch 23px                          proposed, measured
ATM / online services  4 and 3 rows, pitch 20px                   proposed, measured
empty transactions    refused: "no column below the heading repeats"
```

⛔ **And the reason the last two were missed is worth more than the fix.** The
prompt asked for *"a region of three or more near-identical rows — a results
table, an account list, a label/value block, a menu of links"*, which reads as
complete. Measured, three runs each: it found the account-detail block **0 of 3**
times and the loan result **0 of 3**. Describing the LABEL/VALUE shape in its own
right — *"one record's own fields, one per row, each row reading `Field Name:
value` … easy to overlook because it is not a grid"* — found both **3 of 3**, and
lost nothing. The model was not failing to see them; it was answering a question
that did not ask for them.

The four hand-measured panels stay in the store beside the discovered ones because
four artifacts name their ids, not because a hand is still required.

⚠️ **The origin column said `needs a panel` under the hand-authored three until
2026-09-30, and that had become a false REASON rather than a stale label.** They
are hand-written because they predate panel discovery. `read_savings_balance` in
particular is a Python literal in `capabilities.py`: its approved artifact is
byte-identical to an export of that declaration, and its v1 named `global_nav` —
a screen with no control map — which is how a hand-written artifact carries 8
faults and a recorded one carries 0.

Everything downstream of the artifact — validation, approval, replay,
composition, the guardrails — already treats both origins identically, which is
why both discovered capabilities replay on both tenants alongside the rest.

⚠️ **And the comparison favours the machine, precisely.** `interfaceai
capability check` resolves every control an artifact names against the control
maps it would replay against:

```
log_in.v1.draft                 3 faults   precondition + steps name a screen
read_savings_balance.v1.draft   8 faults   called 'global_nav' — which has no map
log_in_discovered.v1            0 faults   first emission, no correction
```

A fault is a step naming a control **that does not exist** — I invented a screen
and wrote six steps against it. The current hand-written artifacts are at 0 too,
because they were corrected; the point is which needed correcting. **A
hand-written artifact can name anything. A discovered one can only name what it
actually saw.**

## What the tenants column shows

**Three of five replay identically on a tenant they were never recorded
against, with no change to the artifact.** That is §3.7's whole claim, and it
holds because an artifact names `(screen, control_id)` while the **control map**
holds the pixels — so the only tenant-specific thing in the system is a
directory of templates.

The two that stop fail **at pre-flight, before a browser opens**:

```
FAILED at pre-flight
  expected  session_loss_probe to be permitted for feature
  observed  this tenant permits ['log_in', 'log_in_discovered', …]
```

A tenant *refusing* a capability is not the same as a capability *not working*
there, and the outcome type says which — `Failed` with a policy reason, never a
locator that missed.

### Capabilities compose, and composition travels

`read_savings_balance` and `session_loss_probe` both `invoke log_in v2` — in the
**same browser session**, version pinned. On tenant B that invocation resolves
against **B's** control map. One artifact, two institutions, same pinned
dependency, and nothing in the capability knows which bank it is on.

That is why an invoked capability is drawn in the **same green as the
terminus**: it is not a step, it is a whole capability with its own steps and
its own checkpoint, running inside this one.

```
  language      value · control · capability · outcome        docs/language.md
      ↓
  capability    names (screen, control_id) — tenant-agnostic, versioned
      ↓
  control map   the pixels, keyed (app, tenant, screen) — the ONLY tenant layer
```

[`docs/layering.md`](docs/layering.md) draws that and is honest that the third
layer is not yet what it should be: today a full map per tenant, where it wants
to be an app default plus only the controls that drift.

⚠️ **The honest limit.** Both images ship the stock unbranded UI. Put a
different brand on tenant B and **8 of 25 locators survive** — exactly the
image-anchored ones, while every text-anchored one drifts. `maps adopt` then
writes nothing and replay refuses at the precondition, which is the design
working. [REPORT §4](REPORT.md#4-heterogeneity--multi-tenant).

## Rationale, against the brief

Written down so the scope reads as chosen rather than as whatever fit.

| the brief asks for | what carries it |
|---|---|
| §2 *goal → LLM → record → replay → escalate → stay safe* | the five above, end to end |
| §3.2 *"both a human reviewer and a calling agent … what it does, what it needs, what it returns"* | this page, `interfaceai status`, and the generated diagrams |
| §3.3 *"distinguish expected business outcomes from recoverable conditions and hard failures"* | four outcome types, each with an observed instance above |
| §3.6 *"a human takes control of the live session"* | `log_in_discovered`'s handoff run |
| §3.7 *"reuse across institutions running the same app"* | the tenants column |
| §7 *"we do not reward feature breadth"* | **why there are five and not fifteen** |

⛔ **Still missing, and named rather than buried:** nothing here produces a
**validation error raised by the application**. §3.3 lists it. ParaBank raises
one for an insufficient-funds transfer, and no capability does transfers — so
that is the sixth capability worth building, and the only one that would add an
*outcome* rather than a feature.
