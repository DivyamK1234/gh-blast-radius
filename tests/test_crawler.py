"""Tests for the OrgCrawler."""

from __future__ import annotations

from gh_blast_radius.crawler import OrgCrawler
from gh_blast_radius.github_client import GitHubClient
from gh_blast_radius.models import FileInfo, RepoInfo


class MockClient(GitHubClient):
    """Mock client for testing crawler without hitting network."""

    def __init__(self) -> None:
        pass

    def list_repos(self, org: str, include_archived: bool = False) -> list[RepoInfo]:
        return [
            RepoInfo("test-org", "consumer-repo", "test-org/consumer-repo", "main"),
        ]

    def get_workflow_files(self, org: str, repo: str) -> list[FileInfo]:
        return [FileInfo(".github/workflows/ci.yml", "sha1")]

    def get_file_content(
        self, org: str, repo: str, path: str, ref: str | None = None
    ) -> str | None:
        if path == ".github/workflows/ci.yml":
            return """
jobs:
  build:
    uses: test-org/shared/.github/workflows/build.yml@v1
"""
        if path == ".github/workflows/build.yml":
            return """
name: Build
on:
  workflow_call:
    inputs:
      env:
        required: true
"""
        return None


def test_crawler_builds_graph() -> None:
    client = MockClient()
    crawler = OrgCrawler(client)

    graph = crawler.crawl_org("test-org")

    stats = graph.get_stats()
    assert stats["total_producers"] == 1
    assert stats["total_consumers"] == 1

    deps = graph.get_dependencies("test-org/consumer-repo")
    assert len(deps) == 1
    assert deps[0].repo == "shared"

    consumers = graph.get_consumers(deps[0])
    assert len(consumers) == 1
    assert consumers[0].job_name == "build"
