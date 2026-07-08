"""Diff and impact analysis engine for gh-blast-radius.

Compares two versions of a shared workflow's YAML to determine which consumers
would break, which would see warnings, and which are unaffected.
"""

from __future__ import annotations
