# AutoForge AI OS — Complete Development Roadmap

# AutoForge AI OS Roadmap

> This document defines the canonical implementation roadmap for AutoForge AI OS.
>
> Architecture changes must be reflected here only after approval through the ADR process.
>
> The canonical architecture is defined in `architecture/ARCHITECTURE.md`.

============================================================
PHASE 1 — Architecture Foundation
============================================================

Goal:
Establish the canonical architecture of AutoForge AI OS.

Deliverables

• Canonical System Architecture
• Platform Philosophy
• Architectural Principles
• Engine Boundaries
• Shared Platform Services
• Request Lifecycle
• AI Execution Architecture
• Capability Registry
• Model Router
• Execution Continuity Manager
• Event Architecture
• Runtime Architecture
• Knowledge Architecture
• Memory Architecture
• Learning Architecture
• Connector Layer
• Observability
• Security
• Governance
• Architecture Decision Record (ADR) Process

Outcome

✓ Architecture v1.0 Frozen

------------------------------------------------------------

============================================================
PHASE 2 — Kernel
============================================================

Goal

Design, implement and validate the Kernel.

2.1 Specification

• Kernel Architecture
• Responsibilities
• Interfaces
• State Interactions
• Event Interactions
• Orchestration Rules

2.2 Implementation

• Kernel Core
• Request Intake
• Execution Planning
• Engine Orchestration
• Service Orchestration
• Lifecycle Coordination

2.3 Validation

• Unit Tests
• Integration Tests
• Orchestration Tests

Outcome

✓ Kernel v1.0 Frozen

------------------------------------------------------------

============================================================
PHASE 3 — Runtime State Manager
============================================================

Goal

Implement the canonical state system.

Specification

• Runtime Architecture
• State Models
• State Transitions
• State APIs

Implementation

• Runtime Core
• State Store
• State Manager
• Transition Engine

Validation

• State Consistency
• Recovery Tests
• Performance Tests

Outcome

✓ Runtime v1.0 Frozen

------------------------------------------------------------

============================================================
PHASE 4 — Event Platform
============================================================

Goal

Implement platform communication.

Specification

• Event Bus
• Event Model
• Event Contracts
• Event Routing

Implementation

• Event Bus
• Event Publishers
• Event Consumers
• Event Routing

Validation

• Event Delivery
• Ordering
• Recovery
• Replay

Outcome

✓ Event Platform Frozen

------------------------------------------------------------

============================================================
PHASE 5 — Knowledge Platform
============================================================

Goal

Implement engineering knowledge retrieval.

Specification

• Knowledge Engine
• Knowledge Router
• Source Connectors
• Knowledge Fusion

Implementation

• Knowledge Engine
• Retrieval Pipeline
• Fusion Pipeline
• Research Brief Generator

Validation

• Retrieval Quality
• Trust Scoring
• Fusion Accuracy

Outcome

✓ Knowledge Platform Frozen

------------------------------------------------------------

============================================================
PHASE 6 — Memory Platform
============================================================

Goal

Implement persistent contextual memory.

Specification

• Working Memory
• Project Memory
• Long-Term Memory
• Reflection Memory
• Semantic Memory

Implementation

• Memory Engine
• Storage Layer
• Retrieval Layer
• Memory Indexing

Validation

• Persistence
• Retrieval Accuracy
• Context Reconstruction

Outcome

✓ Memory Platform Frozen

------------------------------------------------------------

============================================================
PHASE 7 — AI Infrastructure Platform
============================================================

Goal

Implement provider abstraction.

Specification

• Capability Registry
• Model Router
• Execution Continuity Manager

Implementation

Capability Registry

• Provider Metadata
• Model Metadata
• Capability Metadata
• Deployment Metadata

Model Router

• Routing Policies
• Model Selection
• Cost Optimization
• Local-first Routing

Execution Continuity Manager

• Retry
• Failover
• Context Preservation
• Checkpoint Recovery

Validation

• Provider Switching
• Failover
• Offline Mode
• Local-first Behaviour

Outcome

✓ AI Infrastructure Frozen

------------------------------------------------------------

============================================================
PHASE 8 — Connector Platform
============================================================

Goal

Implement external integrations.

Specification

• Connector Layer
• Connector Contracts

Implementation

• Filesystem
• Git
• GitHub
• Browser
• Docker
• REST
• MCP
• Database
• Vector Store

Validation

• Connector Reliability
• Authentication
• Performance

Outcome

✓ Connector Platform Frozen

------------------------------------------------------------

============================================================
PHASE 9 — Workflow Platform
============================================================

Goal

Implement workflow orchestration.

Specification

• Workflow Engine
• Scheduler

Implementation

• DAG Engine
• Queue
• Scheduling
• Dependencies
• Retry Policies
• Recovery

Validation

• Parallel Execution
• Dependency Resolution
• Workflow Recovery

Outcome

✓ Workflow Platform Frozen

------------------------------------------------------------

============================================================
PHASE 10 — Execution Platform
============================================================

Goal

Implement autonomous engineering execution.

Specification

• Execution Engine
• Worker Lifecycle

Implementation

• Worker Dispatcher
• Engineering Loop
• Artifact Pipeline

Validation

• Worker Coordination
• Execution Stability
• Engineering Loop

Outcome

✓ Execution Platform Frozen

------------------------------------------------------------

============================================================
PHASE 11 — Review Platform
============================================================

Goal

Implement autonomous review.

Specification

• Review Engine
• Review Policies

Implementation

• Architecture Review
• Code Review
• Security Review
• Performance Review
• Documentation Review

Validation

• Review Accuracy
• Quality Gates

Outcome

✓ Review Platform Frozen

------------------------------------------------------------

============================================================
PHASE 12 — Artifact Platform
============================================================

Goal

Manage engineering outputs.

Implementation

• Artifact Manager
• Versioning
• Publishing
• Traceability
• Lineage

Validation

• Version History
• Rollback
• Provenance

Outcome

✓ Artifact Platform Frozen

------------------------------------------------------------

============================================================
PHASE 13 — AI Workforce
============================================================

Goal

Build specialised engineering workers.

Workers

- Research Engineer
- Architecture Engineer
- Planning Engineer
- UI Designer
- Backend Engineer
- Frontend Engineer
- Database Engineer
- ML Engineer
- Infrastructure Engineer
- DevOps Engineer
- QA Engineer
- Security Engineer
- Performance Engineer
- Documentation Engineer
- Legacy Systems Research Engineer
- Legacy Code Archaeologist
- Legacy Architecture Analyst
- Legacy Data Engineer
- Legacy Integration Engineer
- Business Rules Analyst
- Dependency & Impact Analyst
- Modernization Architect
- Migration Engineer

Validation

• Worker Capability Matching
• Multi-Agent Coordination
• Worker Model Policy & Task Requirements Integration (ADR-014)
• Effective Model Requirements resolution and dynamic runtime propagation
• Model capacity allocation routing
• Legacy evidence assembly (Fact, Inference, Hypothesis, Unknown)

Outcome

✓ AI Workforce Model Policies & Allocation Integrated

------------------------------------------------------------

============================================================
PHASE 14 — Observability Platform
============================================================

Goal

Complete platform visibility.

Implementation

• Deterministic Metrics (System, Workflow, Execution, Worker, AI Infrastructure, Node, Artifact, Review, Legacy Modernization)
• Structured Logs (JSON schema, security redaction, error normalization)
• Traces (Span propagation, correlation chains, provenance tracking)
• Dashboard Projections (13 programmatic read models: System, Workflow, Execution, Workforce, AI Infrastructure, Capability, Provider, Model, Inference Node, Artifact, Review, Legacy Modernization, HITL/Governance)

Validation

• Event ingestion and subscription
• Correlation chain propagation
• Cost and Latency aggregation
• Behavioral and security tests

Outcome

✓ Observability Frozen

------------------------------------------------------------

============================================================
PHASE 15 — Security & Governance Platform
============================================================

Goal:
Establish enterprise-grade security, access governance, isolation, and human approval gates across the platform.

Specification & Coverage:

• Authentication (Identity verification, session management, service authentication)
• Authorization (Access control policies, permission enforcement)
• Role-Based Access Control (RBAC) (Fine-grained roles, resource scopes, privilege bounds)
• Sandboxing (Isolated execution environments, process confinement, resource quotas)
• Secrets Management (Secure storage, non-leaking injection, rotation, redaction)
• API Key Management (Provider credentials, key isolation, rate limit tracking)
• Credential Storage (Encrypted at rest, secure retrieval, least-privilege exposure)
• Audit Trail (Immutable, tamper-evident security and administrative event logging)
• Human Approval Gates (Human-in-the-loop oversight for consequential actions)
• Consequential-Action Governance:
  - Technology-stack finalization gates
  - Architecture finalization gates
  - Migration/cutover gates
  - Production deployment gates

