"""The seam where a queue would attach, and the one runner that exists."""

from __future__ import annotations

import inspect
from pathlib import Path

from interfaceai import jobs
from interfaceai.capabilities import LOG_IN


def test_NOTHING_implements_JobQueue_and_that_is_the_design() -> None:
    """§7 names queues as unrewarded infrastructure; §3.7 wants the seam anyway.

    A Protocol with no implementer is a documented contract. A class whose
    methods raise `NotImplementedError` is a call site waiting to happen —
    `project.md` has the scar from shipping three constants before anything ran
    once, each with a confident docstring nobody could falsify.

    So this asserts the ABSENCE. If someone adds a queue, they delete this test
    deliberately rather than discovering the rule in review.
    """
    implementers = [
        obj
        for _, obj in inspect.getmembers(jobs, inspect.isclass)
        if obj is not jobs.JobQueue and hasattr(obj, "submit") and hasattr(obj, "cancel")
    ]
    assert not implementers, f"something implements JobQueue: {implementers}"


def test_the_runner_is_reached_through_the_PROTOCOL_shape() -> None:
    """`InProcessRunner` satisfies `JobRunner` structurally, not by inheriting.

    Protocols are structural on purpose: a second runner does not have to
    import ours to be one.
    """
    runner = jobs.InProcessRunner(
        evidence_root=Path("evidence"), maps_root=Path("control_maps"), replay_fn=lambda *a, **k: k
    )
    assert isinstance(runner, jobs.JobRunner) or hasattr(runner, "run")
    assert inspect.signature(jobs.JobRunner.run).parameters.keys() == {"self", "request"}


def test_a_JobRequest_carries_what_a_CALLER_asked_for_and_no_wiring() -> None:
    """The split a queue depends on.

    A `JobRequest` must be serialisable — it is what would go on the wire. If
    it carried the control-map store or a browser, a queue could never send it,
    which is exactly the corner §3.7 says not to paint yourself into.
    """
    request = jobs.JobRequest(capability=LOG_IN, params={"a": "b"}, requested_by="agent:x")
    fields = set(request.__dataclass_fields__)
    assert fields == {"capability", "params", "tenant", "requested_by", "confirm_risky"}
    for forbidden in ("store", "surface", "vision", "operator", "secrets"):
        assert forbidden not in fields, f"{forbidden} is WIRING, not a request"


def test_job_status_words_are_not_outcome_words() -> None:
    """A job is queued or running; a RUN succeeds or needs a person.

    Collapsing the two is how a caller ends up branching on "pending" as though
    it were an answer — the same mistake a `Recoverable` outcome would have
    been.
    """
    from interfaceai.outcomes import BusinessOutcome, Failed, NeedsOperator, Success

    statuses = {s.value for s in jobs.JobStatus}
    outcomes = {c.__name__.lower() for c in (Success, BusinessOutcome, Failed, NeedsOperator)}
    assert not statuses & outcomes
