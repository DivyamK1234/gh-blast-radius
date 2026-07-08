"""Tests for the CLI entry point and command registration."""

from __future__ import annotations

from typer.testing import CliRunner

from gh_blast_radius.cli import app

runner = CliRunner()


class TestCLIBasics:
    """Test that the CLI skeleton is properly wired up."""

    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "blast radius" in result.output.lower() or "gh-blast-radius" in result.output

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # Typer exits with code 0 or 2 when no_args_is_help triggers (version-dependent)
        assert result.exit_code in (0, 2)
        # Should show help text regardless
        assert "Usage" in result.output or "usage" in result.output


class TestScanCommand:
    """Test the scan command stub."""

    def test_scan_requires_org(self) -> None:
        result = runner.invoke(app, ["scan"])
        assert result.exit_code != 0  # Missing required --org

    def test_scan_missing_token(self) -> None:
        result = runner.invoke(app, ["scan", "--org", "test-org"], env={"GITHUB_TOKEN": ""})
        assert result.exit_code == 1
        assert "GITHUB_TOKEN environment variable not set" in result.output

    def test_scan_help(self) -> None:
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "--org" in result.output
        assert "--full-rescan" in result.output


class TestConsumersCommand:
    """Test the consumers command stub."""

    def test_consumers_requires_ref(self) -> None:
        result = runner.invoke(app, ["consumers"])
        assert result.exit_code != 0  # Missing required argument

    def test_consumers_missing_graph(self) -> None:
        result = runner.invoke(app, ["consumers", "org/repo/.github/workflows/build.yml"])
        assert result.exit_code == 1
        assert "Graph not found for org 'org'" in result.output

    def test_consumers_help(self) -> None:
        result = runner.invoke(app, ["consumers", "--help"])
        assert result.exit_code == 0
        assert "--transitive" in result.output
        assert "--format" in result.output


class TestDepsCommand:
    """Test the deps command stub."""

    def test_deps_requires_repo(self) -> None:
        result = runner.invoke(app, ["deps"])
        assert result.exit_code != 0

    def test_deps_missing_graph(self) -> None:
        result = runner.invoke(app, ["deps", "myorg/frontend"])
        assert result.exit_code == 1
        assert "Graph not found for org 'myorg'" in result.output

    def test_deps_help(self) -> None:
        result = runner.invoke(app, ["deps", "--help"])
        assert result.exit_code == 0


class TestDiffCommand:
    """Test the diff command stub."""

    def test_diff_requires_options(self) -> None:
        result = runner.invoke(app, ["diff"])
        assert result.exit_code != 0

    def test_diff_stub(self) -> None:
        result = runner.invoke(
            app,
            ["diff", "--workflow", ".github/workflows/build.yml", "--old", "main", "--new", "dev"],
        )
        assert result.exit_code == 1

    def test_diff_help(self) -> None:
        result = runner.invoke(app, ["diff", "--help"])
        assert result.exit_code == 0
        assert "--workflow" in result.output
        assert "--old" in result.output
        assert "--new" in result.output


class TestStatsCommand:
    """Test the stats command stub."""

    def test_stats_stub(self) -> None:
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 1

    def test_stats_help(self) -> None:
        result = runner.invoke(app, ["stats", "--help"])
        assert result.exit_code == 0


class TestModelsImport:
    """Verify that models can be imported and instantiated."""

    def test_workflow_ref(self) -> None:
        from gh_blast_radius.models import WorkflowRef

        ref = WorkflowRef(org="myorg", repo="shared", path=".github/workflows/build.yml", ref="v2")
        assert ref.full_name == "myorg/shared/.github/workflows/build.yml"
        assert ref.full_name_with_ref == "myorg/shared/.github/workflows/build.yml@v2"

    def test_workflow_ref_normalized(self) -> None:
        from gh_blast_radius.models import WorkflowRef

        ref = WorkflowRef(org="myorg", repo="shared", path=".github/workflows/build.yml", ref="v2")
        normalized = ref.normalized()
        assert normalized.ref is None
        assert normalized.full_name == ref.full_name

    def test_impact_report_summary(self) -> None:
        from gh_blast_radius.models import ConsumerEdge, ImpactReport, ImpactResult, WorkflowRef

        ref = WorkflowRef(org="o", repo="r", path="p")
        consumer = ConsumerEdge(
            target=ref,
            consumer_repo="o/c",
            consumer_workflow=".github/workflows/ci.yml",
            job_name="build",
        )
        report = ImpactReport(
            workflow_ref=ref,
            old_ref="v1",
            new_ref="v2",
            results=[
                ImpactResult(consumer=consumer, severity="breaking", reasons=["input removed"]),
                ImpactResult(consumer=consumer, severity="unaffected", reasons=[]),
            ],
        )
        assert report.summary == {"breaking": 1, "warning": 0, "unaffected": 1}
