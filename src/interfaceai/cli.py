"""`interfaceai` CLI. Environment commands only so far -- the agent loop and replay
engine get their own subcommands once those exist.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from interfaceai import (
    capabilities,
    capability,
    control_map_store,
    decisions,
    handoff,
    outcomes,
    parabank,
    screenshot2controls,
    vision_llm,
    vocabulary,
)
from interfaceai import capability as capability_mod
from interfaceai import discover as discover_mod
from interfaceai import replay as replay_mod
from interfaceai import status as status_mod
from interfaceai import surface as surface_mod
from interfaceai.settings import get_settings

app = typer.Typer(no_args_is_help=True, help="Computer-use automation for legacy bank apps.")
env = typer.Typer(no_args_is_help=True, help="Manage the local ParaBank target.")
app.add_typer(env, name="env")

console = Console()


@env.command("status")
def status() -> None:
    """Report whether each configured ParaBank tenant is serving."""
    settings = get_settings()
    targets = {
        "tenant-a (baseline)": settings.parabank_base_url,
        "tenant-b (feature)": settings.parabank_b_base_url,
    }
    any_up = False
    for name, url in targets.items():
        up = parabank.is_up(url)
        any_up = any_up or up
        if not up:
            state = "[red]down    [/]"
        elif parabank.is_seeded(url):
            state = "[green]ready   [/]"
        else:
            # Serving HTML with no schema behind it. Fix with `make reset`.
            state = "[yellow]no data [/]"
        console.print(f"{state} {name:<22} {url}")
    if not any_up:
        console.print("\n[yellow]Nothing is up.[/] Start it with: [bold]make up[/]")
        raise typer.Exit(1)


@env.command("reset")
def reset(
    tenant_b: bool = typer.Option(False, "--tenant-b", help="Target the feature variant instead."),
) -> None:
    """Reseed the database to the documented fixtures."""
    settings = get_settings()
    url = settings.parabank_b_base_url if tenant_b else settings.parabank_base_url
    if not parabank.is_up(url):
        console.print(f"[red]ParaBank is not up at {url}[/]")
        raise typer.Exit(1)
    parabank.ParaBankAdmin(url).init_db()

    # Verify rather than assume. The lazy-init path this replaces reported
    # "Initializing..." on every request for minutes while the schema never
    # appeared, so a POST returning 200 is not evidence the fixtures are there.
    for _ in range(20):
        if parabank.is_seeded(url):
            console.print(f"[green]Reseeded and verified[/] {url}")
            return
        time.sleep(1)

    console.print(
        f"[red]Seed did not take[/] {url} -- account "
        f"{parabank.DEMO_SAVINGS_ACCOUNT_ID} still not readable"
    )
    raise typer.Exit(1)


@env.command("break")
def break_db(
    tenant_b: bool = typer.Option(False, "--tenant-b", help="Target the feature variant instead."),
) -> None:
    """Drop to ParaBank's minimal dataset, to exercise replay error handling.

    Not a wipe: one customer and one account survive. Account 13344 still
    resolves but as CHECKING $5,022.93 instead of SAVINGS $1,231.10, so a
    capability recorded against the seeded state should report a violated
    checkpoint rather than the wrong balance. Every other account is gone, which
    is the 'record not found' business outcome. Undo with `interfaceai env reset`.
    """
    settings = get_settings()
    url = settings.parabank_b_base_url if tenant_b else settings.parabank_base_url
    if not parabank.is_up(url):
        console.print(f"[red]ParaBank is not up at {url}[/]")
        raise typer.Exit(1)
    parabank.ParaBankAdmin(url).clean_db()
    console.print(
        f"[yellow]Minimal dataset[/] {url} -- only customer 12212 and account "
        f"13344 (now CHECKING $5,022.93) remain"
    )


# ---------------------------------------------------------------------------
# capability -- the artifact (assignment 3.2)
# ---------------------------------------------------------------------------

cap = typer.Typer(no_args_is_help=True, help="Inspect, export and approve capability artifacts.")
app.add_typer(cap, name="capability")

ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"

# Hoisted: ruff B008 refuses a call in an argument default.
_MAPS_OPTION = typer.Option(
    Path("control_maps"), "--maps", help="Control-map store root (written by discovery)."
)


def _capability_named(name: str) -> capability.Capability:
    """A capability by NAME -- authored OR discovered.

    ⛔ **Not every capability is authored, and looking only in the registry broke
    the one command discovery's output has to pass.** `log_in_discovered` and
    every draft a discovery run has just emitted live only as artifacts, so
    `capability approve <a discovered name>` answered *"no capability named ...;
    known: log_in, read_savings_balance, ..."* -- a draft that could never be
    promoted, which makes the draft -> approved gate unreachable for exactly the
    artifacts it exists for.

    `resolve_artifact` is the registry's `load` and already knows the rule
    (highest version, approved first), so the fallback is one call rather than a
    second copy of the filename convention.
    """
    try:
        return capabilities.get(name)
    except KeyError:
        return capability_mod.load_capability(
            capability_mod.resolve_artifact(ARTIFACTS, name, approved_only=False)
        )


@cap.command("list")
def cap_list() -> None:
    """Every authored capability, with its signature and approval state."""
    for c in capabilities.REGISTRY:
        params = ", ".join(f"{p.name}: {capability.slot_type(p.slot)}" for p in c.params)
        returns = ", ".join(f"{o.name}: {capability.slot_type(o.slot)}" for o in c.returns)
        colour = "green" if c.approval is capability.Approval.APPROVED else "yellow"
        console.print(
            f"[bold]{c.name}[/]({params}) -> {returns or 'nothing'}  "
            f"[{colour}]{c.approval}[/]  v{c.version}"
        )


@cap.command("show")
def cap_show(
    name: str = typer.Argument(..., help="Capability name, e.g. read_savings_balance"),
) -> None:
    """Print one capability as the JSON that would be exported."""
    try:
        console.print_json(capability.dump_capability(capabilities.get(name)))
    except KeyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


@cap.command("validate")
def cap_validate() -> None:
    """Check every authored capability against the vocabulary in force."""
    failed = False
    for c in capabilities.REGISTRY:
        try:
            capability.validate_capability(c)
        except capability.CapabilityError as exc:
            failed = True
            console.print(f"[red]FAIL[/] {c.name}: {exc}")
        else:
            console.print(f"[green]ok  [/] {c.name} v{c.version}")
    console.print(
        f"\nvocabulary v{vocabulary.VOCABULARY_VERSION}, {len(vocabulary.VOCABULARY.terms)} terms"
    )
    if failed:
        raise typer.Exit(1)


@cap.command("export")
def cap_export() -> None:
    """Write every authored capability to artifacts/ as a draft."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    for c in capabilities.REGISTRY:
        capability.validate_capability(c)
        path = ARTIFACTS / capability.artifact_filename(c)
        path.write_text(capability.dump_capability(c))
        console.print(f"[green]wrote[/] {path.relative_to(ARTIFACTS.parent)}")


