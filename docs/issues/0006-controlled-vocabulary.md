# 0006 — A straw-man controlled vocabulary for controls

**Severity:** high — it is one of the three parts of the fix for
[0001](0001-incomplete-inventory.md).

## The problem it solves

Control ids are currently slugs of whatever the model happened to call a thing,
so identity is downstream of a coin flip. A **controlled vocabulary** is a fixed
set of terms that the model must *resolve into* rather than invent. Its job is
not to be complete or correct — it is to be **fixed**. A wrong-but-stable
vocabulary kills the 15/24/22 variance; a perfect-but-regenerated one does not.

Two levels, easy to conflate:

| | Example | Status |
|---|---|---|
| Control role | `textbox`, `button`, `link` | exists — `ControlRole`, closed |
| Entity + slot | `customer.ssn`, `payee.city`, `account.from` | **missing** |

The second level is what this issue is about. ParaBank's own field names already
carry it: `customer.address.city` and `payee.address.city` are the same *slot*
on different *entities*, and `fromAccountId` / `toAccountId` is the same shape.

## Where a first vocabulary comes from

ParaBank publishes a WADL, so its API can be read once, offline, as a Rosetta
Stone — and then discarded. Measured coverage of the UI it has to describe:

```
UI form fields across 8 forms : 22
concept present in the WADL   : 18   (81%)
genuinely new                 :  4
```

The four misses are the interesting part, and they are not random:

| Missing | Why |
|---|---|
| `repeatedPassword` | UI-only — confirmation fields do not exist in an API |
| `verifyAccount` | UI-only — a verification step |
| `payee.accountNumber` | the API says `accountId`; a **synonym**, not a gap |
| `input` | ParaBank's own sloppy field name on the transfer form |

**APIs model state; UIs model data entry.** Confirmation fields, verification
steps and "are you sure" controls are UI-native, so they come from the screens,
not the spec. A tiled inventory (see [0001](0001-incomplete-inventory.md)) reads
the screens, so the two sources compose: **API for nouns and slots, screens for
UI-native controls, user requests for verbs.**

## Two honest limits

**The API is a bootstrap, not a method.** The premise of this project is
applications with no API at all. Reading one here is legitimate because the
vocabulary is the artifact and the API is thrown away — but nothing in the
design may *depend* on a spec existing.

**ParaBank is retail banking; the brief's target is back-office.** Holds,
freezes, memo posting, KYC flags, overrides, maker-checker — none of that is in
this API and none of it will be. So the Rosetta Stone yields the customer-facing
vocabulary and misses the operations vocabulary entirely. Standards exist for
that layer (BIAN models banking service domains, ISO 20022 covers payments
messaging) but they are heavyweight and, more importantly, the wrong instinct.

## What actually generalises

Not the vocabulary — the **method**. In a real engagement the vocabulary would
be elicited from the people who use the application: the human operators are the
SMEs, and knowledge elicitation from them produces both the language *and* the
ground-truth examples for progressively more nuanced capabilities.

What is built here is explicitly a **straw man**: provisional, built to be
argued with and replaced. Saying that is stronger than claiming general coverage
from a demo app's retail API.

## Proposed seed

Entities: `customer`, `payee`, `account`, `transaction`, `position`, `loan`
Slots: `username`, `password`, `firstName`, `lastName`, `ssn`, `street`, `city`,
`state`, `zipCode`, `phoneNumber`, `amount`, `fromAccountId`, `toAccountId`,
`accountType`, `downPayment`, `fromDate`, `toDate`, `transactionId`
UI-native: `confirmPassword`, `verifyField`, `submit`, `cancel`, `navLink`

~30 terms. Small enough to put in a prompt, fixed enough to stabilise naming.

## Measured: the churn is in NAMING, not in finding

Three tiled scans of the same screenshot, diffed by control rather than counted:

```
run 1: 26    run 2: 26    run 3: 26      count perfectly stable

found in ALL 3 runs : 18
varies across runs  :  8
```

Six of those eight are three controls described two different ways:

```
buttonwithagroupofpeopleic  [1,0,1]  \
customerloginbuttonpersoni  [0,1,0]  /   the SAME button

buttonwithahouseiconlikely  [1,0,1]  \
homebuttonhouseiconinthece  [0,1,0]  /   the SAME button

buttonwithanenvelopeiconli  [1,0,1]  \
contactbuttonenvelopeiconi  [0,1,0]  /   the SAME button
```

They are ParaBank's three orange header icons -- home, accounts, contact --
which carry **no text label, only an icon**. With no text to anchor a name the
model writes prose, and prose varies between runs. The remaining two entries are
a double-counted "READ MORE" (there are two on the page) and a footer line that
is arguably not a control.

**Nothing was dropped. The instability is in what things are CALLED.**

This sharpens the case for a controlled vocabulary: it is not only for search and
cross-tenant reuse, it is the fix for identity instability on unlabelled
controls. Forcing the three prose descriptions to resolve to `home_button`,
`accounts_button`, `contact_button` removes the churn entirely.

It also separates two failure modes that looked alike. A control WITH a text
label (`log_in_button`) going missing is an omission by the broad scan, which
tiling addresses. A control WITHOUT one churning between names is a naming
problem, which only a vocabulary addresses.

## What to measure next

Whether inventorying the same screenshot N times with the vocabulary in the
prompt produces the same set of resolved concepts — and specifically whether a
required control is ever missing. That is the number [0001](0001-incomplete-inventory.md)
is about.
