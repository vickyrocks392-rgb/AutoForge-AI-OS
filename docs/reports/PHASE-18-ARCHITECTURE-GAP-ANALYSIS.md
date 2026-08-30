# PHASE 18 — AUTONOMOUS ENGINEERING & MODERNIZATION
## Architecture Gap Analysis

**Date:** 2026-08-30
**Checkpoint:** commit `51d7201` (`chore: freeze phase 17-b ui integration checkpoint`)
**Baseline test suite:** 1,163 passed / 0 failed (16 / 16 packages)

This document is the forensic gap analysis produced at the START of Phase 18.
It classifies the existing repository state into: EXISTING / ALREADY
IMPLEMENTED, PARTIALLY IMPLEMENTED, MISSING, PHASE 18 REQUIRED, and
PHASE 19 / FUTURE (do not implement). No code was modified to produce this
analysis.

---

## 1. EXISTING / ALREADY IMPLEMENTED

| Subsystem | Package | Phase | Notes |
| :-- | :-- | :-- | :-- |
| Event Platform (transport) | `packages/event_platform` | 4 | EventBus, validator, schema registry, replay, subscriptions. Transport vocabulary already contains `workflow.*`, `worker.*`, `model.selected`, `approval.*`, `artifact.*`, `review.*`, `legacy.*`-style types. |
| Canonical event vocabulary | `packages/events` | 4 | `EventCategory` + `EventType` enums; `BaseEvent` immutable envelope. |
| Workflow Engine | `packages/workflows` | 9 | WorkflowEngine, DAG, scheduler, queue, retry, recovery/checkpoint, ApprovalGate (HITL). Task states: PENDING/READY/RUNNING/SUCCEEDED/FAILED/RETRYING/BLOCKED/WAITING_APPROVAL/CANCELLED. |
| Execution Engine | `packages/execution` | 10 | EngineeringWorker lifecycle, WorkerDispatcher, EngineeringLoop (understand→plan→implement→test→evaluate→diagnose→repair), deterministic EvaluationEngine, FailureDiagnoser, ArtifactPipeline, ExecutionGovernance, ExecutionRecovery, ExecutionContext. |
| Review Platform | `packages/review` | 11 | ReviewEngine, quality gates, deterministic checks, specialized reviewers, AI reviewer, ReviewPolicy with HITL escalation, ReviewLoop. |
| Artifact Platform | `packages/artifacts` | 12 | ArtifactManager, LocalArtifactStore, versioning, lineage, provenance, publication (HITL for DEPLOYMENT types), rollback, policies, events. |
| Workforce | `packages/workforce` | 13 | 23 workers (14 greenfield + 9 legacy), `WORKER_REGISTRY` (capability matching), ExpertiseModel + WorkerModelProfile + permissions, legacy analyzers (COBOL/Java/SQL), legacy models (LegacySystemModel, BusinessRule, LegacyEvidence/FactState), ModelCapacityManager, CapacityAwareRouter. |
| Security Platform | `packages/security` | 15 | engine, governance, HITL, sandbox, worker_guard, audit, authorization, identity, credentials. |
| Runtime State Manager | `packages/runtime` | 3 | RuntimeStateManager, checkpoint manager, snapshots, transitions. |
| Kernel | `packages/kernel` | 2 | Kernel orchestrator, intent analysis, planning coordination, lifecycle, approval. |
| AI Infrastructure | `packages/ai_infrastructure` | 7/17 | CapabilityRegistry, ModelRouterService (RoutingRequest/Decision), provider adapters (ollama/openai-compatible/anthropic/gemini), ExecutionContinuityService, RoutedModelExecutor, model/node metadata. |
| Observability | `packages/observability` | 12/17-A | 13 read-model dashboards, dual-level (node-local + fleet), EventTelemetryCollector, routing decision trail, real hardware verification scripts. |
| Knowledge Platform | `packages/knowledge_platform` | 5 | KnowledgeEngine, RetrievalPipeline, connectors, trust scoring, citations/provenance. |
| Persistence | `packages/persistence` | 12 | Repositories (project/task/artifact/execution/memory), unit of work. |
| Application Service | `apps/api` | 16 | AutoForgeApiService with intent analysis, HITL approval records, observability dashboards, workforce profiles, workspace modes. **UI is FROZEN (17-B).** |
## 2. PARTIALLY IMPLEMENTED

