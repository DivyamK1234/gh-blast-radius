# Architecture

## System Overview

`gh-blast-radius` is composed of six core components that work together to map, cache, and analyze the dependency graph of GitHub Actions workflows across an entire organization.

```mermaid
graph TD
    subgraph "Data Ingestion"
        A["GitHub API\norg repos + contents"] --> B["Repo Crawler\n(crawler.py)\nLists repos, fetches YAML"]
        B --> C["Raw File Cache\n(github_client.py)\nSHA-based, avoids\nre-fetching unchanged"]
    end

    subgraph "Parsing & Graph Construction"
        B --> D["Workflow Parser\n(parser.py)\nResolves uses: chains,\nextracts inputs/secrets"]
        D --> E["Graph Builder\n(graph.py)\nnetworkx DiGraph:\nproducers ↔ consumers"]
    end

    subgraph "Persistence"
        E <--> F["Local Graph Store\n(storage.py)\nJSON serialization\n.workflow-impact/*.json"]
    end

    subgraph "User-Facing Interfaces"
        E --> G["CLI\n(cli.py)\nscan · consumers · deps\nstats · diff"]
        E --> H["PR Comment Bot\n(action.yml)\nAuto impact report\non pull requests"]
    end

    subgraph "Outputs"
        G --> I["Terminal\nRich tables, JSON,\nor Markdown"]
        H --> J["GitHub Pull Request\n🛑 Breaking change comment\n+ failed CI check"]
    end

    style A fill:#2d333b,stroke:#444,color:#adbac7
    style B fill:#1f6feb,stroke:#1f6feb,color:#fff
    style C fill:#2d333b,stroke:#444,color:#adbac7
    style D fill:#1f6feb,stroke:#1f6feb,color:#fff
    style E fill:#8957e5,stroke:#8957e5,color:#fff
    style F fill:#2d333b,stroke:#444,color:#adbac7
    style G fill:#238636,stroke:#238636,color:#fff
    style H fill:#238636,stroke:#238636,color:#fff
    style I fill:#2d333b,stroke:#444,color:#adbac7
    style J fill:#2d333b,stroke:#444,color:#adbac7
```

## Component Details

| Component | File | Responsibility |
|-----------|------|----------------|
| **GitHub Client** | `github_client.py` | Authenticated HTTP client with rate-limit retry, pagination, and SHA-based file caching |
| **Repo Crawler** | `crawler.py` | Enumerates org repos, discovers `.github/workflows/` files, triggers lazy resolution of external refs |
| **Workflow Parser** | `parser.py` | Parses YAML with custom safe-loaders, extracts `inputs`, `secrets`, `outputs`, and `permissions` |
| **Dependency Graph** | `graph.py` | `networkx.DiGraph` wrapper — stores `WorkflowNode` producers and `ConsumerEdge` connections |
| **Graph Store** | `storage.py` | Serializes/deserializes the graph to `.workflow-impact/<org>_graph.json` |
| **CLI** | `cli.py` | Typer-based CLI exposing `scan`, `consumers`, `deps`, `stats`, and `diff` commands |
| **GitHub Action** | `action.yml` | Composite action wrapper — runs scan + diff inside CI, posts Markdown impact report as a PR comment |

## Data Flow

### Scan Flow
```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant Crawler
    participant GitHubAPI
    participant Parser
    participant Graph
    participant Store

    User->>CLI: gh-blast-radius scan --org myorg
    CLI->>Crawler: crawl("myorg")
    Crawler->>GitHubAPI: GET /orgs/myorg/repos
    GitHubAPI-->>Crawler: [repo1, repo2, ...]
    loop Each repo
        Crawler->>GitHubAPI: GET /repos/myorg/repo/contents/.github/workflows
        GitHubAPI-->>Crawler: [ci.yml, deploy.yml, ...]
        loop Each workflow file
            Crawler->>GitHubAPI: GET file content (cached by SHA)
            GitHubAPI-->>Crawler: YAML content
            Crawler->>Parser: parse(yaml_content)
            Parser-->>Crawler: WorkflowNode + ConsumerEdges
            Crawler->>Graph: add_node() / add_edge()
        end
    end
    CLI->>Store: save(graph, ".workflow-impact/myorg_graph.json")
    CLI-->>User: ✅ Scan complete — 16 producers, 4 consumers, 28 edges
```

### PR Check Flow
```mermaid
sequenceDiagram
    participant Dev as Developer
    participant GH as GitHub
    participant Action as gh-blast-radius Action
    participant CLI
    participant GitHubAPI

    Dev->>GH: Opens PR modifying shared/build.yml
    GH->>Action: Triggers on pull_request
    Action->>CLI: scan --org myorg
    CLI->>GitHubAPI: Build fresh dependency graph
    GitHubAPI-->>CLI: Graph built
    Action->>CLI: diff shared/build.yml --old base_sha --new head_sha --format markdown
    CLI->>GitHubAPI: Fetch old YAML (base) + new YAML (head)
    GitHubAPI-->>CLI: YAML contents
    CLI-->>Action: Markdown impact report
    Action->>GH: gh pr comment — posts impact table
    Action->>CLI: diff --fail-on-breaking
    alt Breaking changes found
        CLI-->>Action: Exit code 1
        Action-->>GH: ❌ CI check fails, PR blocked
    else No breaking changes
        CLI-->>Action: Exit code 0
        Action-->>GH: ✅ CI check passes
    end
```
