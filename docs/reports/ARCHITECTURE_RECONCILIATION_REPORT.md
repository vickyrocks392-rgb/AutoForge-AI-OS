# AUTOFORGE AI OS — TECHNOLOGY & ARCHITECTURE RECONCILIATION REPORT

**Mission type:** Architecture Reconciliation / Technology Evaluation (decision & documentation only)
**Scope:** No implementation · no migration · no frozen-phase changes · no dependency additions
**Inspected baselines:** Phase 7 `b928590` · Phase 8 `f40b380` · Phase 9 `3b63d51` · Phase 10 `1c9b96b`
**Validation confirmed live:** 431 passed (workflows 194 + ai_infrastructure 83 + execution 37 + composition 24 + connectors 93) · 0 failures
**Date:** 2026-08-27

> This report is an architectural decision document. It does not modify any frozen
> implementation, does not add dependencies, and does not begin Phase 11. Every
> framework recommendation is a decision to be ratified through the ADR process
> before any implementation proceeds.

---

## 1. EXECUTIVE VERDICT

**The canonical AutoForge architecture is sound and internally consistent. It remains
the PRIMARY architecture. External technologies are components to be placed behind
AutoForge abstractions — never replacements for the architecture.**

| Technology | Verdict | One-line rationale |
|---|---|---|
| **Temporal** | **RECOMMENDED** (production durable backend, behind an adapter; deferred timing) | Solves a real gap (durable, distributed long-running execution). Sits **under** the WorkflowEngine as an orchestration backend. |
| **LangGraph** | **DO NOT USE** (now) | AutoForge already has a bounded reasoning loop (EngineeringLoop + Worker + AI adapter); LangGraph duplicates it and couples reasoning to a graph framework. |
| **LangChain** | **DO NOT USE** | Model Router (Phase 7) is already the authoritative provider abstraction; LangChain adds coupling and a second model layer. |
| **Langfuse** | **OPTIONAL** (LLM telemetry backend, Phase-14-timed; adapter; never system of record) | Genuinely complementary for LLM telemetry (prompts, tokens, cost, eval) behind the AutoForge Observability port. |
| **CrewAI** | **DO NOT USE** | Direct overlap with Workflow + Worker Dispatcher + Engineering Loop + AI Infrastructure; no unique value. |

**Framing that governs every decision:**

```
AutoForge architecture            ← PRIMARY
        ↓
Stable AutoForge abstraction      ← boundary (interface / contract)
        ↓
Framework adapter                 ← replaceable
        ▼
External technology               ← component only
```

Where AutoForge does not need a stable abstraction, the technology is **not used**.

---

## 2. ORIGINAL ARCHITECTURE SUMMARY

The canonical design (`architecture/ARCHITECTURE.md`, `VISION.md`, `ROADMAP.md`)
is an **AI Operating System**, not a chatbot, IDE, or script. Organised around the
**Kernel** as the sole executive orchestrator: the platform owns orchestration,
*every subsystem owns its own execution*.

**Canonical request pipeline:**
```
User → Kernel → [Strategic Engine] → Workflow Engine → Scheduler
     → Execution Engine → Review Engine → Artifact Manager → Finished Product
```

**Shared Platform Services:** Runtime State Manager (authoritative state), Canonical
Events + Event Bus, Knowledge Engine, Memory Engine, Learning Engine, Capability
Registry, Model Router, Execution Continuity Manager, Connector Layer, Observability,
Dashboard, Security.

**Commitments relevant to this mission:**
1. **Kernel owns orchestration; engines own execution** — a hard separation.
2. **Workflow Engine owns coordination only** — never implementation.
3. **Scheduler is an internal Workflow/Execution component** — not a top-level engine.
4. **Runtime is the single authority for durable state & checkpoints.**
5. **Model Router is provider- and model-agnostic; Capability Registry owns AI metadata.**
6. **Deterministic orchestration around probabilistic AI** — the control layer is predictable.
7. **Long-running, recoverable, checkpointable executions** (8–10 h+ sessions).
8. **Local-first & vendor-neutral** — no cloud required for ordinary development.
9. **Human-governed autonomy + HITL approval gates** for consequential actions.
10. **Event-driven, state-driven** subsystem communication.
11. Durable execution is a **goal** (VISION §"Enable long-running, recoverable executions"),
    not a mandate to import any specific product.

