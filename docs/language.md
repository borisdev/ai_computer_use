# The languages

Boris asked whether there is a control language and a capability language, and
whether there are others. There are **four**, they are small on purpose, and
three of them are drawn from the code by `uv run interfaceai language`.

```
① VALUE      what a value MEANS          21 qualifiers · money/string/date · sensitive
② CONTROL    what a thing on screen IS   8 roles, and what may be done to each
③ CAPABILITY what a STEP may do          7 verbs, checkpoints, composition
④ OUTCOME    how a run may END           4 types, and no fifth
```

⚠️ **Four small closed sets, not one big one.** Each answers a different
question, and keeping them apart is what makes the guardrails expressible: a
rule like *"you cannot click a table"* is a statement about ② and ③ together,
and it has nowhere to live if they are one vocabulary.

---

## ① The value language — `vocabulary.py`

21 qualifiers, each with a type and a `sensitive` flag.

```
money    3    amount, down_payment, balance
date     2
string  16    including username, password, ssn  ← sensitive
```

**What `sensitive` buys.** A sensitive slot cannot hold a literal — only an
`input_ref` resolved at replay — **and cannot be extracted back out**. The
second half was missing until a discovery run proposed `EXTRACT username`, which
would have handed a credential to the caller past every redaction.

**Versioned.** `VOCABULARY_VERSION` is stamped into every artifact, so a
vocabulary change cannot silently redefine a term a saved artifact depends on.

⚠️ **One vocabulary across apps and tenants**, deliberately, until something
concretely conflicts. These 34 terms are retail banking; a back-office tool
would need holds and maker-checker. Drifting early gives you a synonym list.

### ⭐ And the seam §2.2 asks for is the LOCATOR, not the Surface

> *"The surface may be a browser, but treat that as one case of a more general
> 'computer use' problem (accessibility tree, screenshot + coordinates,
> OS-level automation, etc. are all fair game)."*

The obvious reading is wrong, and being exact about it is the point.

**`Surface` is a PIXEL surface.** Every method takes or returns pixels and
coordinates — `screenshot() -> bytes`, `left_click(x, y)`, `zoom(...)`. There
is no `find` and no selector. So:

```
browser screen → desktop screen    SAME Surface, SAME locator language,
                                   nothing above changes. This is the real
                                   portability, and it is why pixels beat DOM.

browser DOM, a11y tree             NOT different surfaces. A Chromium surface
                                   can screenshot AND query the DOM — they are
                                   ADDITIVE. What differs is how you FIND it.

a REST API                         ⛔ not a surface. §1: "when a system exposes
                                   an API, we integrate through the API —
                                   that's always the preferred path and is out
                                   of scope here."
```

So the seam is a **discriminated union on `kind`**, and only `visual` is built
(`locators.py`). `VisualLocator` carries `kind: Literal["visual"]` *today*,
with one member — because a discriminator added *with* the second kind is a
discriminator that cannot read anything written before it.

⚠️ **`DomLocator` is declared with a resolver that refuses**, kept as the
counter-example rather than as a feature:

| | visual | dom |
|---|---|---|
| survives a tenant **rebrand** | ❌ 8 of 25 | ✅ selectors ignore pixels |
| survives a **DOM refactor** | ✅ | ❌ one renamed class |
| works on a **desktop app** | ✅ | ❌ no DOM to query |
| works with **no test ids** | ✅ | ❌ ParaBank has none |

**Neither wins. They fail in opposite directions**, and that is the whole
argument for ADR 0002 — a DOM recording cannot replay against a desktop app,
which is the case this design is built for.

## ② The control language — `ControlRole` + `ACTIONS_BY_ROLE`

What a thing on screen **is**, and what may be done to it:

```
textbox   → enter_text        checkbox → toggle
button    → click             radio    → toggle
link      → click             select   → select

table_control_panel → NOTHING        unknown → NOTHING
```

⭐ **The two with no permitted action are the interesting half.** You cannot
click a `table_control_panel` — it is a *region with structure*, reached only by
`extract`, because grounding one of N identical rows lands on the wrong record
**3 times in 4** and says `ready` while doing it. And `unknown` has none because
a control we could not classify is not one we may act on.

`check_capability` enforces the first geometrically: it refuses a direct click
on **any** control whose click point falls inside a panel's region, so the bad
path cannot be authored rather than merely being discouraged.

## ③ The capability language — `StepVerb` + `Checkpoint` + `invokes`

Seven verbs, and the shapes in every generated diagram are these:

```
invoke     [[ ]]   another capability, in the SAME browser session
enter      [  ]    writes into the page
select     [  ]    writes into the page
click      (  )    acts — and RED AND THICK when irreversible
wait_for   >  ]    looks, changes nothing
observe    >  ]    looks, changes nothing
extract   [/  /]   takes a value OUT
```

Plus two things that are not verbs:

- **`Checkpoint`** — the only thing that can turn `Success` into `Failed`. It may
  compare an extracted **value**, never a presence, because a presence check
  passes on the wrong record.
- **`requires` / `establishes`** — pre- and postconditions. `establishes` is how
  recovery knows which capability restores a lost session.

**Composition is a verb, not a framework.** `invoke` runs another capability in
the same session with its version pinned, which is why it is drawn in the same
green as the terminus — an invoked capability *is* a capability, with its own
steps and its own checkpoint.

## ④ The outcome language — `outcomes.py`

```
Success          it did the thing          (may carry `recovered`)
BusinessOutcome  a fair negative answer    exit 0 — "no such account"
Failed           a checkpoint was violated
NeedsOperator    stopped safely, a human is needed
```

⛔ **And there is no fifth.** A `Recoverable` variant was proposed and refused:
a recovered condition is **not a terminal state**, so a caller branching on it
would be branching on something that is not an answer. `Success.recovered`
names what a run survived. A test asserts the type's absence, so adding one is a
conscious act.

---

## Why so small

Each set is closed and short enough to read in one sitting, which is what makes
three things possible:

1. **The guardrails are expressible.** *"An irreversible step must be followed by
   an observation"* is one sentence across ② and ③, and it is a validator.
2. **The model's answers can be constrained.** `extract_panel` builds its
   response schema from the columns at call time; the same trick closes
   `control_id` to what is actually on screen.
3. **A diagram can be generated.** Shape and colour come from the language, so a
   reader learns it by looking rather than by reading this page.

⚠️ **The measured argument for keeping them fixed:** one screenshot, three
draws, **62 control ids over two screens, 0 churn**. An id is derived from label
+ role + position, not invented. Stability is what a controlled language buys,
and it is checkable.
