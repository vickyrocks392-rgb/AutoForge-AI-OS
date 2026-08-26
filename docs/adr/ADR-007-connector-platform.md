# ADR-007: Connector Platform Realisation (Filesystem, Git, GitHub)

**Date:** 2026-08-27

**Status:** Accepted

---

## Context

`architecture/ROADMAP.md` Phase 8 requires a Connector Layer and Connector
Contracts delivering external integrations (Filesystem, Git, GitHub, Browser,
Docker, REST, MCP, Database, Vector Store). At phase start:

- Architecture v1.0 §18 already reserved the **Connector Layer** as a shared
  platform service orchestrated by the Kernel; no implementation existed.
- `packages/tools` was an empty stub; no worker-facing file/git capability
  existed anywhere (`docs/AUTONOMOUS_WORKER_ARCHITECTURE_RECONCILIATION.md`
  marks ACT/OBSERVE as MISSING).
- Phase 7 established certified conventions: consumer-owned structural
  ports, composition-root construction, per-package error taxonomies,
  canonical-event-only publishing (ADR-001), local-first/offline behaviour.
- The canonical event vocabulary has NO connector types; the Event Platform
  transport requires dot-prefixed type/category coherence for round-trip.
- Vector/embedding infrastructure is already placed with the Knowledge
  Platform by the Autonomous Worker reconciliation.

Forces: enable real autonomous engineering soon without vendor coupling,
without weakening the frozen event vocabulary or Phase 7 boundaries, and
without building fake placeholders merely to tick roadmap boxes
(YC-quality: working, fast, presentable, provable).

---

## Decision

1. **New package boundary.** `packages/connectors`
   (`autoforge-connectors`) implements the Connector Layer as an ordinary
   platform package with the repository's standard layout
   (README/pyproject/src/tests) and **zero third-party runtime dependencies**
   (pathlib/shutil/subprocess/urllib only). The Kernel, Runtime and AI
   Infrastructure do NOT depend on it; future engines receive it by
   injection at the composition root.

2. **Contract strategy — narrow ports, not one mega-interface.**
   Connectors expose concrete classes plus small structural seams:
   `ConnectorEventSink` (events out) and `GitHubTransport` (network out).
   A universal "everything-connector" interface is explicitly rejected;
   each external system keeps its own operation surface, so replaceability
   lives where risk actually exists (transport/credentials/events).

3. **Realised connectors (this phase).** See the realised-scope table in
   `docs/subsystems/CONNECTOR_PLATFORM_SPECIFICATION.md`. In summary:
   - **Filesystem** — `WorkspaceFilesystem`: single resolved workspace root;
     relative POSIX paths only; rejection of absolute inputs, `..` traversal
     and symlink escapes (incl. not-yet-existing targets verified via the
     deepest existing ancestor); deterministic ops (read/write/append/
     mkdir/move/delete/metadata/list); overwrites need explicit consent.
   - **Git** — `GitConnector`: argv-list subprocess execution inside the
     bound work tree; refname/pathspec validation; per-command timeout;
     inspection (status/diff/log/head/branch) and mutation (stage/commit/
     branches/checkout/guarded reset); stderr mapped onto the taxonomy.
   - **GitHub** — `GitHubConnector` + `GitHubTransport` port + stdlib
     `UrllibGitHubTransport`: metadata, contents read/write, refs &
     branch creation, pull requests, issues; status→taxonomy mapping incl.
     rate-limit detection; credentials isolated via `SecretValue`.

4. **Error taxonomy (package-owned).** `ConnectorError` base with structured
   `details`, stable dotted `category`, `retryable` flag. Deterministic:
   validation/not_found/conflict/authentication/authorization/unsupported/
   operation_failed. Transient: unavailable/timeout/rate_limit/transport.
   Third-party exceptions never escape; there is deliberately NO global
   cross-platform error hierarchy.

5. **Canonical event mapping (no new vocabulary).**
   - connector operation failed → `EventType.FAILURE_DETECTED`
     (category FAILURE) with `metadata.component="connectors"`,
     connector/operation/error_category/duration.
   - capability loss → `EventType.SERVICE_DEGRADED`.
   - successful operations emit NO bus events; per-operation latency/status
     flow through returned `OperationObservation` objects (`last_operation`),
     avoiding event noise and generic flat verbs whose wire round-trip is
     unmappable. If future evidence proves this insufficient, the required
     canonical extension follows ADR-001's additive process (explicit stop &
     report).

6. **Composition integration (ADR-002 pattern preserved).**
   `autoforge_composition.build_connector_platform()` returns
   `ConnectorPlatformServices(events, filesystem, git|None, github)`; git is
   optional when the workspace is not a repository; token/transport are
   injected from platform configuration; network I/O cannot occur implicitly.

7. **Scope of deferred categories (documented, not faked).** Browser, Docker,
   REST, MCP, Database: deferred until their consuming phases exist (Docker ≈
   execution infra for Phase 10, orchestration stays in Phase 10; REST = thin
   genericisation after more consumers than GitHub appear; MCP full protocol
   gated on the first MCP-compatible tool need). Vector Store: remains a
   Knowledge Platform responsibility unless a future ADR moves it.

---

## Consequences

- Later phases obtain real project-manipulation capability through DI only;
  no engine imports concrete connectors (dependency inversion held).
- Certified foundations remain untouched: no changes to Kernel/Runtime/
  Events/AI Infrastructure contracts; event vocabulary unchanged.
- Security posture improved materially: sandboxed filesystem boundary,
  classified git execution, isolated credentials; formal secrets system and
  permission model remain future governance scope (Architecture §22).
- Performance-relevant properties shipped and testable (budgets, timeouts,
  latency observation); measured numbers stay out of documentation until a
  dedicated observability phase exists.
- Known limitations recorded: GitHub pagination absent (first page only);
  git remote push/pull excluded until authentication flows are governed;
  filesystem symlink containment follows POSIX resolution semantics.
