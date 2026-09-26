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
from interfaceai.screenshot2controls import LocatedControl, ScreenOutput

# Keys become path segments, so they may not contain separators or dots.
_SAFE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


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

    def check_ref(ref: ControlRef, where: str, verb: StepVerb | None) -> None:
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
            if action not in supported_actions(control.role):
                faults.append(
                    f"{where}: {ref.control_id} is a {control.role}, which does not accept {action}"
                )

    for precondition in capability.requires:
        check_ref(precondition.control, f"precondition {precondition.name!r}", None)

    for n, step in enumerate(capability.steps):
        if step.control is not None:
            check_ref(step.control, f"step {n} ({step.verb})", step.verb)

    return faults