Validation:

• Security testing
• Permission and privilege escalation testing
• Sandbox isolation and escape prevention testing
• Credential/secret leakage prevention testing
• Governance bypass and gate enforcement testing
• Penetration testing

Outcome:
✓ Security & Governance Frozen

------------------------------------------------------------

============================================================
PHASE 16 — AutoForge Product Experience
============================================================

Goal:
Build the top-level human interface to the AutoForge AI OS.

Architectural Authority Invariant:
The UI is strictly a presentation, monitoring, and control layer. The UI is NOT an authority. Authoritative state resides exclusively in the Runtime State Manager, Kernel, and Platform Services.

Required Layering Architecture:

```
UI (Web / Desktop Shell)
  ↓
Engineering Experience / Read Models (ADR-004)
  ↓
Application Services
  ↓
Authoritative Platform Services (Kernel, Runtime, Engines)
```

Interface Modules & Workspaces:

• Application Shell (Global navigation, workspace switcher, system status indicator)
• Command Center (Executive operational control, request dispatch, active executions)
• Project Management (Project registry, lifecycle status, configuration)
• Engineering Workspace (Interactive engineering canvas, code/diff viewers, artifact trees)
• Engineering Experience Read Model (Correlation-aware, provenance-linked timeline view)
• Research Interface (Knowledge exploration, source inspection, research brief viewer)
• Planning Interface (Strategic reasoning, decomposition graphs, implementation blueprints)
• Architecture Interface (System blueprints, ADR viewer, component dependency graphs)
• Workforce Interface (23-worker status, active assignments, worker capability inspector)
• Workflow / DAG Visualization (Interactive dependency graph, step execution status, live progress)
• Execution Visualization (Engineering loop progression, tool execution logs, step outputs)
• Review Interface (Multi-aspect review reports, findings inspector, quality gate evaluations)
• Artifact Interface (Artifact catalog, version history, lineage graph, diff viewer)
• Legacy Modernization Workspace (Archaeology views, reconstructed architecture, migration plans)
• Model / Provider / Node Interface (Node topology, active models, provider health, capacity)
• HITL Approval Center (Pending consequential gates, evidence summaries, approve/reject/steer controls)
• Settings & System Controls (Platform configuration, environment parameters, connector settings)

Observability UX:

• Live system metrics (CPU, memory, thread pool, event bus throughput)
• Worker activity (Active workers, task assignments, execution state)
• Workflow activity (Running DAGs, completed steps, blocked steps)
• Queue depth (Scheduling backlog, priority distributions, wait times)
• Execution speed (Step durations, loop turnaround times)
• Model speed & Latency (Per-model latency, average model speed, P50/P95/P99 distributions)
• Model throughput & token consumption (Prompt/completion tokens, velocity)
• Model utilization & Node capacity (Active concurrent slots, hardware load)
• Failures & Retries (Error counts, retry attempts, recovery rates)
• Cost tracking (Real-time and aggregated monetary/token expenditure)
• Traces & Provenance (Distributed trace visualizer, span waterfall, correlation chains)
• Historical performance (Execution trends, duration benchmarks)

Self-Improvement Center UX (Exposing Phase 19):

• What AutoForge learned (Extracted patterns, optimizations, heuristic updates)
• Why it learned it (Failure analyses, performance benchmarks, empirical evidence)
• Evidence & Experimentation (Evaluation runs, comparative benchmarks, regression suites)
• Candidate improvements (Proposed routing, worker prompt, or workflow optimizations)
• Accepted/rejected changes (Decision log, rationale, approval status)
• Active versions & Rollback history (Version lineage, instantaneous rollback controls)
• Routing, Worker, and Workflow improvements (Granular domain optimization tracking)

Outcome:
✓ AutoForge Product Experience Frozen

------------------------------------------------------------

============================================================
PHASE 17 — AI Runtime & Real Model Integration
============================================================

Goal:
Connect model policies and allocation abstractions to ACTUAL local and cloud inference execution.

Architecture & Flow:

```
Worker (Declares Domain Capabilities)
  ↓
Worker Model Profile (LLM Requirements & Policy, ADR-014)
  ↓
Task Model Requirements (Task-Specific Refinements)
  ↓
Effective Model Requirements (Deterministically Resolved Union)
  ↓
ModelAllocator (Capacity Verification & Slot Management)
  ↓
Phase-7 ModelRouter (Policy-Driven Selection & Candidate Ranking)
  ↓
Provider Adapter (Protocol Translation)
  ↓
Deployment (Local / Cloud / Hybrid)
  ↓
Inference Node (M1, HP, Future M6, Cloud Provider)
  ↓
Actual Model (Ollama, llama.cpp, vLLM, OpenAI, Claude, Gemini, etc.)
  ↓
Inference Execution (Streaming, Tokenization, Structured Output)
  ↓
Observability (Metrics, Tracing, Cost, Latency Telemetry)
```

Core Capabilities:

• Worker Model Profiles & Policies (Deterministic requirements for all 23 workers)
• Task Model Requirements integration and dynamic propagation
• Effective Model Requirements resolution (Strengthening union, conflicting constraint rejection)
• ModelAllocator & ModelRouterService live integration
• Local Inference Adapters (Ollama, llama.cpp, vLLM, LM Studio)
• Cloud Inference Adapters (OpenAI, Anthropic Claude, Google Gemini, Groq, DeepSeek, OpenRouter)
• Real hardware node topologies:
  - `local-m1` (Apple Silicon M1 local inference node)
  - `local-hp` (HP workstation local inference node)
  - Future `local-mac-mini-m6` compatibility (Zero worker-level code changes to add nodes)
• Concurrent multi-model and multi-node execution (Support 3+ models/nodes active simultaneously)
• Capacity management, slot reservation, and concurrency bounds
• Provider health monitoring, proactive failover, and retry execution
• Local-first routing with graceful cloud fallback (when enabled)
• Full offline operation capability
• Model performance and empirical benchmark telemetry

Invariants:
- Workers MUST NEVER hardcode model IDs; model selection is centralized and policy-driven.
- Hardware topology additions require only configuration, not worker modifications.
- Model selection is empirically benchmarked and governed by deterministic policies.

Outcome:
✓ Real AI Runtime Frozen

------------------------------------------------------------

============================================================
PHASE 18 — Autonomous Engineering & Modernization
============================================================

Goal:
Integrate the 23-worker AI Workforce with the complete workflow, execution, review, artifact, model-routing, and observability platform for fully autonomous software engineering and enterprise modernization.

Greenfield Pipeline:

```
Idea
  → Research (Knowledge gathering, domain synthesis)
  → Planning (Requirements, task decomposition)
  → Architecture (System design, ADRs, component specs)
  → Design (API contracts, data schemas, UI/UX specs)
  → Implementation (Code generation, component build)
  → Testing (Unit, integration, regression test suite generation)
  → Evaluation (Deterministic verification, test suite execution)
  → Diagnosis (Failure root-cause analysis on test failure)
  → Repair (Targeted code modification loop)
  → Review (Multi-aspect automated review gates)
  → Artifact (Package, manifest, and provenance generation)
  → Deployment (Staging, infrastructure as code, release package)
```

Legacy Modernization Pipeline:

```
Legacy System
  → Discovery (Repository scanning, technology inventory)
  → Archaeology (Deep code analysis, idiom extraction)
  → Architecture Reconstruction (Component mapping, call graphs)
  → Business Rules Extraction (Rule catalog, boundary invariants)
  → Dependency Analysis (Coupling metrics, external integration mapping)
  → Modernization Architecture (Target architecture, migration strategy)
  → HITL Approval Gate (Mandatory human sign-off on target architecture)
  → Migration Implementation (Incremental translation, adapter generation)
  → Testing & Equivalence Validation (Behavioral parity, regression tests)
  → Validation (Performance, security, and contract verification)
  → Cutover & Deployment (Phased rollout, rollback readiness)
```

Preserved Specialized Workforce (23 Workers):

14 Greenfield Workers:
1. Research Engineer (Domain exploration, literature, state-of-the-art analysis)
2. Architecture Engineer (System design, component boundaries, ADRs)
3. Planning Engineer (Task breakdown, dependency DAGs, resource planning)
4. UI Designer (User experience flows, design tokens, component specifications)
5. Backend Engineer (APIs, business logic, domain services, data pipelines)
6. Frontend Engineer (Client applications, UI components, state management)
7. Database Engineer (Schema design, migrations, query optimization, indexing)
8. ML Engineer (Model integration, prompt engineering, fine-tuning pipelines)
9. Infrastructure Engineer (Containerization, cloud infrastructure, IaC)
10. DevOps Engineer (CI/CD pipelines, release orchestration, build systems)
11. QA Engineer (Test plan creation, automated test generation, edge-case analysis)
12. Security Engineer (Vulnerability assessment, threat modeling, security review)
13. Performance Engineer (Profiling, bottleneck identification, optimization)
14. Documentation Engineer (Architecture guides, API docs, operations runbooks)