---

## 3. CURRENT ARCHITECTURE SUMMARY

A Python monorepo. Verified dependency direction:
```
composition
 └─ execution → workflows → {models, runtime(facade/vocab)}
            ├── connectors
            └── ai_infrastructure → kernel (Kernel interfaces only)
```
- Kernel / Runtime / Events / Event-Platform / Models / Knowledge — frozen foundation.
- **Phase 7** (ADR-006): Capability Registry, Model Router (selection only), Execution
  Continuity Manager (retry/failover). Pure rules, deterministic, local-first; provider
  adapters pluggable; no real provider yet.
- **Phase 8** (ADR-007): Connector Platform — filesystem, git, GitHub.
- **Phase 9** (ADR-008): Workflow Platform — DAG, state machine, queue, scheduler,
  deterministic retry, HITL ApprovalGate, recovery snapshots. Declared in-process (no
  Redis/Kafka/Celery/Temporal).
- **Phase 10** (ADR-009): Execution Platform — Worker lifecycle/dispatcher, Engineering
  Loop (understand→plan→implement→test→evaluate→diagnose→repair→retest), deterministic
  evaluation, failure diagnosis, artifact/provenance, HITL governance, real End-to-End engineering loop.
- Composition root wires everything.

**Runtime context today:** single-node, in-process, local-first, deterministic encoder
---

## 4. ORIGINAL vs CURRENT — COMPONENT-BY-COMPONENT

| Component | Original responsibility | Current impl | Phase | Framework rel. | Gap | Status |
|---|---|---|---|---|---|---|
| Kernel | executive orchestration | `autoforge-kernel` | 2 | none | residual stubs | ALIGNED |
| Runtime State Manager | authoritative state + checkpoints | `autoforge-runtime` | 3 | none | — | ALIGNED |
| Event Platform | transport/delivery | `autoforge-event_platform` | 4 | none | — | ALIGNED |
| Events (vocab) | canonical event model | `autoforge-events` | 0/1 | none | — | ALIGNED |
| Knowledge | retrieval/fusion | `autoforge-knowledge_platform` | 5 | none | partially wired | PARTIALLY ALIGNED |
| Memory | persistent context | `autoforge-memory` (spec) | 6 | none | not implemented | MISSING |
| Context Engineering | task-context assembly | ADR-003 + ExecutionContext | 0/10 | none | minimal | PARTIALLY ALIGNED |
| AI Infrastructure | CapRegistry / Router / Continuity | `autoforge-ai_infrastructure` | 7 | port-only | no real provider | ALIGNED |
| Model Router | provider-agnostic selection | RouterService + policies | 7 | none | — | ALIGNED |
| Connector Platform | external infrastructure | `autoforge-connectors` | 8 | none | — | ALIGNED |
| Workflow Platform | orchestration of work | `autoforge-workflows` engine/scheduler | 9 | none (in-process) | durable/distributed missing | PARTIALLY ALIGNED |
| Execution Platform | implementation | `autoforge-execution` (loop/worker/dispatch) | 10 | none | — | ALIGNED |
| Engineering Loop | per-worker build-test loop | `EngineeringLoop` | 10 | none | — | ALIGNED |
| Agent Runtime | reasoning/agent state | no formal layer | — | none | boundary unclear | NEEDS RECONCILIATION |
| Workers | specialised workforce | generic `EngineeringWorker` | 10 | — | Phase 13 | PARTIALLY ALIGNED |
| Review Engine | quality gates | — | 11 | — | — | MISSING |
| Artifacts | provenance pipeline | `ArtifactPipeline` + provenance | 10 | — | full ArtifactManager (P12) | PARTIALLY ALIGNED |
| Observability | telemetry (incl. LLM) | — | 14 | — | Langfuse candidate | MISSING |
| Security | authZ + sandbox | workspace confinement | 10/15 | — | — | PARTIALLY ALIGNED |
| Governance + HITL | approval gates | ApprovalGate + ExecutionGovernance | 9/10 | none | stack-finalization gate missing | ALIGNED (partial) |
| Learning | learning loop | — | 18 | — | — | MISSING |
| Durable orchestration | long-running recoverable | snapshots (in-process) | 9/10 | Temporal (candidate) | distributed/crash durability | NEEDS RECONCILIATION |

