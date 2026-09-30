"""Where control maps live, so a capability can name a control instead of carrying it.

A capability step says `(screen, control_id)`. A **control map** — the
`ScreenOutput` that `extract_control_locators` produces — is what turns that
name into a `LocatedControl` with a `VisualLocator` behind it. Discovery
writes; replay reads.

    (app, tenant, screen)               -> ScreenOutput      what is persisted
    (app, tenant, screen, control_id)   -> LocatedControl    what a step asks for

Three decisions worth stating, because each is a way this could quietly do the
wrong thing:

**Tenant is a lookup dimension, never a fallback.** Tenant B missing a screen
is a miss, not a cue to serve tenant A's pixels. Template matching is the least
portable locator there is (`docs/findings.md` §3.7) — a rebranded tenant's
pixels differ, so a silent fallback would click confidently in the wrong place.
The whole point of keying by tenant is that a miss stays a miss.

**A miss says which key failed.** "No such screen for this tenant" and "no such
control on that screen" send you to different places. A bare `None` sends you
to neither.

**Lookups return the whole `LocatedControl`, not just the locator.** `role`
gates which actions are legal (`decisions.validate_decision` refuses typing
into a link) and `status` says whether discovery ever grounded it. Handing the
executor a locator alone would strip both checks.

### Naming, deliberately

`ScreenOutput` has been "the control map" since `controlmap.py`, and
`decisions.py` still takes a `control_map` parameter. This module reuses that
word rather than minting a synonym — `docs/parabank-screens.md` already spends
"screen map" on a different thing, the catalogue of 29 screens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from interfaceai.capability import Capability, ControlRef, StepVerb
from interfaceai.decisions import ManualActionKind, supported_actions
from interfaceai.screenshot2controls import (
    ControlRole,
    LocatedControl,
    ResolveInput,
    ScreenOutput,
    locate_control,
)

# Keys become path segments, so they may not contain separators or dots.
_SAFE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def panel_containing(control_map: ScreenOutput, control: LocatedControl) -> LocatedControl | None:
    """The panel whose region holds this control's click point, if any.

    ⚠️ **One implementation, two callers, deliberately.** The artifact check refuses
    a capability that names a row directly, and the DISCOVERY loop has to refuse
    the same decision while it is still a decision -- a model offered
    `13344_link` will take it, and catching that only after the run leaves an
    unapprovable draft and a wasted session (Copilot, #13/#14). Two copies of this
    geometry would eventually disagree about what a row is.
    """
    if control.click_point is None or control.role is ControlRole.TABLE_CONTROL_PANEL:
        return None
    for panel in control_map.controls:
        if panel.role is not ControlRole.TABLE_CONTROL_PANEL or panel.panel is None:
            continue
        if panel.click_point is None:
            continue
        spec, origin = panel.panel, panel.click_point
        x0, y0 = origin.x + spec.dx, origin.y + spec.dy
        if (
            x0 <= control.click_point.x <= x0 + spec.width
            and y0 <= control.click_point.y <= y0 + spec.height
        ):
            return panel
    return None


def row_instead_of_panel(panel: LocatedControl, control: LocatedControl) -> str:
    """Why a direct click on a row is refused, and what to do instead."""
    return (
        f"{control.id} sits inside {panel.id}'s region, so it is a ROW. Grounded rows "
        f"land on the wrong record 10 times in 11 (docs/issues/0009) -- reach it with a "
        f"row_key on {panel.id} instead"
    )


class ControlMapMiss(LookupError):
    """A lookup found nothing, and says which part of the key failed.

    A `LookupError` rather than a bare `ValueError` because a miss is an
    expected outcome of asking — the caller decides whether it is fatal.
    """


@dataclass(frozen=True)
class MapKey:
    app: str
    tenant: str
    screen: str

    def __post_init__(self) -> None:
        for field, value in (("app", self.app), ("tenant", self.tenant), ("screen", self.screen)):
            if not _SAFE.match(value):
                raise ValueError(f"{field}={value!r} is not a safe path segment")

    def __str__(self) -> str:
        return f"{self.app}/{self.tenant}/{self.screen}"


class ControlMapStore:
    """File-backed: one JSON per screen, under `<root>/<app>/<tenant>/<screen>.json`.

    A directory tree rather than a database because the maps are the thing a
    human most wants to look at when a replay goes wrong, and because
    `ScreenOutput` already round-trips through JSON with its template PNGs
    base64'd inline. If that stops scaling, the templates move to blobs and
    this interface does not change.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, key: MapKey) -> Path:
        return self.root / key.app / key.tenant / f"{key.screen}.json"

    # --- write -------------------------------------------------------------

    def put(self, key: MapKey, control_map: ScreenOutput) -> Path:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(control_map.model_dump_json(indent=2) + "\n")
        return path

    # --- read --------------------------------------------------------------

    def get(self, key: MapKey) -> ScreenOutput:
        path = self.path(key)
        if not path.exists():
            known = self.screens(key.app, key.tenant)
            raise ControlMapMiss(
                f"no control map for screen {key.screen!r} of {key.app}/{key.tenant}"
                + (f"; recorded screens: {', '.join(known)}" if known else "; nothing recorded")
            )
        return ScreenOutput.model_validate_json(path.read_text())

    def control(self, key: MapKey, control_id: str) -> LocatedControl:
        control_map = self.get(key)
        for control in control_map.controls:
            if control.id == control_id:
                return control
        raise ControlMapMiss(
            f"no control {control_id!r} on {key}; that screen has "
            f"{len(control_map.controls)}: {', '.join(c.id for c in control_map.controls)}"
        )

    # --- browse ------------------------------------------------------------

    def screens(self, app: str, tenant: str) -> list[str]:
        directory = self.root / app / tenant
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.json"))

    def tenants(self, app: str) -> list[str]:
        directory = self.root / app
        if not directory.is_dir():
            return []
        return sorted(p.name for p in directory.iterdir() if p.is_dir())


