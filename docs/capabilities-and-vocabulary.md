# Five capabilities, and the vocabulary they imply

Derived backwards: choose the capabilities the system must perform, then take
the vocabulary to be exactly what those capabilities need. Not exhaustive
coverage of the application — coverage of the work.

This produces two things the project is missing at once: a **controlled
vocabulary** (which is one third of the fix for
[issue 0001](issues/0001-incomplete-inventory.md)) and the beginnings of the
**capability artifact** the brief calls a focal point of evaluation (§3.2).

## Why backwards

An exhaustive vocabulary is unbounded, unverifiable and mostly unused. A
capability-derived one is small, finite, and every term is justified by
something the system actually has to do. It also gives ground truth for free:
each capability has a known correct outcome, so "did the vocabulary work" is a
measurable question rather than an aesthetic one.

## The five

Chosen from the brief's own worked examples (§2) and ParaBank's authenticated
screens. Ordered by how much they exercise, easiest first.

| # | Capability | Exercises |
|---|---|---|
| 1 | Read a member's savings balance | login, navigate, read a value, checkpoint |
| 2 | Transfer funds between accounts | multi-field form, confirmation screen, validation error |
| 3 | Open a new account | dropdown, confirmation, a result the caller must capture |
| 4 | Update a customer's address | many fields, idempotence, no money moves |
| 5 | Find transactions by amount | search form, result set, empty-result business outcome |

**1** is the brief's own example and has a known answer — account 13344, SAVINGS,
**$1,231.10** — so it is self-checking. **2** is the first that can fail three
different ways: insufficient funds (business outcome), below minimum balance
(validation error), and a wrong account (violated checkpoint). **5** is the one
that most naturally returns "nothing found", which the brief is explicit must
not be reported as a crash.

## The vocabulary that falls out

Three parts. Nothing here exists because an application has it; everything is
here because one of the five capabilities needs it.

### Nouns — what the work is about

```
account   customer   transaction   payee   position   loan
```

### Verbs — what is done to them

```
look_up   transfer   open   update   search   confirm   pay
```

### Qualifiers — the typed slots a capability takes or returns

```
account_id    account_type   balance        amount
from_account  to_account     from_date      to_date
username      password       first_name     last_name
ssn           street         city           state
zip_code      phone_number   transaction_id down_payment
payee_name
```

**34 terms.** Small enough to put in a prompt verbatim, which is the whole
requirement — its job is to be *fixed*, not complete.

## Cross-checked against ParaBank's own WADL

The API is read once, offline, purely as a spell-check — to catch cases where we
invented a synonym for something the application already names. Then discarded.

```
nouns        4/6   in the WADL     missing: payee, loan
verbs        2/7   in the WADL     missing: look_up, open, search, confirm, pay
qualifiers  18/21  in the WADL     missing: account_type, balance, payee_name
```

The misses are informative rather than alarming:

- **Verbs barely appear at all (2/7).** A WADL encodes verbs as GET and POST.
  Domain verbs — *transfer*, *look up*, *open*, *confirm* — live in what people
  ask for, not in a spec. This is the concrete argument for deriving verbs from
  requests rather than from an API.
- **`balance` is a response field, not a parameter**, so it is absent from a
  parameter list while being the single most important thing capability 1
  returns. An API's *inputs* are not an application's *vocabulary*.
- **`payee` and `loan`** are real ParaBank screens (`billpay.htm`,
  `requestloan.htm`) whose nouns the REST surface happens not to expose.
- **`from_account` / `to_account`** are present as `fromAccountId` /
  `toAccountId` — a naming convention difference, not a gap.

**As a validation step this failed: it changed nothing.** All 34 terms survived;
not one was added, renamed or removed because of it. Kept here only for the
lesson it produced — *an API's inputs are not an application's vocabulary, and
domain verbs live in what people ask for* — and then dropped as a method. Do not
repeat it on the next application.

## Layer 2: step verbs

The 34 terms above are a vocabulary of **data** — what controls are *about*. A
capability also needs a vocabulary of **control flow**: how to move from control
to control, when to wait, what to assert, when to stop and ask a person.

| Verb | Why it exists |
|---|---|
| `require` | a **precondition** — `authenticated`, `on_screen(overview)` |
| `enter` / `click` / `select` | act on a control |
| `wait_for` | a page load, a slow response |
| `observe` | screenshot — the evidence trail (§3.5) |
| `assert` | the **checkpoint** (§3.3) — did we reach the expected state |
| `extract` | a typed output the caller gets back (§3.2) |
| `escalate` | stuck, or risky-and-unconfirmed (§3.6) |

Eight verbs, and each maps onto a requirement — a good sign the decomposition is
real rather than invented.

`require` is the one most easily forgotten and the most load-bearing. It is what
makes **resume after a human handoff** safe: the operator may have logged out or
navigated away, so resume must re-check preconditions before acting. It is also
the honest answer to logged-out `overview.htm` returning HTTP 200 with an empty
table — a precondition catches that, a checkpoint does not.

## Layer 3: a capability is a compound

```
read_savings_balance:
  requires:   authenticated
  params:     account_id: str          <- a SLOT from layer 1
  steps:      [...]                    <- layer 2 verbs over layer 1 controls
  checkpoint: on_screen(account_details) and account_id matches
  returns:    balance: Money
```

## What this is not

A **straw man**, deliberately. In a real engagement the vocabulary would be
elicited from the people who operate the application — they are the SMEs, and
knowledge elicitation from them yields both the language and the ground-truth
examples for progressively harder capabilities. See
[issue 0006](issues/0006-controlled-vocabulary.md).

It is also retail-banking vocabulary. The brief's target is **back-office** —
holds, freezes, memo posting, KYC flags, overrides, maker-checker. None of that
is in ParaBank and none of it is here. What generalises is the method, not
these 34 words.

## What it needs to become code

- **A schema.** `ControlledVocabulary` with nouns, verbs, qualifiers, and a
  `version`. A capability records which version it was authored against, so v2
  cannot silently redefine a term a saved artifact depends on.
- **A resolver.** `ConceptResolver` as a Protocol, so the strategy is swappable
  and measurable. For 34 terms the simplest implementation wins: put the
  vocabulary in the prompt and let the model resolve directly, no separate step.
  A cached, embedding-backed resolver of the kind nobsmed-v2 uses — described
  there as *convergently deterministic*, an LLM whose every result is cached so
  the same input yields the same output after the first call — earns its
  complexity at thousands of terms, not at 34. Naming it as the growth path is
  enough.

Stability is the property that matters either way: a resolver that answers
differently on two runs reintroduces exactly the churn the vocabulary exists to
remove ([issue 0006](issues/0006-controlled-vocabulary.md) measured that churn —
three unlabelled icon buttons renaming themselves between scans).
