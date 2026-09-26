"""`interfaceai` CLI. Environment commands only so far -- the agent loop and replay
engine get their own subcommands once those exist.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from interfaceai import (
    capabilities,
    capability,
    control_map_store,
    parabank,
    vision_llm,
    vocabulary,
)
from interfaceai import discover as discover_mod
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
        source = capabilities.get(name)
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


def main() -> None:  # pragma: no cover
    sys.exit(app())
