"""Tests for the Graph builder and Storage module."""

from gh_blast_radius.graph import DependencyGraph
from gh_blast_radius.models import ConsumerEdge, WorkflowNode, WorkflowRef
from gh_blast_radius.storage import load_graph, save_graph


def test_graph_add_producer_and_consumer() -> None:
    graph = DependencyGraph()

    ref = WorkflowRef("org", "repo", "path", "v1")
    producer = WorkflowNode(ref=ref, type="reusable_workflow")

    graph.add_producer(producer)

    edge = ConsumerEdge(
        target=ref,
        consumer_repo="org/consumer",
        consumer_workflow=".github/workflows/ci.yml",
        job_name="build",
        ref_used="v1",
    )
    graph.add_consumer_edge(edge)

    stats = graph.get_stats()
    assert stats["total_producers"] == 1
    assert stats["total_consumers"] == 1

    consumers = graph.get_consumers(ref)
    assert len(consumers) == 1
    assert consumers[0].consumer_repo == "org/consumer"

    deps = graph.get_dependencies("org/consumer")
    assert len(deps) == 1
    assert deps[0].org == "org"


def test_storage_save_and_load(tmp_path) -> None:
    graph = DependencyGraph()

    ref = WorkflowRef("org", "shared", "build.yml", "v2")
    producer = WorkflowNode(
        ref=ref,
        type="reusable_workflow",
        inputs={},
        secrets={},
        outputs={"success": "true"},
    )
    graph.add_producer(producer)

    edge = ConsumerEdge(
        target=ref,
        consumer_repo="org/frontend",
        consumer_workflow=".github/workflows/deploy.yml",
        job_name="deploy",
        ref_used="v2",
        inputs_passed={"env": "prod"},
    )
    graph.add_consumer_edge(edge)

    file_path = tmp_path / "graph.json"
    save_graph(graph, file_path)

    assert file_path.exists()

    loaded_graph = load_graph(file_path)

    stats = loaded_graph.get_stats()
    assert stats["total_producers"] == 1
    assert stats["total_consumers"] == 1

    consumers = loaded_graph.get_consumers(ref)
    assert len(consumers) == 1
    assert consumers[0].inputs_passed == {"env": "prod"}