---

## 5. ARCHITECTURAL DRIFT ANALYSIS

1. **Did Phase 9 become a home-grown Temporal?** **No.** It implemented a large slice of
   temporal-like semantics in-process, but these encode **domain** semantics (DAG,
   dependency, approval, retry policy) that belong to AutoForge. Only the
   durability/distribution slice belongs to Temporal. Risk = duplication → mitigated
   by a single adapter, never by replacing the engine.
2. **Did Phase 10 become an Agent Runtime?** It introduced `EngineeringLoop` +
   `worker.py` — an agentic loop embedded in the Execution layer. Per ARCHITECTURE §8,
   this is **correct** (Execution owns engineering loops). It did not hijack Workflow. A
   formal Agent Runtime handle is desired for Phase 13.
3. **Engineering Loop in correct layer?** ✅ Execution layer (ADR-009).
4. **AI reasoning separated from workflow orchestration?** ✅ WorkflowEngine is
   deterministic; AI is invoked only through `AIEngineeringProvider` at the agent level.
5. **Runtime still authoritative?** ✅ facades project into Runtime (ADR-002/003).
6. **Workflow still domain-level?** ✅ definition-time models; scheduling is policy; no AI in decisions.
7. **Execution still execution-level?** ✅ confined environment, argv, timeout, artifacts.
8. **Connectors still infrastructure?** ✅ uniform boundary.
9. **Model Router still provider-agnostic?** ✅ selection-only; executors injectable; reference catalog is non-normative.
10. **HITL correctly located?** ✅ responsibilities + governance; a tech-stack-finalization gate is missing (see §18).
11. **Technology-stack finalization governed?** ⚠️ **MISSING as an enforced gate** — must be added.
12. **Long-running workflows represented?** ⚠️ semantically yes; across processes/machines, no.
13. **Durable execution missing?** ⚠️ in-process snapshot/recovery exists; distributed/crash durable does not.
14. **Duplicating established-tech capability?** ⚠️ partially — Phase 9 re-implements durable
    primitives, but they encode AutoForge domain semantics (not pure duplication). Keep as
    domain; let Temporal provide runtime persistence.
---

## 6. TEMPORAL ANALYSIS (Primary Reconciliation)

### 6.1 Central model

```
AutoForge Workflow Domain (WorkflowEngine: semantics, tasks, DAG, policy, HITL)
        ↓
Workflow Abstraction (stable interface)
        ↓
Orchestration Adapter  ◄── the ONLY layer that knows Temporal
        ├── InProcess Backend   (local / offline / deterministic — default)
        └── Temporal Backend    (production: durable distributed execution)
```

**This model is correct and is the recommended architecture.** Do **NOT** replace the
WorkflowEngine with raw Temporal APIs — that would erase the deterministic domain
semantics, HITL policy, canonical events, and Runtime authority that define AutoForge.

### 6.2 Responsibility matrix

| Concern | AutoForge | Temporal (adapter) |
|---|---|---|
| Workflow / DAG / task **semantics** | ✅ | — |
| Dependency policy & task meaning | ✅ | — |
| Governance & HITL policy | ✅ | signal *transport* for approval only |
| **Deterministic scheduling decisions** | ✅ domain rules | durable execution of those rules |
| **Retry semantics** (which errors / policies) | ✅ domain policy | durable enforcement of that policy |
| Timers / backoff / waits | ✅ expression | ✅ durable execution |
| Signals (e.g. approval resume) | ✅ semantics | ✅ delivery |
| Run-state persistence | platform (Runtime) | workflow-run durability |
| Crash recovery / distribution / worker pool | — | ✅ |

### 6.3 Answers to the 13 reconciliation questions

1. **Which stay AutoForge?** Workflow/domain semantics, dependency policy, HITL &
   approval policy, governance, task meaning, engineering contracts, project state,
   Deterministic-First rules (retry-policy *meaning*, security, compatibility), Runtime
   authority, and the InProcess backend.
2. **Which delegate to Temporal?** Durable **execution**: run persistence, durable
   timers/waits/backoff, durable signals, crash recovery, distributed scheduling, activity execution.