@cap.command("approve")
def cap_approve(
    name: str = typer.Argument(..., help="Capability name to promote."),
    by: str = typer.Option(..., "--by", help="Who reviewed it. Recorded in the artifact."),
) -> None:
    """Promote an exported draft to approved -- the gate unattended replay checks.

    Deliberately a separate command and a separate file. Discovery emits a
    draft; a person reads the steps and the checkpoints and promotes it. An
    artifact that approved itself would make the gate decoration.
    """
    try:
        source = _capability_named(name)
    except KeyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    approved = capability.approve(source, by)
    capability.validate_capability(approved)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / capability.artifact_filename(approved)
    path.write_text(capability.dump_capability(approved))
    console.print(f"[green]approved[/] {path.relative_to(ARTIFACTS.parent)} by {by}")


@cap.command("check")
def cap_check(
    maps: Path = _MAPS_OPTION,
) -> None:
    """Check every capability against the control maps it would replay against.

    `capability validate` checks an artifact against itself and the vocabulary.
    This is the other half: does every control it names actually exist, was it
    grounded, was its screen recorded at the artifact's viewport, and does its
    role accept the action the step asks for. An unresolvable control name is a
    fault worth finding here rather than mid-replay.
    """
    store = control_map_store.ControlMapStore(maps)
    total = 0
    for c in capabilities.REGISTRY:
        faults = control_map_store.check_capability(c, store)
        total += len(faults)
        if not faults:
            console.print(f"[green]ok  [/] {c.name}")
            continue
        console.print(f"[red]FAIL[/] {c.name} \u2014 {len(faults)} fault(s)")
        for fault in faults:
            console.print(f"       {fault}")
    if total:
        recorded = sorted(
            f"{t}/{sc}" for t in store.tenants("parabank") for sc in store.screens("parabank", t)
        )
        console.print(
            f"\n[yellow]{total} fault(s)[/] against {maps}/ "
            f"({', '.join(recorded) if recorded else 'nothing recorded yet'})"
        )
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# discover -- the goal-driven LLM run (assignment 3.1)
# ---------------------------------------------------------------------------

