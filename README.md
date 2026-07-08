# gh-blast-radius 💥

> **Know what breaks before you push.**

Analyze the blast radius of changes to shared GitHub Actions reusable workflows
and composite actions across your organization.

## The Problem

Platform and DevEx teams build shared GitHub Actions — reusable workflows and
composite actions — that dozens or hundreds of repos depend on. When you change
a shared workflow, there's no way to know what breaks until you break it.

**gh-blast-radius** builds a dependency graph of your org's shared workflows and
lets you query it: *"If I change this workflow, which repos are affected?"*

## Installation

```bash
pip install gh-blast-radius
```

Requires Python 3.11+.

## Quick Start

```bash
# Scan your org and build the dependency graph
gh-blast-radius scan --org my-org --token ghp_xxxxx

# Who uses this shared workflow?
gh-blast-radius consumers my-org/shared/.github/workflows/build.yml

# What does this repo depend on?
gh-blast-radius deps my-org/frontend

# What breaks if I change this workflow?
gh-blast-radius diff --workflow .github/workflows/build.yml --old main --new feature-branch

# Summary statistics
gh-blast-radius stats
```

## Status

🚧 **Under active development** — see the [roadmap](#roadmap) below.

## Roadmap

- [x] Project scaffold + CLI skeleton
- [ ] GitHub API client with caching and rate limiting
- [ ] Workflow parser (single-level → recursive composite actions)
- [ ] Dependency graph builder + local storage
- [ ] `consumers` and `deps` commands
- [ ] `diff` command with impact analysis
- [ ] `stats` command
- [ ] GitHub Action for PR comments
- [ ] Documentation + real-world examples

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