3. **Which are an adapter?** Mapping AutoForge `WorkflowDefinition` ↔ Temporal
   workflow/activity and the reverse projection back to domain + canonical events. No
   Temporal types leak into the domain.
4. **Should WorkflowEngine become a domain abstraction over Temporal?** Yes — it remains
   the domain abstraction and gains an isolated `OrchestrationAdapter` (InProcess default).
5. **In-process backend for local/offline?** **Yes — mandatory.** Deterministic, infra-free, unit-testable.
6. **Production backend?** Temporal (or another durable executor behind the same adapter)
   for durable/distributed/long-running production; InProcess remains valid for
   single-host/offline deployments.
7. **Local-first dev?** The composition root selects the InProcess adapter when no
   Temporal server is configured. No cloud/infrastructure required for ordinary development.
8. **Temporal ↔ Runtime?** Runtime is authoritative; Temporal holds workflow-run
   durability projected back via the existing `RuntimeFacade`; checkpoints stay in
   Runtime (ADR-002/003) — not conflated with Temporal event history.
9. **Temporal ↔ Execution?** Temporal schedules workflow steps that the Execution Engine /
   Worker Dispatcher runs; the Execution Platform is the activity implementation — not replaced.
10. **HITL pause/resume?** AutoForge `ApprovalGate` (WAITING_APPROVAL) maps to a durable
    Temporal wait released by an approval Signal; AutoForge keeps the meaning.
11. **Checkpoints ↔ durable state?** Runtime `CheckpointManager` + `WorkflowSnapshot`
    remain the canonical checkpoint path; Temporal history is run durability, not a second system of record.
12. **Retries divided?** Phase 7 `ExecutionContinuityService` = provider retry/failover at
    the model layer; Phase 9 `retry.should_retry/backoff` = domain task retry semantics;
    Temporal = durable/low-level activity retry. **Policy is expressed by AutoForge,
    enforced durably by Temporal.**
13. **Prevent duplicated orchestration?** The adapter is the single chokepoint; the domain
    remains the only owner of orchestration policy. No raw Temporal API usage elsewhere.

> **Boundary principle (Temporal):** AutoForge owns semantics, policies, governance, HITL,
> contracts, and engineering lifecycle. Temporal owns durable execution mechanics. Do not
> duplicate ownership. (Matrix above is the explicit ownership record.)
---

## 7. LANGGRAPH ANALYSIS

**Decision: DO NOT USE (now).**

| LangGraph offering | AutoForge equivalent | Verdict |
|---|---|---|
| Stateful agent reasoning | `EngineeringLoop` + `ExecutionContext.prior_iterations` | already owned |
| Tool selection | domain decision / AI adapter | already owned |
| Agent loops | bounded Engineering Loop (understand→…→retest) | already owned |
| Graph transitions | explicit `LoopStatus` FSM + `AIEngineeringProvider` | already owned |
| Agent-side checkpoints | Runtime + `ExecutionRecovery` | already owned |
| AI-specific state | `ExecutionContext` (attempts, diagnosis) | already owned |

**AutoForge Workflow ≠ AI reasoning graph.** A workflow step is a deterministic domain
operation; an inference is a probabilistic model call. Merging them couples durable
orchestration (Temporal-eligible) with probabilistic reasoning (Model Router) and
violates Deterministic-First + Separation of Concerns.

**When it could return:** only if Phase 13 (AI Workforce) proves a genuine need for
richer multi-step agent reasoning — then introduce a minimal **AgentRuntime** boundary
(§13) *first*, and optionally evaluate LangGraph/native behind it. That decision is
deferred, not pre-made. **For now: DO NOT USE.**

---

## 8. LANGCHAIN ANALYSIS

**Decision: DO NOT USE.**

- Phase 7 **Model Router is authoritative and provider-agnostic**. LangChain would create
  a *second* model abstraction and re-couple AutoForge to a provider toolkit. Violates the
  rule that the Model Router stays authoritative.
- Candidate value (tool abstractions, retrieval, structured output, prompt/tool interfaces)
  is covered by **Connector Platform**, **Capability Registry**, and structured domain models.