EVIDENCE = Path(__file__).resolve().parents[2] / "evidence" / "runs"

_GOAL_OPTION = typer.Option(..., "--goal", help="What to accomplish, in natural language.")
_NAME_OPTION = typer.Option(..., "--name", help="Capability name for the emitted artifact.")
_PARAM_OPTION = typer.Option(
    None,
    "--param",
    help="Declare a caller input: name=slot=value, e.g. account_id=account_id=13344. Repeatable.",
)
_SECRET_OPTION = typer.Option(
    None,
    "--secret",
    help="Offer a credential by NAME: input_ref=slot. Value comes from settings, never the CLI.",
)


def _parse_params(raw: list[str] | None) -> tuple[discover_mod.Parameter, ...]:
    out = []
    for item in raw or []:
        parts = item.split("=", 2)
        if len(parts) != 3:
            raise typer.BadParameter(f"--param must be name=slot=value, got {item!r}")
        out.append(discover_mod.Parameter(name=parts[0], slot=parts[1], value=parts[2]))
    return tuple(out)


def _parse_secrets(raw: list[str] | None) -> tuple[discover_mod.SecretBinding, ...]:
    """Values are resolved from settings here, so a credential never enters argv.

    A password on a command line lands in shell history and in `ps` output for
    every user on the box, which is the kind of finding 3.4 is about.
    """
    settings = get_settings()
    known = {
        "parabank_username": settings.parabank_demo_username,
        "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
    }
    out = []
    for item in raw or []:
        ref, _, slot = item.partition("=")
        if ref not in known:
            raise typer.BadParameter(
                f"unknown secret {ref!r}; this build resolves: {', '.join(sorted(known))}"
            )
        out.append(discover_mod.SecretBinding(input_ref=ref, slot=slot or ref, value=known[ref]))
    return tuple(out)


