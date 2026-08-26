# Connector Platform (`autoforge-connectors`)

Phase 8 shared platform service providing **standardised access to external
systems through a uniform, replaceable boundary** (Architecture v1.0 §18).
It gives later Workflow (Phase 9) and Execution (Phase 10) layers a safe way
for engineering workers to act on real software projects.

## Components

| Connector | Class | Purpose |
|---|---|---|
| Filesystem | `WorkspaceFilesystem` | Sandboxed read/write surface over one workspace root |
| Git | `GitConnector` | Controlled repository inspection & mutation via subprocess |
| GitHub | `GitHubConnector` | REST operations behind a replaceable transport with credential isolation |

Shared infrastructure: error taxonomy (`errors.py`), input validators
(`validation.py`), secret redaction (`security.py`), canonical event factory
(`events.py`), per-operation instrumentation (`instrumentation.py`).

## Boundary note — Knowledge connectors are NOT this

`packages/knowledge_platform` contains knowledge-source *retrieval*
connectors (`connectors/base_connector.py`, …). They produce `KnowledgeItem`s
for research flows and are a **different concern**; do not merge them into or
out of the Connector Platform.

## Quick start

```python
from autoforge_connectors import GitConnector, SecretValue, WorkspaceFilesystem

fs = WorkspaceFilesystem("/path/to/project")
fs.write_text("src/app/main.py", "print('hi')\n")          # parents auto-created
assert fs.read_text("src/app/main.py").startswith("print")

git = GitConnector.discover("/path/to/project/src")        # binds repo root
git.stage(["src/app/main.py"])
print(git.commit("feat: scaffold app"))                    # full SHA
```

GitHub usage requires an injected transport (offline testability) and only
ever receives credentials wrapped in `SecretValue`:

```python
import autoforge_connectors as ac

gh = ac.GitHubConnector(
    transport=ac.UrllibGitHubTransport(),
    token=ac.SecretValue(token_from_platform_config),
)
summary = gh.get_repository("owner", "name")
```

## Security model

- **Filesystem** — paths are workspace-relative POSIX strings; absolute
  inputs, `..` segments and symlinks resolving outside the root are rejected
  before any effect (`ConnectorValidationError`). No shell is ever invoked.
- **Git** — argv-list execution only; refnames/pathspecs validated against
  option-injection patterns; per-command wall-clock budget;
  `GIT_TERMINAL_PROMPT=0`; failures classified deterministically.
- **GitHub** — tokens live in `SecretValue` (redacted `repr`/`str`), become
  headers at exactly one seam, never enter logs/events/errors; transports are
  contractually forbidden from logging headers/bodies.
- Secrets are supplied by the platform configuration through the composition
  root — this package stores nothing.

## Error taxonomy

Every public operation raises subclasses of `ConnectorError` carrying stable
`category` strings and `retryable` flags (see `errors.py`). Deterministic:
validation / not_found / conflict / authentication / authorization /
unsupported / operation_failed. Transient: unavailable / timeout / rate_limit
/ transport.

## Events

Using ONLY frozen canonical vocabulary (`autoforge_events`, ADR-001):
operation failures → `failure.detected` (category FAILURE); capability loss →
`service.degraded`. Successful operations emit no bus events — latency/status
are returned via `OperationObservation` on each connector's
`last_operation`. Rationale: ADR-007.

## Status of roadmap connector categories

Realised now: **Filesystem, Git, GitHub (+ contracts shared by future ones)**.
Intentionally deferred (documented in ADR-007): Browser, Docker,
REST, MCP, Database, Vector Store (vector/embedding stays with the Knowledge
Platform per `docs/AUTONOMOUS_WORKER_ARCHITECTURE_RECONCILIATION.md`).
No placeholder implementations exist.

## Testing

```bash
python -m pytest packages/connectors/tests      # unit + local integration
python -m pytest packages/composition/tests     # wiring & regression
```

Filesystem/Git tests run real workspaces/repositories under temp dirs;
GitHub tests are fully offline via fake transports at the transport seam.