- A specific utility would only be justified **behind an adapter** (e.g. a Phase-7
  `ModelExecutor` implementation) so it remains replaceable. **No material value now.**

---

## 9. CREWAI ANALYSIS

**Decision: DO NOT USE.**

CrewAI's value is specialized multi-role agent coordination. AutoForge already owns the
equivalent structure: **Phase 13 AI Workforce** (specialized engineers), **Phase 9
Workflow** (task/DAG/dependency/approvals), **Phase 10 Worker Dispatcher**
(dispatch/concurrency), **Engineering Loop / Worker** (execution), **AI Infrastructure**
(model routing). CrewAI would create **overlapping ownership** at every boundary and erode
the deterministic/HITL guarantees. The "use only if genuinely justified" bar is **not
met.** Do not use.

---

## 10. LANGFUSE ANALYSIS

**Decision: OPTIONAL — LLM-telemetry backend (Phase-14-timed), adapter-backed, never the
system of record.**

- **Platform Observability** remains authoritative for system/workflow/execution telemetry.
- **Langfuse** fits the **LLM slice**: prompts, generations, completions, token usage,
  latency, cost, and evaluation signals flowing through the Model Router.
- **Trace correlation:** reuse canonical `correlation_id` / `workflow_id` / `task_id` /
  `worker_id` so Langfuse traces are a correlated **read model**, not an authority.
- **Privacy/security:** self-hostable to honor Security-by-default + offline; no prompt/
  secret leakage beyond the configured sink.
- **Timing:** adopt later under Phase 15 (Observability); optional; not needed for the
  Phase 11 (Review) build.
---

## 11. TECHNOLOGY DECISION MATRIX

| Technology | Purpose | AutoForge owns | Framework owns (adapter-based) | Integration boundary | Benefits | Costs | Lock-in | Current need | Future need | **Decision** |
|---|---|---|---|---|---|---|---|---|---|---|
| **Temporal** | durable/distributed workflow execution | semantics, policy, HITL, contracts | durable exec, persistence, timers, signals, crash recovery, distribution | `OrchestrationAdapter` (WorkflowEngine plugin) | crash-proof long runs, reliability | infra + temporal server, ops | low–moderate (via adapter) | DEFER | HIGH (P12/21) | **RECOMMENDED** (behind adapter; deferred timing) |
| **LangGraph** | agentic reasoning graph | reasoning = Model Router / AI adapter | graph transitions, agent checkpoints | AgentRuntime adapter (future) | familiarity | duplication, coupling | moderate | none | LOW | **DO NOT USE** |
| **LangChain** | model/tool abstractions | Model Router authoritative | model semantics, toolchains | ModelExecutor port | familiarity | coupling, churn | high | none | none | **DO NOT USE** |
| **Langfuse** | LLM observability/eval | Platform Observability | LLM telemetry, cost/eval | Observability LLM port | complete LLM telemetry | self-host | moderate | none | Phase 14 | **OPTIONAL** |
| **CrewAI** | multi-agent coordination | Workflow + Dispatcher + Loop owned by AF | agent crews, delegation | — | little | overlap, duplicate ownership | moderate–high | none | none | **DO NOT USE** |

Every decision keeps **AutoForge architecture first**; frameworks are components behind
adapters, or are not adopted at all. Values: MANDATORY / RECOMMENDED / OPTIONAL / DEFER /
DO NOT USE. None of the five frameworks is MANDATORY; the structural invariants that ARE
mandatory are: the abstraction/adapter pattern, the in-process backend, and Runtime authority.

---

## 12. WORKFLOW ↔ TEMPORAL BOUNDARY

```
AutoForge owns:  workflow semantics; DAG & dependency policy; deterministic schedule
                 decisions; retry *semantics*; approval/HITL policy; task meaning;
                 engineering lifecycle contract; workflow contracts; governance;
                 Deterministic-First rules (gates, security, compatibility, license).
Temporal owns:   durable execution; durable run-state persistence; durable timers/
                 backoff; durable signals; crash recovery (process restart / machine);
                 distributed workflow scheduling; activity execution; deterministic replay.
```

**Prevent duplication:** only the adapter knows how to map AutoForge domain → Temporal;
AutoForge never re-implements Temporal mechanics, and Temporal never owns engineering policy.

---

