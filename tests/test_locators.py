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


def test_a_locator_written_BEFORE_the_discriminator_still_loads() -> None:
    """Backward compatibility is the whole reason `kind` has a default.

    ⚠️ This used to read a committed control map and assert it had NO `kind`
    field. That passed until panel discovery regenerated the maps, and then it
    failed on CORRECT behaviour — the test depended on a fixture staying stale
    rather than on the property it was about. A check that goes red when the
    repo improves is a check that gets deleted.

    So the legacy shape is constructed here instead. Without the default, every
    control map written before the union became unreadable on the commit that
    introduced it.
    """
    from interfaceai.screenshot2controls import VisualLocator

    legacy = {
        "schema_version": 1,
        "template_png": "",
        "reference_size": {"width": 1280, "height": 900},
        "reference_crop": {"x": 0, "y": 0, "width": 10, "height": 10},
        "click_offset": {"x": 5, "y": 5},
    }
    assert "kind" not in legacy
    assert VisualLocator.model_validate(legacy).kind == "visual"


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