@app.command("discover")
def discover_cmd(
    goal: str = _GOAL_OPTION,
    name: str = _NAME_OPTION,
    param: list[str] = _PARAM_OPTION,
    secret: list[str] = _SECRET_OPTION,
    maps: Path = _MAPS_OPTION,
    tenant: str = typer.Option("baseline", "--tenant"),
    max_steps: int = typer.Option(12, "--max-steps"),
    headless: bool = typer.Option(True, "--headless/--headed"),
    confirm_risky: bool = typer.Option(
        False, "--confirm-risky", help="Permit irreversible steps. Off by default."
    ),
) -> None:
    """Run the LLM against the live target and record the flow as a draft capability."""
    settings = get_settings()
    entry_point = (
        settings.parabank_b_base_url if tenant != "baseline" else settings.parabank_base_url
    )
    if not parabank.is_seeded(entry_point):
        console.print(f"[red]{entry_point} is not seeded[/] -- run `interfaceai env reset` first")
        raise typer.Exit(1)

    target = capability.Target(app="parabank", tenant=tenant, base_url=entry_point)
    outcome = discover_mod.discover(
        goal=goal,
        name=name,
        target=target,
        entry_point=f"{entry_point}/index.htm",
        vision=vision_llm.call_vision_llm,
        store=control_map_store.ControlMapStore(maps),
        evidence_root=EVIDENCE,
        params=_parse_params(param),
        secrets=_parse_secrets(secret),
        max_steps=max_steps,
        headless=headless,
        confirm_risky=confirm_risky,
        allowed_origins=settings.allowed_origins,
    )

    if isinstance(outcome, discover_mod.DiscoverySuccess):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        path = ARTIFACTS / capability.artifact_filename(outcome.capability)
        path.write_text(capability.dump_capability(outcome.capability))
        console.print(
            f"[green]discovered[/] {outcome.capability.name} in {len(outcome.steps)} steps, "
            f"{outcome.model_calls} model calls, {outcome.seconds:.0f}s"
        )
        console.print(f"  artifact  {path}")
        console.print(f"  evidence  {outcome.evidence_dir}")
        console.print(f"  maps      {maps}/")
        faults = control_map_store.check_capability(
            outcome.capability, control_map_store.ControlMapStore(maps)
        )
        for fault in faults:
            console.print(f"  [yellow]fault[/] {fault}")
        return

    if isinstance(outcome, discover_mod.PassToOperator):
        console.print(f"[yellow]needs a human[/] at step {outcome.step_index} on {outcome.screen}")
        console.print(f"  why       {outcome.reason}")
        console.print(f"  screen    {outcome.screenshot}")
        console.print(f"  evidence  {outcome.evidence_dir}")
        raise typer.Exit(2)

    console.print(f"[red]discovery failed[/] at step {outcome.step_index}: {outcome.reason}")
    console.print(f"  evidence  {outcome.evidence_dir}")
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# replay -- the production path (assignment 3.3)
# ---------------------------------------------------------------------------

_ARTIFACT_ARG_OPTIONAL = typer.Argument(
    None, help="An artifact path. Prefer --capability; this is the low-level form."
)
_CAPABILITY_OPTION = typer.Option(
    None, "--capability", "-c", help="Capability NAME. Resolves its approved artifact."
)
_VERSION_OPTION = typer.Option(
    None, "--version", help="Pin a version. Defaults to the highest approved."
)
_ARTIFACT_ARG = typer.Argument(..., help="Path to an APPROVED capability artifact.")
_INPUT_OPTION = typer.Option(None, "--param", help="Bind a typed input: name=value. Repeatable.")