## 13. AGENT RUNTIME BOUNDARY

**Formal Agent Runtime: RECOMMENDED as a boundary now; formalize at Phase 13 (AI
Workforce); no new package during Phase 11.**

| Layer | Owns |
|---|---|
| **Agent Runtime** (future) | agent state, tool availability, reasoning, agent lifecycle, model invocation, agent checkpoints |
| **Workflow** | business/engineering workflow, dependencies, governance, HITL, lifecycle, durable orchestration |
| **Execution** | workspace, commands, artifacts, evaluation |
| **Model Router** | provider-agnostic model selection |

Today the agent responsibilities are embedded in `EngineeringWorker` + AI adapter; this
separation is the conceptual boundary, implemented when the AI Workforce lands. Phase 11
(Review) does **not** require an AgentRuntime package.

---

## 14. EXECUTION / AI-INFRA / CONNECTOR / RUNTIME BOUNDARIES

- **Execution** — ✅ correct (Phase 10 ADR-009): confined env, argv list, timeout, artifacts.
- **AI Infrastructure** — ✅ correct (ADR-006): router/continuity/capability; model calls only
  via ModelRouter → `ModelExecutor` adapters.
- **Connector** — ✅ infrastructure only; never a policy engine.
- **Runtime** — ✅ authoritative state/checkpoints; Temporal is only a durable run-execution
  store, never an authority over platform state.
---

## 15. HITL ARCHITECTURE AND TECHNOLOGY-STACK FINALIZATION

**Non-negotiable:** AutoForge must not silently finalize its technology stack.

| Stage | Layer / owner | Deterministic / AI |
|---|---|---|
| 1. Requirements | Kernel / project intake | Deterministic |
| 2. Research | Strategic Engine (Research role) | AI reasoning + deterministic knowledge |
| 3. Candidate technologies | Strategic Engine | AI synthesis → candidate list |
| 4. Deterministic compatibility checks | Deterministic validation | **Deterministic** |
| 5. Security / license / runtime checks | Security + deterministic policy | **Deterministic** |
| 6. AI tradeoff analysis | Strategic Engine | AI tradeoffs (proposals only) |
| 7. Candidate technology stack | from above | — |
| 8. **Human approval gate** | Governance / HITL (ApprovalGate) | Human — **required before finalization** |
| 9. Finalized tech stack | config / ADR record | human-approved |

**Rules:** human approval precedes consequential finalization; a deterministic policy
failure (compatibility/license/security/runtime) is final and AI cannot override it.
**Gap:** currently no component enforces step 8 for tech-stack finalization — this must be
added as a governance type (Workflow ApprovalGate + ExecutionGovernance extension).

---

## 16. DETERMINISTIC-FIRST ARCHITECTURE

**Deterministic:** state transitions, dependency resolution, workflow scheduling, retry
policy, timeouts, security, validation, compatibility, license policy, resource limits,
test pass/fail, approval requirements, policy enforcement.

**AI reasoning:** planning, synthesis, architecture alternatives, tradeoffs, diagnosis,
repair, ambiguous engineering.

The LLM is never a policy engine. Phase 9/10/7 already implement this (pure-function
scheduling, non-overridable evaluation, deterministic retry). Temporal supplies only durable
execution mechanics — deterministic-first is preserved.

---

## 17. LOCAL-FIRST vs PRODUCTION DURABLE MODE (Dual-mode)

**The dual-mode architecture is sound** and mirrors MANIFEST offline-first / online-enhanced.

```
Local dev:      AutoForge + local models  + with-process adapter + local execution
Production:     AutoForge + Temporal + distributed workers (where needed)
                + local/cloud models + connectors
```

Local dev must never require cloud infrastructure. The composition root selects the
orchestration backend by config, defaulting to InProcess.

---

## 18. PROVIDER / FRAMEWORK AGNOSTICISM

Kept behind AutoForge adapters everywhere:
- **AI:** ModelRouter → ProviderAdapter.
- **Workflow:** AutoForge Workflow → OrchestrationAdapter → Temporal | InProcess.
- **Agent Runtime:** AutoForge AgentRuntime → LangGraph / alternative / native (future).
- **Observability:** AutoForge Observability → Langfuse / alternative (Phase 14).

