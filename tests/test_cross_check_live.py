"""Geometry proposes, perception verifies — and a disagreement stops the run.

`live` — needs ParaBank up and seeded, and spends model calls.

The row position is computed from an autocorrelated pitch. The same panel call
that reads the table is also asked which numbered band each row sits inside, so
the model independently confirms the positions we computed. Zero extra calls.

⚠️ **Not a second algorithm.** One band per row needs the pitch, so the band
pass is downstream of the autocorrelation. What the model supplies is a
CONFIRMATION of what we computed, which is stronger than recomputing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interfaceai import parabank
from interfaceai.control_map_store import ControlMapStore, MapKey
from interfaceai.settings import get_settings
from interfaceai.surface import OffLoop, PlaywrightSurface
from interfaceai.table import Offset, extract_panel
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
KEY = MapKey(app="parabank", tenant="baseline", screen="overview")

pytestmark = pytest.mark.live


@pytest.fixture
def overview_screenshot():
    settings = get_settings()
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().init_db()
    with PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface:
        page = surface.page
        surface.navigate(f"{settings.parabank_base_url}/index.htm")
        page.fill("input[name='username']", settings.parabank_demo_username)
        page.fill("input[name='password']", settings.parabank_demo_password.get_secret_value())
        page.click("input[value='Log In']")
        page.wait_for_load_state("networkidle")
        page.goto(f"{settings.parabank_base_url}/overview.htm")
        page.wait_for_load_state("networkidle")
        surface.wait(1.0)
        yield surface.screenshot()


def _read(screenshot: bytes, *, key_height: int | None = None, pitch: int | None = None):
    panel = ControlMapStore(ROOT / "control_maps").control(KEY, "accounts_table_panel")
    spec = panel.panel
    assert spec is not None
    key = Offset(
        dx=spec.key_dx,
        dy=spec.key_dy,
        width=spec.key_width,
        height=key_height or spec.height,
    )
    with OffLoop() as off:
        return off.run(
            extract_panel(
                screenshot,
                panel.locator,
                panel=Offset(dx=spec.dx, dy=spec.dy, width=spec.width, height=spec.height),
                key_column=key,
                columns=spec.columns,
                key_column_name=spec.key_column,
                vision=call_vision_llm,
                row_pitch=pitch or spec.row_pitch,
            )
        )


def test_the_measured_pitch_agrees_with_what_the_model_sees(overview_screenshot) -> None:
    read = _read(overview_screenshot)
    assert read.rhythm is not None and read.rhythm.pitch == 28
    assert len(read.data.rows) == 11
    assert read.misaligned == (), read.misaligned
    assert read.cross_checked


def test_a_HARMONIC_pitch_is_caught(overview_screenshot) -> None:
    """The failure this guard exists for, forced and observed.

    Zebra striping makes autocorrelation return twice the row pitch — measured,
    real, and pinned in `tests/test_table.py`. ParaBank's per-row content is
    strong enough that it does not happen here, so it is forced: a key column
    too SHORT to autocorrelate falls back to a recorded pitch, and 56 is handed
    in.

    ⚠️ The forced column keeps its x and y. An earlier version moved it 420px
    right, which made the margin 440px and painted the bands over the whole
    table — 0 rows read, and a green result for the wrong reason.
    """
    read = _read(overview_screenshot, key_height=12, pitch=56)
    assert read.rhythm is not None and read.rhythm.pitch == 56
    assert len(read.data.rows) == 11, "the table must still be READABLE"
    assert read.misaligned, "a doubled pitch must not pass the cross-check"
    assert len(read.misaligned) >= 8, read.misaligned
    assert "pitch or phase is wrong" in read.misaligned[0]


def test_reading_still_works_when_the_geometry_is_wrong(overview_screenshot) -> None:
    """The disagreement is about POSITION, not content.

    Values come from the model and are still trustworthy; only a click computed
    from the disputed geometry is not. `replay` acts on that distinction —
    extraction proceeds, drilling does not.
    """
    read = _read(overview_screenshot, key_height=12, pitch=56)
    ids = {r.account_id for r in read.data.rows}
    assert "13344" in ids
    assert len(ids) == 11