9 Legacy Modernization Workers:
15. Legacy Systems Research Engineer (Legacy ecosystem research, framework context)
16. Legacy Code Archaeologist (Deep codebase traversal, dead-code detection, idiom recovery)
17. Legacy Architecture Analyst (Legacy component reconstruction, dependency recovery)
18. Legacy Data Engineer (Legacy schemas, stored procedures, data migration pipelines)
19. Legacy Integration Engineer (Legacy protocols, RPC/SOAP interfaces, adapter design)
20. Business Rules Analyst (Implicit business logic extraction and specification)
21. Dependency & Impact Analyst (Cross-system blast-radius and migration risk analysis)
22. Modernization Architect (Target modernization blueprint, strangler pattern plans)
23. Migration Engineer (Automated translation, bridge synthesis, cutover implementation)

Handling Unfamiliar Legacy Codebases:
• Deterministic evidence collection
• Technology-specific analysis where parsers exist; generic fallback AST/regex analysis otherwise
• Strict epistemic separation: FACT vs INFERENCE vs HYPOTHESIS vs UNKNOWN
• Explicit analysis gaps (system never hallucinates missing information)
• Complete provenance tracking back to exact source file and line ranges
• Uncertainty tracking and confidence scoring
• Mandatory human approval gates for all consequential modernization decisions

Outcome:
✓ Autonomous Engineering Foundation Established

------------------------------------------------------------

============================================================
PHASE 18 SUBPHASE EXECUTION STRUCTURE & ROADMAP
============================================================

The canonical execution of Phase 18 progresses through explicit, sequentially ordered subphases:

### Completed Foundational Subphases (18-A through 18-F):
• **18-A — Routing Semantics & Verification (Complete)**: Specialized worker routing verification in isolation.
• **18-B — Live Orchestrated Greenfield Routing & Verification (Complete)**: Greenfield orchestrator workflow with live Ollama daemon.
• **18-C — Greenfield Pipeline Execution Engine & Loops (Complete)**: EngineeringWorker lifecycle and deterministic execution loops.
• **18-D — Scoped Local Qdrant RAG Integration (Complete)**: Offline local Qdrant vector retrieval for engineering context.
• **18-E — Deterministic Evaluation, Diagnosis & Repair Loop (Complete)**: Closed-loop diagnosis, repair plan synthesis, and file mutation verification.
• **18-F — Bounded Autonomous Transformation Proof (Complete)**: Initial 5-file bounded modernization slice.

---

### 18-G — Legacy Modernization — COMPLETE (EXISTING COMMERCIAL CAPABILITY)
• **Scope**: Specialized enterprise legacy modernization engine.
• **Evidence**: Tested and certified across real 511-file mixed-language enterprise workload (`IBM Bank-of-Z` BANKING_CORE / `aws-samples/carddemo`).
• **Certification**: Officially achieved **18-G.6 REAL COMMERCIAL PROJECT AUTONOMOUS COMPLETION CERTIFICATION (LEVEL 2 — REAL PROJECT AUTONOMY PROVEN)**.
• **Certified Pipeline**:
  Discovery → Workload Closure → Semantic Extraction → Dependency Analysis → Architecture Reconstruction → Transformation Planning → Deterministic Synthesis → Build/Package → Runtime Verification → Behavioral Verification → Repair → Regression Verification → Evidence/Provenance.
• **Commercial Status**: Serves as Offering #4 in the AutoForge Commercial Portfolio ($1,000+).
• **CRITICAL INVARIANT**: ALREADY BUILT AND CERTIFIED. Do NOT create a duplicate modernization implementation phase.

---

### 18-H — AI Runtime / Heavy Optimization / Multi-Node Readiness — CURRENTLY FROZEN UNTIL M6 ARRIVAL
• **Scope**: Heavy performance optimization and multi-node hardware fabric readiness audit.
• **Empirical Performance**: Certified at 364,953.2 source NLOC/hour delivery rate; 104.66s delivery wall clock.
• **Fabric Preparation**: 3-node inference topology prepared (`local-m1` + `local-hp` + `local-mac-mini-m6` configuration seam in `run_18h2_nodes.py`).
• **Status**: FROZEN pending physical arrival, setup, and benchmarking of the M6 hardware node.

---

### 18-COMMERCIAL — Commercial AI Engineering Services — NEW PLANNED PHASE

**Purpose**:
Turn AutoForge's already-built AI engineering infrastructure into four concrete, independently sellable engineering services that can be delivered on Fiverr / as subcontracting work without waiting for the future 3-node inference experiment.

These services directly compose the existing AutoForge architecture rather than becoming separate agent systems or disconnected products.

The existing Legacy Code Modernization capability remains the fifth commercial offering and continues to live under 18-G.

#### Five-Service Commercial Portfolio:
1. **RAG Knowledge Assistant** — Target: $750–$1,000+
2. **Custom AI Agent** — Target: $1,000+
3. **AI Automation** — Target: $750–$1,000+
4. **Legacy Code Modernization** — Target: $1,000+ (EXISTING 18-G CAPABILITY — CERTIFIED)
5. **Code Migration / Refactoring** — Target: $1,000+

#### AutoForge Primitives Composition Invariant:
These are commercial offerings, not five separate software architectures. They all compose existing AutoForge primitives:
• Kernel (`packages/kernel`)
• Strategic Engine & Orchestration (`packages/orchestration`)
• Workflow Engine & DAG Scheduler (`packages/workflows`)
• Execution Engine & Engineering Loop (`packages/execution`)
• Review Engine & Quality Gates (`packages/review`)
• Artifact Manager, Lineage & Provenance (`packages/artifacts`)
• Runtime State Manager & Checkpoints (`packages/runtime`)
• Event Bus & Platform (`packages/event_platform`, `packages/events`)
• Knowledge Engine & Retrieval (`packages/knowledge_platform`)
• Memory Engine (Working, Project, Semantic) (`packages/memory`)
• Learning Engine boundary (`packages/learning`, strictly gated)
• Model Router & Policies (`packages/ai_infrastructure`)
• Model Allocator & Capacity Manager (`packages/workforce`)
• 23-Worker Specialized AI Workforce (`packages/workforce`)
• Local RAG & Vector Storage (Qdrant)
• Tool execution & external connectors (`packages/connectors`, `packages/tools`)
• Deterministic transformation & synthesis
• Verification, test execution & regression checking
• Repair loops & root-cause diagnosis
• Provenance, evidence logging & audit trail

---

### Phase 18-COMMERCIAL Cross-Cutting Architecture

All commercial Power Engines (18-COMMERCIAL-A through D) and the existing Legacy Modernization Engine (18-G) strictly adhere to the following first-class cross-cutting architectural contracts:

#### 1. Core Automation Principle: "Autonomy by Default, Human Intervention by Exception"
The foundational product principle across all AutoForge commercial engines is:
**AUTOFORGE SHOULD COMPLETE CUSTOMER WORK WITH THE MINIMUM POSSIBLE HUMAN INTERFERENCE.**
A customer should never have to manually guide AutoForge through every step. Each Power Engine operates autonomously by default throughout its entire execution lifecycle.

Human-in-the-loop (HITL) intervention is explicitly **NOT** the default workflow. The roadmap rejects micromanagement workflows ("AI proposes → human clicks approve for every tiny step"). Human intervention occurs ONLY when a defined risk condition, uncertainty boundary, security authorization, or irreversible external action requires human approval. Everything else executes autonomously to completion.

#### 2. Shared Autonomous Execution & Human-in-the-Loop (HITL) Safety Framework
A cross-cutting architectural framework shared across all Power Engines:
• **Autonomous Execution Conditions**: AutoForge proceeds automatically when:
  - Required inputs, documents, or repositories are available and validated.
  - The planned action is within established workspace and security policies.
  - Confidence and risk metrics satisfy platform acceptance thresholds.
  - Required tools and external connectors are pre-authorized.
  - Execution is fully reversible, idempotent, or safely sandboxed.
  - Verification gates pass (compilation, automated tests, contract checks).
  - No explicit approval-only condition is triggered.
• **Continuous Risk Detection**: Continuous detection monitors for:
  - Destructive filesystem, database, or cloud operations.
  - Irreversible external actions or third-party state mutations.
  - Production-impacting changes to live systems or infrastructure.
  - Credential, secret, or security-sensitive boundary access.
  - Financial, contractual, or licensing-sensitive operations.
  - Ambiguous or conflicting customer requirements.
  - Insufficient source evidence or incomplete semantic models.
  - Low-confidence transformations or repair plans.
  - Unresolved verification failures or regressions exceeding retry bounds.
  - Policy violations or unsafe generated artifacts.
  - Unexpected external side effects or unauthorized network emissions.
  - Scope expansion beyond customer authorization.
