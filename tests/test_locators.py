"""The locator seam: one kind built, one declared, and the trade made visible."""

from __future__ import annotations

import pytest

from interfaceai.locators import DomLocator, Locator, resolve_dom


def test_a_serialised_locator_says_WHICH_KIND_it_is() -> None:
    """A union that can only be one thing still has to say so.

    ⚠️ Otherwise an artifact written today cannot be read back once there are
    two kinds — the discriminator has to be there BEFORE the second member,
    not added with it.
    """
    from interfaceai.screenshot2controls import VisualLocator

    fields = VisualLocator.model_fields
    assert "kind" in fields
    assert DomLocator(selector="#login").kind == "dom"


def test_existing_control_maps_load_without_a_kind_field() -> None:
    """The committed maps predate the discriminator and must still resolve.

    A default is what makes adding a discriminator a non-event. Without it,
    every control map in the repo becomes unreadable on the commit that
    introduces the union.
    """
    import json
    from pathlib import Path

    from interfaceai.screenshot2controls import VisualLocator

    maps = Path(__file__).resolve().parents[1] / "control_maps"
    raw = json.loads((maps / "parabank" / "baseline" / "index.json").read_text())
    locator = next(
        c["locator"] for c in raw["controls"] if c.get("locator") and c["status"] == "ready"
    )
    assert "kind" not in locator, "fixture no longer exercises the missing-field case"
    assert VisualLocator.model_validate(locator).kind == "visual"


def test_the_DOM_kind_refuses_rather_than_pretending() -> None:
    """A stub that RETURNED something would let a caller believe it works.

    §2.2 calls an accessibility tree "fair game", so the seam is real. ADR 0002
    keeps the DOM out of the agent and replay paths, so the implementation is
    not. Both are true, and the refusal is what says so at the call site
    instead of only in prose.
    """
    with pytest.raises(NotImplementedError, match="declared shape"):
        resolve_dom(DomLocator(selector="#username"))


def test_both_kinds_satisfy_the_Locator_protocol_structurally() -> None:
    """A second locator does not have to import ours to be one."""
    from interfaceai.screenshot2controls import VisualLocator

    assert isinstance(DomLocator(selector="#x"), Locator)
    assert "kind" in VisualLocator.model_fields
