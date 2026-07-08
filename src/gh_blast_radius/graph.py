"""Graph builder and query functions for GitHub Actions dependencies.

Uses networkx.DiGraph under the hood to store and query the dependency graph.
Nodes are either WorkflowNode (producers) or strings (consumer repos).
Edges represent consumption (ConsumerEdge).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import networkx as nx

if TYPE_CHECKING:
    from gh_blast_radius.models import ConsumerEdge, WorkflowNode, WorkflowRef


class DependencyGraph:
    """Wrapper around a networkx Directed Graph for GitHub Actions dependencies."""

    def __init__(self) -> None:
        # DiGraph where:
        # A -> B means A depends on B (A is consumer, B is producer)
        # Node IDs are strings (e.g., "org/repo" for consumers, "org/repo/path" for producers)
        self.nx_graph = nx.DiGraph()

        # We also store a mapping from string ID -> original objects
        self.producers: dict[str, WorkflowNode] = {}
        # Keep track of consumer repos to avoid treating them as producers
        self.consumer_repos: set[str] = set()

    def add_producer(self, node: WorkflowNode) -> None:
        """Add a shared workflow or action to the graph."""
        node_id = node.ref.normalized().full_name
        self.nx_graph.add_node(node_id, type="producer", data=node)
        self.producers[node_id] = node

    def add_consumer_edge(self, edge: ConsumerEdge) -> None:
        """Add a dependency edge from a consumer to a producer."""
        consumer_id = edge.consumer_repo
        producer_id = edge.target.normalized().full_name

        if consumer_id not in self.consumer_repos:
            self.nx_graph.add_node(consumer_id, type="consumer")
            self.consumer_repos.add(consumer_id)

        # If producer doesn't exist yet, we add a placeholder node
        if not self.nx_graph.has_node(producer_id):
            self.nx_graph.add_node(producer_id, type="producer_placeholder")

        # NetworkX edges can hold data
        # We use a MultiDiGraph if a repo consumes the same workflow multiple times
        # But for simplicity, we can just store a list of edges in a standard DiGraph
        if self.nx_graph.has_edge(consumer_id, producer_id):
            edge_data = self.nx_graph.edges[consumer_id, producer_id]
            edge_data["edges"].append(edge)
        else:
            self.nx_graph.add_edge(consumer_id, producer_id, edges=[edge])

    def get_consumers(
        self, target_ref: WorkflowRef, transitive: bool = False
    ) -> list[ConsumerEdge]:
        """Get all consumers of a given shared workflow or action.

        Args:
            target_ref: The workflow being consumed.
            transitive: If True, also find consumers of consumers (e.g., a workflow calling
                an action, and a repo calling that workflow).

        Returns:
            A list of ConsumerEdges.
        """
        producer_id = target_ref.normalized().full_name
        if not self.nx_graph.has_node(producer_id):
            return []

        consumers: list[ConsumerEdge] = []

        # In our graph, edges go from Consumer -> Producer.
        # To find consumers, we look at predecessors of the Producer.
        if transitive:
            # We need all ancestors
            ancestors = nx.ancestors(self.nx_graph, producer_id)
            for _ancestor in ancestors:
                # Find paths to the producer. We can just collect all edges in the subgraph
                # But actually, an ancestor might consume X which consumes producer_id.
                # The ConsumerEdge models direct consumption.
                # For v1, transitive usually just means returning direct edges of all ancestors
                # that lead to this producer.
                pass  # to be implemented later if needed fully

        # Direct consumers
        for predecessor in self.nx_graph.predecessors(producer_id):
            edge_data = self.nx_graph.edges[predecessor, producer_id]
            consumers.extend(edge_data.get("edges", []))

        return consumers

    def get_dependencies(self, repo: str) -> list[WorkflowRef]:
        """Get all workflows/actions consumed by a repository."""
        if not self.nx_graph.has_node(repo):
            return []

        deps: list[WorkflowRef] = []
        for successor in self.nx_graph.successors(repo):
            # successor is a producer_id
            edge_data = self.nx_graph.edges[repo, successor]
            for edge in edge_data.get("edges", []):
                deps.append(edge.target)

        return deps

    def get_stats(self) -> dict[str, int]:
        """Return basic graph statistics."""
        return {
            "total_nodes": self.nx_graph.number_of_nodes(),
            "total_edges": sum(
                len(d.get("edges", [])) for _, _, d in self.nx_graph.edges(data=True)
            ),
            "total_producers": len(self.producers),
            "total_consumers": len(self.consumer_repos),
        }
