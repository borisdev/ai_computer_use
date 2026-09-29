"""Requested work, and the seam where a queue would attach.

⚠️ `job` is not a new word. The original schema had it: **a job is requested
work; a run is an attempt.** That distinction was cut with the SQLite layer and
is reintroduced here as the CLI's noun, because it is what a caller asks for —
"run `read_savings_balance` for this tenant" — while a *run* is what the engine
produces trying.

⛔ `JobQueue` IS DECLARED AND NOTHING IMPLEMENTS IT. That is the point.

§7: *"Designing your core abstractions so they could scale to the real
environment is valuable; prematurely building that infrastructure is not"* —
and it names queues specifically. §5: *"mock it deliberately and document what
you mocked and why."* §3.7: *"the core abstractions not to paint you into a
corner."*

So the seam is expressed as a TYPE rather than as a class whose methods raise.
A Protocol with no implementer is a documented contract; a method raising
`NotImplementedError` is a call site waiting to happen, and `project.md` has the
scar from shipping three constants before anything ran once.

This repo already does exactly this twice: `Surface` is a Protocol and there is
no `DesktopSurface` raising anything; `Operator` is a Protocol and the console
is mocked by `TerminalOperator` being *minimal*, not by a `WebOperator` that
raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from interfaceai.capability import Capability
from interfaceai.outcomes import CapabilityResult


@dataclass(frozen=True)
class JobRequest:
    """What a caller asked for. Everything needed to run it, and nothing more.

    ⚠️ `requested_by` is EVIDENCE, never a branch. A developer at a terminal, a
    test, and an agent calling this as a library must produce the same run —
    what differs is who to ask when it stops, and that arrives as `operator`.
    """

    capability: Capability
    params: dict[str, str] = field(default_factory=dict)
    tenant: str | None = None
    requested_by: str = "cli"
    confirm_risky: bool = False


class JobStatus(StrEnum):
    """⛔ For `JobQueue` only. Nothing produces these yet.

    Deliberately NOT the same words as `CapabilityResult`. A job is queued or
    running; a *run* succeeds or needs a person. Collapsing the two is how a
    caller ends up branching on "pending" as though it were an answer — the
    same mistake `Recoverable` would have been.
    """

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"


@runtime_checkable
class JobRunner(Protocol):
    """Runs a job NOW, in this process. The only half that is implemented.

    ⚠️ `runtime_checkable` only checks that the METHOD EXISTS -- it does not
    check the signature. `isinstance(x, JobRunner)` passing means `x.run` is
    there, not that it takes a `JobRequest`. Real conformance is the type
    checker's job; this is a guard rail for a caller holding an object it did
    not construct.
    """

    def run(self, request: JobRequest) -> CapabilityResult: ...


class JobQueue(Protocol):
    """⛔ DESIGNED, NOT BUILT — §7 names queues as unrewarded infrastructure.

    Declared so the seam is visible and typed. The whole change when a queue
    arrives is that `submit` returns a `JobId` which later resolves to the same
    `CapabilityResult` `run` returns today — `JobRunner` does not change, and
    neither does anything above it. That is what "not painted into a corner"
    means concretely.

    ⚠️ Nothing implements this. Adding a class whose methods raise would turn a
    documented contract into a call site waiting to happen.
    """

    def submit(self, request: JobRequest) -> str: ...

    def status(self, job_id: str) -> JobStatus: ...

    def result(self, job_id: str) -> CapabilityResult | None: ...

    def cancel(self, job_id: str) -> None: ...


@dataclass
class InProcessRunner:
    """The one `JobRunner`: replay, here, now, blocking.

    A thin adapter and deliberately so — it exists to give the Protocol a real
    caller, not to add behaviour. Everything it holds is the wiring a job needs
    and a `JobRequest` should not carry: where evidence goes, which control
    maps, how to reach a model.
    """

    evidence_root: Path
    maps_root: Path
    replay_fn: object  # `replay.replay`; a Protocol here would be ceremony
    wiring: dict[str, object] = field(default_factory=dict)

    def run(self, request: JobRequest) -> CapabilityResult:
        return self.replay_fn(  # type: ignore[operator]
            request.capability,
            request.params,
            evidence_root=self.evidence_root,
            confirm_risky=request.confirm_risky,
            requested_by=request.requested_by,
            **self.wiring,
        )
