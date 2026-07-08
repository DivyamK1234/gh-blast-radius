"""Org Crawler to build the DependencyGraph using GitHubClient and Parser."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from gh_blast_radius.graph import DependencyGraph
from gh_blast_radius.parser import (
    parse_action_file,
    parse_producer_interface,
    parse_workflow_file,
)

if TYPE_CHECKING:
    from gh_blast_radius.github_client import GitHubClient
    from gh_blast_radius.models import ConsumerEdge, WorkflowRef

logger = logging.getLogger(__name__)


class OrgCrawler:
    """Crawls a GitHub organization to build a DependencyGraph."""

    def __init__(self, client: GitHubClient) -> None:
        self.client = client
        self.graph = DependencyGraph()

    def crawl_org(self, org: str, include_archived: bool = False) -> DependencyGraph:
        """Crawl all repositories in an organization.

        Args:
            org: The GitHub organization name.
            include_archived: Whether to include archived repositories.

        Returns:
            The populated DependencyGraph.
        """
        logger.info("Starting crawl for org: %s", org)
        repos = self.client.list_repos(org, include_archived=include_archived)
        logger.info("Found %d repositories.", len(repos))

        for repo in repos:
            logger.info("Scanning %s", repo.full_name)
            self._scan_repo(repo.full_name, repo.last_commit_sha)

        return self.graph

    def _scan_repo(self, repo_full_name: str, default_branch_sha: str) -> None:
        """Scan a single repository for workflows and actions."""
        org, repo_name = repo_full_name.split("/", 1)
        workflow_files = self.client.get_workflow_files(org, repo_name)

        edges: list[ConsumerEdge] = []
        for file_info in workflow_files:
            try:
                content = self.client.get_file_content(
                    org, repo_name, file_info.path, ref=default_branch_sha
                )
            except Exception as e:
                logger.warning(f"Could not fetch {file_info.path} from {org}/{repo_name}: {e}")
                continue

            if not content:
                continue

            file_edges = parse_workflow_file(content, repo_full_name, file_info.path)
            edges.extend(file_edges)

        # For v1, we can also try to find composite actions in the repo.
        # This requires searching the repo tree for action.yml files.
        # to find all `action.yml` files in a repo is one way.
        # Alternatively, we can just resolve producers lazily based on what is consumed!
        # Yes, lazy resolution is MUCH more efficient.
        # If repo A consumes B/actions/setup, we only need to parse B/actions/setup.

        for edge in edges:
            self.graph.add_consumer_edge(edge)

            target = edge.target
            producer_id = target.normalized().full_name
            if producer_id not in self.graph.producers:
                self._resolve_producer(target, default_branch_sha)

    def _resolve_producer(self, target: WorkflowRef, consumer_sha: str) -> None:
        """Fetch and parse a producer to add it to the graph."""
        try:
            if target.path.endswith(".yml") or target.path.endswith(".yaml"):
                content = self.client.get_file_content(
                    target.org, target.repo, target.path, ref=target.ref
                )
                if content:
                    node = parse_producer_interface(content, "reusable_workflow", target)
                    self.graph.add_producer(node)
            else:
                content = self.client.get_action_manifest(
                    target.org, target.repo, target.path, ref=target.ref
                )
                if content:
                    node = parse_producer_interface(content, "composite_action", target)
                    self.graph.add_producer(node)

                    nested_edges = parse_action_file(
                        content, f"{target.org}/{target.repo}", f"{target.path}/action.yml"
                    )
                    for edge in nested_edges:
                        self.graph.add_consumer_edge(edge)
                        producer_id = edge.target.normalized().full_name
                        if producer_id not in self.graph.producers:
                            self._resolve_producer(edge.target, target.ref or "")
        except Exception as e:
            logger.warning(f"Could not resolve producer {target.full_name}: {e}")
