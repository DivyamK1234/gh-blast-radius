"""GitHub API client for gh-blast-radius.

Provides authenticated access to the GitHub REST API via httpx, with
automatic pagination, rate-limit handling, retry logic, and local caching.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from pathlib import Path

import httpx

from gh_blast_radius.models import FileInfo, RepoInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_CACHE_DIR = Path(".workflow-impact") / "cache"
DEFAULT_PER_PAGE = 100
MAX_RETRIES = 3
RATE_LIMIT_BUFFER = 10  # Start slowing down when this many requests remain


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""


class AuthenticationError(GitHubClientError):
    """Raised when authentication fails (401)."""


class RateLimitExceededError(GitHubClientError):
    """Raised when rate limit is exhausted and cannot be waited out."""


class NotFoundError(GitHubClientError):
    """Raised when a resource is not found (404)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubClient:
    """Authenticated GitHub REST API client with pagination, rate limiting, and caching.

    Args:
        token: GitHub personal access token or GitHub App token.
            If ``None``, falls back to the ``GITHUB_TOKEN`` environment variable.
        cache_dir: Directory for the local content-addressed cache.
            Set to ``None`` to disable caching.
        base_url: GitHub API base URL (for GitHub Enterprise support).
    """

    def __init__(
        self,
        token: str,
        *,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        base_url: str = GITHUB_API_BASE,
    ) -> None:
        if not token:
            raise AuthenticationError(
                "A GitHub token is required. Pass --token or set the GITHUB_TOKEN env var."
            )

        self._base_url = base_url.rstrip("/")
        self._cache_dir = cache_dir
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            follow_redirects=True,
        )

        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_repos(
        self,
        org: str,
        *,
        include_archived: bool = False,
    ) -> list[RepoInfo]:
        """List all repositories in an organization.

        Args:
            org: GitHub organization name.
            include_archived: If ``True``, include archived repositories.

        Returns:
            List of :class:`RepoInfo` for each repository.
        """
        repos: list[RepoInfo] = []
        data = self._paginate(f"/orgs/{org}/repos", params={"type": "all"})

        for item in data:
            if not include_archived and item.get("archived", False):
                logger.debug("Skipping archived repo: %s", item["full_name"])
                continue

            repos.append(
                RepoInfo(
                    org=org,
                    name=item["name"],
                    full_name=item["full_name"],
                    default_branch=item.get("default_branch", "main"),
                    archived=item.get("archived", False),
                    last_commit_sha=self._get_default_branch_sha(
                        org, item["name"], item.get("default_branch", "main")
                    ),
                )
            )

        logger.info("Found %d repos in org '%s'", len(repos), org)
        return repos

    def get_workflow_files(self, org: str, repo: str) -> list[FileInfo]:
        """List all workflow files in a repository's ``.github/workflows/`` directory.

        Args:
            org: Organization name.
            repo: Repository name.

        Returns:
            List of :class:`FileInfo` for each ``.yml`` / ``.yaml`` file found.
            Returns an empty list if the directory does not exist.
        """
        try:
            data = self._request("GET", f"/repos/{org}/{repo}/contents/.github/workflows")
        except NotFoundError:
            logger.debug("No .github/workflows/ in %s/%s", org, repo)
            return []

        if not isinstance(data, list):
            # The Contents API returns an object (not a list) when the path
            # points to a single file, or a git tree reference for very large
            # directories.  For tree references we'd need the Git Trees API;
            # for now log a warning and return empty.
            logger.warning(
                "Unexpected response format for %s/%s workflows dir "
                "(possibly >1000 files — falling back to empty list).",
                org,
                repo,
            )
            return []

        files: list[FileInfo] = []
        for item in data:
            if item.get("type") != "file":
                continue
            name = item.get("name", "")
            if not (name.endswith(".yml") or name.endswith(".yaml")):
                continue
            files.append(
                FileInfo(
                    path=item["path"],
                    sha=item["sha"],
                    size=item.get("size", 0),
                    download_url=item.get("download_url"),
                )
            )

        logger.debug("Found %d workflow files in %s/%s", len(files), org, repo)
        return files

    def get_file_content(
        self,
        org: str,
        repo: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> str:
        """Fetch the decoded text content of a file.

        Uses a content-addressed local cache keyed by ``{org}/{repo}/{path}@{sha}``.
        If the file is in cache (matched by SHA), the cached content is returned
        without making a network request.

        Args:
            org: Organization name.
            repo: Repository name.
            path: File path within the repo (e.g. ``".github/workflows/ci.yml"``).
            ref: Git ref (branch, tag, or SHA). Defaults to the repo's default branch.

        Returns:
            The file content as a decoded UTF-8 string.

        Raises:
            NotFoundError: If the file does not exist.
            GitHubClientError: On other API errors.
        """
        params: dict[str, str] = {}
        if ref:
            params["ref"] = ref

        # First, get metadata (including SHA) via the Contents API
        data = self._request("GET", f"/repos/{org}/{repo}/contents/{path}", params=params)

        if isinstance(data, list):
            raise GitHubClientError(
                f"Expected a file but got a directory listing for {org}/{repo}/{path}"
            )

        sha = data.get("sha", "")

        # Check cache
        cached = self._cache_get(org, repo, path, sha)
        if cached is not None:
            logger.debug("Cache hit for %s/%s/%s@%s", org, repo, path, sha[:8])
            return cached

        # Decode content from the API response
        content_b64 = data.get("content", "")
        encoding = data.get("encoding", "base64")

        if encoding == "base64" and content_b64:
            content = base64.b64decode(content_b64).decode("utf-8")
        elif data.get("download_url"):
            # Fallback for files >1MB where GitHub omits inline content
            response = self._client.get(data["download_url"])
            response.raise_for_status()
            content = response.text
        else:
            raise GitHubClientError(
                f"Cannot decode content for {org}/{repo}/{path} "
                f"(encoding={encoding}, has_download_url={bool(data.get('download_url'))})"
            )

        # Store in cache
        self._cache_put(org, repo, path, sha, content)
        return content

    def get_action_manifest(
        self,
        org: str,
        repo: str,
        action_path: str,
        *,
        ref: str | None = None,
    ) -> str | None:
        """Fetch the ``action.yml`` or ``action.yaml`` manifest for a composite action.

        Tries ``action.yml`` first, then ``action.yaml``.

        Args:
            org: Organization name.
            repo: Repository name.
            action_path: Directory path of the action (e.g. ``".github/actions/setup"``).
            ref: Git ref. Defaults to the repo's default branch.

        Returns:
            The manifest content as a string, or ``None`` if not found.
        """
        for filename in ("action.yml", "action.yaml"):
            full_path = f"{action_path.rstrip('/')}/{filename}"
            try:
                return self.get_file_content(org, repo, full_path, ref=ref)
            except NotFoundError:
                continue
        return None

    def get_rate_limit(self) -> dict:
        """Return the current rate limit status.

        Returns:
            Dict with ``limit``, ``remaining``, ``reset`` (unix timestamp), and
            ``used`` keys from the ``core`` rate limit resource.
        """
        data = self._request("GET", "/rate_limit")
        return data.get("resources", {}).get("core", {})

    # ------------------------------------------------------------------
    # Internal: HTTP request with retries + rate limiting
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict | list:
        """Make a single API request with retry and rate-limit handling.

        Args:
            method: HTTP method.
            path: API path (relative to base_url).
            params: Query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            AuthenticationError: On 401.
            NotFoundError: On 404.
            RateLimitExceeded: When rate limit is exhausted beyond patience.
            GitHubClientError: On other errors after retries exhausted.
        """
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.request(method, path, params=params)

                # Handle rate limiting
                self._check_rate_limit(response)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 401:
                    raise AuthenticationError(
                        "Authentication failed (401). Check your GitHub token."
                    )

                if response.status_code == 404:
                    raise NotFoundError(f"Not found: {method} {path}")

                if response.status_code == 403:
                    # Could be rate limit or permission issue
                    remaining = int(response.headers.get("x-ratelimit-remaining", "1"))
                    if remaining == 0:
                        self._wait_for_rate_limit(response)
                        continue  # Retry after waiting
                    raise GitHubClientError(
                        f"Forbidden (403): {response.json().get('message', 'Unknown')}"
                    )

                if response.status_code >= 500:
                    wait = 2**attempt
                    logger.warning(
                        "Server error %d on attempt %d/%d, retrying in %ds...",
                        response.status_code,
                        attempt,
                        MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                # Other 4xx errors — don't retry
                raise GitHubClientError(
                    f"API error {response.status_code}: "
                    f"{response.json().get('message', response.text)}"
                )

            except httpx.TransportError as exc:
                last_error = exc
                wait = 2**attempt
                logger.warning(
                    "Network error on attempt %d/%d (%s), retrying in %ds...",
                    attempt,
                    MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise GitHubClientError(
            f"Request failed after {MAX_RETRIES} retries: {last_error}"
        )

    def _paginate(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> list[dict]:
        """Fetch all pages of a paginated endpoint.

        Follows ``Link: <...>; rel="next"`` headers automatically.

        Args:
            path: API path.
            params: Base query parameters.

        Returns:
            Concatenated list of all items across all pages.
        """
        return self._paginate_impl(path, params)

    def _paginate_impl(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> list[dict]:
        """Internal paginator that properly follows Link headers."""
        all_items: list[dict] = []
        merged_params = {**(params or {}), "per_page": str(DEFAULT_PER_PAGE)}
        url = path
        is_first = True

        while url:
            try:
                if is_first:
                    response = self._client.request("GET", url, params=merged_params)
                    is_first = False
                else:
                    # Subsequent pages — url is a full URL from Link header
                    response = self._client.get(url)

                self._check_rate_limit(response)

                if response.status_code == 401:
                    raise AuthenticationError(
                        "Authentication failed (401). Check your GitHub token."
                    )
                if response.status_code == 404:
                    raise NotFoundError(f"Not found: GET {path}")
                if response.status_code != 200:
                    raise GitHubClientError(
                        f"API error {response.status_code}: {response.text}"
                    )

                data = response.json()
                if isinstance(data, list):
                    all_items.extend(data)
                else:
                    all_items.append(data)

                # Parse Link header for next page URL
                url = self._parse_next_link(response)

            except httpx.TransportError as exc:
                logger.warning("Network error during pagination: %s", exc)
                raise GitHubClientError(f"Pagination failed: {exc}") from exc

        return all_items

    # ------------------------------------------------------------------
    # Internal: Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self, response: httpx.Response) -> None:
        """Log a warning if we're approaching the rate limit."""
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            remaining_int = int(remaining)
            if remaining_int <= RATE_LIMIT_BUFFER and remaining_int > 0:
                reset_at = int(response.headers.get("x-ratelimit-reset", "0"))
                wait_seconds = max(0, reset_at - int(time.time()))
                logger.warning(
                    "Approaching rate limit: %d requests remaining (resets in %ds)",
                    remaining_int,
                    wait_seconds,
                )
            elif remaining_int == 0:
                self._wait_for_rate_limit(response)

    def _wait_for_rate_limit(self, response: httpx.Response) -> None:
        """Sleep until the rate limit resets."""
        reset_at = int(response.headers.get("x-ratelimit-reset", "0"))
        wait_seconds = max(1, reset_at - int(time.time()) + 1)

        if wait_seconds > 300:
            raise RateLimitExceededError(
                f"Rate limit exceeded. Resets in {wait_seconds}s (>{300}s max wait). "
                "Consider using a GitHub App token for higher limits."
            )

        logger.warning(
            "Rate limit hit (0 remaining). Sleeping for %ds until reset...",
            wait_seconds,
        )
        time.sleep(wait_seconds)

    # ------------------------------------------------------------------
    # Internal: Link header parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_next_link(response: httpx.Response) -> str | None:
        """Extract the ``next`` URL from the ``Link`` response header.

        GitHub returns pagination links like:
        ``<https://api.github.com/...?page=2>; rel="next", <...>; rel="last"``

        Returns:
            The URL for the next page, or ``None`` if there is no next page.
        """
        link_header = response.headers.get("link", "")
        if not link_header:
            return None

        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                # Extract URL between < and >
                url_start = part.index("<") + 1
                url_end = part.index(">")
                return part[url_start:url_end]

        return None

    # ------------------------------------------------------------------
    # Internal: Caching
    # ------------------------------------------------------------------

    def _cache_key(self, org: str, repo: str, path: str, sha: str) -> str:
        """Generate a deterministic cache key from the file coordinates."""
        raw = f"{org}/{repo}/{path}@{sha}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        """Return the filesystem path for a cache entry, or None if caching is disabled."""
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"{key}.json"

    def _cache_get(self, org: str, repo: str, path: str, sha: str) -> str | None:
        """Look up a cached file content by its coordinates.

        Returns:
            The cached content string, or ``None`` if not cached.
        """
        if not sha:
            return None
        cache_path = self._cache_path(self._cache_key(org, repo, path, sha))
        if cache_path is None or not cache_path.exists():
            return None
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return data.get("content")
        except (json.JSONDecodeError, OSError):
            return None

    def _cache_put(self, org: str, repo: str, path: str, sha: str, content: str) -> None:
        """Store file content in the local cache."""
        if not sha:
            return
        cache_path = self._cache_path(self._cache_key(org, repo, path, sha))
        if cache_path is None:
            return
        try:
            data = {
                "org": org,
                "repo": repo,
                "path": path,
                "sha": sha,
                "content": content,
            }
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write cache for %s/%s/%s: %s", org, repo, path, exc)

    # ------------------------------------------------------------------
    # Internal: Helpers
    # ------------------------------------------------------------------

    def _get_default_branch_sha(self, org: str, repo: str, branch: str) -> str:
        """Get the latest commit SHA on a branch.

        Returns:
            The commit SHA string, or empty string on failure.
        """
        try:
            data = self._request("GET", f"/repos/{org}/{repo}/branches/{branch}")
            if isinstance(data, dict):
                return data.get("commit", {}).get("sha", "")
        except GitHubClientError:
            logger.debug("Could not fetch branch SHA for %s/%s@%s", org, repo, branch)
        return ""
