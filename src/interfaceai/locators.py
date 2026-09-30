"""How a control is FOUND. The seam §2.2 asks for, and the one kind that exists.

> *"The surface may be a browser, but treat that as one case of a more general
> 'computer use' problem (accessibility tree, screenshot + coordinates,
> OS-level automation, etc. are all fair game)."* — §2.2

⛔ THE AXIS OF VARIATION IS THE LOCATOR, NOT THE SURFACE. This is worth being
exact about because the obvious reading is wrong.

`Surface` is a PIXEL surface -- every method takes or returns pixels and
coordinates: `screenshot() -> bytes`, `left_click(x, y)`, `zoom(x0,y0,x1,y1)`.
There is no `find` and no selector. So:

    browser screen  ->  desktop screen     SAME Surface, SAME locator language,
                                           nothing above changes. This is the
                                           real portability, and it is why the
                                           design chose pixels over the DOM.

    browser DOM, accessibility tree        NOT different surfaces. A Chromium
                                           surface can screenshot AND query the
                                           DOM -- they are ADDITIVE. What
                                           differs is how you FIND the control.

⚠️ And an API is **not** a surface at all: §1 says *"when a system exposes an
API, we integrate through the API -- that's always the preferred path and is
out of scope here."*

⭐ SO THE SEAM IS A DISCRIMINATED UNION ON `kind`, and only `visual` is built.
Same pattern as `JobQueue` in `jobs.py`: the contract is declared in the type
system, where nothing can call it by accident, rather than as a class whose
methods raise.

`DomLocator` below is a **declared shape with a deliberately useless
resolver**, kept because it is the counter-example that makes the trade
legible: a DOM locator survives the reskin that kills 17 of our 25 visual ones,
and cannot replay against a desktop app at all. Neither wins; they fail in
opposite directions.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import Field

from interfaceai.contracts import Contract


@runtime_checkable
class Locator(Protocol):
    """What every locator kind must answer: *is this control here, and where?*

    ⚠️ `kind` is a `Literal` on each member, so a serialised locator says which
    it is and Pydantic can discriminate a union without guessing. A locator
    that does not say what it is cannot be safely read back from an artifact.
    """

    kind: str


class DomLocator(Contract):
    """⛔ DECLARED, NOT BUILT. A CSS selector, for a surface with a clean DOM.

    Kept as the counter-example rather than as a feature:

        survives a tenant REBRAND        ✅  a selector does not care about pixels
        survives a DOM refactor          ❌  one renamed class and it is gone
        works on a DESKTOP app           ❌  there is no DOM to query
        works with no test ids           ❌  ParaBank has none, which is why
                                             this project uses pixels

    ADR 0002 forbids the agent and replay paths from using the DOM, and that
    stands -- a DOM recording cannot replay against a desktop app, which is the
    whole point of the `Surface` seam. This type exists so the union has a
    second member and the trade is visible in the code rather than only in
    prose. `resolve_dom` refuses.
    """

    kind: Literal["dom"] = "dom"
    selector: str = Field(min_length=1)
    # Which frame, for the framesets a legacy app is full of.
    frame: str | None = None


def resolve_dom(locator: DomLocator) -> None:
    """⛔ Refuses, and the refusal is the documentation.

    A stub that RETURNED something would let a caller believe a DOM locator
    works here. `project.md`: an abstraction with no caller is speculation with
    tests, and a method that quietly succeeds is worse than one that is absent.
    """
    raise NotImplementedError(
        f"DomLocator({locator.selector!r}) is a declared shape, not an implementation. "
        "ADR 0002 keeps the DOM out of the agent and replay paths -- a DOM recording "
        "cannot replay against a desktop app. Tests may use the DOM as an ORACLE."
    )
