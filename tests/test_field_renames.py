"""Fields that were renamed, and the call sites a merge can silently miss.

⛔ WHY THIS FILE EXISTS. `Acted.url` became `Acted.location`, and one call site
in `discover.py` kept the old name. **320 tests passed.** The bug reached
`main` and `interfaceai discover` raised `AttributeError` on its first real
use — found by running a command for the README, not by the suite.

Two branches had touched `discover.py`: one renamed the field, the other added
panel discovery. Git merged them textually, and neither side was wrong on its
own. That is the shape a type checker catches and a test suite does not, unless
the suite exercises the line — and discovery's action-recording path is LIVE
only, so it never ran offline.

These tests are static: they read the source. That is the point — they cost
nothing and they cover the paths a live suite skips.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "interfaceai"

# field name -> the dataclasses that no longer have it
RENAMED = {"url": ("Acted", "HumanAction", "InterventionRequest")}


# Receivers whose `.url` belongs to someone else's API. Playwright's `Page.url`
# is a real attribute and always will be; flagging it would make this check
# noise, and a noisy check gets deleted.
FOREIGN = {"self.page", "page", "response", "request.url"}


def test_no_source_file_reads_a_renamed_field() -> None:
    """`x.url` on one of OUR objects is a rename that did not finish.

    ⚠️ Narrowed after its first run flagged `self.page.url` — Playwright's own
    API. A check that fires on correct code is one nobody keeps. `base_url` is
    also a real, different field and is not matched, because this reads
    attribute ACCESS rather than substrings.
    """
    offenders: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text()
        for node in ast.walk(ast.parse(text)):
            if not (isinstance(node, ast.Attribute) and node.attr in RENAMED):
                continue
            receiver = ast.get_source_segment(text, node.value) or ""
            if receiver in FOREIGN:
                continue
            offenders.append(f"{path.name}:{node.lineno}  {receiver}.{node.attr}")
    assert not offenders, (
        "a renamed field is still read:\n  "
        + "\n  ".join(offenders)
        + f"\n\nrenamed away from: {RENAMED}\n"
        "If the receiver is a third-party object, add it to FOREIGN."
    )


def test_the_dataclasses_really_dropped_it() -> None:
    """Guards the guard: if `url` came back, the test above means nothing."""
    from interfaceai.handoff import HumanAction, InterventionRequest
    from interfaceai.surface import Acted

    for cls in (Acted, HumanAction, InterventionRequest):
        fields = set(cls.__dataclass_fields__)
        assert "location" in fields, f"{cls.__name__} lost `location`"
        assert "url" not in fields, f"{cls.__name__} has `url` again — update RENAMED"
