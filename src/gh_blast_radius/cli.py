"""CLI entry point for gh-blast-radius.

All commands are registered on the top-level Typer ``app``. Each command
delegates to the appropriate module — the CLI layer is intentionally thin,
handling only argument parsing and output formatting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from gh_blast_radius import __version__
from gh_blast_radius.crawler import OrgCrawler
from gh_blast_radius.diff import compute_impact
from gh_blast_radius.github_client import GitHubClient
from gh_blast_radius.parser import parse_producer_interface, parse_workflow_ref
from gh_blast_radius.storage import load_graph, save_graph

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
    """Crawl a GitHub org and build/update the dependency graph."""
    if not token:
        err_console.print(
            "[red]Error: GITHUB_TOKEN environment variable not set, and --token not provided.[/]"
        )
        raise typer.Exit(code=1)

    client = GitHubClient(token=token)
    crawler = OrgCrawler(client)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description=f"Scanning organization '{org}'...", total=None)
        try:
            graph = crawler.crawl_org(org, include_archived=include_archived)
        except Exception as e:
            err_console.print(f"[red]Error scanning organization:[/] {e}")
            raise typer.Exit(code=1) from e

    save_path = Path(".workflow-impact") / f"{org}_graph.json"
    save_graph(graph, save_path)

    stats = graph.get_stats()
    console.print(
        Panel(
            f"Successfully scanned [bold]{org}[/].\n"
            f"Producers found: {stats['total_producers']}\n"
            f"Consumer repos: {stats['total_consumers']}\n"
            f"Total dependency edges: {stats['total_edges']}\n\n"
            f"Graph saved to [bold]{save_path}[/]",
            title="[bold green]Scan Complete[/]",
            border_style="green",
        )
    )


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
    # We need to know which org graph to load. For simplicity, we extract it from the workflow_ref
    ref = parse_workflow_ref(workflow_ref, "")
    if not ref:
        err_console.print(f"[red]Error: Invalid workflow reference '{workflow_ref}'.[/]")
        raise typer.Exit(code=1)

    graph_path = Path(".workflow-impact") / f"{ref.org}_graph.json"
    if not graph_path.exists():
        err_console.print(
            f"[red]Error: Graph not found for org '{ref.org}'. "
            f"Run `gh-blast-radius scan --org {ref.org}` first.[/]"
        )
        raise typer.Exit(code=1)

    graph = load_graph(graph_path)
    consumers_list = graph.get_consumers(ref, transitive=transitive)

    if output_format == "json":
        import dataclasses

        console.print(json.dumps([dataclasses.asdict(c) for c in consumers_list], indent=2))
        return

    if not consumers_list:
        console.print(f"[yellow]No consumers found for {workflow_ref}[/]")
        return

    table = Table(title=f"Consumers of {workflow_ref}", show_lines=True)
    table.add_column("Consumer Repo", style="cyan", no_wrap=True)
    table.add_column("Workflow", style="magenta")
    table.add_column("Job (Step)", style="green")
    table.add_column("Ref", style="blue")
    table.add_column("Inputs Passed", style="yellow")

    for c in consumers_list:
        step_str = f" (step {c.step_index})" if c.step_index is not None else ""
        job_step = f"{c.job_name}{step_str}"
        inputs_str = ", ".join(f"{k}={v}" for k, v in c.inputs_passed.items())
        table.add_row(
            c.consumer_repo,
            c.consumer_workflow,
            job_step,
            c.ref_used,
            inputs_str or "-",
        )

    console.print(table)


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
    if "/" not in repo:
        err_console.print("[red]Error: Repo must be in 'org/repo' format.[/]")
        raise typer.Exit(code=1)

    org = repo.split("/")[0]
    graph_path = Path(".workflow-impact") / f"{org}_graph.json"
    if not graph_path.exists():
        err_console.print(
            f"[red]Error: Graph not found for org '{org}'. "
            f"Run `gh-blast-radius scan --org {org}` first.[/]"
        )
        raise typer.Exit(code=1)

    graph = load_graph(graph_path)
    deps_list = graph.get_dependencies(repo)

    if output_format == "json":
        import dataclasses

        console.print(json.dumps([dataclasses.asdict(d) for d in deps_list], indent=2))
        return

    if not deps_list:
        console.print(f"[yellow]No dependencies found for {repo}[/]")
        return

    table = Table(title=f"Dependencies of {repo}", show_lines=True)
    table.add_column("Target Org", style="cyan", no_wrap=True)
    table.add_column("Target Repo", style="magenta")
    table.add_column("Path", style="green")

    for d in deps_list:
        table.add_row(
            d.org,
            d.repo,
            d.path or "-",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@app.command()
def diff(
    workflow_ref: Annotated[
        str,
        typer.Argument(
            help=(
                "Shared workflow or action reference, "
                "e.g. 'myorg/shared-workflows/.github/workflows/build.yml'"
            ),
        ),
    ],
    old: Annotated[
        str,
        typer.Option(
            "--old",
            help="Old version: a git ref (e.g. 'main', 'v1').",
        ),
    ],
    new: Annotated[
        str,
        typer.Option(
            "--new",
            help="New version: a git ref (e.g. 'feature-branch').",
        ),
    ],
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            help="GitHub personal access token. Defaults to GITHUB_TOKEN env var.",
            envvar="GITHUB_TOKEN",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: 'table', 'json', or 'markdown'."),
    ] = "table",
    fail_on_breaking: Annotated[
        bool,
        typer.Option("--fail-on-breaking", help="Exit with code 1 if there are breaking changes."),
    ] = False,
) -> None:
    """Compare two versions of a shared workflow and report what would break."""
    if not token:
        err_console.print(
            "[red]Error: GITHUB_TOKEN environment variable not set, and --token not provided.[/]"
        )
        raise typer.Exit(code=1)

    ref = parse_workflow_ref(workflow_ref, "")
    if not ref:
        err_console.print(f"[red]Error: Invalid workflow reference '{workflow_ref}'.[/]")
        raise typer.Exit(code=1)

    graph_path = Path(".workflow-impact") / f"{ref.org}_graph.json"
    if not graph_path.exists():
        err_console.print(
            f"[red]Error: Graph not found for org '{ref.org}'. "
            f"Run `gh-blast-radius scan --org {ref.org}` first.[/]"
        )
        raise typer.Exit(code=1)

    graph = load_graph(graph_path)
    consumers = graph.get_consumers(ref, transitive=False)

    client = GitHubClient(token=token)

    producer_type = (
        "reusable_workflow"
        if (ref.path.endswith(".yml") or ref.path.endswith(".yaml"))
        else "composite_action"
    )

    try:
        if producer_type == "reusable_workflow":
            old_content = client.get_file_content(ref.org, ref.repo, ref.path, ref=old)
            new_content = client.get_file_content(ref.org, ref.repo, ref.path, ref=new)
        else:
            old_content = client.get_action_manifest(ref.org, ref.repo, ref.path, ref=old)
            new_content = client.get_action_manifest(ref.org, ref.repo, ref.path, ref=new)
    except Exception as e:
        err_console.print(f"[red]Error fetching files from GitHub:[/] {e}")
        raise typer.Exit(code=1) from e

    old_node = parse_producer_interface(old_content, producer_type, ref)
    new_node = parse_producer_interface(new_content, producer_type, ref)

    report = compute_impact(ref, old_node, new_node, consumers, old, new)

    if output_format == "json":
        import dataclasses

        console.print(json.dumps(dataclasses.asdict(report), indent=2))
        return

    summary = report.summary

    if output_format == "markdown":
        lines = [
            f"### Impact Report: `{workflow_ref}`",
            f"Comparing `{old}` → `{new}`",
            "",
            "| Severity | Consumer Repo | Workflow | Job (Step) | Reasons |",
            "|----------|---------------|----------|------------|---------|",
        ]

        for result in report.results:
            if result.severity == "breaking":
                sev_str = "🛑 **BREAKING**"
            elif result.severity == "warning":
                sev_str = "⚠️ WARNING"
            else:
                sev_str = "✅ UNAFFECTED"

            c = result.consumer
            step_str = f" (step {c.step_index})" if c.step_index is not None else ""
            job_step = f"{c.job_name}{step_str}"
            reasons_str = "<br>".join(result.reasons) or "-"

            lines.append(
                f"| {sev_str} | `{c.consumer_repo}` | `{c.consumer_workflow}` | "
                f"`{job_step}` | {reasons_str} |"
            )

        lines.append("")
        lines.append(
            f"**Summary:** 🛑 Breaking: {summary['breaking']} | "
            f"⚠️ Warning: {summary['warning']} | "
            f"✅ Unaffected: {summary['unaffected']}"
        )

        print("\n".join(lines))

        if fail_on_breaking and summary["breaking"] > 0:
            raise typer.Exit(code=1)
        return

    table = Table(
        title=f"Impact Report: {workflow_ref} ({old} → {new})",
        show_lines=True,
    )
    table.add_column("Severity", justify="center")
    table.add_column("Consumer Repo", style="cyan", no_wrap=True)
    table.add_column("Workflow", style="magenta")
    table.add_column("Job (Step)", style="green")
    table.add_column("Reasons")

    for result in report.results:
        if result.severity == "breaking":
            sev_str = "[bold red]BREAKING[/]"
        elif result.severity == "warning":
            sev_str = "[bold yellow]WARNING[/]"
        else:
            sev_str = "[dim green]UNAFFECTED[/]"

        c = result.consumer
        step_str = f" (step {c.step_index})" if c.step_index is not None else ""
        job_step = f"{c.job_name}{step_str}"
        reasons_str = "\n".join(result.reasons) or "-"

        table.add_row(
            sev_str,
            c.consumer_repo,
            c.consumer_workflow,
            job_step,
            reasons_str,
        )

    console.print(table)

    console.print(
        f"\n[bold]Summary:[/] "
        f"[red]Breaking: {summary['breaking']}[/] | "
        f"[yellow]Warning: {summary['warning']}[/] | "
        f"[green]Unaffected: {summary['unaffected']}[/]"
    )

    if fail_on_breaking and summary["breaking"] > 0:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


@app.command()
def stats(
    org: Annotated[str, typer.Option("--org", "-o", help="GitHub organization.")],
) -> None:
    """Show summary statistics about the dependency graph."""
    graph_path = Path(".workflow-impact") / f"{org}_graph.json"
    if not graph_path.exists():
        err_console.print(
            f"[red]Error: Graph not found for org '{org}'. "
            f"Run `gh-blast-radius scan --org {org}` first.[/]"
        )
        raise typer.Exit(code=1)

    graph = load_graph(graph_path)

    basic_stats = graph.get_stats()

    # Calculate blast radius distribution
    widest_radius = 0
    widest_ref = ""
    for producer_id, node in graph.producers.items():
        consumers = graph.get_consumers(node.ref)
        if len(consumers) > widest_radius:
            widest_radius = len(consumers)
            widest_ref = producer_id

    table = Table(title=f"Graph Statistics: {org}", show_header=False)
    table.add_row("Total Shared Workflows/Actions", str(basic_stats["total_producers"]))
    table.add_row("Total Consumer Repositories", str(basic_stats["total_consumers"]))
    table.add_row("Total Dependency Edges", str(basic_stats["total_edges"]))
    if widest_ref:
        table.add_row("Widest Blast Radius", f"{widest_ref} ({widest_radius} consumers)")

    console.print(table)


# ---------------------------------------------------------------------------
# visualize
# ---------------------------------------------------------------------------


@app.command()
def visualize(
    org: Annotated[str, typer.Option("--org", "-o", help="GitHub organization to visualize.")],
) -> None:
    """Generate a Mermaid.js diagram of the dependency graph."""
    graph_path = Path(".workflow-impact") / f"{org}_graph.json"
    if not graph_path.exists():
        err_console.print(
            f"[red]Error: Graph not found for org '{org}'. "
            f"Run `gh-blast-radius scan --org {org}` first.[/]"
        )
        raise typer.Exit(code=1)

    graph = load_graph(graph_path)

    lines = []
    lines.append("```mermaid")
    lines.append("graph TD")

    def clean_id(s: str) -> str:
        return s.replace("/", "_").replace(".", "_").replace("-", "_")

    for producer_id in graph.producers:
        c_id = clean_id(producer_id)
        label = producer_id.replace(f"{org}/", "")
        lines.append(f'    {c_id}["{label}"]')
        lines.append(f"    style {c_id} fill:#8957e5,color:#fff,stroke:none")

    for consumer_id in graph.consumer_repos:
        c_id = clean_id(consumer_id)
        label = consumer_id.replace(f"{org}/", "")
        lines.append(f'    {c_id}["{label}"]')
        lines.append(f"    style {c_id} fill:#238636,color:#fff,stroke:none")

    # Add edges
    for u, v, data in graph.nx_graph.edges(data=True):
        if "edges" in data:
            lines.append(f"    {clean_id(u)} --> {clean_id(v)}")

    lines.append("```")
    print("\n".join(lines))
