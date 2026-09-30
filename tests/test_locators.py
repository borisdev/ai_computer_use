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


def test_a_locator_written_before_the_discriminator_still_loads() -> None:
    """The maps written before the discriminator must still resolve.

    A default is what makes adding a discriminator a non-event. Without it, every
    control map in the repo becomes unreadable on the commit that introduces the
    union.

    ⚠️ **This owned no fixture until it broke.** It used to read a LIVE control map
    and assert `"kind" not in locator` — true only until something legitimately
    rewrote that map, because writing one through the model serialises the
    discriminator in. Re-running panel discovery normalised every map and the test
    reported *"fixture no longer exercises the missing-field case"*, which is the
    assertion doing its job and the fixture being in the wrong place. A
    backward-compatibility test has to carry the old shape itself; a file the
    system writes cannot be relied on to stay old.
    """
    from interfaceai.screenshot2controls import ClickPoint, CropBox, ImageSize, VisualLocator

    written_before_the_union = {
        "schema_version": 1,
        "template_png": "",
        "reference_size": ImageSize(width=1280, height=900).model_dump(),
        "reference_crop": CropBox(x=246, y=250, width=240, height=96).model_dump(),
        "click_offset": ClickPoint(x=120, y=64).model_dump(),
        "match_threshold": 0.95,
        "ambiguity_margin": 0.05,
    }
    assert "kind" not in written_before_the_union
    assert VisualLocator.model_validate(written_before_the_union).kind == "visual"


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
