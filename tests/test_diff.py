"""Tests for the diff impact analysis engine."""

from gh_blast_radius.diff import compute_impact
from gh_blast_radius.models import ConsumerEdge, InputDef, SecretDef, WorkflowNode, WorkflowRef


def test_compute_impact_unaffected() -> None:
    ref = WorkflowRef("org", "repo", "path.yml")
    old_node = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        inputs={"env": InputDef(required=True)},
    )
    new_node = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        inputs={"env": InputDef(required=True)},
    )
    consumers = [
        ConsumerEdge(
            target=ref,
            consumer_repo="org/consumer",
            consumer_workflow="ci.yml",
            job_name="build",
            inputs_passed={"env": "prod"},
        )
    ]

    report = compute_impact(ref, old_node, new_node, consumers, "v1", "v2")
    assert len(report.results) == 1
    assert report.results[0].severity == "unaffected"
    assert report.summary == {"breaking": 0, "warning": 0, "unaffected": 1}


def test_compute_impact_removed_input_is_breaking() -> None:
    ref = WorkflowRef("org", "repo", "path.yml")
    old_node = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        inputs={"env": InputDef(), "version": InputDef()},
    )
    new_node = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        inputs={"env": InputDef()},
    )
    consumers = [
        ConsumerEdge(
            target=ref,
            consumer_repo="org/consumer",
            consumer_workflow="ci.yml",
            job_name="build",
            inputs_passed={"env": "prod", "version": "1.0"},
        )
    ]

    report = compute_impact(ref, old_node, new_node, consumers, "v1", "v2")
    assert report.results[0].severity == "breaking"
    assert "Input 'version' was removed" in report.results[0].reasons[0]


def test_compute_impact_new_required_input_is_breaking() -> None:
    ref = WorkflowRef("org", "repo", "path.yml")
    old_node = WorkflowNode(ref=ref, type="reusable_workflow")
    new_node = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        inputs={"env": InputDef(required=True)},
    )
    consumers = [
        ConsumerEdge(
            target=ref,
            consumer_repo="org/consumer",
            consumer_workflow="ci.yml",
            job_name="build",
        )
    ]

    report = compute_impact(ref, old_node, new_node, consumers, "v1", "v2")
    assert report.results[0].severity == "breaking"
    assert "New required input 'env'" in report.results[0].reasons[0]


def test_compute_impact_new_optional_input_is_warning() -> None:
    ref = WorkflowRef("org", "repo", "path.yml")
    old_node = WorkflowNode(ref=ref, type="reusable_workflow")
    new_node = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        inputs={"env": InputDef(required=False)},
    )
    consumers = [
        ConsumerEdge(
            target=ref,
            consumer_repo="org/consumer",
            consumer_workflow="ci.yml",
            job_name="build",
        )
    ]

    report = compute_impact(ref, old_node, new_node, consumers, "v1", "v2")
    assert report.results[0].severity == "warning"
    assert "New optional input 'env'" in report.results[0].reasons[0]


def test_compute_impact_secrets_inherit() -> None:
    ref = WorkflowRef("org", "repo", "path.yml")
    old_node = WorkflowNode(ref=ref, type="reusable_workflow")
    new_node = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        secrets={"api_key": SecretDef(required=True)},
    )
    consumers = [
        ConsumerEdge(
            target=ref,
            consumer_repo="org/consumer",
            consumer_workflow="ci.yml",
            job_name="build",
            secrets_passed="inherit",
        )
    ]

    report = compute_impact(ref, old_node, new_node, consumers, "v1", "v2")
    # Because it uses inherit, it automatically fulfills required secrets without breaking
    assert report.results[0].severity == "unaffected"