• **Extensible Detector Architecture**: Risk detectors are implemented as modular, composable inspection rules rather than a hardcoded static list. Additional domain-specific detectors can be registered dynamically.

#### 3. HITL as a Gated Wait State (`WAITING_FOR_HUMAN_APPROVAL`)
When a risk detector or authorization boundary triggers, AutoForge does not abort or fail:
• **State Transition**: The workflow transitions into an explicit observable state: `WAITING_FOR_HUMAN_APPROVAL`.
• **Preserved Execution State**: The workflow durably captures and preserves:
  - Current execution state, active stage, and DAG position.
  - Full execution plan and pending task hierarchy.
  - Generated intermediate artifacts and source/target working trees.
  - Complete forensic evidence ledger and telemetry references.
  - Precise reason for escalation and risk classification.
  - Proposed action and evaluated alternatives (with trade-offs).
  - Required approval scope and boundary parameters.
• **Post-Decision Flow**:
  - **Approval Granted**: `RESUME → EXECUTE → VERIFY → CONTINUE AUTONOMOUSLY`.
  - **Approval Rejected**: `REJECT → REPLAN / ABORT / SAFE-ROLLBACK` (policy-governed).
• **Architectural Dependency on Phase 18-J**: This wait-and-resume capability depends conceptually on the future **Phase 18-J (Durable Execution + Resume + Idempotency)** for process-restart survival, distributed checkpointing, and idempotent replay. *(Durable execution is NOT implemented here; the architectural dependency is explicitly recorded).*

#### 4. Minimal and High-Value Human Approval Policy
The roadmap explicitly rejects unnecessary HITL prompts that degrade autonomy:
• **Explicitly Rejected Micro-Approvals**:
  - NO "Approve every generated file."
  - NO "Approve every tool call."
  - NO "Approve every planning step."
  - NO "Approve every worker dispatch."
• **High-Value Escalation Examples**:
  - *"AutoForge detected that this action would modify production infrastructure. Approval required."*
  - *"AutoForge detected unresolved behavioral divergence between legacy batch output and modernized target. Human decision required."*
  - *"AutoForge requires authorization to access external customer database."*
The operator intervenes only at meaningful decision boundaries; AutoForge handles everything else autonomously.

#### 5. Risk & Approval Engine & Canonical Event Model
A shared cross-cutting platform component responsible for governance determination (not task execution):
• **Responsibilities**:
  - Determine whether an action is safe for autonomous execution.
  - Verify authorization credentials and scope boundaries.
  - Classify risk type, severity level, and evidence chain.
  - Formulate precise approval requests with explicit scope boundaries.
  - Validate safety invariants before permitting workflow resumption.
• **Canonical Event Stream**: Integrates directly with the platform event bus and emits/consumes canonical events:
  - `RISK_DETECTED` — Specific risk detector triggered with evidence payload.
  - `APPROVAL_REQUIRED` — Workflow halted; `WAITING_FOR_HUMAN_APPROVAL` engaged.
  - `APPROVAL_GRANTED` — Authorized operator signed off on proposed scope.
  - `APPROVAL_REJECTED` — Operator rejected proposal with recorded rationale.
  - `EXECUTION_BLOCKED` — Execution suspended at safety boundary.
  - `EXECUTION_RESUMED` — Execution restored following approved escalation.
  - `SAFE_ABORT_REQUESTED` — Clean shutdown without orphan processes or state corruption.
  - `SAFE_ROLLBACK_REQUESTED` — Reversal of unverified mutations to last verified checkpoint.

#### 6. Live Engineering Workspace / Transformation Studio
A first-class AutoForge product capability (internal working name: **TRANSFORMATION STUDIO** or **LIVE ENGINEERING WORKSPACE**):
• **Core Philosophy**: A live, event-driven window into real autonomous engineering—NOT a canned dashboard with synthetic animations. Every visual element is fed directly from the canonical event stream.
• **VS Code + Cline-Like Engineering Experience**: An integrated, high-fidelity developer workspace where the operator watches AutoForge engineer the project autonomously:
  - **Project Explorer & File Tree**: Live view of repository files, newly created files, and modified trees.
  - **Live Code Editor**: Real-time syntax-highlighted editor displaying code as it is generated, refactored, or repaired.
  - **Integrated Terminal / Output**: Live streaming build, compilation, test runner, and CLI outputs.
  - **Worker Activity Panel**: Active worker dispatch status, capability requirements, and assigned model/node.
  - **Workflow & Task DAG Visualizer**: Real-time stage progression and dependency execution status.
  - **Canonical Event Stream**: Filterable log of platform, execution, and risk events.
  - **Build & Test Verification Status**: Granular compile logs, test pass/fail counts, and coverage metrics.
  - **Artifact & Evidence Browser**: Full access to intermediate and final artifacts with cryptographic hashes.
  - **Risk & Approval Panel**: Clear visualization of pending escalations, risk evidence, and one-click action controls.
  - **Execution Timeline & Telemetry**: Wall clock, critical path duration, token velocity, and TTFT metrics.

#### 7. Dual-Pane Experience & Multi-Engine Live Observability
• **Dual-Pane Source/Target View for Legacy Modernization (18-G)**:
  - **Left Pane (Source / Legacy)**: Legacy codebases (COBOL, JCL, Copybooks, BMS, SQL, IMS, Assembler).
  - **Right Pane (Target / Modernized)**: Generated modern target code (Java, Spring Boot, TypeScript, Python, etc.).
  - **Granular Real-Time Event Progress**:
    `FILE DISCOVERED → FILE ANALYZED → SYMBOLS EXTRACTED → DEPENDENCY IDENTIFIED → BUSINESS RULE RECONSTRUCTED → TRANSFORMATION PLANNED → TARGET ARTIFACT GENERATED → BUILD STARTED → BUILD PASSED → TEST STARTED → BEHAVIORAL COMPARISON → DIVERGENCE DETECTED → REPAIR STARTED → REPAIR COMPLETED → VERIFICATION PASSED`.
• **Live Observability Adapted for All Power Engines**:
  - **RAG Knowledge Assistant**: Documents Ingested → Document Parsing → Semantic Chunking → Embedding Generation → Vector Indexing → Query Retrieval → Context Construction → LLM Answer Generation → Answer & Citation Verification.
  - **Custom AI Agent**: Goal Decomposition → Strategic Plan → Worker Allocation → Tool Execution → Working/Project Memory Access → Artifact Synthesis → Deterministic Verification → Autonomous Completion.
  - **AI Automation**: Input Document/Data Intake → AI Classification/Extraction → Deterministic Transformation → Tool/API Execution → Schema Validation → Final Structured Output.
  - **Code Migration / Refactoring**: Source Repository Analysis → Semantic AST Extraction → Transformation Planning → Target Code Generation → Target Build → Test Execution → Behavioral Parity Comparison → Closed-Loop Repair.

#### 8. Synchronized Semantic Lineage (Source ↔ Target)
The Transformation Studio establishes bidirectional semantic traceability between legacy/source artifacts and modernized/refactored targets:
• **Lineage Granularities**:
  - File-to-file lineage (e.g., `CBTRN01C.cbl` ↔ `TransactionProcessor.java`).
  - Symbol & declaration lineage (e.g., `01 WS-TRAN-REC` ↔ `TransactionRecordDTO`).
  - Procedure/function lineage (e.g., `PROCESS-CARD-PAYMENT` ↔ `CardPaymentService.process()`).
  - Business-rule lineage (e.g., `BR-CARD-004: Interest Rate Calculation` ↔ `InterestRateCalculator.compute()`).
  - Dependency & integration lineage (e.g., VSAM KSDS file reads ↔ Spring Data JPA repository queries).
  - Transformation provenance (source file/line ranges, transformation rule, worker ID, model ID).
  - Verification evidence linked directly to lineage nodes (test case ID, equivalence run ID).

#### 9. Live Diff & Behavioral Verification Surface
• Visual side-by-side diffs showing exactly what AutoForge altered, generated, or repaired.
• Immediate visual reporting of compilation errors, behavioral parity checks, and test regressions.
• Interactive inspection of diagnostic root causes and synthesized repair plans.
• **Architectural Invariant**: The UI is strictly an observability surface over the real platform runtime; it never performs execution or state manipulation on its own.

