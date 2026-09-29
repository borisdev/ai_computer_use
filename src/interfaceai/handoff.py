"""Human-in-the-loop: stop, hand over the live session, take it back (3.6).

The brief asks for four things, and the scope note says the operator UI may be
mocked so long as "the handoff mechanism and the control-transfer model" are
real:

    detect and route        an intervention request carrying enough to act on
    take the live session   the SAME browser, not a fresh one
    record what was done    every human action, in the run evidence
    hand control back       verify before resuming

## The mechanism, and the one thing that is mocked

The operator drives the live page through a **terminal console** rather than by
clicking in a window. Everything else is real: it is the same `PlaywrightSurface`
mid-run, the same page, the same session cookies, and the automation is genuinely
stopped while the human holds it.

⚠️ **Why not `page.pause()`**, which was the earlier plan and which Playwright
documents as opening Inspector with codegen controls: it requires a **headed**
browser, and the machine this runs on has no display. A demo that only works on
one laptop is not a demo. Recorded rather than quietly swapped.

Two honest consequences:

- **The human's actions go through the same action layer the agent uses**, which
  means they are recorded exactly and completely -- better evidence than
  Inspector's export, which the handoff bundle itself flagged as unvalidated.
- **The human cannot do something the surface cannot express.** A real console
  would let them do anything. This is the mock, and it is the cost.

## Ownership

`owner` is explicit and recorded: `worker` while automation runs, `human`
between pause and resume. Nothing physically prevents a second actor -- with a
headed browser a person could click during automation -- so this is a protocol
plus a recorded state, not an interlock. Stated here rather than implied.

## Resume is never "continue from line N"

The operator may have navigated anywhere. On resume the executor re-observes and
decides, in this order:

    postcondition of the failed step now met   -> advance past it
    precondition still met, action was safe    -> retry it
    anything uncertain                         -> stay paused

Only the first two resume. "Uncertain" includes any irreversible step whose
effect cannot be confirmed -- never blindly repeat a submission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from interfaceai.decisions import ManualActionKind
from interfaceai.surface import ActionPolicy, NotAllowedError, PlaywrightSurface, use_control


class Owner(StrEnum):
    WORKER = "worker"
    HUMAN = "human"


class Resolution(StrEnum):
    RESUMED = "resumed"
    ABORTED = "aborted"


@dataclass(frozen=True)
class InterventionRequest:
    """Everything a human needs to act, carried with the request (3.6)."""

    why: str
    capability: str
    step_index: int
    screen: str
    url: str
    completed_steps: tuple[str, ...]
    frame: Path | None = None


@dataclass
class HumanAction:
    """One thing the human did, through the same action layer the agent uses."""

    action: ManualActionKind
    x: int
    y: int
    url: str
    value_length: int | None = None  # never the value


@dataclass
class HumanResolution:
    resolution: Resolution
    actions: list[HumanAction] = field(default_factory=list)
    note: str = ""


@runtime_checkable
class Operator(Protocol):
    """Where an intervention goes. A terminal today; a console later.

    ⚠️ `adopt_policy` is not optional politeness. The RUN owns the gate; an
    operator that brings its own is an operator checked against different rules
    from the agent it is rescuing, which is exactly the hole Copilot found on
    PR #5 and exactly what the write-up claimed was impossible.
    """

    def adopt_policy(self, policy: ActionPolicy) -> None: ...

    def resolve(
        self, request: InterventionRequest, surface: PlaywrightSurface
    ) -> HumanResolution: ...


_HELP = """\
commands (the automation is STOPPED; you hold this session)
  click X Y            click at a point on the live page
  type TEXT            type into whatever has focus
  goto URL             navigate (allowlist still applies)
  shot                 save a screenshot to the run evidence
  url                  print the current url
  resume               hand control back; the run re-verifies before continuing
  abort                give up on this run
  help                 this text
