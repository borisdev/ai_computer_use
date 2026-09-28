# The two engine flows

⚠️ **These draw the ENGINE, not a capability.** A capability's own flowchart is
generated from its artifact — `interfaceai diagram <name>` — and cannot drift
from what replays. These two are hand-drawn because they describe the code, and
they are the only diagrams here that a reader must check against it.

Related: [`status.md`](status.md) for what exists right now ·
[`failure-modes.md`](failure-modes.md) for what can go wrong.

---

## 1 · Discovery — an LLM in the loop, once

```mermaid
flowchart TD
    G(["goal + target"]) --> NAV["navigate to the entry point"]
    NAV --> SHOT["screenshot"]
    SHOT --> MAP{"control map<br/>for this screen?"}
    MAP -->|"cached"| DECIDE
    MAP -->|"no"| BUILD["READ on a clean shot<br/>LOCATE on the gridded one<br/>then ground each control"]
    BUILD --> STORE[("control map store<br/>app / tenant / screen")]
    STORE --> DECIDE["decide ONE action<br/>(the model, with the goal)"]
    DECIDE -->|"act"| ACT["locate -> validate -> use"]
    ACT --> SHOT
    DECIDE -->|"finish"| DRAFT["synthesise a DRAFT capability"]
    DECIDE -->|"stuck"| OP(["PassToOperator"])
    ACT -->|"refused"| OP
    DRAFT --> A(["artifact + evidence"])

    style BUILD fill:#fff4e5,stroke:#d97706,color:#000
    style DECIDE fill:#fff4e5,stroke:#d97706,color:#000
    style OP fill:#fef2f2,stroke:#dc2626,color:#000
```

**Orange is where a model is consulted.** Cyclical by nature — it keeps choosing
a next action until the goal is met, it is stuck, or a stopping condition fires
(`max_steps`, timeout).

**Cost is dominated by the map, not the loop.** Grounding a screen is ~20–25
calls; a decision is one. So a map is built once per screen and reused by later
steps, later runs, and replay. Measured: a cold run maps two screens in ~100
calls; a warm one completes in **4 calls and 15 seconds**.

---

## 2 · Replay — no model decides anything

```mermaid
flowchart TD
    A(["approved artifact + typed inputs"]) --> GATE{"approved?<br/>permitted?<br/>controls recorded?"}
    GATE -->|"no"| F(["Failed — pre-flight"])
    GATE -->|"yes"| PRE{"preconditions hold?"}
    PRE -->|"no"| NO(["NeedsOperator"])
    PRE -->|"yes"| STEP["next step"]

    STEP -->|"invoke"| SUB["run that capability<br/>in the SAME session"]
    SUB --> STEP
    STEP -->|"enter / click / select"| ACT["locate -> validate -> use"]
    STEP -->|"wait_for"| POLL["poll until present"]
    STEP -->|"extract"| READ["read a control, or a PANEL<br/>then select the row IN CODE"]
    ACT --> STEP
    POLL --> STEP
    READ --> STEP

    ACT -->|"fails"| REC{"a declared postcondition<br/>no longer holds?"}
    REC -->|"yes, once"| SUB
    REC -->|"no"| HAND{"operator attached?"}
    HAND -->|"no"| NO
    HAND -->|"yes"| HUMAN["human takes the live session"]
    HUMAN --> VERIFY{"re-verify"}
    VERIFY -->|"target satisfied"| STEP
    VERIFY -->|"safe to retry"| STEP
    VERIFY -->|"uncertain"| NO

    STEP -->|"all done"| CHECK{"checkpoints hold?"}
    CHECK -->|"no"| FAIL(["Failed — expected vs observed"])
    CHECK -->|"yes"| S(["Success — outputs, and what it recovered from"])
    READ -->|"row absent"| BO(["BusinessOutcome — no such record"])

    style READ fill:#fff4e5,stroke:#d97706,color:#000
    style S fill:#f0fdf4,stroke:#16a34a,color:#000
    style BO fill:#fefce8,stroke:#ca8a04,color:#000
    style FAIL fill:#fef2f2,stroke:#dc2626,color:#000
    style NO fill:#fefce8,stroke:#ca8a04,color:#000
```

**A linear walk, not a loop** — the step list comes from the artifact, and the
node vocabulary is closed: `invoke · enter · click · select · wait_for ·
observe · extract`.

**One orange box.** `extract` is the only place a model is consulted, and only
to turn pixels into a value — perception, not decision. Nothing chooses an
action, an order or a verdict. **A capability with no `extract` step replays
with zero model calls.**

### Four exits, and each is a different thing

| | means | the caller should |
|---|---|---|
| `Success` | it worked. `recovered` names anything it survived | use the outputs |
| `BusinessOutcome` | a legitimate negative answer — no such record | use the answer |
| `Failed` | a checkpoint was violated, or the artifact cannot run | debug: expected vs observed |
| `NeedsOperator` | stopped safely; a person is needed | look, with the context carried |

There is deliberately **no `Recoverable`**: a recovered condition is not a
terminal state. If recovery works the run ends `Success`; if not, it escalates.