#### 10. Customer Deliverable Package Contract
Every commercial Power Engine must produce a complete, production-grade, customer-deliverable project folder:
• **Not Merely Code Snippets**: Deliverables represent complete, turnkey project packages ready for customer deployment or integration.
• **Workload-Specific Packaging Structure** (tailored by the specific Power Engine):
  - `source/` — Customer source files or input documents.
  - `generated/` — Target modernized code, agents, automation scripts, or assistant configurations.
  - `tests/` — Generated unit, integration, and regression test suites.
  - `docs/` — Architecture documentation, API specifications, runbooks, and operator manuals.
  - `configuration/` — Environment variables, Dockerfiles, compose specs, and dependency manifests.
  - `scripts/` — Build, run, migration, and verification automation scripts.
  - `artifacts/` — Compiled binaries, fat JARs, distributions, or serialized knowledge indexes.
  - `evidence/` — Execution traces, benchmark results, and verification records.
  - `verification/` — Test execution logs, behavioral parity comparisons, and coverage reports.
  - `provenance/` — Cryptographic manifests, worker/model attribution, and transformation ledgers.
  - `README.md` — Comprehensive project summary, setup instructions, usage guide, and assumptions.
  - `DELIVERY_REPORT.md` — Final executive delivery summary with verification scorecards.

#### 11. User-Configurable Output Management (`AUTOFORGE_OUTPUT_ROOT`)
A shared Output / Delivery Manager contract allowing the user to control destination paths:
• **Environment & Configurable Root**: Supported via `AUTOFORGE_OUTPUT_ROOT` with OS-portable path resolution (macOS, Linux, Windows).
• **Configurable Packaging Options**:
  - Project-specific delivery subfolder naming (`<project-id>-delivery/`).
  - Timestamped delivery archives (`<project-id>-delivery-<timestamp>/`).
  - Toggleable inclusions: execution logs, raw evidence, source artifacts, test recordings, verification reports.

#### 12. Automated Final Delivery Pipeline
The complete, uninterrupted end-to-end commercial lifecycle:
```
CUSTOMER REQUEST
      ↓
POWER ENGINE INTAKE
      ↓
AUTONOMOUS EXECUTION (Analyze → Plan → Implement)
      ↓
CONTINUOUS RISK DETECTION
      ↓
HITL GATE (Only if high-risk boundary triggered)
      ↓
DETERMINISTIC VERIFICATION (Build, Test, Equivalence)
      ↓
CLOSED-LOOP REPAIR (Automatic root-cause diagnosis & re-verification)
      ↓
FINAL VERIFICATION SIGN-OFF
      ↓
DELIVERY PACKAGE GENERATION (Workload-specific structure)
      ↓
CUSTOMER OUTPUT DIRECTORY (Configured by AUTOFORGE_OUTPUT_ROOT)
      ↓
FINAL DELIVERY REPORT (Executive summary & verification scorecard)
```

#### 13. Canonical Power Engine Lifecycle Contract
All commercial Power Engines implement the standard 11-stage autonomous execution lifecycle:
```
INTAKE → UNDERSTAND/ANALYZE → PLAN → EXECUTE → OBSERVE → VERIFY → DIAGNOSE → REPAIR → RE-VERIFY → PACKAGE → DELIVER
```
Augmented with safety hooks:
```
[STAGE EXECUTION] → [RISK CHECK] ──(Risk/Boundary Detected)──→ [WAITING_FOR_HUMAN_APPROVAL]
                                                │
                                    (Approval Granted)
                                                ↓
                                             [RESUME]
```

---

#### 18-COMMERCIAL-A — RAG Knowledge Assistant
• **Target Fiverr Price**: $750–$1,000+
• **Purpose**: Deliver production-quality knowledge assistants over customer-provided documents, repositories, technical material, or organizational knowledge.
• **Expected Capability Surface**:
  - Document ingestion
  - PDF / document parsing
  - Code / document ingestion
  - Chunking strategies
  - Embeddings generation
  - Vector storage (Qdrant / local persistence)
  - Semantic retrieval
  - Top-k retrieval & ranking
  - Similarity thresholds
  - Context construction & window management
  - LLM answer generation
  - Conversational interaction & turn management
  - Source / provenance citations & references
  - Persistent knowledge stores
  - Retrieval evaluation & precision metrics
  - Answer verification & hallucination guardrails
  - Local / private deployment where applicable
• **Potential Customer Deliverables**:
  - Company knowledge assistant
  - Documentation assistant
  - PDF knowledge assistant
  - Technical knowledge assistant
  - Research assistant
  - Codebase knowledge assistant
  - Internal knowledge chatbot
• **Status**: COMPLETE & FULLY CERTIFIED.
• **Cross-Cutting Extraction**: The Shared Customer Delivery & Deployment Platform (`autoforge_power_engines.delivery`) has been cleanly extracted as a universal AutoForge capability. All future commercial Power Engines compose this platform.

---

#### Shared Customer Delivery & Deployment Platform (Universal Cross-Cutting Capability)
• **Architectural Role**: "Build customer delivery and deployment once. Every Power Engine composes it."
• **Decoupled Architecture**:
  - Power Engines own the workload-specific logic (e.g. RAG index, Agent tool runtime, Automation scheduler, Migration AST).
  - The shared platform owns the delivery/deployment mechanics (`CustomerDeploymentSpec`, `ServiceDefinition`, container orchestration, persistent volumes, launchers, management CLI, health verification, and boundary sanitization).
• **Universal Capabilities Provided to All Power Engines**:
  - `Deploy.command` (macOS one-click desktop launcher)
  - `deploy.sh` (Linux/macOS POSIX one-command fallback with auto-detection & zero-data-loss local fallback)
  - `Deploy.bat` (Windows one-click launcher)
  - `manage.sh` (lifecycle management CLI: `start`, `stop`, `restart`, `status`, `logs`)
  - `docker-compose.yml` (multi-service topology, private bridge networking, localhost-only public bindings)
  - `Dockerfile` (non-root `appuser:appuser` container security)
  - `data/` (strict persistent volume segregation outside containers surviving updates)
  - `scripts/health_check.py` (composable diagnostic health check framework)
  - `README.md` (standardized 15-section customer guide)
  - `DELIVERY_REPORT.md` (executive delivery scorecard & verification evidence)
  - `ProprietaryBoundarySanitizer` (enforces 0 AutoForge internal code leakage across export boundary)
• **Consumed By**:
  - 18-COMMERCIAL-A: RAG Knowledge Power Engine (Certified)
  - 18-COMMERCIAL-B: Custom AI Agent Power Engine (Certified)
  - 18-COMMERCIAL-C: AI Automation Power Engine (Frozen)
  - 18-COMMERCIAL-D: Code Migration / Refactoring Power Engine (Complete / Frozen)
  - 18-G: Legacy Modernization Engine where applicable
  - All future commercial Power Engines

---

#### 18-COMMERCIAL-B — Custom AI Agent
• **Target Fiverr Price**: $1,000+
• **Status**: COMPLETE & CERTIFIED
• **Purpose**: Deliver custom goal-oriented AI agents using AutoForge's existing agent / workforce architecture.
• **Expected Capability Surface**:
  - Goal interpretation & intent analysis
  - Task decomposition & DAG creation
  - Strategic planning
  - Specialized AI workers (from the 23-worker workforce)
  - Worker-specific model requirements
  - Dynamic model routing & policy enforcement
  - Capacity-aware allocation & slot reservation
  - Tool calling & external execution
  - Working & project memory
  - RAG / knowledge retrieval integration
  - Multi-step autonomous execution
  - State tracking & transition logging
  - Failure detection & classification
  - Retries & automated recovery
  - Verification & quality gate evaluation
  - Result synthesis & summary generation
  - Artifact generation & cataloging
  - Structured outputs & JSON schema enforcement
  - Provider abstraction (Ollama, cloud fallback)
  - Local-first execution
• **Potential Customer Deliverables**:
  - Research agent
  - Coding agent
  - Documentation agent
  - Customer-support agent
  - Analysis agent
  - Repository agent
  - Domain-specific autonomous workflow agent

---

#### 18-COMMERCIAL-C — AI Automation
• **Target Fiverr Price**: $750–$1,000+
• **Status**: Implementation complete; final forensic freeze gate passed. C FROZEN
• **Purpose**: Deliver complete AI-powered business workflows combining AI reasoning with deterministic execution.
• **Canonical Execution Pattern**:
  `INPUT → AI REASONING → DETERMINISTIC PROCESSING → TOOL/API EXECUTION → VALIDATION → OUTPUT`
• **Expected Capability Surface**:
  - Workflow orchestration & DAG sequencing
  - AI decision points & branching logic
  - Document processing & parsing
  - Text & data classification
  - Structured information extraction
  - Deterministic data transformation
  - API integrations & webhooks
  - Tool execution & sandboxed scripts
  - Data processing pipelines
  - Conditional workflows & fallbacks
  - Parallel tasks & concurrency control
  - Deterministic validation & schema checks
  - Retry & error handling policies
  - Structured outputs & data serialization
  - Report & document generation
