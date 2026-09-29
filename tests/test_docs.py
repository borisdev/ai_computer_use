"""Claims the documents make about themselves, checked.

Not prose review — the handful of statements that are mechanically falsifiable
and that went wrong anyway. Every one of these corresponds to a real defect
found on PR #5, mostly by Copilot, mostly in a sentence someone retyped.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "REPORT.md", "HANDOFF.md")


def _stated_counts() -> dict[str, tuple[int, int, int]]:
    patterns = (
        re.compile(r"(\d+) tests? [—-] (\d+) offline, (\d+) live"),
        re.compile(r"(\d+) tests \((\d+) offline, (\d+) live\)"),
    )
    found: dict[str, tuple[int, int, int]] = {}
    for name in DOCS:
        text = (ROOT / name).read_text()
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                found[name] = tuple(int(g) for g in match.groups())  # type: ignore[assignment]
                break
    return found


def test_every_document_states_the_SAME_test_count() -> None:
    """⚠️ Three documents stated 247, 249 and 257 simultaneously.

    In the same commit where HANDOFF.md gained a warning about stale counts.
    Found by Copilot on PR #5's third pass.

    This checks only that they AGREE, which is static and costs nothing.
    Whether they are RIGHT needs a collection run, which is
    `scripts/sync_test_counts.py --check`.
    """
    stated = _stated_counts()
    assert len(stated) == len(DOCS), f"no count found in {sorted(set(DOCS) - set(stated))}"
    unique = set(stated.values())
    assert len(unique) == 1, f"documents disagree: {stated}"


def test_the_stated_total_is_its_own_parts() -> None:
    """A total that is not offline + live is wrong however fresh it is."""
    for name, (total, offline, live) in _stated_counts().items():
        assert total == offline + live, f"{name}: {offline} + {live} != {total}"


def test_every_CLI_command_the_docs_show_actually_exists() -> None:
    """⚠️ `interfaceai diagram <name>` was DEAD on main while two documents
    told a reader to run it.

    Adding a `language` command put its `@app.command` decorator between
    `@app.command("diagram")` and `diagram_cmd`, so both names bound to the new
    function and `diagram_cmd` had none. The CLI still started, `language`
    still worked, and the offline suite stayed green -- nothing exercised the
    command list. Found by trying to USE it.

    This reads the command names off the Typer app rather than running the CLI,
    so it is fast and still catches a decorator that moved.
    """
    import re

    from interfaceai.cli import app

    registered = {c.name or c.callback.__name__ for c in app.registered_commands}
    registered |= {g.name for g in app.registered_groups}

    documented: set[str] = set()
    for name in ("README.md", "REPORT.md"):
        for verb in re.findall(r"interfaceai ([a-z][a-z-]*)", (ROOT / name).read_text()):
            documented.add(verb)

    missing = sorted(documented - registered)
    assert not missing, f"documented but not a command: {missing} (have: {sorted(registered)})"
