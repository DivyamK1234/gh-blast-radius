"""Data models for gh-blast-radius.

All domain objects are defined here as dataclasses. Frozen dataclasses are used
for value objects that serve as graph node/edge identifiers. Mutable dataclasses
are used for report objects that are assembled incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Core identifiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowRef:
    """Unique identifier for a shared workflow or composite action.

    Attributes:
        org: GitHub organization name.
        repo: Repository name (without org prefix).
        path: Path within the repo, e.g. ".github/workflows/build.yml"
              or ".github/actions/setup".
        ref: Git ref used by the consumer (e.g. "v2", "main", "abc123...").
             ``None`` when used as a normalized/aggregated key (ref-agnostic).
    """

    org: str
    repo: str
    path: str
    ref: str | None = None

    @property
    def full_name(self) -> str:
        """Return ``org/repo/path`` without the ref component."""
        return f"{self.org}/{self.repo}/{self.path}"

    @property
    def full_name_with_ref(self) -> str:
        """Return ``org/repo/path@ref``, or ``full_name`` if ref is None."""
        if self.ref:
            return f"{self.full_name}@{self.ref}"
        return self.full_name

    def normalized(self) -> WorkflowRef:
        """Return a copy with ``ref`` set to ``None`` for aggregation."""
        return WorkflowRef(org=self.org, repo=self.repo, path=self.path, ref=None)


# ---------------------------------------------------------------------------
# Workflow / action interface definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputDef:
    """Definition of a single input declared by a workflow or action.

    Attributes:
        required: Whether the input is required by the producer.
        default: Default value if any, else ``None``.
        description: Human-readable description from the YAML.
    """

    required: bool = False
    default: str | None = None
    description: str = ""


@dataclass(frozen=True)
class SecretDef:
    """Definition of a single secret declared by a reusable workflow.

    Attributes:
        required: Whether the secret is required.
        description: Human-readable description from the YAML.
    """

    required: bool = False
    description: str = ""


@dataclass(frozen=True)
class WorkflowNode:
    """A shared reusable workflow or composite action with its public interface.

    This represents a *producer* — the thing that other repos consume.

    Attributes:
        ref: The :class:`WorkflowRef` identifying this node.
        type: Whether this is a ``reusable_workflow`` or ``composite_action``.
        inputs: Declared inputs (name → :class:`InputDef`).
        secrets: Declared secrets (name → :class:`SecretDef`).
            Only applicable for reusable workflows.
        outputs: Declared outputs (name → description string).
        permissions: Permissions block from the workflow, if any.
    """

    ref: WorkflowRef
    type: Literal["reusable_workflow", "composite_action"]
    inputs: dict[str, InputDef] = field(default_factory=dict)
    secrets: dict[str, SecretDef] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    permissions: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Consumer edges
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsumerEdge:
    """An edge representing a specific repo/job/step consuming a shared workflow or action.

    Attributes:
        consumer_repo: Full repo identifier, e.g. ``"myorg/frontend"``.
        consumer_workflow: Workflow file path, e.g. ``".github/workflows/ci.yml"``.
        job_name: The job key within the consumer's workflow.
        step_index: Step index within the job (``None`` for reusable workflow
            calls which are job-level, not step-level).
        ref_used: The git ref pinned by the consumer (e.g. ``"v2"``, ``"main"``).
        inputs_passed: Input values passed via ``with:`` (name → expression/value).
        secrets_passed: Secrets passed via ``secrets:`` (name → expression/value),
            or the literal string ``"inherit"`` when ``secrets: inherit`` is used.
        permissions: Permissions block at the job level, if any.
    """

    consumer_repo: str
    consumer_workflow: str
    job_name: str
    step_index: int | None = None
    ref_used: str = ""
    inputs_passed: dict[str, str] = field(default_factory=dict)
    secrets_passed: dict[str, str] | str = field(default_factory=dict)
    permissions: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Impact / diff reports
# ---------------------------------------------------------------------------


@dataclass
class ImpactResult:
    """Impact assessment for a single consumer from a diff.

    Attributes:
        consumer: The :class:`ConsumerEdge` being assessed.
        severity: One of ``"breaking"``, ``"warning"``, or ``"unaffected"``.
        reasons: Human-readable explanations for the severity classification.
    """

    consumer: ConsumerEdge
    severity: Literal["breaking", "warning", "unaffected"]
    reasons: list[str] = field(default_factory=list)


@dataclass
class ImpactReport:
    """Full impact report from comparing two versions of a shared workflow.

    Attributes:
        workflow_ref: The shared workflow/action being changed.
        old_ref: Git ref or file path for the old version.
        new_ref: Git ref or file path for the new version.
        results: Per-consumer impact results.
        summary: Aggregate counts by severity.
    """

    workflow_ref: WorkflowRef
    old_ref: str
    new_ref: str
    results: list[ImpactResult] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        """Compute summary counts by severity."""
        counts: dict[str, int] = {"breaking": 0, "warning": 0, "unaffected": 0}
        for result in self.results:
            counts[result.severity] = counts.get(result.severity, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Helper types for the GitHub client / storage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoInfo:
    """Lightweight repository metadata returned by the GitHub client.

    Attributes:
        org: Organization name.
        name: Repository name.
        full_name: ``"org/name"``.
        default_branch: Default branch (e.g. ``"main"``).
        archived: Whether the repo is archived.
        last_commit_sha: SHA of the latest commit on the default branch.
    """

    org: str
    name: str
    full_name: str
    default_branch: str
    archived: bool = False
    last_commit_sha: str = ""


@dataclass(frozen=True)
class FileInfo:
    """Metadata for a file returned by the GitHub Contents API.

    Attributes:
        path: File path within the repo.
        sha: Git blob SHA for content-addressed caching.
        size: File size in bytes.
        download_url: Direct download URL (may be ``None`` for large files).
    """

    path: str
    sha: str
    size: int = 0
    download_url: str | None = None
