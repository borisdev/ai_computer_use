"""Reading the evidence back — §3.2's human half and §3.5's other end.

The reader has to be at least as careful as the writer. Two bugs here made a
run look like something it was not, and both are pinned below.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interfaceai import capabilities
from interfaceai.capability import Approval
from interfaceai.status import as_markdown, as_mermaid, read_artifacts, read_runs

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, name: str, events: list[dict]) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    (directory / "trace.jsonl").write_text(
        "\n".join(json.dumps({"ts": "2026-09-28T12:00:00", **e}) for e in events) + "\n"
    )
    return directory


# --- the two bugs ----------------------------------------------------------


def test_an_INVOKED_success_does_not_make_a_failed_parent_look_successful(
    tmp_path: Path,
) -> None:
    """The bug that made `request_loan` — which always escalates — read SUCCESS.

    An invoked capability writes into the same evidence file. Its
    `replay_succeeded` is not the run's verdict.
    """
    _run(
        tmp_path,
        "20260928T120000Z",
        [
            {"event": "replay_started", "capability": "request_loan"},
            {"event": "invoke_started", "capability": "log_in"},
            {"event": "replay_succeeded", "capability": "log_in", "outputs": {}},
            {"event": "invoke_finished", "capability": "log_in"},
            {"event": "replay_finished", "capability": "request_loan", "outcome": "NeedsOperator"},
        ],
    )
    (row,) = read_runs(tmp_path)
    assert row.outcome == "needs_human"
    assert row.capability == "request_loan"


def test_a_run_that_ended_without_an_operator_is_not_reported_as_incomplete(
    tmp_path: Path,
) -> None:
    """`NeedsOperator` with no operator attached emitted no terminal event, so
    the reader called it "incomplete" — which reads like a crash. The run now
    states its own verdict."""
    _run(
        tmp_path,
        "20260928T120000Z",
        [
            {"event": "replay_started", "capability": "read_savings_balance"},
            {"event": "replay_finished", "capability": "read_savings_balance", "outcome": "Failed"},
        ],
    )
    (row,) = read_runs(tmp_path)
    assert row.outcome == "FAILED"


# --- reading outcomes ------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("Success", "SUCCESS"),
        ("BusinessOutcome", "business_outcome"),
        ("Failed", "FAILED"),
        ("NeedsOperator", "needs_human"),
    ],
)
def test_every_result_variant_reads_back(tmp_path: Path, outcome: str, expected: str) -> None:
    _run(
        tmp_path,
        "20260928T120000Z",
        [
            {"event": "replay_started", "capability": "x"},
            {"event": "replay_finished", "capability": "x", "outcome": outcome},
        ],
    )
    assert read_runs(tmp_path)[0].outcome == expected


def test_a_recovered_run_does_not_read_like_a_clean_one(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "20260928T120000Z",
        [
            {"event": "replay_started", "capability": "probe"},
            {"event": "recovered", "condition": "session gone"},
            {
                "event": "replay_finished",
                "capability": "probe",
                "outcome": "Success",
                "recovered": ["session gone"],
            },
        ],
    )
    row = read_runs(tmp_path)[0]
    assert row.outcome == "SUCCESS"
    assert "recovered" in row.detail


def test_a_truncated_trace_says_so_rather_than_guessing(tmp_path: Path) -> None:
    """A run that crashed has no verdict, and inventing one would be worse."""
    _run(tmp_path, "20260928T120000Z", [{"event": "replay_started", "capability": "x"}])
    assert read_runs(tmp_path)[0].outcome == "incomplete"


def test_a_directory_with_no_trace_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "20260928T120000Z").mkdir()
    assert read_runs(tmp_path) == []


# --- artifacts -------------------------------------------------------------


def test_the_approved_copy_hides_the_draft_it_came_from() -> None:
    rows = read_artifacts(ROOT / "artifacts")
    versions = [(r.name, r.version) for r in rows]
    assert len(versions) == len(set(versions)), "one row per name+version"
    approved = {r.name for r in rows if r.approval is Approval.APPROVED}
    assert "read_savings_balance" in approved


def test_composition_is_visible_in_the_listing() -> None:
    rows = {(r.name, r.version): r for r in read_artifacts(ROOT / "artifacts")}
    assert "log_in" in rows[("read_savings_balance", 3)].invokes


# --- the generated page and diagram ---------------------------------------


def test_the_page_names_the_command_that_regenerates_it() -> None:
    page = as_markdown(read_artifacts(ROOT / "artifacts"), [], limit=5)
    assert "interfaceai status --markdown" in page
    assert "Do not edit by hand" in page


def test_the_diagram_is_read_from_the_artifact_so_it_cannot_drift() -> None:
    """Every node comes from a step. Nothing is hand-drawn.

    ⚠️ Assert on SUBSTANCE, not on formatting. This used to check the literal
    string "invoke log_in", which broke the moment the label gained `<b>` tags
    for styling -- a test that fails on a colour change is a test that will be
    deleted rather than read.
    """
    capability = capabilities.get("read_savings_balance")
    drawn = as_mermaid(capability)

    # the invoked child, its pinned version, and one node per step
    assert "log_in" in drawn and "v2" in drawn
    for step in capability.steps:
        if step.control is not None:
            assert step.control.control_id in drawn
    assert drawn.count("-->") >= len(capability.steps)

    # shape and colour carry the language, so the classes must actually be used
    assert ":::invoke" in drawn and ":::read" in drawn
    assert "classDef invoke" in drawn