• **Potential Customer Deliverables**:
  - Document-processing automation
  - Lead-processing automation
  - Resume-processing automation
  - Research automation
  - Email classification & triage
  - Data extraction & enrichment
  - Report generation pipelines
  - Data migration workflows
  - Business-process automation
• **Execution Boundary**: Do NOT implement yet.

---

#### 18-COMMERCIAL-D — Code Migration / Refactoring
• **Target Fiverr Price**: $1,000+
• **Status**: COMPLETE / FROZEN — FINAL FORENSIC FREEZE GATE PASSED
• **Purpose**: Generalize AutoForge's deterministic transformation and verification capabilities beyond the already-established legacy modernization service.
• **Critical Boundary Distinction**:
  This is NOT a replacement for 18-G. 18-G remains the specialized enterprise Legacy Code Modernization capability (COBOL/JCL/VSAM/CICS → modern targets). 18-COMMERCIAL-D is the broader code transformation, refactoring, and framework migration service.
• **Expected Capability Surface**:
  - **Language migration**:
    * Validated language-to-language transformations
    * Syntax and semantic migration
    * Compatibility transformation
  - **Framework migration**:
    * Framework upgrades (e.g., major version leaps)
    * Dependency migrations
    * API migrations & deprecation remediation
    * Architectural migrations
  - **Refactoring**:
    * Monolith → modular structures
    * Structural refactoring & package decoupling
    * Duplicate-code reduction & deduplication
    * API restructuring & contract modernization
    * Repository restructuring
    * Modernization of established code patterns
  - **Engineering generation**:
    * Test suite generation & expansion
    * Documentation & API specification generation
    * API generation & scaffold synthesis
    * Configuration generation (CI/CD, Docker, IaC)
  - **Verification**:
    * Build verification & compilation checks
    * Test execution & coverage assessment
    * Regression detection & test comparison
    * Behavioral comparison & parity checking
    * Targeted repair loops on test failure
    * Final artifact validation & manifest generation
• **CRITICAL INVARIANT**:
  Do NOT claim arbitrary language/framework pairs are supported until they are empirically validated. The service must expose only transformation pairs that AutoForge can actually execute, compile, and verify.
• **Implementation State**: Engine implemented with 11-stage canonical lifecycle, bounded repair loop, AST-subordinated LLM integration, sandboxed execution runner, standalone customer deployment package builder, and comprehensive 17-test validation suite. Zero proprietary leaks across export boundary. Awaiting forensic freeze gate.

---

### Remaining Autonomous Engineering Hardening & Certification Subphases:

### 18-I — Generated Workload Containerization + Sandboxing
• Confined container/sandbox execution for generated workloads, tests, and target artifacts.
• Strict workspace isolation, filesystem confinement, and resource limits.

### 18-J — Durable Execution + Resume + Idempotency
• Process-restart survival for orchestrator workflows.
• Idempotent replay, state checkpoints, crash recovery, and resume boundaries.

### 18-K — Runtime + Packaging + Delivery
• Target delivery pipelines, production artifact packaging, fat JAR/bundle synthesis, and staging verification.

### 18-L — Full Autonomous Engineering Certification
• End-to-end certification of greenfield and legacy autonomous engineering across the complete platform.
• Formal sign-off and gate closure prior to Phase 19.

---

### Canonical Phase Ordering & Boundaries:
```
18-G           — Legacy Modernization (COMPLETE — Existing Commercial Offering)
18-H           — AI Runtime / Heavy Optimization (FROZEN pending M6 arrival)
18-COMMERCIAL  — Commercial AI Engineering Services (NEW PLANNED PHASE)
  ├── 18-COMMERCIAL-A — RAG Knowledge Assistant ($750–$1,000+)
  ├── 18-COMMERCIAL-B — Custom AI Agent ($1,000+)
  ├── 18-COMMERCIAL-C — AI Automation ($750–$1,000+)
  └── 18-COMMERCIAL-D — Code Migration / Refactoring ($1,000+)
18-I           — Generated Workload Containerization + Sandboxing
18-J           — Durable Execution + Resume + Idempotency
18-K           — Runtime + Packaging + Delivery
18-L           — Full Autonomous Engineering Certification
      ↓
PHASE 19       — Continuous Learning & Self-Improvement (STRICTLY ONLY AFTER 18-L)
```

------------------------------------------------------------

============================================================
PHASE 19 — Continuous Learning & Self-Improvement
============================================================

Goal:
Establish the continuous learning, reflection, pattern discovery, and safe self-improvement substrate of AutoForge AI OS.

Core Subsystems:

• Learning Engine (Execution analysis, telemetry mining, pattern synthesis)
• Reflection Engine (Post-execution analysis of successes, failures, and bottlenecks)
• Pattern Discovery (Recurring solution template extraction, anti-pattern detection)
• Failure Learning (Root-cause classification, avoidance heuristic generation)
• Knowledge Promotion (Promoting proven empirical solutions to platform knowledge)
• Workflow Optimization (DAG scheduling optimization, parallelization refinement)
• Routing Optimization (Empirical model selection heuristics, cost/latency tuning)
• Worker Optimization (Worker prompt refinement, few-shot exemplar curation)
• Engineering Loop Optimization (Repair strategy tuning, test generation heuristics)
• Platform Self-Improvement (Safe, governed adaptation of platform heuristics)
• Benchmarking & Experimentation (Automated evaluation suites, A/B testing harnesses)
• Improvement Provenance, Versioning & Instant Rollback

MANDATORY GATED SELF-IMPROVEMENT SAFETY PIPELINE:

```
Candidate Improvement
  ↓
Evaluation (Static verification, semantic validation)
  ↓
Benchmark (Empirical measurement against benchmark suite)
  ↓
Regression Suite (Verification of zero regression on historical workloads)
  ↓
Accept / Reject Gate (Deterministic policy check + HITL if required)
  ↓
Version Assignment (Immutable semantic versioning of optimized artifact)
  ↓
Rollback Capability Verified (Atomic rollback handle created)
  ↓
Activate (Live deployment to runtime)
```

Invariants:
- NO silent self-modification under any circumstances.
- Memory ≠ Learning (ADR-005): Memory stores execution state and historical artifacts; Learning synthesizes generalized behavioral improvements.
- Context Engineering remains first-class (ADR-003) and composes Knowledge/Memory capabilities without duplication.
- The Product Experience exposes the Self-Improvement Center (as specified in Phase 16).

Outcome:
✓ Self-Learning Platform Frozen

------------------------------------------------------------

============================================================
PHASE 20 — Modernization Service MVP
============================================================

Goal:
Package the AutoForge AI OS as our internal engine to deliver the commercial Legacy Modernization Service.

Business Strategy Invariant:
Our initial business model is: WE SELL LEGACY MODERNIZATION AS A SERVICE. We are NOT initially selling AutoForge software licenses to external customers. AutoForge is our internal autonomous engineering engine.

Commercial Modernization Pipeline:

```
Customer Legacy System Intake
  ↓
Discovery & Inventory (Repository scan, language/framework census, LOC metrics)
  ↓
Archaeology & Technology Identification (Dialect analysis, third-party libraries)
  ↓
Architecture Reconstruction (Component graph, data flows, integration map)
  ↓
Business Rules Extraction (Rule catalog, boundary invariants, edge cases)
  ↓
Dependency & Data Analysis (Database schemas, stored procedures, RPCs)
  ↓
Modernization Strategy & Target Architecture (Strangler fig / clean rebuild)
  ↓
HITL Customer Architecture Review & Sign-Off
  ↓
Migration Planning (Work breakdown, incremental cutover phases, risk matrix)
  ↓
Migration Implementation (Code translation, modernization, test harness)
  ↓
Testing & Equivalence Validation (Parity tests, integration tests, fuzzing)
  ↓
Documentation & Deliverables (Target code, architecture specs, runbooks)
  ↓
Deployment & Cutover Support (Rollout assistance, rollback plans)
```

Critical Acceptance Test:
A genuinely unfamiliar, proprietary enterprise legacy codebase (e.g., COBOL, legacy Java EE, Delphi, C/C++, legacy .NET) must travel from raw codebase intake to fully validated modern target deliverables with explicit uncertainty representation and zero hallucinated requirements.

Outcome:
✓ Commercial Modernization Service MVP

------------------------------------------------------------

============================================================
PHASE 21 — Desktop Application & Distribution
============================================================

Goal:
Package and distribute the complete AutoForge AI OS as a standalone, local-first desktop application.

Architectural Distinction:
Phase 16 designed and built the Product Experience and UI components. Phase 21 packages, integrates, and distributes them as the official AutoForge Desktop Application.