| Capability | Status | Gap |
| :-- | :-- | :-- |
| Model/node routing | `CapacityAwareRouter.route_task` + `AIInfrastructureAdapter._build_routing_request` route per-inference. | No stage-level routing decision retained as durable provenance; no visible per-stage model/provider/node assignment in a project execution record. |
| Review integration | Review platform complete. | Not wired as an explicit workflow *stage gate* whose verdict transitions orchestration state. |
| HITL | Multiple overlapping gates (workflow ApprovalGate, security hitl, review policies, artifact publication). | No single persisted HITL gate record (actor/timestamp/decision/reason/workflow/stage) at the orchestration level. |
| Legacy modernization | analyzers + models + discovery utilities exist. | No executable stage pipeline with epistemic labels, provenance ledger, HITL gates, and truthful migration/cutover behavior. |
| RAG | knowledge_platform retrieval exists. | Not integrated into workflow stages (research/archaeology/rules/architecture/diagnosis) with retrieval provenance records. |
| Evaluations | `EvaluationEngine` (exit codes/tests/files). | No stage verdict state machine (PASS/FAIL/BLOCKED/UNKNOWN) combining test results, requirements, acceptance criteria, artifact checks, runtime checks, review results. |
| Diagnostics | `FailureDiagnoser` produces DiagnosisReport. | No structured failure-context capture (failure_type/stage/worker/execution/model/node) and no diagnosis→rectification bound counter. |
| Observability metrics | 13 dashboards fed by collector. | No project-execution metrics object (started/completed/duration/attempts/rectifications/tests/artifacts) and no `stage.*`/orchestration telemetry in the collector. |

## 3. MISSING — PHASE 18 REQUIRED

1. **Stage-scoped orchestration layer** building executable GREENFIELD and LEGACY_MODERNIZATION workflows that map pipeline stages to the real 23-worker workforce.
2. **Durable project execution state machine** (project_id/workflow_id/execution_id/stage_id/worker_id/model_id/node_id/timestamps/status/attempt/failure/artifacts/provenance/telemetry refs) surviving process restart.
3. **Capability-driven worker assignment** at orchestration level (assignment provenance; truthful failure when no worker matches).
4. **Structured worker contracts** (input: task/project context/prior artifacts/evidence/constraints/requirements/tools/model requirements; output: result/artifacts/evidence/provenance/confidence/recommendations/failure).
5. **Model/node routing decisions retained per stage** (worker→effective requirements→ModelAllocator/Router→RoutingDecision; model/provider/node recorded as provenance).
6. **Rectification controller** — bounded; retry (transient infra) vs rectification (engineering repair) distinguished; counters: attempt_count, failure_count, error_count, repair_count, successful_repair_count, rectification_loop_count.
7. **Stage evaluation gates** with structured verdicts (PASS/FAIL/BLOCKED/UNKNOWN).
8. **Structured failure capture + diagnosis routing**; root cause `UNKNOWN` permitted when not determinable.
9. **Review as an explicit orchestrator gate** (APPROVED/REJECTED/NEEDS_REVISION/BLOCKED), persisted and observable.
10. **HITL gate records with persistence** (actor/timestamp/decision/reason) at the workflow/stage level; WAITING_FOR_HITL state semantics.
11. **Artifact provenance registration** per stage/worker with canonical types (SOURCE/TEST/PLAN/ARCHITECTURE/DESIGN/BUILD/APPLICATION/INSTALLER/DISTRIBUTION/REPORT).
12. **Deployment stage** — truthful target (`local workspace`) or `UNAVAILABLE`.
13. **RAG integration** into research/archaeology/business-rules/architecture-reconstruction/diagnosis with retrieval provenance.
14. **Orchestration lifecycle events** (`workflow.*`, `stage.*`, `worker.assigned`, `model.routed`, `evaluation.*`, `diagnosis.*`, `repair.*`, `rectification.*`, `deployment.*`, `review.started`, `execution.created`) — extend the canonical + transport event vocabulary.
15. **Project execution metrics** persisted: started_at, completed_at, duration, attempt_count, failure_count, error_count, retry_count, rectification_count, worker_count, inference_count, test_count, passed_tests, failed_tests, artifact_count.
16. **Cancellation / resumability / idempotency** at orchestration level (durable last-stage state; resume without re-running prior stages; idempotent artifact registration).
17. **Security boundary enforcement** at orchestrator level (verification-command guard: argv-only, no shell metacharacters; workspace path confinement; project isolation).
18. **Backend read-models** exposing real Phase 18 state (APIs only; UI frozen).
| Composition Root | `packages/composition` | 1 | build_autoforge_system wiring all platforms + CanonicalEventBus + Runtime. |
## 4. PHASE 18 REQUIRED (specified in ROADMAP §PHASE 18 / this prompt)

