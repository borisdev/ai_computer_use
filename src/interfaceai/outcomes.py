"""What a capability run reports back. Assignment 3.3's result contract.

⛔ **Every variant here has at least one OBSERVED instance.** The brief names
three classes and six example conditions; naming a type for one we have never
produced would be inventing a guard for a failure nobody has seen, which is the
same mistake as a threshold with no measured effect.

The tally, from real runs (`tests/test_failure_modes.py` reproduces each):

    Success           8 acted steps across 3 discovery runs
    BusinessOutcome   2  account 99999 via capability 1 (LIVE, through the
                         whole replay path); account 54321 after `env break`
    Failed            6  landmark 0.8365 / anchor 0.8715 / anchor 0.0000 /
                         no rhythm / checkpoint 5022.93 != 1231.10 /
                         control `unresolved`
    NeedsOperator     1  the first discovery run escalated mid-login

⛔ **There is deliberately no `Recoverable` VARIANT**, and the reason sharpened
once one was actually built. A recovered condition is not a terminal state: if
recovery works the run ends `Success`, and if it does not it ends
`NeedsOperator`. Modelling it as a third result would make every successful run
ambiguous -- "did this succeed, or recover?" is answered by `Success.recovered`,
which names what was survived without pretending the run ended there.

Two conditions the brief names that ParaBank cannot produce at all -- a
permission denial from the application, and an unexpected dialog -- are cut and
recorded in `docs/failure-modes.md` rather than mocked.

## Why it mirrors `DiscoveryOutcome`

Discovery already returns `Success | Failure | PassToOperator`, and every layer
below returns a value or a typed refusal: `locate_control` has four statuses,
`extract_panel` raises `PanelNotFound`, `use_control` raises `NotAllowedError`.
This is the same shape named once at the top rather than invented a fifth time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class BusinessOutcomeKind(StrEnum):
    """Results the CALLER needs to hear, which are not failures.

    "No such member" is a legitimate answer, and conflating it with a crash is
    the mistake the brief's glossary calls out by name.
    """

    RECORD_NOT_FOUND = "record_not_found"


@dataclass(frozen=True)
class Success:
    """The capability ran and its checkpoints held.

    `recovered` names conditions the run hit and handled -- a lost session
    re-established, say. **A recovered condition is not a terminal outcome**,
    which is why there is no `Recoverable` variant: if recovery works the run
    SUCCEEDS, and if it does not the run escalates. The brief asks that the
    three classes be distinguished, and they are -- but one of them is a thing a
    run survives rather than a thing it ends as, and modelling it as a result
    would have made every successful run ambiguous.
    """

    outputs: dict[str, str]
    steps_run: int
    evidence_dir: Path | None = None
    recovered: tuple[str, ...] = ()


@dataclass(frozen=True)
class BusinessOutcome:
    """The application gave a legitimate negative answer. Not an error.

    Observed: after `interfaceai env break`, account 54321 no longer exists and
    ParaBank renders `Could not find account #54321` -- as **HTTP 200 with plain
    text**, so a status-code check cannot detect it (`docs/parabank.md` §8).
    """

    kind: BusinessOutcomeKind
    detail: str
    steps_run: int
    evidence_dir: Path | None = None


@dataclass(frozen=True)
class Failed:
    """A checkpoint was violated, or a step could not be carried out.

    `expected` and `observed` are both required because the failure that matters
    most -- account 13344 reading `5022.93` where the recording said `1231.10` --
    is only debuggable as a pair. A bare "checkpoint failed" would have been
    indistinguishable from a not-found.
    """

    step_index: int
    step: str
    expected: str
    observed: str
    evidence_dir: Path | None = None


@dataclass(frozen=True)
class NeedsOperator:
    """Stopped, safely, and a human has to look (assignment 3.6).

    Not a failure: being stuck is a legitimate result. Carries enough to act on
    -- which step, what state, and why it stopped.

    Seven triggers exist in the discovery loop and **six need no model
    judgement**: a guardrail refusal, a decision refused because the control is
    `unresolved`, a locate that came back `not_found` or `ambiguous`, an
    irreversible step that nobody confirmed, an unknown secret ref, and a
    malformed move. Only "the model says it is stuck" depends on the model.
    """

    why: str
    step_index: int
    screen: str
    frame: Path | None = None
    evidence_dir: Path | None = None
    # What was already done before stopping, so a human can resume rather than
    # restart. Resume re-checks preconditions first -- it is never "continue
    # from line N", because the operator may have navigated anywhere.
    completed_steps: tuple[str, ...] = field(default_factory=tuple)


CapabilityResult = Success | BusinessOutcome | Failed | NeedsOperator


def is_actionable_by_caller(result: CapabilityResult) -> bool:
    """True when the agent-facing product can just use the answer.

    `Success` and `BusinessOutcome` are both answers. The other two are not.
    """
    return isinstance(result, Success | BusinessOutcome)