# ---------------------------------------------------------------------------
# Checking a capability against what was actually recorded
# ---------------------------------------------------------------------------
#
# `validate_capability` checks an artifact against itself and against the
# vocabulary. It cannot tell whether `account_link` will ever resolve, because
# that is a fact about recorded pixels, not about the artifact. This is the
# other half, and it is the reason to build the store before the executor:
# an unresolvable control name becomes an authoring-time fault instead of a
# surprise mid-replay on a bank screen.
#
# Collects every fault rather than raising on the first, because the caller is
# a person fixing a draft and one round trip per mistake is a bad trade.

_VERB_ACTIONS: dict[StepVerb, ManualActionKind] = {
    StepVerb.ENTER: ManualActionKind.ENTER_TEXT,
    StepVerb.CLICK: ManualActionKind.CLICK,
    StepVerb.SELECT: ManualActionKind.SELECT,
}


def check_capability(capability: Capability, store: ControlMapStore) -> list[str]:
    """Every fault between an artifact and the control maps it would replay against.

    Empty list means every control it names was recorded, was grounded, sits on
    a screen captured at the artifact's viewport, and accepts the action the
    step asks of it.
    """
    faults: list[str] = []
    target = capability.target

    def check_ref(
        ref: ControlRef, where: str, verb: StepVerb | None, row_key: object = None
    ) -> None:
        try:
            key = MapKey(app=target.app, tenant=target.tenant, screen=ref.screen)
        except ValueError as exc:
            faults.append(f"{where}: {exc}")
            return
        try:
            control_map = store.get(key)
            control = store.control(key, ref.control_id)
        except ControlMapMiss as exc:
            faults.append(f"{where}: {exc}")
            return

        # A coordinate only means anything relative to the viewport it was
        # recorded at, so a map captured at another size cannot serve this
        # artifact -- `locate_control` would report `incompatible` at runtime.
        size = control_map.image_size
        if (size.width, size.height) != (capability.viewport_width, capability.viewport_height):
            faults.append(
                f"{where}: {key} was recorded at {size.width}x{size.height}, "
                f"but the capability pins {capability.viewport_width}x{capability.viewport_height}"
            )

        # `unresolved` means discovery never grounded a click point. Acting on
        # it would mean clicking a coordinate we do not have.
        if control.status != "ready":
            faults.append(
                f"{where}: {ref.control_id} on {key} is {control.status} ({control.reason})"
            )

        if verb is not None and verb in _VERB_ACTIONS:
            action = _VERB_ACTIONS[verb]
            if control.role is ControlRole.TABLE_CONTROL_PANEL:
                # A panel is not clickable AT ITS ANCHOR -- that point means
                # nothing. It is drillable through a row key, which is a
                # different thing and gets its own check. Widening
                # ACTIONS_BY_ROLE instead would permit the meaningless click.
                if action is not ManualActionKind.CLICK or row_key is None:
                    faults.append(
                        f"{where}: {ref.control_id} is a panel -- it is read, or drilled "
                        f"into with a row_key, never {action}ed directly"
                    )
                elif control.panel is None or control.panel.key_click_dx is None:
                    faults.append(
                        f"{where}: {ref.control_id} does not declare key_click_dx, so its "
                        "rows are readable but not openable"
                    )
            elif action not in supported_actions(control.role):
                faults.append(
                    f"{where}: {ref.control_id} is a {control.role}, which does not accept {action}"
                )

    def check_not_inside_a_panel(ref: ControlRef, where: str) -> None:
        """Refuse a direct click on a control that lives inside a panel's region.

        ⚠️ This is what makes `docs/issues/0009` unreachable rather than merely
        unused. Grounding a table row lands on the WRONG row 10 times in 11 --
        re-measured 2026-09-28 against the DOM oracle, and A4's read/locate
        split did not help because the defect is in placement, not reading.

        Those controls are still in the map, still `ready`, and still wrong:
        `13344_link` is grounded at (500,523), which is inside 13011's row. A
        capability naming it would open another customer's account and report
        success.

        The test is geometric, not a guess about names: if the control's click
        point falls inside a TABLE_CONTROL_PANEL's region on the same screen,
        it is a row and must be reached with a `row_key` instead.
        """
        try:
            key = MapKey(app=target.app, tenant=target.tenant, screen=ref.screen)
            control_map = store.get(key)
            control = store.control(key, ref.control_id)
        except (ValueError, ControlMapMiss):
            return  # already reported by check_ref
        panel = panel_containing(control_map, control)
        if panel is not None:
            faults.append(f"{where}: {row_instead_of_panel(panel, control)}")

    for n, step in enumerate(capability.steps):
        if step.verb is StepVerb.CLICK and step.control is not None and step.row_key is None:
            check_not_inside_a_panel(step.control, f"step {n} (click)")

    for precondition in capability.requires:
        check_ref(precondition.control, f"precondition {precondition.name!r}", None)

    for n, step in enumerate(capability.steps):
        if step.control is not None:
            check_ref(step.control, f"step {n} ({step.verb})", step.verb, step.row_key)

    return faults


