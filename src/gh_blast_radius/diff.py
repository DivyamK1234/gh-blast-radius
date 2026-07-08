"""Diff and impact analysis engine."""

from __future__ import annotations

from typing import Literal

from gh_blast_radius.models import (
    ConsumerEdge,
    ImpactReport,
    ImpactResult,
    WorkflowNode,
    WorkflowRef,
)


def compute_impact(
    workflow_ref: WorkflowRef,
    old_node: WorkflowNode,
    new_node: WorkflowNode,
    consumers: list[ConsumerEdge],
    old_ref_name: str,
    new_ref_name: str,
) -> ImpactReport:
    """Compare two versions of a WorkflowNode and compute the impact on its consumers.

    Args:
        workflow_ref: The shared workflow/action being changed.
        old_node: The interface of the old version.
        new_node: The interface of the new version.
        consumers: List of consumer edges depending on the workflow.
        old_ref_name: Name of the old git ref or path.
        new_ref_name: Name of the new git ref or path.

    Returns:
        An ImpactReport detailing the effect on each consumer.
    """
    results: list[ImpactResult] = []

    # Pre-calculate interface changes
    removed_inputs = set(old_node.inputs.keys()) - set(new_node.inputs.keys())
    removed_secrets = set(old_node.secrets.keys()) - set(new_node.secrets.keys())

    new_required_inputs = {
        name
        for name, input_def in new_node.inputs.items()
        if input_def.required and input_def.default is None and name not in old_node.inputs
    }
    new_required_secrets = {
        name
        for name, secret_def in new_node.secrets.items()
        if secret_def.required and name not in old_node.secrets
    }

    new_optional_inputs = {
        name
        for name, input_def in new_node.inputs.items()
        if (not input_def.required or input_def.default is not None) and name not in old_node.inputs
    }
    new_optional_secrets = {
        name
        for name, secret_def in new_node.secrets.items()
        if not secret_def.required and name not in old_node.secrets
    }

    # Evaluate each consumer
    for consumer in consumers:
        severity: Literal["breaking", "warning", "unaffected"] = "unaffected"
        reasons: list[str] = []

        # Check inputs
        for input_name in consumer.inputs_passed:
            if input_name in removed_inputs:
                severity = "breaking"
                reasons.append(f"Input '{input_name}' was removed, but consumer passes it.")

        for input_name in new_required_inputs:
            if input_name not in consumer.inputs_passed:
                severity = "breaking"
                reasons.append(f"New required input '{input_name}' is not passed by consumer.")

        for input_name in new_optional_inputs:
            if input_name not in consumer.inputs_passed:
                if severity == "unaffected":
                    severity = "warning"
                reasons.append(
                    f"New optional input '{input_name}' added (consumer does not pass it)."
                )

        # Check secrets
        if isinstance(consumer.secrets_passed, dict):
            for secret_name in consumer.secrets_passed:
                if secret_name in removed_secrets:
                    severity = "breaking"
                    reasons.append(f"Secret '{secret_name}' was removed, but consumer passes it.")

            for secret_name in new_required_secrets:
                if secret_name not in consumer.secrets_passed:
                    severity = "breaking"
                    reasons.append(
                        f"New required secret '{secret_name}' is not passed by consumer."
                    )

            for secret_name in new_optional_secrets:
                if secret_name not in consumer.secrets_passed:
                    if severity == "unaffected":
                        severity = "warning"
                    reasons.append(
                        f"New optional secret '{secret_name}' added (consumer does not pass it)."
                    )
        elif consumer.secrets_passed == "inherit":
            # If they inherit, they pass everything, so new secrets are satisfied automatically.
            # However, if a secret was removed, technically it's fine since they inherit,
            # it just won't be used.
            # But maybe we should warn? For now, we assume 'inherit' covers all bases safely.
            pass

        results.append(
            ImpactResult(
                consumer=consumer,
                severity=severity,
                reasons=reasons,
            )
        )

    return ImpactReport(
        workflow_ref=workflow_ref,
        old_ref=old_ref_name,
        new_ref=new_ref_name,
        results=results,
    )
