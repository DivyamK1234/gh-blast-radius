"""Parser for GitHub Actions workflows and composite actions.

Uses PyYAML with CSafeLoader for fast, safe parsing of YAML files.
Extracts dependencies (uses:), inputs, secrets, and permissions.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import yaml

from gh_blast_radius.models import (
    ConsumerEdge,
    InputDef,
    SecretDef,
    WorkflowNode,
    WorkflowRef,
)

logger = logging.getLogger(__name__)

# Use CSafeLoader if available (written in C, much faster), fallback to SafeLoader
try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader  # type: ignore


class ParserError(Exception):
    """Raised when YAML parsing fails."""


def parse_yaml_safe(content: str) -> dict[str, Any]:
    """Parse a YAML string safely.

    Args:
        content: The YAML string.

    Returns:
        The parsed dictionary, or an empty dict if the file is empty/invalid.

    Raises:
        ParserError: If the YAML is malformed.
    """
    if not content.strip():
        return {}
    try:
        data = yaml.load(content, Loader=SafeLoader)
        if not isinstance(data, dict):
            return {}
        return data
    except yaml.YAMLError as exc:
        raise ParserError(f"Failed to parse YAML: {exc}") from exc


def parse_workflow_ref(uses_string: str, current_org_repo: str) -> WorkflowRef | None:
    """Parse a `uses:` string into a WorkflowRef.

    Args:
        uses_string: The string from `uses:`.
        current_org_repo: The current repo in "org/repo" format (used for local actions).

    Returns:
        A WorkflowRef, or None if the string is not a valid GitHub reference
        (e.g., docker:// image).
    """
    uses_string = uses_string.strip()

    if uses_string.startswith("docker://") or uses_string.startswith("http"):
        return None

    ref = None
    if "@" in uses_string:
        repo_path, ref = uses_string.split("@", 1)
    else:
        repo_path = uses_string

    if repo_path.startswith("./") or repo_path.startswith("../"):
        # Local action relative to repository root
        org, repo = current_org_repo.split("/", 1)
        # Normalize by removing leading slashes and dots safely
        import re
        path = re.sub(r"^(\.\.?/)+", "", repo_path)
        return WorkflowRef(org=org, repo=repo, path=path, ref=ref)

    parts = repo_path.split("/")
    if len(parts) < 2:
        return None

    org = parts[0]
    repo = parts[1]
    path = "/".join(parts[2:])

    return WorkflowRef(org=org, repo=repo, path=path, ref=ref)


def parse_producer_interface(
    content: str,
    node_type: Literal["reusable_workflow", "composite_action"],
    ref: WorkflowRef,
) -> WorkflowNode:
    """Parse a workflow or action file to extract its public interface.

    Args:
        content: YAML string of the file.
        node_type: Whether it's a workflow or composite action.
        ref: The WorkflowRef for this node.

    Returns:
        A WorkflowNode representing the producer interface.
    """
    try:
        data = parse_yaml_safe(content)
    except ParserError as exc:
        logger.warning("Failed to parse producer interface for %s: %s", ref.full_name, exc)
        return WorkflowNode(ref=ref, type=node_type)

    inputs: dict[str, InputDef] = {}
    secrets: dict[str, SecretDef] = {}
    outputs: dict[str, str] = {}
    permissions: dict[str, str] | None = None

    if node_type == "reusable_workflow":
        on_block = data.get("on")
        if on_block is None:
            on_block = data.get(True, {})
        if isinstance(on_block, dict):
            workflow_call = on_block.get("workflow_call", {})
            if isinstance(workflow_call, dict):
                # Parse inputs
                for k, v in workflow_call.get("inputs", {}).items():
                    if isinstance(v, dict):
                        inputs[str(k)] = InputDef(
                            required=bool(v.get("required", False)),
                            default=str(v["default"]) if "default" in v else None,
                            description=str(v.get("description", "")),
                        )
                # Parse secrets
                for k, v in workflow_call.get("secrets", {}).items():
                    if isinstance(v, dict):
                        secrets[str(k)] = SecretDef(
                            required=bool(v.get("required", False)),
                            description=str(v.get("description", "")),
                        )
                # Parse outputs
                for k, v in workflow_call.get("outputs", {}).items():
                    if isinstance(v, dict):
                        outputs[str(k)] = str(v.get("description", ""))

        perms = data.get("permissions")
        if isinstance(perms, dict):
            permissions = {str(k): str(v) for k, v in perms.items()}

    elif node_type == "composite_action":
        # Parse inputs
        for k, v in data.get("inputs", {}).items():
            if isinstance(v, dict):
                inputs[str(k)] = InputDef(
                    required=bool(v.get("required", False)),
                    default=str(v["default"]) if "default" in v else None,
                    description=str(v.get("description", "")),
                )
        # Parse outputs
        for k, v in data.get("outputs", {}).items():
            if isinstance(v, dict):
                outputs[str(k)] = str(v.get("description", ""))

    return WorkflowNode(
        ref=ref,
        type=node_type,
        inputs=inputs,
        secrets=secrets,
        outputs=outputs,
        permissions=permissions,
    )


def _extract_with_and_secrets(
    block: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str] | str]:
    """Helper to extract `with:` and `secrets:` from a job or step block."""
    inputs_passed: dict[str, str] = {}
    secrets_passed: dict[str, str] | str = {}

    with_block = block.get("with")
    if isinstance(with_block, dict):
        inputs_passed = {str(k): str(v) for k, v in with_block.items()}

    secrets_block = block.get("secrets")
    if isinstance(secrets_block, dict):
        secrets_passed = {str(k): str(v) for k, v in secrets_block.items()}
    elif secrets_block == "inherit":
        secrets_passed = "inherit"

    return inputs_passed, secrets_passed


def parse_workflow_file(
    content: str, current_org_repo: str, filepath: str
) -> list[ConsumerEdge]:
    """Extract ConsumerEdges from a normal GitHub workflow file.

    Finds reusable workflow calls at the job level and composite action
    calls at the step level.

    Args:
        content: YAML string of the workflow.
        current_org_repo: "org/repo" of the repo containing this file.
        filepath: Path to the workflow file within the repo.

    Returns:
        A list of ConsumerEdge objects for every dependency found.
    """
    edges: list[ConsumerEdge] = []
    try:
        data = parse_yaml_safe(content)
    except ParserError as exc:
        logger.warning("Failed to parse workflow file %s: %s", filepath, exc)
        return edges

    jobs = data.get("jobs", {})
    if not isinstance(jobs, dict):
        return edges

    for job_name, job_block in jobs.items():
        if not isinstance(job_block, dict):
            continue

        job_permissions = None
        perms = job_block.get("permissions")
        if isinstance(perms, dict):
            job_permissions = {str(k): str(v) for k, v in perms.items()}

        # 1. Job-level uses: (Reusable workflows)
        uses_string = job_block.get("uses")
        if isinstance(uses_string, str):
            ref = parse_workflow_ref(uses_string, current_org_repo)
            if ref:
                inputs_passed, secrets_passed = _extract_with_and_secrets(job_block)
                edges.append(
                    ConsumerEdge(
                        target=ref,
                        consumer_repo=current_org_repo,
                        consumer_workflow=filepath,
                        job_name=str(job_name),
                        step_index=None,
                        ref_used=ref.ref or "",
                        inputs_passed=inputs_passed,
                        secrets_passed=secrets_passed,
                        permissions=job_permissions,
                    )
                )

        # 2. Step-level uses: (Actions)
        steps = job_block.get("steps", [])
        if isinstance(steps, list):
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                step_uses = step.get("uses")
                if isinstance(step_uses, str):
                    ref = parse_workflow_ref(step_uses, current_org_repo)
                    if ref:
                        inputs_passed, _ = _extract_with_and_secrets(step)
                        edges.append(
                            ConsumerEdge(
                                target=ref,
                                consumer_repo=current_org_repo,
                                consumer_workflow=filepath,
                                job_name=str(job_name),
                                step_index=i,
                                ref_used=ref.ref or "",
                                inputs_passed=inputs_passed,
                                secrets_passed={},  # Steps don't have secrets:
                                permissions=job_permissions,
                            )
                        )

    return edges


def parse_action_file(
    content: str, current_org_repo: str, filepath: str
) -> list[ConsumerEdge]:
    """Extract ConsumerEdges from a composite action (action.yml) file.

    Finds nested composite action calls in runs.steps.

    Args:
        content: YAML string of the action manifest.
        current_org_repo: "org/repo" of the repo containing this file.
        filepath: Path to the action file within the repo.

    Returns:
        A list of ConsumerEdge objects for every dependency found.
    """
    edges: list[ConsumerEdge] = []
    try:
        data = parse_yaml_safe(content)
    except ParserError as exc:
        logger.warning("Failed to parse action file %s: %s", filepath, exc)
        return edges

    runs = data.get("runs", {})
    if not isinstance(runs, dict) or runs.get("using") != "composite":
        return edges

    steps = runs.get("steps", [])
    if not isinstance(steps, list):
        return edges

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_uses = step.get("uses")
        if isinstance(step_uses, str):
            ref = parse_workflow_ref(step_uses, current_org_repo)
            if ref:
                inputs_passed, _ = _extract_with_and_secrets(step)
                edges.append(
                    ConsumerEdge(
                        target=ref,
                        consumer_repo=current_org_repo,
                        consumer_workflow=filepath,
                        job_name="composite-run",
                        step_index=i,
                        ref_used=ref.ref or "",
                        inputs_passed=inputs_passed,
                        secrets_passed={},
                        permissions=None,
                    )
                )

    return edges
