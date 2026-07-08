"""CLI entry point for gh-blast-radius.

All commands are registered on the top-level Typer ``app``. Each command
delegates to the appropriate module — the CLI layer is intentionally thin,
handling only argument parsing and output formatting.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from gh_blast_radius import __version__

app = typer.Typer(
    name="gh-blast-radius",
    help=(
        "Analyze the blast radius of shared GitHub Actions reusable workflows "
        "and composite actions across your organization."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"gh-blast-radius [bold green]{__version__}[/]")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """gh-blast-radius — know what breaks before you push."""


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@app.command()
def scan(
    org: Annotated[str, typer.Option("--org", "-o", help="GitHub organization to scan.")],
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            help="GitHub personal access token. Defaults to GITHUB_TOKEN env var.",
            envvar="GITHUB_TOKEN",
        ),
    ] = None,
    full_rescan: Annotated[
        bool,
        typer.Option(
            "--full-rescan",
            help="Ignore cached data and re-fetch all repos.",
        ),
    ] = False,
    include_archived: Annotated[
        bool,
        typer.Option(
            "--include-archived",
            help="Include archived repositories in the scan.",
        ),
    ] = False,
) -> None:
    """Crawl a GitHub org and build/update the dependency graph.

    Scans every repo in the organization for reusable workflow and composite
    action usage, builds the dependency graph, and persists it locally.
    """
    console.print(
        Panel(
            "[yellow]⚠ scan command is not yet implemented.[/]\n\n"
            f"Will scan org: [bold]{org}[/]\n"
            f"Full rescan: {full_rescan}\n"
            f"Include archived: {include_archived}\n"
            f"Token: {'provided' if token else 'not provided (set GITHUB_TOKEN)'}",
            title="[bold]gh-blast-radius scan[/]",
            border_style="yellow",
        )
    )
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# consumers
# ---------------------------------------------------------------------------


@app.command()
def consumers(
    workflow_ref: Annotated[
        str,
        typer.Argument(
            help=(
                "Shared workflow or action reference to query, "
                "e.g. 'myorg/shared-workflows/.github/workflows/build.yml'"
            ),
        ),
    ],
    transitive: Annotated[
        bool,
        typer.Option(
            "--transitive",
            help="Include transitive consumers (through nested composite actions).",
        ),
    ] = False,
    tree: Annotated[
        bool,
        typer.Option("--tree", help="Display results as a tree instead of a table."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: 'table' or 'json'."),
    ] = "table",
) -> None:
    """List every repo/job/step that consumes a shared workflow or action."""
    console.print(
        Panel(
            "[yellow]⚠ consumers command is not yet implemented.[/]\n\n"
            f"Querying consumers of: [bold]{workflow_ref}[/]\n"
            f"Transitive: {transitive}\n"
            f"Format: {output_format}",
            title="[bold]gh-blast-radius consumers[/]",
            border_style="yellow",
        )
    )
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# deps
# ---------------------------------------------------------------------------


@app.command()
def deps(
    repo: Annotated[
        str,
        typer.Argument(
            help="Repository to query, e.g. 'myorg/frontend'.",
        ),
    ],
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: 'table' or 'json'."),
    ] = "table",
) -> None:
    """List every shared workflow/action a given repo depends on."""
    console.print(
        Panel(
            "[yellow]⚠ deps command is not yet implemented.[/]\n\n"
            f"Querying dependencies of: [bold]{repo}[/]\n"
            f"Format: {output_format}",
            title="[bold]gh-blast-radius deps[/]",
            border_style="yellow",
        )
    )
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@app.command()
def diff(
    workflow: Annotated[
        str,
        typer.Option(
            "--workflow",
            "-w",
            help="Path to the shared workflow file within its repo.",
        ),
    ],
    old: Annotated[
        str,
        typer.Option(
            "--old",
            help="Old version: a git ref (e.g. 'main', 'v1') or a local file path.",
        ),
    ],
    new: Annotated[
        str,
        typer.Option(
            "--new",
            help="New version: a git ref (e.g. 'feature-branch') or a local file path.",
        ),
    ],
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: 'table' or 'json'."),
    ] = "table",
) -> None:
    """Compare two versions of a shared workflow and report what would break.

    Analyzes the old and new YAML to detect removed inputs, renamed secrets,
    permission changes, etc., and cross-references against all known consumers
    to classify each as breaking, warning, or unaffected.
    """
    console.print(
        Panel(
            "[yellow]⚠ diff command is not yet implemented.[/]\n\n"
            f"Workflow: [bold]{workflow}[/]\n"
            f"Old: {old}\n"
            f"New: {new}\n"
            f"Format: {output_format}",
            title="[bold]gh-blast-radius diff[/]",
            border_style="yellow",
        )
    )
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


@app.command()
def stats() -> None:
    """Show summary statistics about the dependency graph.

    Displays: total shared workflows/actions, total consumer edges,
    widest blast radius (most consumers), and ref distribution.
    """
    console.print(
        Panel(
            "[yellow]⚠ stats command is not yet implemented.[/]\n\n"
            "Will display summary statistics from the persisted graph.",
            title="[bold]gh-blast-radius stats[/]",
            border_style="yellow",
        )
    )
    raise typer.Exit(code=1)
