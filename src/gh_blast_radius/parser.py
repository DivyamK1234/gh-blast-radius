"""Workflow and action YAML parser for gh-blast-radius.

Parses GitHub Actions workflow files and composite action manifests to extract
``uses:`` references, inputs, secrets, permissions, and outputs. Handles
recursive resolution of nested composite actions.
"""

from __future__ import annotations