# ---------------------------------------------------------------------------
# Cross-tenant reuse (assignment 3.7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdoptionReport:
    """What happened when one tenant's control map was offered to another."""

    screen: str
    matched: tuple[str, ...]
    drifted: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.drifted

    def __str__(self) -> str:
        n = len(self.matched) + len(self.drifted)
        return f"{self.screen}: {len(self.matched)}/{n} locators matched"


def adopt_control_map(
    store: ControlMapStore,
    source: MapKey,
    target: MapKey,
    live_screenshot: bytes,
) -> AdoptionReport:
    """Reuse one tenant's map for another, but VERIFY every locator first.

    The 3.7 question is whether an artifact recorded for one institution works
    at another running the same vendor product. Copying the map blindly would
    answer "yes" for reasons nobody checked; this re-runs every locator against
    the target tenant's live screen and reports which ones actually match.

    Nothing is written when anything drifted. A partially-adopted map is worse
    than none: the drifted control fails at replay, far from the decision that
    caused it, and the run looks like an application problem.

    Measured 2026-09-27 for ParaBank `baseline` -> `feature`, two genuinely
    different image digests: **19/19 on the login screen, every one at 1.0000**.
    Same vendor build, unbranded, so the locators transfer exactly. A tenant
    that restyled its CSS would show up here as drift, which is the point --
    the check is what distinguishes the two cases.
    """
    control_map = store.get(source)
    matched: list[str] = []
    drifted: list[str] = []
    for control in control_map.controls:
        if control.status != "ready" or control.locator is None:
            continue
        found = locate_control(
            ResolveInput(screenshot_png=live_screenshot, locator=control.locator)
        )
        (matched if found.status == "matched" else drifted).append(control.id)

    report = AdoptionReport(screen=target.screen, matched=tuple(matched), drifted=tuple(drifted))
    if report.clean:
        store.put(target, control_map)
    return report
