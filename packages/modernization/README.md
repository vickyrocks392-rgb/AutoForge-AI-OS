# autoforge-modernization

Legacy Modernization Engine for AutoForge AI OS — **Phase 18-G**.

## Status

**G.1 — Foundation** (this release). Establishes the contracts, data models,
capability registry, business-aware planning gate, data-plane separation, and
observability scaffolding that later 18-G stages (G.2–G.5) will consume.

## What This Package Is

- Foundation + contracts + data models.
- Technology capability registry (machine-readable).
- Specialist tooling contract.
- Business-aware planning gate (current vs intent vs target).
- Lockdown mode + client/research data-plane separation.
- Project sizing, throughput, estimation models.
- Market benchmark model.
- Context optimization contracts.
- Modernization observability contracts.
- RAG/Knowledge integration boundary (delegates to 18-D).
- Provenance references (delegates to 18-F).

## What This Package Is NOT

- ❌ Complete legacy modernization.
- ❌ Transformation execution engine (G.3).
- ❌ Specialist toolchain implementation (G.2).
- ❌ Market research engine (G.4/G.5).
- ❌ Autonomous learning.
- ❌ A duplicated RAG, AI router, execution engine, governance engine, or
  observability system.

## Reuse

This package reuses (does not duplicate) the following certified subsystems:

- `autoforge_models` — canonical domain models.
- `autoforge_events` — canonical event bus.
- `autoforge_runtime` — checkpoint/persistence primitives.
- `autoforge_artifacts` — artifact/lineage/provenance.
- `autoforge_workforce` — `LegacySystemModel`, `LegacyEvidence`,
  `FactState`, `BusinessRule` (18-C workforce).
- `autoforge_observability` — dashboard, metrics, log/trace primitives.
- 18-D RAG — `KnowledgeRAGEngine` facade (consumed by interface, not reimplemented).
- 18-F governance — `GovernanceReportService` (provenance references).
