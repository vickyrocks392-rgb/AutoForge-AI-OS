# AutoForge AI Infrastructure Platform (Phase 7)

Provider-agnostic AI infrastructure for AutoForge AI OS: **Capability
Registry**, **Model Router** and **Execution Continuity Manager**, per
`architecture/ROADMAP.md` Phase 7 and `architecture/ARCHITECTURE.md` §17/§17.1.

## Components

| Component | Module | Responsibility |
|---|---|---|
| Capability Registry | `registry.py` | Authoritative AI infrastructure **metadata** (providers, models, capabilities, deployments). Never routes, never executes. |
| Model Router | `router.py`, `policies.py` | Model/provider **selection only** via injectable routing policies. No retries, no failover. |
| Execution Continuity Manager | `continuity.py` | Retry, failover, context preservation, checkpoint recovery through the Runtime boundary. |
| Execution boundary | `execution.py` | Provider-neutral executor seam where real provider adapters plug in. |
| Kernel adapters | `kernel_adapter.py` | Implements the Kernel's frozen `ModelRouter` / `ExecutionContinuityManager` ABCs for composition-root injection. |

## Boundaries honoured

- **No hardcoded providers** — providers/models/capabilities are registered
  data, never architectural constants.
- **Local-first** — `DeploymentMode.LOCAL` is a first-class routing target;
  offline mode restricts selection to local-capable candidates.
- **One checkpoint system** — durable checkpoints stay in the Runtime State
  Manager; this package depends only on the injected
  `RuntimeCheckpointPort`.
- **No competing Context Engine** — preserved execution context holds only
  the state needed to resume an execution (ADR-003 remains authoritative for
  assembling model context).
- **Canonical events only** — published events use the frozen
  `autoforge_events` vocabulary.

## Status

Implemented as part of Phase 7 (AI Infrastructure Platform).
Real provider integrations are future work behind `ModelExecutor`.
