"""Dependency graph builder and query engine for gh-blast-radius.

Builds a directed graph using networkx where nodes are shared workflows/actions
and consumer repos/jobs, and edges represent "consumes" relationships. Provides
query functions for consumers, dependencies, and statistics.
"""

from __future__ import annotations