Capabilities & Components:

• Desktop Application Shell (Native container, window management, menu integration)
• Embedded Local Backend / Runtime (Self-contained Python runtime, process isolation)
• Local Workers & Execution Engine (In-process and subprocess worker management)
• Local Inference Engine Integration (Bundled/connected Ollama, llama.cpp runtimes)
• Local Persistence & Storage (Embedded SQLite/DuckDB, filesystem workspace)
• Local Knowledge & Memory Engines (Embedded vector search, document indexing)
• Configuration & Secrets Management (Encrypted OS keychain integration)
• Process Management & Background Services (Supervision tree, daemon management)
• IPC & Event Bridge (High-performance inter-process communication)
• Workspace & Multi-Project Management (Local project directories, isolation)
• Offline-First Operation (Full functionality without internet access)
• Optional Cloud Connectivity (On-demand synchronization and cloud model access)
• Application Lifecycle & Crash Recovery (Auto-save, crash recovery, state restoration)
• Auto-Update & Version Migration (Database schema migrations, binary updates)
• Cross-Platform Packaging & Distribution (macOS DMG/pkg, Windows MSI/exe, Linux AppImage/deb)
• Code Signing & Notarization (Apple Developer notarization, Windows Authenticode)

Hardware Topology Support:

```
AutoForge Desktop
  ├── Node 1: Apple Silicon (M1 / M2 / M3 / M4)
  ├── Node 2: HP Workstation / Linux / Windows x86_64
  └── Node 3: Future Node (e.g., Mac Mini M6)
```

Invariant:
Worker implementations remain completely hardware-agnostic; node topologies are managed by the runtime and capability registry.

Outcome:
✓ AutoForge Desktop Frozen

------------------------------------------------------------

============================================================
PHASE 22 — Developer / Extension Platform
============================================================

Goal:
Open AutoForge AI OS to third-party developers, tool creators, and custom extensions.

Capabilities:

• Plugin SDK (Lifecycle hooks, configuration schemas, UI extension slots)
• Connector SDK (Standard interfaces for custom database, VCS, cloud, and tool connectors)
• Worker SDK (SDK for defining custom domain workers, capabilities, and prompt strategies)
• Extension APIs (Stable public APIs for kernel, runtime, and workflow interaction)
• Model / Provider Extension APIs (Pluggable inference providers and local adapters)
• Marketplace & Registry Foundation (Extension discovery, packaging, and dependency resolution)
• Developer Documentation & Scaffolding Tooling (CLI templates, typing, testing harnesses)
• Extension Lifecycle Management (Sandboxed installation, verification, activation, updates)
• Extension Security & Permissions (Capability-based permissions, sandbox constraints)

Outcome:
✓ Extensible Platform

------------------------------------------------------------

============================================================
PHASE 23 — Enterprise Platform
============================================================

Goal:
Deliver multi-tenant, secure, compliant, and governed enterprise deployments of AutoForge.

Capabilities:

• Multi-User & Organization Management (Tenant isolation, team workspaces)
• Enterprise Identity & SSO (SAML 2.0, OIDC, Active Directory / Okta integration)
• Enterprise Role-Based Access Control (Granular project, workspace, and model permissions)
• Immutable Enterprise Audit Logs (SIEM export, compliance reporting, forensic logs)
• Regulatory Compliance Frameworks (SOC2, HIPAA, GDPR readiness features)
• Enterprise Governance & Policy Engine (Enforceable architectural and security policies)
• Enterprise Connectors (Jira, ServiceNow, GitLab Enterprise, Azure DevOps, Confluence)
• Enterprise Deployment Controls (VPC deployment, private cloud, air-gapped installations)
• Centralized Administrative Controls (Cost quotas, model access whitelists, usage limits)

Outcome:
✓ Enterprise Edition

------------------------------------------------------------

============================================================
PHASE 24 — Distributed AI Operating System
============================================================

Goal:
Scale AutoForge AI OS across distributed clusters, hybrid edge-cloud nodes, and multi-machine environments.

Capabilities:

• Distributed Workers (Workers executing across heterogeneous physical/virtual machines)
• Worker Clusters & Swarm Execution (Dynamic worker scaling, elastic job scheduling)
• Distributed Workflow Orchestration (Cross-node DAG execution and state synchronization)
• Hybrid Edge-Cloud Execution (Local reasoning with elastic cloud compute offloading)
• Distributed Multi-Node Inference (Coordinated inference across local hardware nodes)
• Global Resource Scheduling (Network-aware task placement, GPU memory-aware scheduling)
• Remote Worker Execution & Agent Meshes (Peer-to-peer event mesh, secure node peering)
• Edge / Remote Worker Isolation (Confined remote execution environments)
• Robotics & Hardware Automation (Targeted physical system integration where strategically justified)

Outcome:
✓ Distributed AI OS

------------------------------------------------------------

============================================================
PHASE 25 — Production Release
============================================================

Goal:
Harden, benchmark, validate, and officially release AutoForge AI OS v1.0.

Activities:

• Comprehensive Performance Optimization (Latency reduction, memory tuning, event bus optimization)
• Deep Security Hardening & Penetration Testing (Third-party audit, vulnerability remediation)
• Rigorous Benchmarking (Standardized autonomous coding and modernization benchmark suites)
• Stress Testing & Chaos Engineering (Network partitions, worker failures, crash recovery validation)
• Reliability & Endurance Testing (Multi-day continuous autonomous execution runs)
• Comprehensive User & Developer Documentation (Architecture manuals, operations runbooks)
• Operations & Troubleshooting Guides (Runbooks, incident response playbooks)
• Release Candidate (RC) Verification & Public Sign-Off
• Production Release & Distribution

Outcome:
🚀 AutoForge AI OS v1.0

------------------------------------------------------------

============================================================
ORIGINAL ROADMAP RECONCILIATION & MAPPING
============================================================

The canonical 25-phase roadmap directly reconciles and expands the original 22-phase roadmap without losing any capability, renumbering historical phases 1–14, or creating duplicate phases:

| Original Phase | Original Name | Canonical Phase | Canonical Name | Disposition & Reconciliation Notes |
|---|---|---|---|---|
| Phase 1–14 | Historical Phases 1–14 | Phase 1–14 | Historical Phases 1–14 | Retained exactly with frozen status |
| Phase 15 | Security Platform | Phase 15 | Security & Governance Platform | Expanded to cover governance, HITL gates, sandboxing, secrets |
| Phase 16 | MVP Integration | Phase 16 | AutoForge Product Experience | Top-level UI & human interface; MVP capabilities partitioned logically |
| — | — | Phase 17 | AI Runtime & Real Model Integration | Connects Phase 13 policies/allocations to real inference engines |
| Phase 17 | Autonomous Engineering | Phase 18 | Autonomous Engineering & Modernization | Integrates workforce with full OS; Subphases: 18-A..18-F (Foundation), 18-G (Modernization - Certified), 18-H (Optimization - Frozen), 18-COMMERCIAL (A-D Commercial Services), 18-I..18-L (Hardening/Cert) |
| Phase 18 | Continuous Learning | Phase 19 | Continuous Learning & Self-Improvement | Self-learning engine, reflection, strictly gated safety pipeline (Only after 18-L) |
| — | — | Phase 20 | Modernization Service MVP | Commercial service MVP; initial commercial go-to-market engine |
| — | — | Phase 21 | Desktop Application & Distribution | Local-first desktop packaging, distribution, multi-node desktop |
| Phase 19 | Developer Platform | Phase 22 | Developer / Extension Platform | Plugin, connector, worker SDKs, marketplace foundation |
| Phase 20 | Enterprise Platform | Phase 23 | Enterprise Platform | Multi-user, SSO, enterprise governance, compliance, audit |
| Phase 21 | Distributed AI OS | Phase 24 | Distributed AI Operating System | Distributed clusters, swarm execution, edge/cloud scaling |
| Phase 22 | Production Release | Phase 25 | Production Release | Performance, hardening, stress testing, v1.0 release |

------------------------------------------------------------

============================================================
DEPENDENCY & IMPLEMENTATION ORDER
============================================================

The canonical implementation dependency chain flows as follows:

