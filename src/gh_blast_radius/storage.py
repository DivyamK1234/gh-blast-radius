"""Local JSON storage for gh-blast-radius.

Persists the dependency graph to a local JSON file and supports incremental
updates by tracking per-repo commit SHAs.
"""

from __future__ import annotations
