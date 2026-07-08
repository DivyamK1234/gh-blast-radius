"""Tests for the YAML workflow/action parser."""

from __future__ import annotations

from gh_blast_radius.models import WorkflowRef
from gh_blast_radius.parser import (
    parse_action_file,
    parse_producer_interface,
    parse_workflow_file,
    parse_workflow_ref,
)


def test_parse_workflow_ref_standard() -> None:
    ref = parse_workflow_ref("actions/checkout@v4", "myorg/repo")
    assert ref is not None
    assert ref.org == "actions"
    assert ref.repo == "checkout"
    assert ref.path == ""
    assert ref.ref == "v4"

    ref = parse_workflow_ref("myorg/myrepo/.github/workflows/ci.yml@main", "other/repo")
    assert ref is not None
    assert ref.org == "myorg"
    assert ref.repo == "myrepo"
    assert ref.path == ".github/workflows/ci.yml"
    assert ref.ref == "main"


def test_parse_workflow_ref_local() -> None:
    ref = parse_workflow_ref("./.github/actions/setup", "myorg/myrepo")
    assert ref is not None
    assert ref.org == "myorg"
    assert ref.repo == "myrepo"
    assert ref.path == ".github/actions/setup"
    assert ref.ref is None

    # Handle multiple leading slashes
    ref = parse_workflow_ref("../../actions/setup@v1", "myorg/myrepo")
    assert ref is not None
    assert ref.org == "myorg"
    assert ref.repo == "myrepo"
    assert ref.path == "actions/setup"
    assert ref.ref == "v1"


def test_parse_workflow_ref_ignores_docker_and_http() -> None:
    assert parse_workflow_ref("docker://alpine:3.18", "org/repo") is None
    assert parse_workflow_ref("https://github.com/org/repo", "org/repo") is None


def test_parse_producer_interface_reusable_workflow() -> None:
    yaml_content = """
name: CI
on:
  workflow_call:
    inputs:
      env:
        required: true
        type: string
        description: "Environment"
    secrets:
      token:
        required: true
        description: "Access token"
    outputs:
      build_id:
        description: "The ID of the build"
permissions:
  contents: read
  id-token: write
"""
    ref = WorkflowRef("org", "repo", ".github/workflows/ci.yml")
    node = parse_producer_interface(yaml_content, "reusable_workflow", ref)

    assert node.ref == ref
    assert node.type == "reusable_workflow"
    assert node.inputs["env"].required is True
    assert node.inputs["env"].description == "Environment"
    assert node.secrets["token"].required is True
    assert node.outputs["build_id"] == "The ID of the build"
    assert node.permissions == {"contents": "read", "id-token": "write"}


def test_parse_producer_interface_composite_action() -> None:
    yaml_content = """
name: Setup
inputs:
  version:
    required: false
    default: "20"
    description: "Node version"
outputs:
  cache-hit:
    description: "Whether cache was hit"
runs:
  using: composite
  steps: []
"""
    ref = WorkflowRef("org", "repo", "actions/setup")
    node = parse_producer_interface(yaml_content, "composite_action", ref)

    assert node.type == "composite_action"
    assert node.inputs["version"].required is False
    assert node.inputs["version"].default == "20"
    assert node.outputs["cache-hit"] == "Whether cache was hit"


def test_parse_workflow_file() -> None:
    yaml_content = """
jobs:
  build:
    permissions:
      contents: read
    uses: org/shared/.github/workflows/build.yml@v1
    with:
      env: staging
    secrets: inherit

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/setup
        with:
          version: "20"
"""
    edges = parse_workflow_file(yaml_content, "myorg/myrepo", ".github/workflows/ci.yml")

    assert len(edges) == 3

    # Reusable workflow edge
    build_edge = next(e for e in edges if e.job_name == "build")
    assert build_edge.step_index is None
    assert build_edge.ref_used == "v1"
    assert build_edge.inputs_passed == {"env": "staging"}
    assert build_edge.secrets_passed == "inherit"
    assert build_edge.permissions == {"contents": "read"}
    # The target ref
    assert build_edge.target.org == "org"
    assert build_edge.target.repo == "shared"
    assert build_edge.target.path == ".github/workflows/build.yml"

    # Action edge (standard)
    action_edge = next(e for e in edges if e.target.repo == "checkout")
    assert action_edge.job_name == "lint"
    assert action_edge.step_index == 0
    assert action_edge.target.org == "actions"

    # Action edge (local)
    local_edge = next(e for e in edges if e.target.path == ".github/actions/setup")
    assert local_edge.job_name == "lint"
    assert local_edge.step_index == 1
    assert local_edge.target.org == "myorg"
    assert local_edge.target.repo == "myrepo"
    assert local_edge.inputs_passed == {"version": "20"}


def test_parse_action_file() -> None:
    yaml_content = """
name: Setup Node
runs:
  using: composite
  steps:
    - uses: actions/setup-node@v4
      with:
        node-version: "20"
    - uses: ./.github/actions/install-deps
"""
    edges = parse_action_file(yaml_content, "myorg/myrepo", ".github/actions/setup-node/action.yml")

    assert len(edges) == 2

    # Standard nested composite action
    setup_node = edges[0]
    assert setup_node.target.org == "actions"
    assert setup_node.target.repo == "setup-node"
    assert setup_node.inputs_passed == {"node-version": "20"}

    # Local nested composite action
    install_deps = edges[1]
    assert install_deps.target.org == "myorg"
    assert install_deps.target.repo == "myrepo"
    assert install_deps.target.path == ".github/actions/install-deps"