Exactly items 1–18 above, delivered incrementally and validated by:

- Greenfield E2E acceptance: deterministic calculator application through the ACTUAL orchestrated workflow (Idea→Research→Planning→Architecture→Design→Implementation→Testing→Evaluation→Review→Artifact→Deployment).
- Failure/repair E2E: intentional defect → TEST FAILURE → DIAGNOSIS → REPAIR → REIMPLEMENT → RETEST → PASS; truthful counters.
- HITL E2E: RUNNING→WAITING_FOR_HITL→approve→RUNNING; and rejection path.
- Legacy E2E: deterministic fixture; FACT/INFERENCE/HYPOTHESIS/UNKNOWN + provenance; discovery→rules→architecture reconstruction→modernization proposal→HITL; no fake migration/cutover success.
- Observability E2E: complete workflow; query the existing read models; truthful project/worker/model/node/stage/failure/rectification/HITL telemetry.

## 5. PHASE 19 / FUTURE — DO NOT IMPLEMENT

- Learning/reflection engines, pattern discovery, failure learning, knowledge promotion, workflow/routing/worker optimization heuristics, benchmarking/experimentation, self-improvement pipelines, autonomous AutoForge self-modification.
- Phase 18 only PRODUCES evaluation/failure/review/telemetry data that Phase 19 may later consume.

## 6. PHASE 21 / FUTURE — DO NOT IMPLEMENT

- Native desktop packaging/distribution (packaging, installers, app distribution).
- Phase 18 runtime artifacts use the existing verified runtime/build mechanisms; unavailable native packaging must be truthfully reported.

## 7. IMPLEMENTATION DECISIONS (derived from the analysis)

1. New package: **`packages/orchestration`** (`autoforge-orchestration`) — the Phase 18 orchestration platform. It composes existing subsystems (WorkforceDispatcher, ModelRouterService, ReviewEngine, ArtifactManager, Security worker_guard, KnowledgeEngine retrieval, EventPlatform) and adds the stage machine + bounded loops. No duplicate state/event/telemetry systems.
2. Greenfield knowledge/implementation stages execute through the REAL registered `WorkforceWorker` machinery via `WorkforceDispatcher` (worker profiles, loop, evaluation, artifacts), using the injectable AI provider (scripted/test provider offline; real provider adapters online).
3. Legacy analysis stages (discovery/archaeology/rules/architecture reconstruction/dependency analysis) are DETERMINISTIC, using the existing analyzers + `LegacySystemModel`, with explicit epistemic labels and evidence provenance — never simulated completion.
4. Model/node routing flows through `CapacityAwareRouter` / `ModelRouterService` (the centralized router) and the resolved decision is retained as per-stage provenance.
5. Events extend the existing canonical + transport vocabularies and flow through `CanonicalEventBus` → `EventPlatform` → `EventTelemetryCollector` (no new event bus).
6. Durable state is JSON snapshot per execution in an explicit state directory (survives restart); resumption reads the last durable stage.
7. No UI changes; `apps/api` only gains a read-only Real Phase 18 state endpoint if required.