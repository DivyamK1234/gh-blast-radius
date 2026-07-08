"""GitHub API client for gh-blast-radius.

Provides authenticated access to the GitHub REST API via httpx, with
automatic pagination, rate-limit handling, retry logic, and local caching.
"""

from __future__ import annotations
