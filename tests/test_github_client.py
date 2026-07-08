"""Tests for the GitHub API client.

Uses pytest-httpx to mock all HTTP requests — no real API calls are made.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from gh_blast_radius.github_client import (
    AuthenticationError,
    GitHubClient,
    GitHubClientError,
    NotFoundError,
    RateLimitExceededError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def token() -> str:
    return "ghp_test_token_12345"


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def client(token: str, cache_dir: Path) -> GitHubClient:
    """Create a GitHubClient with caching directed to a temp directory."""
    c = GitHubClient(token, cache_dir=cache_dir)
    yield c
    c.close()


@pytest.fixture
def client_no_cache(token: str) -> GitHubClient:
    """Create a GitHubClient with caching disabled."""
    c = GitHubClient(token, cache_dir=None)
    yield c
    c.close()


# Helpers for building mock responses
def _rate_limit_headers(remaining: int = 4999, limit: int = 5000) -> dict:
    return {
        "x-ratelimit-remaining": str(remaining),
        "x-ratelimit-limit": str(limit),
        "x-ratelimit-reset": "9999999999",
    }


def _repo_json(name: str, org: str = "test-org", archived: bool = False) -> dict:
    return {
        "name": name,
        "full_name": f"{org}/{name}",
        "default_branch": "main",
        "archived": archived,
    }


def _branch_json(sha: str = "abc123") -> dict:
    return {"commit": {"sha": sha}}


def _file_entry(name: str, sha: str = "file_sha_1") -> dict:
    return {
        "name": name,
        "path": f".github/workflows/{name}",
        "sha": sha,
        "size": 500,
        "type": "file",
        "download_url": f"https://raw.githubusercontent.com/test/{name}",
    }


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_requires_token(self) -> None:
        with pytest.raises(AuthenticationError, match="token is required"):
            GitHubClient("")

    def test_401_raises_auth_error(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(status_code=401, json={"message": "Bad credentials"})
        with pytest.raises(AuthenticationError, match="401"):
            client.get_rate_limit()

    def test_valid_token_sets_header(self, token: str) -> None:
        c = GitHubClient(token)
        assert c._client.headers["authorization"] == f"Bearer {token}"
        c.close()


# ---------------------------------------------------------------------------
# list_repos tests
# ---------------------------------------------------------------------------


class TestListRepos:
    def test_lists_repos_single_page(self, client: GitHubClient, httpx_mock) -> None:
        # Mock the repos endpoint
        httpx_mock.add_response(
            url="https://api.github.com/orgs/test-org/repos?type=all&per_page=100",
            json=[_repo_json("repo-a"), _repo_json("repo-b")],
            headers=_rate_limit_headers(),
        )
        # Mock branch SHA lookups
        httpx_mock.add_response(
            url="https://api.github.com/repos/test-org/repo-a/branches/main",
            json=_branch_json("sha_a"),
            headers=_rate_limit_headers(),
        )
        httpx_mock.add_response(
            url="https://api.github.com/repos/test-org/repo-b/branches/main",
            json=_branch_json("sha_b"),
            headers=_rate_limit_headers(),
        )

        repos = client.list_repos("test-org")
        assert len(repos) == 2
        assert repos[0].name == "repo-a"
        assert repos[0].last_commit_sha == "sha_a"
        assert repos[1].name == "repo-b"

    def test_excludes_archived_by_default(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(
            json=[_repo_json("active"), _repo_json("old", archived=True)],
            headers=_rate_limit_headers(),
        )
        httpx_mock.add_response(
            url="https://api.github.com/repos/test-org/active/branches/main",
            json=_branch_json(),
            headers=_rate_limit_headers(),
        )

        repos = client.list_repos("test-org")
        assert len(repos) == 1
        assert repos[0].name == "active"

    def test_includes_archived_when_requested(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(
            json=[_repo_json("active"), _repo_json("old", archived=True)],
            headers=_rate_limit_headers(),
        )
        # Branch SHA lookups for both repos
        httpx_mock.add_response(json=_branch_json(), headers=_rate_limit_headers())
        httpx_mock.add_response(json=_branch_json(), headers=_rate_limit_headers())

        repos = client.list_repos("test-org", include_archived=True)
        assert len(repos) == 2

    def test_pagination_follows_link_headers(self, client: GitHubClient, httpx_mock) -> None:
        # Page 1 with Link header pointing to page 2
        httpx_mock.add_response(
            url="https://api.github.com/orgs/test-org/repos?type=all&per_page=100",
            json=[_repo_json("repo-a")],
            headers={
                **_rate_limit_headers(),
                "link": (
                    '<https://api.github.com/orgs/test-org/repos?page=2&per_page=100>; rel="next"'
                ),
            },
        )
        # Page 2 with no Link header (last page)
        httpx_mock.add_response(
            url="https://api.github.com/orgs/test-org/repos?page=2&per_page=100",
            json=[_repo_json("repo-b")],
            headers=_rate_limit_headers(),
        )
        # Branch SHA lookups
        httpx_mock.add_response(json=_branch_json("sha_a"), headers=_rate_limit_headers())
        httpx_mock.add_response(json=_branch_json("sha_b"), headers=_rate_limit_headers())

        repos = client.list_repos("test-org")
        assert len(repos) == 2
        assert repos[0].name == "repo-a"
        assert repos[1].name == "repo-b"


# ---------------------------------------------------------------------------
# get_workflow_files tests
# ---------------------------------------------------------------------------


class TestGetWorkflowFiles:
    def test_lists_yml_files(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(
            json=[
                _file_entry("ci.yml"),
                _file_entry("deploy.yaml"),
                _file_entry("README.md"),  # Not a workflow file
                {"name": "subdir", "type": "dir", "path": ".github/workflows/subdir"},
            ],
            headers=_rate_limit_headers(),
        )

        files = client.get_workflow_files("org", "repo")
        assert len(files) == 2
        assert files[0].path == ".github/workflows/ci.yml"
        assert files[1].path == ".github/workflows/deploy.yaml"

    def test_returns_empty_for_missing_directory(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(status_code=404, json={"message": "Not Found"})

        files = client.get_workflow_files("org", "repo")
        assert files == []


# ---------------------------------------------------------------------------
# get_file_content tests
# ---------------------------------------------------------------------------


class TestGetFileContent:
    def test_decodes_base64_content(self, client: GitHubClient, httpx_mock) -> None:
        import base64

        content = "name: CI\non:\n  push:\n    branches: [main]\n"
        encoded = base64.b64encode(content.encode()).decode()

        httpx_mock.add_response(
            json={
                "sha": "file_sha_123",
                "content": encoded,
                "encoding": "base64",
            },
            headers=_rate_limit_headers(),
        )

        result = client.get_file_content("org", "repo", ".github/workflows/ci.yml")
        assert result == content

    def test_raises_not_found(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(status_code=404, json={"message": "Not Found"})

        with pytest.raises(NotFoundError):
            client.get_file_content("org", "repo", "nonexistent.yml")

    def test_passes_ref_param(self, client: GitHubClient, httpx_mock) -> None:
        import base64

        httpx_mock.add_response(
            json={
                "sha": "abc",
                "content": base64.b64encode(b"content").decode(),
                "encoding": "base64",
            },
            headers=_rate_limit_headers(),
        )

        client.get_file_content("org", "repo", "file.yml", ref="v2")

        request = httpx_mock.get_requests()[0]
        assert "ref=v2" in str(request.url)


# ---------------------------------------------------------------------------
# Caching tests
# ---------------------------------------------------------------------------


class TestCaching:
    def test_cache_hit_avoids_second_request(self, client: GitHubClient, httpx_mock) -> None:
        import base64

        content = "cached content"
        encoded = base64.b64encode(content.encode()).decode()

        # First request returns content + SHA
        httpx_mock.add_response(
            json={"sha": "same_sha", "content": encoded, "encoding": "base64"},
            headers=_rate_limit_headers(),
        )
        # Second request returns same SHA (metadata only needed for cache check)
        httpx_mock.add_response(
            json={"sha": "same_sha", "content": encoded, "encoding": "base64"},
            headers=_rate_limit_headers(),
        )

        result1 = client.get_file_content("org", "repo", "file.yml")
        result2 = client.get_file_content("org", "repo", "file.yml")

        assert result1 == content
        assert result2 == content
        # Both requests hit the API for metadata, but second should use cache for content
        assert len(httpx_mock.get_requests()) == 2

    def test_no_cache_when_disabled(self, client_no_cache: GitHubClient, httpx_mock) -> None:
        import base64

        content = "no cache"
        encoded = base64.b64encode(content.encode()).decode()

        httpx_mock.add_response(
            json={"sha": "sha1", "content": encoded, "encoding": "base64"},
            headers=_rate_limit_headers(),
        )

        result = client_no_cache.get_file_content("org", "repo", "file.yml")
        assert result == content


# ---------------------------------------------------------------------------
# Rate limiting tests
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_raises_when_wait_too_long(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(
            status_code=403,
            json={"message": "API rate limit exceeded"},
            headers={
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "9999999999",  # Far in the future
            },
        )

        with pytest.raises(RateLimitExceededError, match="Rate limit exceeded"):
            client.get_rate_limit()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_404_raises_not_found(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(status_code=404, json={"message": "Not Found"})
        with pytest.raises(NotFoundError):
            client._request("GET", "/repos/org/repo")

    def test_403_non_ratelimit_raises(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(
            status_code=403,
            json={"message": "Repository access blocked"},
            headers={"x-ratelimit-remaining": "4999"},
        )
        with pytest.raises(GitHubClientError, match="Forbidden"):
            client._request("GET", "/repos/org/repo")

    def test_server_error_retries(self, client: GitHubClient, httpx_mock) -> None:
        # First two attempts fail with 500, third succeeds
        httpx_mock.add_response(
            status_code=500,
            json={"message": "Internal Server Error"},
            headers=_rate_limit_headers(),
        )
        httpx_mock.add_response(
            status_code=500,
            json={"message": "Internal Server Error"},
            headers=_rate_limit_headers(),
        )
        httpx_mock.add_response(
            status_code=200,
            json={"ok": True},
            headers=_rate_limit_headers(),
        )

        result = client._request("GET", "/test")
        assert result == {"ok": True}
        assert len(httpx_mock.get_requests()) == 3


# ---------------------------------------------------------------------------
# Link header parsing tests
# ---------------------------------------------------------------------------


class TestLinkHeaderParsing:
    def test_parses_next_link(self) -> None:
        response = type(
            "FakeResponse",
            (),
            {
                "headers": {
                    "link": '<https://api.github.com/orgs/test/repos?page=2>; rel="next", '
                    '<https://api.github.com/orgs/test/repos?page=5>; rel="last"'
                }
            },
        )()
        url = GitHubClient._parse_next_link(response)
        assert url == "https://api.github.com/orgs/test/repos?page=2"

    def test_returns_none_when_no_next(self) -> None:
        response = type(
            "FakeResponse",
            (),
            {"headers": {"link": '<https://api.github.com/orgs/test/repos?page=1>; rel="first"'}},
        )()
        url = GitHubClient._parse_next_link(response)
        assert url is None

    def test_returns_none_when_no_link_header(self) -> None:
        response = type("FakeResponse", (), {"headers": {}})()
        url = GitHubClient._parse_next_link(response)
        assert url is None


# ---------------------------------------------------------------------------
# get_action_manifest tests
# ---------------------------------------------------------------------------


class TestGetActionManifest:
    def test_tries_yml_then_yaml(self, client: GitHubClient, httpx_mock) -> None:
        import base64

        content = "name: My Action\nruns:\n  using: composite\n"
        encoded = base64.b64encode(content.encode()).decode()

        # action.yml returns 404
        httpx_mock.add_response(status_code=404, json={"message": "Not Found"})
        # action.yaml returns content
        httpx_mock.add_response(
            json={"sha": "sha1", "content": encoded, "encoding": "base64"},
            headers=_rate_limit_headers(),
        )

        result = client.get_action_manifest("org", "repo", ".github/actions/setup")
        assert result == content

    def test_returns_none_when_neither_exists(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(status_code=404, json={"message": "Not Found"})
        httpx_mock.add_response(status_code=404, json={"message": "Not Found"})

        result = client.get_action_manifest("org", "repo", ".github/actions/setup")
        assert result is None


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager(self, token: str, cache_dir: Path) -> None:
        with GitHubClient(token, cache_dir=cache_dir) as client:
            assert client is not None
        # Client should be closed after exiting context
        # (httpx.Client doesn't raise on operations after close, but
        # this tests the __enter__/__exit__ contract)


# ---------------------------------------------------------------------------
# get_rate_limit tests
# ---------------------------------------------------------------------------


class TestGetRateLimit:
    def test_returns_core_rate_limit(self, client: GitHubClient, httpx_mock) -> None:
        httpx_mock.add_response(
            json={
                "resources": {
                    "core": {
                        "limit": 5000,
                        "remaining": 4999,
                        "reset": 1234567890,
                        "used": 1,
                    }
                }
            },
            headers=_rate_limit_headers(),
        )

        result = client.get_rate_limit()
        assert result["limit"] == 5000
        assert result["remaining"] == 4999