@app.command("replay")
def replay_cmd(
    artifact: Path = _ARTIFACT_ARG_OPTIONAL,
    capability_name: str = _CAPABILITY_OPTION,
    version: int = _VERSION_OPTION,
    param: list[str] = _INPUT_OPTION,
    maps: Path = _MAPS_OPTION,
    headless: bool = typer.Option(True, "--headless/--headed"),
    confirm_risky: bool = typer.Option(
        False, "--confirm-risky", help="Permit irreversible steps. Off by default."
    ),
    tenant: str = typer.Option(
        None,
        "--tenant",
        help="Replay against a DIFFERENT tenant than the artifact was recorded on (3.7).",
    ),
    operator: bool = typer.Option(
        False,
        "--operator",
        help="Hand the live session to a terminal operator when the run blocks (3.6).",
    ),
) -> None:
    """Replay a capability deterministically. No model decides anything."""

    # NAME > PATH. `--capability read_savings_balance` is the address an agent
    # knows; the filename is storage layout. The positional path stays for the
    # low-level case (replaying an arbitrary file, including a draft in a test).
    if capability_name:
        if artifact is not None:
            console.print("[red]give either an artifact path or --capability, not both[/]")
            raise typer.Exit(2)
        try:
            artifact = capability_mod.resolve_artifact(ARTIFACTS, capability_name, version=version)
        except KeyError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
    elif artifact is None:
        console.print("[red]need --capability NAME (or an artifact path)[/]")
        raise typer.Exit(2)

    settings = get_settings()
    inputs: dict[str, str] = {}
    for item in param or []:
        name, _, value = item.partition("=")
        if not value:
            raise typer.BadParameter(f"--param must be name=value, got {item!r}")
        inputs[name] = value

    try:
        loaded = capability.load_capability(artifact)
    except (OSError, ValueError) as exc:
        console.print(f"[red]cannot load {artifact}:[/] {exc}")
        raise typer.Exit(1) from exc

    def retarget(c: capability.Capability, name: str, base: str) -> capability.Capability:
        return c.model_copy(
            update={"target": c.target.model_copy(update={"tenant": name, "base_url": base})}
        )

    if tenant and tenant != loaded.target.tenant:
        # 3.7: the artifact is tenant-agnostic; only the control maps and the
        # entry URL are tenant-specific. `maps adopt` is what establishes that
        # the locators actually transfer.
        base = settings.parabank_b_base_url if tenant != "baseline" else settings.parabank_base_url
        loaded = retarget(loaded, tenant, base)
        console.print(f"[cyan]cross-tenant[/] replaying on {tenant} ({base})")

    # Everything approved in artifacts/ is callable by an `invoke` step. The
    # STEP pins the version, so a library holding a different one is a
    # validation error rather than a silent substitution.
    #
    # ⚠️ Keyed by NAME, so two approved versions of one capability would shadow
    # each other. Keeping the HIGHEST is deliberate rather than whatever the
    # directory listing happened to end on: a step pinned to an older version
    # then fails loudly in `validate_invocations` instead of quietly running
    # whichever file sorted last.
    library: dict[str, capability.Capability] = {}
    for path in sorted(ARTIFACTS.glob("*.approved.json")):
        try:
            found = capability.load_capability(path)
        except (OSError, ValueError):
            continue
        current = library.get(found.name)
        if current is None or found.version > current.version:
            library[found.name] = found

    if tenant and tenant != capability.load_capability(artifact).target.tenant:
        # ⚠️ Retarget the WHOLE call tree, not just the entry capability. An
        # invoked capability recorded for another tenant is refused by
        # `validate_invocations` -- correctly, since its control maps are that
        # tenant's pixels. Cross-tenant replay predates composition here, so
        # the two were never exercised together until a loan capability that
        # invokes `log_in` was pointed at tenant B.
        base = settings.parabank_b_base_url if tenant != "baseline" else settings.parabank_base_url
        library = {n: retarget(c, tenant, base) for n, c in library.items()}

    result = replay_mod.replay(
        loaded,
        inputs,
        store=control_map_store.ControlMapStore(maps),
        evidence_root=EVIDENCE,
        secrets={
            "parabank_username": settings.parabank_demo_username,
            "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
        },
        vision=vision_llm.call_vision_llm,
        allowed_origins=settings.allowed_origins,
        confirm_money_above=settings.confirm_money_above(loaded.target.tenant),
        permitted=settings.allowed_capabilities(loaded.target.tenant),
        confirm_risky=confirm_risky,
        headless=headless,
        operator=handoff.TerminalOperator() if operator else None,
        library=library,
    )

    if isinstance(result, outcomes.Success):
        console.print(f"[green]SUCCESS[/] {loaded.name} in {result.steps_run} steps")
        for name, value in result.outputs.items():
            console.print(f"  {name} = {value}")
        # A run that survived something must not look like one that had a clear
        # path. Saying so is the difference between a handled condition and a
        # hidden one.
        for condition in result.recovered:
            console.print(f"  [yellow]recovered[/] {condition}")
    elif isinstance(result, outcomes.BusinessOutcome):
        console.print(f"[yellow]{result.kind}[/] {result.detail}")
    elif isinstance(result, outcomes.NeedsOperator):
        console.print(f"[yellow]NEEDS A HUMAN[/] at step {result.step_index}: {result.why}")
        if result.completed_steps:
            console.print(f"  completed: {', '.join(result.completed_steps)}")
    else:
        console.print(f"[red]FAILED[/] at {result.step}")
        console.print(f"  expected  {result.expected}")
        console.print(f"  observed  {result.observed}")

    console.print(f"  evidence  {result.evidence_dir}")
    if not outcomes.is_actionable_by_caller(result):
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# maps -- cross-tenant reuse (assignment 3.7)
# ---------------------------------------------------------------------------

