# gh-blast-radius

[![PyPI version](https://img.shields.io/pypi/v/gh-blast-radius.svg)](https://pypi.org/project/gh-blast-radius/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**`gh-blast-radius`** is an open-source CLI tool and GitHub Action that maps the dependency graph of GitHub Actions reusable workflows and composite actions across your entire GitHub organization. 

It answers the question: *"If I change this shared workflow, what breaks?"*

---

## 🛑 The Problem

Platform and DevEx teams build shared GitHub Actions reusable workflows (e.g., `uses: myorg/shared/.github/workflows/build.yml@v2`) and composite actions that dozens or hundreds of other repositories depend on. 

Until now, there was no tooling to map which repos consume these shared resources, what inputs/secrets they rely on, and what would break if the shared workflow changes. Teams often merge an innocent PR to a shared template, only to find out they've broken dozens of downstream applications at once.

`gh-blast-radius` solves this by building a deterministic dependency graph across your organization and letting you query it. Most importantly, it runs as a Pull Request check to physically block breaking changes before they merge.

---

## 🧠 How It Works Under The Hood

This tool is not just a text-searcher; it is a full deterministic graph engine.

1. **Lazy Graph Resolution (`networkx`)**: The `scan` command acts as a spider. It crawls your organization using the GitHub API, parses the YAML of workflows looking for `uses:` keywords, and builds a Directed Graph using the `networkx` library. 
2. **Deterministic YAML Parsing**: It uses `PyYAML` with custom safe-loaders to handle GitHub Actions edge cases (like parsing `on: true` without crashing). It maps exactly what inputs and secrets a consumer is passing to a producer.
3. **Local Caching**: To avoid hammering the GitHub API, it caches file contents locally by their Git SHA. The resulting network is serialized into a single `.workflow-impact/org_graph.json` file.
4. **Diff Engine**: When you run a `diff`, the tool fetches the old and new version of the YAML, computes the schema delta (e.g., "a new required input was added"), checks the graph to see exactly what every consumer is passing, and flags consumers that fail to meet the new schema.

---

## 🚀 Installation

You can install the CLI directly from PyPI. We recommend using `pipx` or `uv` to install it in an isolated environment:

```bash
# Using pipx
pipx install gh-blast-radius

# Using uv
uv tool install gh-blast-radius
```

---

## 🔑 Setup & Authentication

Because `gh-blast-radius` needs to read workflow files from every repository in your organization, it requires a GitHub Personal Access Token (PAT) with `repo` (code read) scope.

Export it in your environment:
```bash
export GITHUB_TOKEN="ghp_your_token_here"
```
*(If you have the GitHub CLI installed, you can dynamically pass your token like this: `GITHUB_TOKEN=$(gh auth token) gh-blast-radius scan ...`)*

---

## 💻 CLI Command Reference

### 1. `scan` (Build the Map)
Before you can query the graph, you must scan your organization. This builds the JSON graph locally.

```bash
gh-blast-radius scan --org my-awesome-org
```
*Output:*
```text
╭─────────────────────────────── Scan Complete ────────────────────────────────╮
│ Successfully scanned my-awesome-org.                                         │
│ Producers found: 42                                                          │
│ Consumer repos: 150                                                          │
│ Total dependency edges: 320                                                  │
│                                                                              │
│ Graph saved to .workflow-impact/my-awesome-org_graph.json                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### 2. `consumers` (Find Who Uses A Template)
To see every repository and job that relies on a specific shared workflow:

```bash
gh-blast-radius consumers my-awesome-org/shared-workflows/.github/workflows/build.yml
```
*Output:*
```text
     Consumers of my-awesome-org/shared-workflows/.github/workflows/build.yml     
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Consumer Repo             ┃ Workflow     ┃ Job (Step) ┃ Ref  ┃ Inputs Passed ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━┩
│ myorg/app-frontend        │ .github/wor… │ build      │ v1   │ language=node │
│ myorg/app-backend         │ .github/wor… │ build      │ main │ language=pyt… │
└───────────────────────────┴──────────────┴────────────┴──────┴───────────────┘
```

### 3. `deps` (Check App Dependencies)
To see what shared workflows a specific application repository relies on:

```bash
gh-blast-radius deps my-awesome-org/app-frontend
```

### 4. `stats` (Graph Statistics)
View aggregate statistics and find out which workflow has the "widest blast radius" (highest risk):

```bash
gh-blast-radius stats --org my-awesome-org
```

### 5. `diff` (Impact Analysis)
Compare two versions of a shared workflow and see exactly which consumers will break. 

```bash
gh-blast-radius diff \
    my-awesome-org/shared-workflows/.github/workflows/build.yml \
    --old main \
    --new feature-add-required-input \
    --fail-on-breaking
```

---

## 🤖 GitHub Actions CI/CD Integration

The most powerful way to use `gh-blast-radius` is to run it automatically on Pull Requests to prevent developers from accidentally merging breaking changes.

We provide a drop-in **Composite Action**. When a developer opens a PR that modifies a shared template:
1. The Action runs the `scan` command to build a fresh, real-time map of your organization.
2. It runs the `diff` command comparing the `main` branch to their `PR` branch.
3. If it detects breaking changes, it **posts a Markdown comment directly on the Pull Request** showing exactly who they broke, and fails the CI check.

### Setup Instructions
Inside the repository where you store your shared workflows (e.g., `my-org/shared-workflows`):

1. Go to **Settings > Secrets and variables > Actions**.
2. Add a repository secret named `ORG_READ_TOKEN` containing a PAT with `repo` access to your entire organization.
3. Create a file at `.github/workflows/blast-radius.yml` and paste the following:

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
    permissions:
      contents: read
      pull-requests: write   # Required to post the PR comment!
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
      
      - name: Check Impact
        uses: DivyamK1234/gh-blast-radius@main
        with:
          github_token: ${{ secrets.ORG_READ_TOKEN }}
          org: ${{ github.repository_owner }}
          
          # Automatically grabs the exact file being modified in the PR
          workflow_ref: ${{ github.repository_owner }}/${{ github.event.repository.name }}/${{ github.event.pull_request.head.repo.path }}
          old_ref: ${{ github.event.pull_request.base.sha }}
          new_ref: ${{ github.event.pull_request.head.sha }}
```

## 🛠️ Local Development

If you want to contribute to the code:
1. Clone the repository.
2. Install dependencies via `uv`: `uv pip install -e ".[dev]"`
3. Run tests: `uv run pytest`
4. Linting: `uv run ruff check src/ tests/`

## License
MIT