```
Phases 1–13: Foundation, Kernel, Runtime, Engines & AI Workforce (Complete)
      ↓
Phase 14: Observability Platform & Dashboards (Complete)
      ↓
Phase 15: Security & Governance Platform (Authentication, RBAC, Sandboxing, HITL Gates)
      ↓
Phase 16: AutoForge Product Experience (UI, Engineering Experience, Visualizers)
      ↓
Phase 17: Real AI Runtime (Live Local/Cloud Inference Adapters, Hardware Topology)
      ↓
Phase 18: Autonomous Engineering & Modernization
  ├── 18-A..18-F: Foundation, Greenfield, RAG, Repair Loop (Complete)
  ├── 18-G: Legacy Modernization (Complete — Existing Commercial Offering #4)
  ├── 18-H: AI Runtime / Heavy Optimization / Multi-Node Readiness (Frozen pending M6)
  ├── 18-COMMERCIAL: Commercial AI Engineering Services (New Planned Phase)
  │     ├── 18-COMMERCIAL-A: RAG Knowledge Assistant ($750–$1,000+)
  │     ├── 18-COMMERCIAL-B: Custom AI Agent ($1,000+)
  │     ├── 18-COMMERCIAL-C: AI Automation ($750–$1,000+)
  │     └── 18-COMMERCIAL-D: Code Migration / Refactoring ($1,000+)
  ├── 18-I: Generated Workload Containerization + Sandboxing
  ├── 18-J: Durable Execution + Resume + Idempotency
  ├── 18-K: Runtime + Packaging + Delivery
  └── 18-L: Full Autonomous Engineering Certification
      ↓
Phase 19: Continuous Learning & Self-Improvement (Gated Safety Learning Pipeline — Strictly Only After 18-L)
      ↓
Phase 20: Modernization Service MVP (Enterprise Commercial Packaging)
      ↓
Phase 21: Desktop Application & Distribution (Local-First Desktop Packaging)
      ↓
Phase 22: Developer / Extension Platform (SDKs, Extension APIs, Marketplace)
      ↓
Phase 23: Enterprise Platform (SSO, Multi-Tenant, Compliance, SIEM)
      ↓
Phase 24: Distributed AI Operating System (Cluster Scaling, Swarm Execution)
      ↓
Phase 25: Production Release (Hardening, Verification, v1.0 Release)
```

------------------------------------------------------------

============================================================
BUSINESS ARCHITECTURE & GO-TO-MARKET ALIGNMENT
============================================================

AutoForge AI OS distinguishes strictly between the internal operating platform and the commercial market offerings:

1. **AutoForge AI OS (Internal Technology Platform)**:
   The comprehensive autonomous software engineering operating system, kernel, workforce, and execution runtime developed across Phases 1–25.

2. **Commercial AI Engineering Services Portfolio (Sellable Go-To-Market Offerings)**:
   AutoForge's already-built AI engineering infrastructure powers five concrete, independently sellable engineering services delivered on Fiverr, as subcontracting work, and for enterprise engagements:

   1. **RAG Knowledge Assistant** ($750–$1,000+) — Subphase 18-COMMERCIAL-A
      - Production knowledge assistants over customer documents, codebases, technical material, or internal knowledge.
   2. **Custom AI Agent** ($1,000+) — Subphase 18-COMMERCIAL-B
      - Goal-oriented custom AI agents composing specialized workers, tools, and local-first execution.
   3. **AI Automation** ($750–$1,000+) — Subphase 18-COMMERCIAL-C
      - Complete business workflows combining AI reasoning with deterministic processing and tool APIs.
   4. **Legacy Code Modernization** ($1,000+) — Existing Subphase 18-G (Complete & Certified)
      - Specialized enterprise legacy modernization (COBOL/JCL/VSAM/CICS → Java/Spring/cloud targets).
   5. **Code Migration / Refactoring** ($1,000+) — Subphase 18-COMMERCIAL-D
      - Broad code transformation, language/framework upgrades, and verified structural refactoring.

   **AutoForge Primitives Composition Invariant**:
   These are commercial offerings, not five separate software architectures. They all compose existing AutoForge primitives:
   • Kernel (`packages/kernel`)
   • Strategic Engine & Orchestration (`packages/orchestration`)
   • Workflow Engine & DAG Scheduler (`packages/workflows`)
   • Execution Engine & Engineering Loop (`packages/execution`)
   • Review Engine & Quality Gates (`packages/review`)
   • Artifact Manager, Lineage & Provenance (`packages/artifacts`)
   • Runtime State Manager & Checkpoints (`packages/runtime`)
   • Event Bus & Platform (`packages/event_platform`, `packages/events`)
   • Knowledge Engine & Retrieval (`packages/knowledge_platform`)
   • Memory Engine (`packages/memory`)
   • Learning Engine boundary (`packages/learning`, strictly gated)
   • Model Router & Policies (`packages/ai_infrastructure`)
   • Model Allocator & Capacity Manager (`packages/workforce`)
   • 23-Worker Specialized AI Workforce (`packages/workforce`)
   • Local RAG & Vector Storage (Qdrant)
   • Tool execution & external connectors (`packages/connectors`, `packages/tools`)
   • Deterministic transformation & synthesis
   • Verification, test execution & regression checking
   • Repair loops & root-cause diagnosis
   • Provenance, evidence logging & audit trail

Go-To-Market Value Flow:

```
Customer Commercial Request (RAG Assistant / Custom Agent / Automation / Modernization / Migration)
  ↓
AutoForge Commercial Service Portfolio (Offerings 1–5)
  ↓
AutoForge AI Workforce (23 Specialized Workers) & Platform Primitives
  ↓
Orchestrated Pipeline (Ingestion / Reasoning / Deterministic Transformation / Synthesis)
  ↓
Verification & Hardening (Testing, Equivalence, Evaluation, Security, Quality Gates)
  ↓
Customer Deliverables (Verified Artifacts, Code, Schemas, Test Suites, Runbooks, Provenance)
```

------------------------------------------------------------

============================================================
ARCHITECTURAL & GOVERNANCE PRINCIPLES
============================================================

All future development across Phases 15–25 must strictly adhere to the following principles:

1. **AutoForge is the Primary Architecture**: External frameworks do not become architectural authorities.
2. **External Framework Containment**:
   - Temporal remains an OPTIONAL durable orchestration adapter; `WorkflowEngine` remains the AutoForge domain authority.
   - LangGraph, LangChain, and CrewAI remain excluded from the live path.
   - Langfuse remains an optional observability export adapter; AutoForge Observability remains the system of record.
3. **AI Non-Authority Invariant**: AI models do not own governance, policy, state authority, HITL gates, determinism, or engineering meaning.
4. **UI Non-Authority Invariant**: The UI is strictly a presentation and control layer; authoritative state resides exclusively in the platform runtime and services.
5. **Worker Model Agnosticism**: Workers declare capability and model requirements; they NEVER hardcode concrete model IDs.
6. **Centralized Model Allocation**: Model selection and capacity management remain centralized in `ModelAllocator` and `ModelRouterService`.
7. **First-Class Legacy Modernization**: Legacy modernization is a co-equal, first-class capability supported by 9 dedicated workers and specialized pipelines.
8. **Preserved Specialized Workforce**: The 23 specialized workers (14 Greenfield + 9 Legacy) remain explicit and must not be reduced to generic agents.
9. **Strict Epistemic Separation for Legacy Systems**: Clear separation of FACT, INFERENCE, HYPOTHESIS, and UNKNOWN with explicit gap identification.
10. **Hardware-Agnostic Worker Design**: Adding new local or remote hardware nodes requires configuration only; worker implementations remain untouched.
11. **Context Engineering as a First-Class Capability**: Composes Knowledge and Memory without duplicating them (ADR-003).
12. **Memory ≠ Learning (ADR-005)**: Memory preserves state and historical context; Learning synthesizes generalized adaptations.
13. **Strictly Gated Self-Improvement Pipeline**: Candidate → Evaluation → Benchmark → Regression → Accept/Reject → Version → Rollback → Activate. No silent self-modification.

------------------------------------------------------------

============================================================
ADDENDUM — PHASE 0 RECORD (2026-08-26)
============================================================

Foundation Stabilization & Integration (Phase 0 of the foundation
programme recorded in docs/PHASE_0_FOUNDATION_STABILIZATION_REPORT.md)
was executed between the frozen subsystem phases and Autonomous Worker
work. This addendum records governance constraints only.

Phase 0 established:

• Canonical event vocabulary (`autoforge_events`) with the Event
  Platform bound to transport-only responsibilities (ADR-001).
• The foundational composition root wiring Kernel, Runtime, canonical
  events and transport in a real process (ADR-002).
• Restored green test substrate and cross-package checkpoint round-trip.
• Contracts (architecture only, no implementation): Context Engineering
  (ADR-003), Engineering Experience read model (ADR-004), Memory ≠
  Learning boundary (ADR-005).

Standing constraints for ALL future phases:

• Context Engineering remains a first-class capability; it composes
  Knowledge/Memory capabilities and never duplicates them (ADR-003).
• Engineering Experience stays a provenance-aware, correlation-aware
  READ model composed from authoritative sources (ADR-004).
• Any benchmark harness and self-improvement work MUST follow the gated
  pipeline: candidate → evaluation → benchmark → regression →
  accept/reject → version → rollback.