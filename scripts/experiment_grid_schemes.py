"""Do margin labels (A1 style) beat numbers-in-cells for cell assignment?

Answer, measured 2026-09-26 against gpt-4.1: no, and neither works.

    exact cell    current 3/15   A1+lines 0/15   A1+ticks 0/15
    row only             --      A1+lines 6/15   A1+ticks 3/15

Five targets on ParaBank's overview, three runs each, DOM oracle for truth.
Committed because it is the experiment behind "stop using cell assignment for
positioning" in docs/issues/0009, and because a scratch script that proves a
design decision is a decision nobody can re-check.

    uv run python3 scripts/experiment_grid_schemes.py     # ~45 model calls
"""

import asyncio
import io
import string
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel

from interfaceai.screenshot2controls import _decode, _grid_overlay
from interfaceai.vision_llm import call_vision_llm

CELL, GUTTER = 80, 34
RAW = Path("evidence/runs/20260926T022551Z/frames/004-03-overview.png").read_bytes()
shot = Image.open(io.BytesIO(RAW)).convert("RGB")

TARGETS = [
    ("account link 13344", (508, 609)),
    ("account link 12345", (508, 357)),
    ("Transfer Funds nav link", (375, 364)),
    ("Log Out nav link", (375, 484)),
    ("Open New Account nav link", (375, 316)),
]


def margin_grid(with_lines):
    c = Image.new("RGB", (shot.width + GUTTER, shot.height + GUTTER), "white")
    c.paste(shot, (GUTTER, GUTTER))
    d = ImageDraw.Draw(c)
    for i in range(shot.width // CELL + 1):
        x = GUTTER + i * CELL
        d.text((x + CELL // 2 - 4, 10), string.ascii_uppercase[i], fill="#c00000")
        d.line((x, GUTTER - 6, x, GUTTER), fill="#c00000", width=2)
        if with_lines:
            d.line((x, GUTTER, x, c.height), fill="#ffc0c0", width=1)
    for i in range(shot.height // CELL + 1):
        y = GUTTER + i * CELL
        d.text((8, y + CELL // 2 - 6), str(i + 1), fill="#c00000")
        d.line((GUTTER - 6, y, GUTTER, y), fill="#c00000", width=2)
        if with_lines:
            d.line((GUTTER, y, c.width, y), fill="#ffc0c0", width=1)
    return c


overlay_png, cells = _grid_overlay(_decode(RAW, "s"), CELL)


def png(i):
    b = io.BytesIO()
    i.save(b, "PNG")
    return b.getvalue()


LINES, TICKS = png(margin_grid(True)), png(margin_grid(False))


class Ans(BaseModel):
    cell: str


async def ask(image, fmt, what, n=3):
    q = (
        f"Which grid cell contains the {what}? The grid is annotation drawn by our "
        f"tooling, not page content. Answer with the cell {fmt}."
    )
    outs = await asyncio.gather(
        *(call_vision_llm(prompt=q, image_png=image, response_model=Ans) for _ in range(n)),
        return_exceptions=True,
    )
    return [("ERR" if isinstance(o, Exception) else o.cell.strip().upper()) for o in outs]


async def main():
    scores = {"current": [0, 0], "A1 lines": [0, 0], "A1 ticks": [0, 0]}
    rowhits = {"A1 lines": [0, 0], "A1 ticks": [0, 0]}
    for what, (tx, ty) in TARGETS:
        tid = next(
            i for i, b in cells.items() if b.x <= tx < b.x + b.width and b.y <= ty < b.y + b.height
        )
        a1 = f"{string.ascii_uppercase[tx // CELL]}{ty // CELL + 1}"
        print(f"\n{what}   truth: cell {tid} / {a1}")
        for label, img, fmt, truth in (
            ("current", overlay_png, "number shown in that cell", str(tid)),
            ("A1 lines", LINES, "as a column letter and row number, e.g. C4", a1),
            ("A1 ticks", TICKS, "as a column letter and row number, e.g. C4", a1),
        ):
            got = await ask(img, fmt, what)
            hit = sum(1 for g in got if g == truth)
            scores[label][0] += hit
            scores[label][1] += len(got)
            if label != "current":
                rh = sum(1 for g in got if g[1:] == truth[1:])
                rowhits[label][0] += rh
                rowhits[label][1] += len(got)
            print(f"   {label:9s} {got!s:34s} {hit}/3")
    print("\n=== exact cell ===")
    for k, (h, n) in scores.items():
        print(f"  {k:9s} {h:2d}/{n}")
    print("=== ROW only (A1 schemes) ===")
    for k, (h, n) in rowhits.items():
        print(f"  {k:9s} {h:2d}/{n}")


asyncio.run(main())