maps_app = typer.Typer(no_args_is_help=True, help="Control maps and cross-tenant reuse.")
app.add_typer(maps_app, name="maps")


@maps_app.command("adopt")
def maps_adopt(
    screen: str = typer.Argument(..., help="Which screen to adopt, e.g. index."),
    source: str = typer.Option("baseline", "--from", help="Tenant the map was recorded on."),
    target: str = typer.Option(..., "--to", help="Tenant to adopt it for."),
    maps: Path = _MAPS_OPTION,
    login: bool = typer.Option(
        False,
        "--login",
        help="Authenticate first. Required for screens behind a session, e.g. overview.",
    ),
) -> None:
    """Reuse one tenant's control map for another, verifying every locator first.

    The 3.7 question: does an artifact recorded at one institution work at
    another running the same vendor product? This re-runs every locator against
    the TARGET tenant's live screen and writes nothing if any drifted — a
    partially-adopted map fails at replay, far from the cause.
    """
    settings = get_settings()
    url = settings.parabank_base_url if target == "baseline" else settings.parabank_b_base_url
    if not parabank.is_seeded(url):
        console.print(f"[red]{url} is not seeded[/] — run `interfaceai env reset --tenant-b`")
        raise typer.Exit(1)

    store = control_map_store.ControlMapStore(maps)
    with surface_mod.PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface:
        surface.navigate(f"{url}/index.htm")
        if login:
            # An authenticated screen logged out is a DIFFERENT screen, and the
            # verifier would report it as tenant drift. Observed exactly that on
            # overview.htm before this flag existed.
            index_map = control_map_store.MapKey(app="parabank", tenant=source, screen="index")
            for control_id, action, value in (
                ("username_textbox", "enter_text", settings.parabank_demo_username),
                (
                    "password_textbox",
                    "enter_text",
                    settings.parabank_demo_password.get_secret_value(),
                ),
                ("log_in_button", "click", None),
            ):
                control = store.control(index_map, control_id)
                found = screenshot2controls.locate_control(
                    screenshot2controls.ResolveInput(
                        screenshot_png=surface.screenshot(), locator=control.locator
                    )
                )
                if found.status != "matched":
                    console.print(f"[red]cannot log in on {target}[/]: {control_id} {found.status}")
                    raise typer.Exit(1)
                surface_mod.use_control(
                    surface,
                    found.point.x,
                    found.point.y,
                    decisions.ManualActionKind(action),
                    value,
                )
            surface.wait(2.0)
        surface.navigate(f"{url}/{screen}.htm")
        # ⚠️ POLL rather than sleep once. A page still fetching its content
        # looks exactly like a drifted tenant to a locator check -- ParaBank's
        # loan form shows "Loading..." where its account dropdown will be, and
        # a single 1s wait reported all four form controls as drift. The
        # checker cannot tell "different" from "not ready", so give it time to
        # become ready and only call it drift if it never does.
        source_key = control_map_store.MapKey(app="parabank", tenant=source, screen=screen)
        target_key = control_map_store.MapKey(app="parabank", tenant=target, screen=screen)
        deadline = time.monotonic() + 15.0
        while True:
            report = control_map_store.adopt_control_map(
                store, source_key, target_key, surface.screenshot()
            )
            if report.clean or time.monotonic() > deadline:
                break
            surface.wait(1.0)

    console.print(f"{source} -> {target}   {report}")
    if report.clean:
        console.print(f"[green]adopted[/] every locator matched; map written for {target}")
        return
    console.print(f"[yellow]drifted[/] {', '.join(report.drifted)}")
    console.print("  nothing written — this tenant needs its own discovery run or overrides")
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# status -- the human half of the artifact (assignment 3.2), and 3.5's readback
# ---------------------------------------------------------------------------

_MARKDOWN_OPTION = typer.Option(
    None, "--markdown", help="Write a committable page here instead of printing."
)
_LIMIT_OPTION = typer.Option(20, "--limit", help="How many recent runs to show.")


