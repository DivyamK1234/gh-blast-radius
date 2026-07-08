# gh-blast-radius

[![PyPI version](https://badge.fury.io/py/gh-blast-radius.svg)](https://badge.fury.io/py/gh-blast-radius)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**`gh-blast-radius`** is an open-source CLI tool and GitHub Action that maps the dependency graph of GitHub Actions reusable workflows and composite actions across your entire GitHub organization. 

It answers the question: *"If I change this shared workflow, what breaks?"*

---

## The Problem

Platform and DevEx teams build shared GitHub Actions reusable workflows (e.g. `uses: myorg/shared/.github/workflows/build.yml@v2`) and composite actions that many other repositories depend on. 

Until now, there was no tooling to map which repos consume these shared resources, what inputs/secrets they rely on, and what would break if the shared workflow changes. Teams often find out they've broken dozens of repos at once.

`gh-blast-radius` solves this by building a deterministic dependency graph across your organization and letting you query it, especially as a PR check to prevent breaking changes.

## Installation

You can install the CLI using pip or pipx:

```bash
pipx install gh-blast-radius
```

## Setup & Authentication

The CLI requires a GitHub Personal Access Token (PAT) with `repo` scope to read workflow files across your organization.

Export it in your environment:
```bash
export GITHUB_TOKEN="ghp_your_token_here"
```

## CLI Usage

### 1. Scan your Organization
Before you can query the graph, you must scan your organization. This crawls all repositories, finds all workflow dependencies, and caches the resulting graph locally in `.workflow-impact/`.

```bash
gh-blast-radius scan --org my-awesome-org
```
*Output:*
```
╭─────────────────────────────── Scan Complete ────────────────────────────────╮
│ Successfully scanned my-awesome-org.                                         │
│ Producers found: 42                                                          │
│ Consumer repos: 150                                                          │
│ Total dependency edges: 320                                                  │
│                                                                              │
│ Graph saved to .workflow-impact/my-awesome-org_graph.json                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### 2. Find Consumers
To see every repository and job that relies on a specific shared workflow:

```bash
gh-blast-radius consumers my-awesome-org/shared-workflows/.github/workflows/build.yml
```
*Output:*
```
     Consumers of my-awesome-org/shared-workflows/.github/workflows/build.yml     
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Consumer Repo             ┃ Workflow     ┃ Job (Step) ┃ Ref  ┃ Inputs Passed ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━┩
│ myorg/app-frontend        │ .github/wor… │ build      │ v1   │ language=node │
│ myorg/app-backend         │ .github/wor… │ build      │ main │ language=pyt… │
└───────────────────────────┴──────────────┴────────────┴──────┴───────────────┘
```

### 3. Check Dependencies
To see what shared workflows a specific repository relies on:

```bash
gh-blast-radius deps my-awesome-org/app-frontend
```

### 4. Graph Statistics
View aggregate statistics and find out which workflow has the "widest blast radius":

```bash
gh-blast-radius stats --org my-awesome-org
```

### 5. Diff & Impact Analysis (The Core Feature)
Before merging a PR to a shared workflow, you can compare the old version to the new version and see exactly which consumers will break.

```bash
gh-blast-radius diff \
    my-awesome-org/shared-workflows/.github/workflows/build.yml \
    --old main \
    --new feature-add-required-input
```
*Output:*
```
Impact Report: myorg/shared-workflows/.github/workflows/build.yml (main → feature-branch)
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   Severity   ┃ Consumer Repo     ┃ Workflow           ┃ Job (Step) ┃ Reasons                        ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│   BREAKING   │ myorg/app-backend │ .github/workflows… │ build      │ New required input 'env' is    │
│              │                   │                    │            │ not passed by consumer.        │
│   WARNING    │ myorg/app-frontend│ .github/workflows… │ build      │ New optional input 'timeout'   │
│              │                   │                    │            │ added.                         │
│  UNAFFECTED  │ myorg/other-repo  │ .github/workflows… │ build      │ -                              │
└──────────────┴───────────────────┴────────────────────┴────────────┴────────────────────────────────┘

Summary: Breaking: 1 | Warning: 1 | Unaffected: 1
```

## GitHub Actions Drop-in

You can block PRs from merging if they introduce breaking changes to shared workflows! Drop this directly into your shared workflow repository:

```yaml
name: Prevent Breaking Changes
on:
  pull_request:
    paths:
      - '.github/workflows/**'
      - '.github/actions/**'

jobs:
  check-blast-radius:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
      
      - name: Check Impact
        uses: DivyamK1234/gh-blast-radius@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          org: ${{ github.repository_owner }}
          # The workflow file being modified
          workflow_ref: ${{ github.repository_owner }}/${{ github.event.repository.name }}/.github/workflows/build.yml
          old_ref: ${{ github.event.pull_request.base.sha }}
          new_ref: ${{ github.event.pull_request.head.sha }}
```

The action will exit with code `1` and fail the PR check if any consumers are categorized as `BREAKING`.

## Local Development

1. Clone the repository.
2. Install dependencies: `uv pip install -e ".[dev]"`
3. Run tests: `pytest`
4. Linting: `ruff check src/ tests/`

## License
MIT