No single model runtime, workflow backend, agent framework, or provider is a mandatory dependency.

---

## 19. GAP LIST

1. Agent Runtime **boundary** not formally formalized (defer to Phase 13).
2. **Technology-stack finalization HITL gate** not enforced by any component (§8) — must be added.
3. **Durable-orchestration backend** not yet adopted (decision recorded; implementation deferred).
4. Memory (P6), Learning (P18), Review (P11), Observability (P14), Security (P15) — per roadmap.
5. Real **provider adapters** missing (later phase).
6. Runtime checkpoints on plain dicts — need a durable store for production durability.
7. Context Engineering minimal (Phase-0 contract; full assembly later).

---

## 20. ADR REQUIREMENTS

Respecting the ADR process (approved decision before canonical change), this mission
**drafts** rather than approves:

- **ADR-010 — Durable Workflow Orchestration** (OrchestrationAdapter + Temporal backend,
  InProcess default). Written as **Proposed**; promoted to `architecture/decisions/` as
  **Accepted** only after approval.
- **Agent Runtime Boundary** (draft, Phase 13).
- **AI Framework Integration Strategy** (reference-only: LangGraph/LangChain/CrewAI DO NOT
  USE now; Langfuse OPTIONAL at Phase 14).

Canonical architecture is not silently changed; proposed ADRs remain **Status: Proposed**.
---

## 21. ROADMAP IMPACT (no roadmap rewrite)

The decision does **not** restructure the roadmap; it clarifies where technology lands.

- **Phase 11 (Review):** no new orchestration dependency; builds on Phase-10 execution/worker; in-process.
- **Phase 12 (Artifact):** unchanged semantics; durability/adapter context relates here.
- **Phase 13 (AI Workforce):** introduces the AgentRuntime boundary (§19).
- **Phase 14 (Observability):** optional Langfuse port for LLM telemetry.
- **Phase 21 (Distributed):** the intended home of the Temporal-backed distributed workers.

**Temporal underneath Phase 9/10:** yes — a durable execution backend *below* the
WorkflowEngine, selected only in production mode; it does **not** displace Phase 9
`WorkflowEngine`/`Scheduler`, which remain the domain abstraction.

---

## 22. RECOMMENDED TARGET ARCHITECTURE (VERIFIED)

The hypothesis is largely correct with two corrections: **LangGraph and LangChain are
removed from the live path** (reasoning is the existing AI adapter), and **Langfuse is an
optional Phase-14 observability sink**; Temporal is a durable backend under the adapter.

```
USER / API
    │
    ▼
KERNEL
    │
    ├── RUNTIME (authoritative state)     ├── EVENTS (canonical)     └── GOVERNANCE / HITL
    │
    ▼
AUTOFORGE WORKFLOW   (domain / DAG / policy / HITL)
    │
    ▼
ORCHESTRATION ADAPTER   ◄── stable boundary; the only layer that knows backends
    ├── InProcess                    └── Temporal (durable waits, recovery)
    │                                      │
    ▼                                      ▼ schedules workflow steps
WORKER DISPATCH → EXECUTION WORKER (Planning/Engineering Loop)
    ├── Reasoning  ── via AIEngineeringProvider (no LangGraph/LangChain)
    ├── Connectors  (Files / Git / GitHub)
    ▼
EXECUTION ENVIRONMENT / workspace / commands / artifacts / evaluation (Deterministic)
    ▼
REVIEW (Phase 11) → GOVERNANCE / HITL → FINAL APPROVAL
   LLM telemetry → Observability (Phase 14) → Langfuse (optional)
```

**Verified correct:** AutoForge first, adapter second, framework third; in-process default;
Temporal production-durable; HITL enforced before consequential finalization.
---

## 23. PHASE 11 IMPLICATIONS

Phase 11 (Review Platform) is **orthogonal** to these reconciliation decisions and can
proceed with no new orchestration dependency:

- Build `ReviewEngine` + `ReviewPolicy` on the existing worker/loop/artifact/evaluation patterns.
- Deterministic quality gates; AI review via the AI adapter (not LangGraph / LangChain).
- Do **not** build the OrchestrationAdapter / Temporal integration during Phase 11; treat
  that as a separate, later-tracked packet (Phase 12/21).