@app.command("status")
def status_cmd(
    markdown: Path = _MARKDOWN_OPTION,
    limit: int = _LIMIT_OPTION,
    maps: Path = _MAPS_OPTION,
) -> None:
    """What capabilities exist, and what the recent runs did.

    Reads `artifacts/` and `evidence/runs/` -- no new storage. §3.2 asks that
    "both a human reviewer and a calling agent" understand a capability; the
    agent half was typed and validated, the human half was a JSON file.
    """
    artifacts = status_mod.read_artifacts(ARTIFACTS)
    runs = status_mod.read_runs(EVIDENCE)

    if markdown:
        markdown.write_text(status_mod.as_markdown(artifacts, runs, limit=limit))
        console.print(f"[green]wrote[/] {markdown}")
        return

    store = control_map_store.ControlMapStore(maps)
    table = Table(title="capabilities", box=None, pad_edge=False)
    for column in ("capability", "v", "approval", "signature", "invokes", "faults"):
        table.add_column(column)
    for a in artifacts:
        try:
            loaded = capability.load_capability(a.path)
            faults = len(control_map_store.check_capability(loaded, store))
        except (OSError, ValueError):
            faults = -1
        mark = "[green]approved[/]" if a.approval is capability.Approval.APPROVED else "draft"
        table.add_row(
            a.name,
            str(a.version),
            mark,
            a.signature,
            ", ".join(a.invokes) or "—",
            "[green]ok[/]" if faults == 0 else f"[red]{faults}[/]",
        )
    console.print(table)

    runs_table = Table(title=f"runs (most recent {limit})", box=None, pad_edge=False)
    for column in ("when", "kind", "capability", "outcome", "steps", "calls", "worst", "detail"):
        runs_table.add_column(column)
    colours = {"SUCCESS": "green", "business_outcome": "yellow", "needs_human": "yellow"}
    for r in runs[:limit]:
        colour = colours.get(r.outcome, "red")
        runs_table.add_row(
            r.started,
            r.kind,
            r.capability,
            f"[{colour}]{r.outcome}[/]",
            str(r.steps),
            str(r.model_calls),
            f"{r.worst_score:.3f}" if r.worst_score is not None else "—",
            r.detail[:52],
        )
    console.print(runs_table)


@app.command("language")
def language_cmd() -> None:
    """Draw the CONTROLLED LANGUAGE as mermaid, generated from the types.

    Verbs, control roles and value slots, with the permitted pairings between
    them -- read from `VOCABULARY`, `ControlRole` and `ACTIONS_BY_ROLE`, so it
    cannot claim a pairing the guardrails would refuse.
    """
    sys.stdout.write(status_mod.language_as_mermaid() + "\n")  # raw: see diagram_cmd


@app.command("diagram")
def diagram_cmd(
    name: str = typer.Argument(..., help="Capability name, e.g. read_savings_balance."),
) -> None:
    """Draw a capability as mermaid, READ FROM THE ARTIFACT.

    A hand-drawn diagram is a claim about the artifact that stops being true the
    moment the artifact changes, and nothing tells you. This one cannot drift.
    """
    try:
        # ⚠️ NOT EVERY CAPABILITY IS AUTHORED. `log_in_discovered` came out of a
        # real discovery run and lives only as an artifact, so the registry has
        # never heard of it -- and it is the most interesting one to draw. A
        # generated-docs story that can only describe hand-written capabilities
        # describes the wrong half of the system.
        capability = _capability_named(name)
    except KeyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    # ⛔ NOT console.print. Rich treats [square brackets] as markup, and mermaid
    # is made of them -- `[[invoke]]`, `[/extract/]`, `>wait_for]`. It also wraps
    # at terminal width, which splits a long `classDef` line in half. Either one
    # produces a diagram that looks fine in a terminal and does not parse when
    # pasted. Raw stdout is the only safe sink for generated source.
    sys.stdout.write(status_mod.as_mermaid(capability) + "\n")


def main() -> None:  # pragma: no cover
    sys.exit(app())
