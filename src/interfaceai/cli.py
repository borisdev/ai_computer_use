"""`interfaceai` CLI. Environment commands only so far -- the agent loop and replay
engine get their own subcommands once those exist.
"""

from __future__ import annotations

import sys
import time

import typer
from rich.console import Console

from interfaceai import parabank
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


def main() -> None:  # pragma: no cover
    sys.exit(app())