"""


class TerminalOperator:
    """Reads commands from a terminal and applies them to the live page.

    Every action goes through `use_control`, so the allowlist and the redaction
    rule apply to the human exactly as they do to the agent — and the run log
    records what was done without recording what was typed.
    """

    def __init__(self, policy: ActionPolicy | None = None, stream=None) -> None:
        # ⚠️ A DEFAULT POLICY HERE IS A GATE THAT PASSES EVERYTHING. The CLI
        # built `TerminalOperator()` with no argument, so the human's actions
        # were checked against an empty `forbidden_values` while the agent's
        # were checked against the run's. Same call, different gate, and the
        # write-up claimed they were the same one.
        #
        # `adopt_policy` is how the run imposes its own; this argument survives
        # only so a test can construct one standalone. Found by Copilot, PR #5.
        self.policy = policy or ActionPolicy()
        self._stream = stream  # injected for tests; None means real stdin

    def adopt_policy(self, policy: ActionPolicy) -> None:
        """Take the RUN's gate. Called by replay before the human touches anything."""
        self.policy = policy

    def _read(self, prompt: str) -> str:
        if self._stream is not None:
            line = self._stream.readline()
            if not line:
                return "abort"
            print(f"{prompt}{line.rstrip()}")
            return line.strip()
        return input(prompt).strip()

    def resolve(self, request: InterventionRequest, surface: PlaywrightSurface) -> HumanResolution:
        print("\n" + "=" * 72)
        print(f"HUMAN NEEDED — {request.capability}, step {request.step_index}")
        print(f"  why        {request.why}")
        print(f"  screen     {request.screen}   {request.url}")
        if request.completed_steps:
            print(f"  completed  {', '.join(request.completed_steps)}")
        if request.frame:
            # ⚠️ A `file://` URL, not a bare path. Most terminals make it
            # clickable, and the browser is HEADLESS here -- this frame is the
            # only view of the page the operator gets. A path they have to copy
            # into something else is a view they will not look at.
            #
            # ⛔ NOT a localhost URL to a served page. There is no live view to
            # serve; it would be this same still image behind a web server,
            # looking authoritative while the page moved on. §3.6 puts a
            # co-browsing console out of scope and #9 records the design that
            # would actually work.
            print(f"  screenshot {Path(request.frame).resolve().as_uri()}")
        print("=" * 72)
        print(_HELP)

        actions: list[HumanAction] = []
        while True:
            raw = self._read("operator> ")
            if not raw:
                continue
            verb, _, rest = raw.partition(" ")
            verb = verb.lower()

            if verb == "resume":
                return HumanResolution(Resolution.RESUMED, actions, rest.strip())
            if verb == "abort":
                return HumanResolution(Resolution.ABORTED, actions, rest.strip())
            if verb == "help":
                print(_HELP)
                continue
            if verb == "url":
                print(surface.current_url())
                continue

            try:
                acted = self._apply(verb, rest, surface)
            except (ValueError, NotAllowedError) as exc:
                print(f"  refused: {exc}")
                continue
            if acted is not None:
                actions.append(acted)
                print(f"  ok  {acted.action} at ({acted.x},{acted.y})")

    def _apply(self, verb: str, rest: str, surface: PlaywrightSurface) -> HumanAction | None:
        if verb == "click":
            parts = rest.split()
            if len(parts) != 2 or not all(p.lstrip("-").isdigit() for p in parts):
                raise ValueError("usage: click X Y")
            x, y = int(parts[0]), int(parts[1])
            acted = use_control(surface, x, y, ManualActionKind.CLICK, policy=self.policy)
        elif verb == "type":
            if not rest:
                raise ValueError("usage: type TEXT")
            # ⛔ THIS USED TO CALL `surface.type_text` DIRECTLY, and the
            # write-up claimed all the while that "the human operator goes
            # through the same gate". It did not: no allowed-action check and
            # no forbidden-value check, so a person could type a secret into a
            # page during a handoff and the guardrail that exists precisely to
            # stop that never ran. Found by Copilot on PR #5.
            #
            # Typing has no target point -- the human has already focused
            # something -- so `use_control` does not fit, but the POLICY still
            # must. Calling it directly is the fix; the gate is the policy, not
            # the function that happens to wrap it.
            self.policy.check(ManualActionKind.ENTER_TEXT, rest)
            surface.type_text(rest)
            return HumanAction(
                ManualActionKind.ENTER_TEXT, -1, -1, surface.current_url(), len(rest)
            )
        elif verb == "goto":
            if not rest:
                raise ValueError("usage: goto URL")
            # `surface.navigate` enforces the ORIGIN allowlist itself, so
            # this one was already gated -- checked before assuming otherwise.
            surface.navigate(rest)
            return HumanAction(ManualActionKind.CLICK, -1, -1, surface.current_url())
        elif verb == "shot":
            surface.screenshot()
            return None
        else:
            raise ValueError(f"unknown command {verb!r}; try 'help'")
        return HumanAction(acted.action, acted.x, acted.y, acted.url, acted.value_length)


class ScriptedOperator:
    """A fixed command list. For tests and for a non-interactive demo."""

    def __init__(self, commands: list[str], policy: ActionPolicy | None = None) -> None:
        import io

        self._inner = TerminalOperator(
            policy=policy, stream=io.StringIO("\n".join(commands) + "\n")
        )

    def adopt_policy(self, policy: ActionPolicy) -> None:
        self._inner.adopt_policy(policy)

    def resolve(self, request: InterventionRequest, surface: PlaywrightSurface) -> HumanResolution:
        return self._inner.resolve(request, surface)