- Keep Phase 9 and Phase 10 frozen implementations untouched.

---

## 24. FINAL DECISIONS

1. **Should AutoForge use Temporal?** Yes — recommended as an optional durable production
   backend behind an adapter (in-process default; implementation deferred).
2. **Exactly where does Temporal sit?** Under `WorkflowEngine` via `OrchestrationAdapter`; durable backend only.
3. **Is Phase 9's WorkflowEngine retained?** Yes — remains the domain abstraction.
4. **Is Phase 9's scheduler retained?** Yes — remains the domain scheduling owner.
5. **Which Phase-9 capabilities move to Temporal?** Durable execution/persistence, timers/
   sleeps, crash recovery, distributed workers, low-level scheduling. **Not** DAG/dependency/
   HITL/retry-policy/approval *policy*.
6. **Temporal ↔ Runtime?** Runtime authoritative; TemporalSchema a run-store projected via
   facade; it is not the checkpoint store.
7. **Temporal ↔ Execution?** Temporal schedules workflow steps to ExecutionEngine/workers;
   it does not execute inside them.
8. **Should AutoForge have an Agent Runtime layer?** Boundary now; formalize at Phase 13; no new package in Phase 11.
9. **Should AutoForge use LangGraph?** No (defer to a future AgentRuntime need).
10. **Should AutoForge use LangChain?** No.
11. **Should AutoForge use Langfuse?** Optional at Phase 14 (adapter).
12. **Should AutoForge use CrewAI?** No.
13. **Mandatory vs optional?** Mandatory = adapter/injection boundaries, in-process backend,
    Runtime authority. Optional = Temporal. Not recommended = LangGraph/LangChain/CrewAI.
    Optional-later = Langfuse.
14. **Remains custom AutoForge IP?** Workflow semantics, HITL/governance, Engineering Loop,
    Model Router + Capability Registry, deterministic evaluation, Release & architecture,
    adapter definitions.
15. **What should never be delegated to frameworks?** Policy, governance, determinism,
    state authority, engineering expectations, and HITL. Delegated via adapter/port: durable run
    execution (Temporal), LLM telemetry (Langfuse).
16. **How is provider/lock-in avoided?** Adapters for workflow, model, agent, observability;
    no hard-mandatory tech; in-process default.
17. **How does local-first mode work?** Composition root selects InProcess adapter by default.
18. **How does production durable mode work?** Temporal backend selected by config; distributed workers where needed.
19. **How does HITL integrate?** ApprovalGate (Workflow) + ExecutionGovernance (Execution) + future tech-stack finalization gate.
20. **How is tech-stack finalization governed?** Human approval before finalization; AI cannot
    override deterministic policy failures (§15).
21. **Does the original architecture remain intact?** Yes — deterministic-first, adapter-based, no core redesign.
22. **What gaps remain?** §19 — finalization gate, AgentRuntime, Memory/Learning, provider store, durable adapter deployment.
23. **Does the roadmap require changes?** No structural changes; placement notes for Phases 12/14/21.
24. **Which ADRs are required?** Proposed ADR-010 (Durable Workflow Orchestration) + drafts for AgentRuntime / AI-Framework strategy.
25. **What should Phase 11 do next?** Build the Review Platform on the existing worker/loop/
    artifact substrate with no new framework dependency.

---

## REFERENCES & EVIDENCE

- `architecture/ARCHITECTURE.md` — Kernel/Engine boundaries, engineering loops, observability, deterministic-first.
- `architecture/ROADMAP.md` — Phases 0–22.
- `architecture/decisions/ADR-006/008/009`; `docs/adr/ADR-{001..007}` + `ADR.md`.
- `packages/workflows/src/autoforge_workflows/*` — engine, scheduler, retry, approval, recovery.
- `packages/execution/src/autoforge_execution/*` — engine, loop, worker, dispatcher, ai_adapter, evaluation, governance.
- `packages/ai_infrastructure/src/autoforge_ai_infrastructure/*` — router, registry, continuity.
- `packages/composition/src/autoforge_composition/*` — composition root.
- Live verification: 431 tests passing (workflows 194 + ai_infra 83 + execution 37 + composition 24 + connectors 93).
(431 tests passing, verified).