# AutoForge AI OS Architecture

## 1. Purpose

This document is the canonical architectural blueprint of AutoForge AI OS. It defines the platform's major subsystems, their responsibilities, boundaries, and interactions at the highest level of abstraction.

Every subsystem architecture document derives from this specification. Subsystem documents may provide additional detail within the boundaries established here, but they must remain consistent with the architectural principles, relationships, and responsibilities defined in this document.

When a subsystem document conflicts with this document, this document is authoritative.

This specification does not describe implementation details, programming languages, frameworks, APIs, databases, deployment architectures, or folder structures.

---

## 2. Platform Overview

AutoForge AI OS is an AI Operating System for autonomous software engineering. It transforms a software idea into a production-quality application through long-running, event-driven, state-driven, multi-agent engineering workflows.

The platform is NOT:

- a chatbot
- an IDE
- a workflow automation script
- a coding assistant

It is an operating platform.

---

## 3. System Architecture

AutoForge AI OS is organised around its Kernel, Platform Engines, Shared Platform Services, and Artifact Management pipeline. The Kernel is the single entry point and executive orchestrator of the operating system. It receives all requests, determines how each request should be executed, which Platform Engines should participate, and when Shared Platform Services should be invoked. Engines and services are invoked as needed and return their results to the Kernel for coordination.

The System Architecture forms a sequential execution pipeline that represents the canonical lifecycle of a request through the platform. The Kernel dynamically composes execution paths — not every request traverses every stage. The following diagram illustrates the normal orchestration flow:

```
User

↓

Kernel

↓

Strategic Engine (optional)

↓

Workflow Engine

↓

Scheduler

↓

Execution Engine

↓

Review Engine

↓

Artifact Manager

↓

Finished Product
```

The Scheduler is an internal orchestration component of the Workflow/Execution pipeline. It is not a top-level platform engine. The Scheduler exists to translate executable workflows into scheduled execution by dispatching work from the Workflow Engine to the AI Workforce through the Execution Engine.

The Kernel also orchestrates the participation of Shared Platform Services — including the Runtime State Manager, Canonical Event Model, Event Bus, Knowledge Engine, Memory Engine, Learning Engine, Capability Registry, Model Router, Execution Continuity Manager, Connector Layer, Observability, Dashboard, and Security — throughout the execution lifecycle when appropriate.

### Kernel

The Kernel is the executive orchestration layer of AutoForge AI OS. It is the single entry point for all requests and is responsible for project intake, execution planning, Platform Engine orchestration, Shared Platform Service orchestration, and lifecycle coordination.

**Project Intake**

- receiving requests
- validating requests
- normalising requests
- assigning execution identifiers
- initialising runtime state
- publishing execution-started events

**Execution Planning**

- determining whether the Strategic Engine is required
- determining whether research is required
- determining whether existing implementation blueprints can be reused

**Platform Engine Orchestration**

- invoking the Strategic Engine when strategic reasoning is required
- invoking the Workflow Engine to transform plans into executable workflows
- invoking the Execution Engine to perform implementation work
- invoking the Review Engine to evaluate artifacts against quality criteria

**Shared Platform Service Orchestration**

The Kernel coordinates the participation of all Shared Platform Services throughout execution when appropriate. Shared Platform Services remain independently reusable — the Kernel determines when they participate in a project's lifecycle, but each service remains solely responsible for its own internal behaviour.

- invoking the Knowledge Engine whenever engineering knowledge is required
- invoking the Memory Engine to retrieve execution context
- invoking the Memory Engine to persist project knowledge
- invoking the Learning Engine after significant execution milestones or project completion
- invoking the Knowledge Engine to promote validated learning into reusable organisational knowledge
- invoking the Runtime State Manager to initialise, read, and transition canonical state
- invoking the Event Bus to publish lifecycle events
- invoking the Capability Registry whenever AI infrastructure discovery or capability metadata is required
- invoking the Model Router when model selection is required for engine operations
- invoking the Execution Continuity Manager whenever execution resilience or provider failover is required
- invoking the Connector Layer when external system access is required
- invoking Observability to capture telemetry during execution
- invoking the Dashboard to expose project state to human operators
- invoking Security to enforce access control and policy gates

**Lifecycle Coordination**

- coordinating execution order
- coordinating engine handoffs
- coordinating shared platform services
- monitoring project progress
- coordinating retries
- coordinating recovery
- coordinating cancellation
- coordinating completion

The Kernel never performs implementation, research, memory management, knowledge management, learning, or review. Its responsibility is orchestration.

The Kernel owns orchestration.

Every other subsystem owns execution.

Orchestration and execution remain intentionally separated throughout AutoForge AI OS.

### Strategic Engine

The Strategic Engine owns all strategic reasoning before implementation begins. It receives strategic work delegated by the Kernel and is invoked only when strategic reasoning is required. The Strategic Engine is responsible for requirement analysis, research, technology evaluation, architecture design, trade-off analysis, implementation planning, and decision making.

The Strategic Engine coordinates the Research Engineer, Software Architect, and Product Planner during the planning phase. It produces an implementation-ready package containing a Research Brief, Architecture Blueprint, Architecture Decisions, Implementation Blueprint, and Acceptance Criteria. This package is returned to the Kernel.

The Strategic Engine never performs implementation. Its responsibility is strategic reasoning and planning.

### Software Architect, Research Engineer, Product Planner

These three roles operate under the coordination of the Strategic Engine during the planning phase.

- **Software Architect** — Designs the system architecture, defines component boundaries, selects architectural patterns, and produces the structural blueprint that guides all subsequent implementation.
- **Research Engineer** — Belongs exclusively to the Strategic Engine. It performs technical research, documentation research, framework research, best practice research, technology comparisons, and engineering recommendations. The Research Engineer is not part of the Execution Engine. The Execution Engine consumes research; it does not generate strategic research.
- **Product Planner** — Defines product requirements, user stories, acceptance criteria, and prioritisation. Ensures that the engineering output aligns with the intended product outcomes.

### Workflow Engine

The Workflow Engine receives the architectural blueprint, research findings, and product requirements, and transforms them into executable workflows. It manages orchestration, dependency resolution, approvals, retries, branching, lifecycle management, and recovery. The Workflow Engine never performs implementation.

### Scheduler

The Scheduler receives executable units of work from the Workflow Engine and dispatches them to the AI Workforce based on availability, capability, and priority. It manages the queue of pending work and ensures that workers are utilised efficiently.

### AI Workforce

The AI Workforce represents the collection of specialised engineering workers responsible for implementation activities. Workers may be added, removed, or specialised without changing the platform architecture.

Every engineering worker follows the Execution Engine Lifecycle. The Execution Engine is responsible for orchestrating worker execution, while each worker is responsible for completing its own iterative implementation lifecycle.

#### Worker Allocation and Model Policy Hierarchy

Workers express their LLM needs through a deterministic model policy and allocation hierarchy (ADR-014):
`Worker (WorkerModelProfile) + Task (TaskModelRequirements) → Effective Model Requirements → ModelAllocator → ModelRouterService → Provider → Deployment → Inference Node → Actual Model`

1. **Worker Model Policy / Profile**: The worker declares what kind of model it needs (required LLM capabilities, minimum context window, reasoning tier, structured output, local-only constraints) rather than a concrete model identity.
2. **Task Model Requirements**: Tasks can refine or strengthen model requirements (e.g. demanding higher context or specialized tool use for a specific step) without silently weakening mandatory worker constraints.
3. **Effective Model Requirements**: Deterministically resolved requirements combining worker defaults and task overrides.
4. **Model Allocation**: Checks capacity and concurrency limits via `ModelCapacityManager` under `ModelAllocator`.
5. **Model Router**: `ModelRouterService` deterministically filters, ranks, and routes to appropriate providers.
6. **Provider**: An abstract execution service hosting models (e.g., `local-m1`, `local-hp`).
7. **Deployment**: Specific deployment mode (e.g., local, cloud).
8. **Inference Node**: The hardware substrate running the model (e.g., M1, HP, or simulated Mac mini).
9. **Model**: The concrete AI model (e.g., Qwen2.5-Coder 7B, Ornith 9B) executing the reasoning loop.

#### Current Local Topologies

The local runtime environment is designed around local-first inference nodes:
- **local-m1**: Apple Mac M1 local Node (running code/reasoning/text capabilities).
- **local-hp**: HP local Node (running code/text capabilities).
- **local-mac-mini-m6**: Future Mac mini M6 local Node (simulated for horizontal scaling).

#### Legacy Evidence-Driven Architecture

Legacy modernization activities are supported by an evidence-driven architecture. Discovery and archaeological tasks gather findings into a persistent evidence log, where each finding is classified into one of the following epistemic types:
- **FACT**: Deterministic, verified evidence collected directly from systems or configuration.
- **INFERENCE**: Logically derived evidence backed by facts and architectural rules.
- **HYPOTHESIS**: Probabilistic guess or AI-derived claim requiring verification.
- **UNKNOWN**: Undocumented or legacy technologies requiring archaeological investigation.

### Engineering Workers

The workforce is divided into 14 Greenfield engineering roles and 9 Legacy modernization roles.

#### Greenfield Workers

- **Research Engineer** — Performs technical research, documentation research, framework research, and technology comparisons.
- **Architecture Engineer** — Produces system architectures, defines component boundaries, and designs architectural blueprints.
- **Planning Engineer** — Translates plans into executable work breakdown structures and task lists.
- **UI Designer** — Designs user interfaces and conducts accessibility audits.
- **Backend Engineer** — Implements server-side logic, APIs, and data processing components.
- **Frontend Engineer** — Implements user-facing interfaces and client-side logic.
- **Database Engineer** — Designs and implements data storage schemas, queries, and data migration strategies.
- **ML Engineer** — Designs machine learning inference flows and data pipelines.
- **Infrastructure Engineer** — Implements cloud resources, containers, and computing infrastructure.
- **DevOps Engineer** — Implements deployment pipelines, environment configurations, and operational tooling.
- **QA Engineer** — Implements test suites, executes quality verification, and reports defects.
- **Security Engineer** — Implements security controls, vulnerability assessments, and compliance measures.
- **Performance Engineer** — Implements performance benchmarks, identifies bottlenecks, and optimises system behaviour.
- **Documentation Engineer** — Produces technical documentation, API references, and user guides.

#### Legacy Workers

- **Legacy Systems Research Engineer** — Performs research on legacy infrastructure, systems, and source configurations.
- **Legacy Code Archaeologist** — Reconstructs and understands historical source code bases and extracts logic.
- **Legacy Architecture Analyst** — Reconstructs and maps architecture diagrams and topology models from legacy systems.
- **Legacy Data Engineer** — Analyzes database schema structures, data storage patterns, and designs data migrations from legacy databases.
- **Legacy Integration Engineer** — Maps external system integration APIs, protocols, and data pathways.
- **Business Rules Analyst** — Identifies, extracts, and documents implicit business rules from legacy code.
- **Dependency & Impact Analyst** — Evaluates code dependencies, impact boundaries, and change risks.
- **Modernization Architect** — Designs targeted modernized architectures for target platforms.
- **Migration Engineer** — Executes the automated or semi-automated migration of codebase, data, and configs to modern structures.

### Review Engine

The Review Engine evaluates all artifacts produced by engineering workers against defined quality criteria. It verifies correctness, architectural compliance, test coverage, documentation quality, performance characteristics, security posture, and policy adherence. Artifacts that fail review are returned to the appropriate worker for remediation.

### Artifact Manager

The Artifact Manager is the final stage of the pipeline. It stores, versions, and publishes all approved artifacts. It maintains lineage and traceability from the original idea through every transformation to the finished product.

### Product Experience (Human Interface Layer)

The Product Experience represents the top-level human interface to the AutoForge AI OS.

**Architectural Authority Invariant:**
The UI is strictly a presentation, monitoring, and steering layer. The UI is NOT an authority. Authoritative state resides exclusively in the Runtime State Manager, Kernel, and platform services.

```
UI (Web / Desktop Shell)
  ↓
Engineering Experience / Read Models (ADR-004)
  ↓
Application Services
  ↓
Authoritative Platform Services (Kernel, Runtime, Engines)
```

The UI exposes:
- **Application Shell & Command Center**: Global navigation, operational control, and execution dispatch.
- **Engineering Workspaces**: Greenfield Engineering Canvas and Legacy Modernization Workspace.
- **Specialized Interfaces**: Research, Planning, Architecture, Workforce, Workflow/DAG, Execution, Review, and Artifact interfaces.
- **Observability UX**: Live telemetry, queue health, worker/workflow activity, latency distributions (P50/P95/P99), model speeds, node utilization, failure/retry metrics, cost aggregation, and distributed trace waterfalls.
- **HITL Approval Center**: Review and decision controls for consequential governance gates.
- **Self-Improvement Center**: Learning evidence, candidate improvements, benchmark/regression results, version lineage, and rollback controls.

---

## 4. Architectural Dependency Principles & Governance Invariants

The following principles govern the dependencies and operational boundaries across all components of AutoForge AI OS:

- **AutoForge is the Primary Architecture** — External frameworks do not become architectural authorities. AutoForge owns its domain abstractions, contracts, and lifecycles.
- **External Framework Containment**:
  - **Temporal**: Remains an OPTIONAL durable orchestration adapter behind the `OrchestrationAdapter` interface. `WorkflowEngine` remains the AutoForge domain abstraction and policy owner.
  - **LangGraph, LangChain, CrewAI**: Remain excluded from the live path. They must not silently enter execution. Any future use requires an explicit, narrowly scoped ADR.
  - **Langfuse**: May serve as an optional observability adapter for LLM telemetry; it is never the system of record. AutoForge Observability remains canonical.
- **AI Non-Authority Invariant** — AI models do not own governance, policy, state authority, HITL approval gates, determinism, or engineering meaning.
- **UI Non-Authority Invariant** — The UI is strictly a presentation and control layer; state authority resides exclusively in authoritative platform services.
- **Worker Model Agnosticism** — Workers declare capability and model requirements (via `WorkerModelProfile`); workers NEVER hardcode concrete model IDs.
- **Centralized Model Allocation** — Model selection, capacity management, and routing remain centralized in `ModelAllocator` and `ModelRouterService`.
- **First-Class Legacy Modernization** — Legacy modernization is a co-equal, first-class capability supported by 9 dedicated workers, specialized archaeological pipelines, and explicit uncertainty tracking.
- **Preserved Specialized Workforce** — The 23 specialized workers (14 Greenfield + 9 Legacy Modernization) remain explicit and must not be reduced to generic agents.
- **Context Engineering as a First-Class Capability** — Composes Knowledge and Memory capabilities without duplicating them (ADR-003).
- **Memory ≠ Learning (ADR-005)** — Memory preserves operational state and historical context; Learning synthesizes generalized adaptations and platform optimizations.
- **Strictly Gated Self-Improvement** — All candidate improvements must pass through the mandatory safety pipeline (Candidate → Evaluation → Benchmark → Regression → Accept/Reject → Version → Rollback → Activate) before activation. No silent self-modification.
- **Separation of Concerns & Single Responsibility** — Every subsystem addresses exactly one distinct domain. Concerns do not overlap across boundaries.
- **Interface First & Contract-Driven** — Subsystems define capabilities through explicit, versioned interfaces before implementation.
- **Event-Driven Communication & State-Driven Coordination** — Subsystems communicate primarily through asynchronous immutable events; state is the canonical record of progress.
- **Recoverable & Resilient Execution** — Every execution unit supports checkpointing, snapshotting, and resumption from known states.

---

## 5. Shared Platform Services

The following services are available horizontally to every engine and worker in the platform. They provide foundational capabilities that cross subsystem boundaries. Shared Platform Services remain horizontally available to authorised platform components through documented interfaces. The Kernel determines when they participate within a project lifecycle, but the services themselves remain independent, reusable, and loosely coupled from any specific engine or orchestration path.

```
                    Shared Platform Services

 ┌────────────────────────────────────────────────────┐
 │ Runtime State Manager                              │
 │ Canonical Event Model                              │
 │ Event Bus                                          │
 │ Knowledge Engine                                   │
 │ Memory Engine                                      │
 │ Learning Engine                                    │
 │ Capability Registry                                │
 │ Model Router                                       │
 │ Execution Continuity Manager                       │
 │ Connector Layer                                    │
 │ Observability                                      │
 │ Dashboard                                          │
 │ Security                                           │
 └────────────────────────────────────────────────────┘
```

### Runtime State Manager

Maintains the canonical state of all tracked entities across the platform, including project state, workflow state, execution state, worker state, and queue state. The Runtime State Manager represents the present — the current condition of every active and historical entity. All subsystems read from and write to this canonical state through documented interfaces.

### Canonical Event Model

Defines the schema-enforced, versioned structure that every event in the platform must conform to. It specifies mandatory fields including identity, type, source, timestamp, payload, and metadata. The Canonical Event Model is the contract between all event producers and consumers.

### Event Bus

Provides the publish-subscribe infrastructure that routes events from producers to consumers. The Event Bus decouples subsystems by enabling asynchronous communication without direct references. It guarantees at-least-once delivery and preserves event ordering within defined partitions.

### Knowledge Engine

Provides trustworthy engineering knowledge before reasoning begins. The Knowledge Engine accepts research requests, routes them to appropriate source connectors, fuses information from multiple sources, and produces executive research briefs. It is the platform's authoritative source of curated, queryable knowledge. Knowledge retrieval may be initiated by the Kernel before planning, during execution, during review, or whenever additional engineering knowledge is required. The Knowledge Engine retains complete ownership of retrieval, ranking, fusion, trust evaluation, and knowledge generation.

### Memory Engine

Provides contextual storage that captures the state and history of specific executions and sessions. The Memory Engine manages working memory, project memory, long-term memory, reflection memory, and semantic memory, enabling continuity within and across related work. The Kernel may initiate memory operations throughout execution, including loading project context, retrieving previous execution history, persisting new memories, and updating long-term memory. Memory management remains entirely within the Memory Engine.

### Learning Engine

Analyses execution histories and outcomes to discover patterns, extract best practices, and generate recommendations for workflow optimisation. The Learning Engine drives continuous improvement across the platform by curating execution-derived information for promotion to knowledge. The Kernel determines when the Learning Engine should be invoked as part of a project's lifecycle. The Learning Engine independently determines what patterns exist, what improvements should be extracted, and what knowledge should be promoted.

### Capability Registry

The Capability Registry is the authoritative AI infrastructure metadata registry for AutoForge AI OS. It describes the complete AI execution ecosystem available to the operating system. It maintains authoritative metadata for AI execution infrastructure including AI providers, AI models, deployment types, execution environments, supported capabilities, supported modalities, supported features, context limits, latency characteristics, throughput characteristics, reliability characteristics, availability, cost characteristics, policy constraints, and execution characteristics.

The Capability Registry allows providers and models to be added, removed, upgraded, or deprecated without requiring architectural changes elsewhere in the operating system. The platform remains provider agnostic by depending on registry metadata rather than on any specific provider or model.

The Capability Registry is metadata only. It does NOT perform routing. It does NOT execute requests. It does NOT perform retries. It does NOT perform failover. It does NOT evaluate runtime failures. Its responsibility is to provide authoritative AI infrastructure metadata to the rest of the operating system.

### Model Router

Selects and dispatches requests to appropriate AI models based on capability requirements, cost, availability, and other selection criteria. Routing targets include strategic reasoning, coding, review, embeddings, speech, vision, local models, and cloud models. The Model Router abstracts model infrastructure from the rest of the platform. The Model Router is responsible only for model selection — it does not own retries or failover. Execution resilience is handled by the Execution Continuity Manager.

### Execution Continuity Manager

Provides execution resilience across the platform. The Execution Continuity Manager is responsible for automatic retries, automatic provider failover, execution checkpoint restoration, execution resumption, context preservation, degraded execution, timeout recovery, and provider outage recovery. It is invoked whenever execution cannot continue normally. The Execution Continuity Manager preserves execution continuity without changing engine behaviour. The Kernel coordinates when the Execution Continuity Manager participates, but the service itself remains independently reusable and loosely coupled from every engine.

### Connector Layer

Provides standardised access to external systems through a uniform interface. Connector types include MCP connectors, native connectors, REST APIs, filesystem connectors, Git connectors, GitHub connectors, browser connectors, Docker connectors, database connectors, vector store connectors, and cloud API connectors. The platform must never depend on a single protocol.

### Observability

Collects, processes, and exposes telemetry data from all platform components. Observability encompasses metrics, logs, traces, workflow graphs, execution graphs, agent activity, queue health, latency, token usage, cost, retries, and failures. Observability data is produced without influencing the behaviour being observed.

### Dashboard

Provides a read-only projection of platform state, metrics, and observability data intended for human operators. Dashboards aggregate signals from the Observability system and present them as visual summaries. They have no write path into the platform's operational state.

The Dashboard exposes read-only visualisations of AI execution infrastructure sourced from Observability, including AI infrastructure inventory, deployment inventory, provider inventory, model inventory, capability inventory, feature inventory, deployment types, provider health, provider availability, routing statistics, execution continuity statistics, provider utilisation, and provider failover history.

The Dashboard MUST remain read-only. The Dashboard must never communicate directly with the Capability Registry. All capability information flows through Observability. Dashboards are read-only projections of platform state.

### Security

Enforces authentication, authorisation, and access control across all platform interfaces. Security encompasses sandboxing, permissions, least privilege, secrets management, audit trails, isolation boundaries, and human approval gates. Security decisions are based on the identity and permissions of the requesting entity, not on the request's origin within the platform.

---

## 6. Request Lifecycle

Every request that enters the platform progresses through the following lifecycle stages. Each stage represents a distinct phase of transformation from raw idea to finished product. The Kernel dynamically orchestrates this lifecycle — not every request traverses every stage, and the order of stages may vary based on the requirements of each request.

```
Idea

↓

Requirement Analysis

↓

Architecture Design

↓

Task Graph Generation

↓

Workflow Construction

↓

Scheduling

↓

Execution

↓

Review

↓

Testing

↓

Deployment

↓

Completion
```

- **Idea** — A high-level objective or problem statement is received from the user.
- **Requirement Analysis** — The idea is analysed and decomposed into structured requirements with defined acceptance criteria.
- **Architecture Design** — The system architecture is designed, defining component boundaries, relationships, and patterns.
- **Task Graph Generation** — The architecture is decomposed into a directed acyclic graph of discrete, schedulable tasks.
- **Workflow Construction** — The task graph is wrapped in a workflow that defines orchestration rules, dependencies, and recovery policies.
- **Scheduling** — Tasks are queued and dispatched to available workers based on priority and capability.
- **Execution** — Workers perform the implementation work, producing artifacts as outputs.
- **Review** — Artifacts are evaluated against quality criteria. Failed artifacts are returned for remediation.
- **Testing** — Approved artifacts are integrated and tested as a complete system.
- **Deployment** — The tested system is prepared for delivery to the target environment.
- **Completion** — The finished product is delivered and the lifecycle is closed.

Knowledge retrieval and research are not a fixed sequential phase in this lifecycle. The Kernel orchestrates research dynamically — knowledge may be retrieved before planning, during execution, during review, or whenever additional engineering knowledge is required. Research is demand-driven and supports multiple lifecycle stages rather than existing as a single fixed step after scheduling.

---

## 7. Workflow Architecture

The Workflow Engine is responsible for orchestrating the execution of work across the platform. It manages the lifecycle of workflows from submission through completion.

### Responsibilities

- **Orchestration** — Coordinates the execution order of tasks according to the defined workflow structure.
- **Dependency Management** — Tracks and resolves dependencies between tasks, ensuring that a task is not executed until its dependencies are satisfied.
- **Approvals** — Manages approval gates at configurable points within the workflow, pausing execution until approval is granted.
- **Retries** — Detects task failures and initiates retry attempts according to configurable policies.
- **Branching** — Supports conditional branching within workflows, enabling different execution paths based on outcomes or decisions.
- **Lifecycle Management** — Manages the full lifecycle of workflows from creation through completion, suspension, or cancellation.
- **Recovery** — Maintains sufficient state to resume interrupted workflows from known checkpoints without data loss or inconsistency.

The Workflow Engine never performs implementation. Its sole responsibility is coordination.

---

## 8. Execution Architecture

The Execution Engine is responsible for executing the units of work dispatched by the Workflow Engine. It receives the Research Brief, Architecture Blueprint, Implementation Blueprint, and Acceptance Criteria produced by the Strategic Engine. The Execution Engine manages the engineering loops in which workers perform implementation.

### Responsibilities

- **Execute Work** — Receives tasks from the Workflow Engine and initiates execution through the appropriate worker.
- **Manage Engineering Loops** — Oversees the iterative cycle of implementation, execution, observation, reflection, and improvement that each worker performs.
- **Coordinate Engineering Workers** — Dispatches tasks to workers, monitors their progress, and collects results.
- **Publish Events** — Publishes events for all significant execution occurrences, including task start, completion, failure, and state transitions.
- **Update Runtime** — Writes execution state transitions to the Runtime State Manager, ensuring that the canonical state reflects current progress.
- **Produce Artifacts** — Captures the outputs produced by workers and submits them to the Artifact Manager.

The Execution Engine does NOT perform architecture design, technology research, framework evaluation, trade-off analysis, or strategic planning. Its responsibility is implementation.

---

## 9. Specialised Execution Lifecycles

AutoForge AI OS uses specialised execution lifecycles rather than a single universal loop. Each major engine owns its own iterative lifecycle appropriate to its responsibilities. All lifecycles share the same iterative engineering philosophy of observe, reflect, and improve, but each is tailored to the specific domain of its owning engine.

### Strategic Engine Lifecycle

The Strategic Engine follows a lifecycle focused on analysis, research, and planning. It produces an implementation-ready package that downstream engines consume.

```
Receive Request

↓

Analyze Requirements

↓

Research

↓

Evaluate Alternatives

↓

Design Architecture

↓

Produce Implementation Blueprint

↓

Produce Research Brief

↓

Produce Acceptance Criteria

↓

Handoff to Kernel
```

- **Receive Request** — The Strategic Engine receives strategic work delegated by the Kernel.
- **Analyze Requirements** — The request is decomposed into structured requirements with defined scope, constraints, and success criteria.
- **Research** — The Research Engineer conducts technical research, documentation research, framework research, best practice research, and technology comparisons under the coordination of the Strategic Engine.
- **Evaluate Alternatives** — Multiple architectural and technological alternatives are evaluated through trade-off analysis.
- **Design Architecture** — The Software Architect produces the system architecture, defining component boundaries, relationships, and patterns.
- **Produce Implementation Blueprint** — A detailed implementation blueprint is produced, specifying the work to be done, the order of execution, and the dependencies between tasks.
- **Produce Research Brief** — A research brief is produced, documenting findings, recommendations, risks, and tradeoffs.
- **Produce Acceptance Criteria** — Acceptance criteria are defined against which the final output will be evaluated.
- **Handoff to Kernel** — The complete implementation-ready package is returned to the Kernel for execution.

### Execution Engine Lifecycle

The Execution Engine follows a lifecycle focused on implementation. It receives the implementation-ready package and drives engineering workers through an iterative build-test-improve cycle.

```
Receive Implementation Blueprint

↓

Understand Context

↓

Implement

↓

Execute

↓

Observe

↓

Improve

↓

Validate

↓

Retry

↓

Publish Events

↓

Update Runtime

↓

Produce Artifacts
```

- **Receive Implementation Blueprint** — The Execution Engine receives the Research Brief, Architecture Blueprint, Implementation Blueprint, and Acceptance Criteria from the Workflow Engine.
- **Understand Context** — The worker examines the task requirements, input artifacts, and context to develop an understanding of what needs to be done.
- **Implement** — The worker produces the implementation output, which may include source code, configuration, documentation, or other artifacts.
- **Execute** — The worker runs the implementation, which may involve compilation, interpretation, or other execution mechanisms.
- **Observe** — The worker collects the results of execution, including output, errors, logs, and performance characteristics.
- **Improve** — The worker iterates on the implementation based on observation, making corrections and improvements.
- **Validate** — The worker verifies that the implementation meets the success criteria and is ready for review.
- **Retry** — If validation fails, the worker may retry the loop from an appropriate earlier stage.
- **Publish Events** — The worker publishes events describing the outcome of the task, including results, metrics, and decisions.
- **Update Runtime** — The worker writes the final state of the task to the Runtime State Manager.
- **Produce Artifacts** — The worker produces the final artifacts and submits them to the Artifact Manager.

### Review Engine Lifecycle

The Review Engine follows a lifecycle focused on evaluation and quality assurance.

```
Receive Artifact

↓

Analyze

↓

Validate

↓

Test

↓

Review

↓

Report Findings

↓

Approve or Reject
```

- **Receive Artifact** — The Review Engine receives an artifact submitted by an engineering worker.
- **Analyze** — The artifact is examined to understand its structure, purpose, and compliance requirements.
- **Validate** — The artifact is validated against the architectural design and defined standards.
- **Test** — The artifact is tested against the acceptance criteria and quality gates.
- **Review** — A comprehensive review is conducted covering correctness, architecture, documentation, performance, security, and policy compliance.
- **Report Findings** — Detailed findings are produced, documenting issues, recommendations, and the rationale for the decision.
- **Approve or Reject** — The artifact is approved for publication or rejected with detailed feedback for remediation.

### Learning Engine Lifecycle

The Learning Engine follows a lifecycle focused on continuous improvement through observation and analysis. The Learning Engine determines the improvements; the Kernel coordinates when learning occurs. Promoted knowledge becomes reusable organisational knowledge for future executions.

```
Observe Executions

↓

Collect Outcomes

↓

Detect Patterns

↓

Analyze Mistakes

↓

Extract Best Practices

↓

Validate Improvements

↓

Promote Knowledge

↓

Kernel Coordination

↓

Improve Future Projects
```

- **Observe Executions** — The Learning Engine monitors execution activity across the platform.
- **Collect Outcomes** — Outcomes, metrics, and results are collected from completed and failed executions.
- **Detect Patterns** — Recurring patterns are identified in successful and unsuccessful executions.
- **Analyze Mistakes** — Common mistakes and failure modes are analysed to understand root causes.
- **Extract Best Practices** — Proven strategies and successful approaches are extracted and formalised.
- **Validate Improvements** — Extracted improvements are validated to ensure they produce the expected benefits.
- **Promote Knowledge** — Validated improvements are promoted into the Knowledge Engine for use in future projects.
- **Kernel Coordination** — The Kernel determines when the promoted knowledge should be applied within future project lifecycles, coordinating the integration of learning outcomes back into platform orchestration.
- **Improve Future Projects** — The platform continuously improves as accumulated knowledge informs future executions.

---

## 10. Review Architecture

The Review Engine evaluates all artifacts produced during execution against defined quality criteria. It is the quality gate of the platform.

### Responsibilities

- **Correctness** — Verifies that artifacts implement the specified requirements correctly and completely.
- **Architecture Validation** — Ensures that artifacts conform to the architectural design and do not introduce architectural violations.
- **Testing** — Verifies that artifacts are accompanied by appropriate test coverage and that tests pass.
- **Documentation Quality** — Evaluates the completeness, clarity, and accuracy of documentation artifacts.
- **Performance** — Assesses whether artifacts meet performance requirements and do not introduce regressions.
- **Security** — Verifies that artifacts comply with security policies and do not introduce vulnerabilities.
- **Policy Compliance** — Ensures that artifacts adhere to organisational policies, coding standards, and regulatory requirements.

Artifacts that fail review are returned to the originating worker with detailed feedback describing the issues that must be addressed. Artifacts that pass review are forwarded to the Artifact Manager for storage and publication.

---

## 11. Artifact Architecture

The Artifact Manager is responsible for the lifecycle of all named, versioned outputs produced or consumed during execution.

### Responsibilities

- **Artifact Storage** — Stores artifacts in a content-addressable manner, ensuring that each artifact can be uniquely identified and retrieved.
- **Versioning** — Maintains version history for all artifacts, enabling access to previous versions and supporting rollback when needed.
- **Lineage** — Tracks the provenance of each artifact, recording which task, worker, and inputs produced it.
- **Traceability** — Maintains the chain of relationships from the original idea through every transformation to the final artifact, enabling full traceability.
- **Retrieval** — Provides efficient retrieval of artifacts by identifier, metadata, and lineage relationships.
- **Publishing** — Makes approved artifacts available to consumers, including downstream workers, the Review Engine, and external systems.

---

## 12. Knowledge Architecture

The Knowledge Engine provides trustworthy engineering knowledge before reasoning begins. It is the platform's authoritative source of curated, queryable information that persists across executions and projects. Knowledge retrieval may be initiated by the Kernel before planning, during execution, during review, or whenever additional engineering knowledge is required. The Knowledge Engine retains complete ownership of retrieval, ranking, fusion, trust evaluation, and knowledge generation.

### Knowledge Sources

The Knowledge Engine draws from the following sources:

- Local Books
- PDFs
- Internal Documentation
- Previous Projects
- Git History
- Research Papers
- Framework Documentation
- RFCs
- Company Documentation
- Runtime Memory
- Long-Term Memory

### Knowledge Pipeline

Research requests flow through the following pipeline:

```
Research Request

↓

Knowledge Router

↓

Source Connectors

↓

Knowledge Fusion

↓

Executive Research Brief

↓

Requesting Engine
```

- **Research Request** — A worker or engine submits a request for knowledge on a specific topic, including scope, context, and desired output format.
- **Knowledge Router** — The Knowledge Router evaluates the request and determines which source connectors are most appropriate for fulfilling it.
- **Source Connectors** — The selected connectors retrieve information from their respective sources. Each connector translates between the platform's internal protocols and the external source's interface.
- **Knowledge Fusion** — The retrieved information is fused into a coherent output. Knowledge Fusion responsibilities include ranking sources by relevance and authority, assigning trust scores based on source reliability, deduplicating overlapping information, summarising findings into a concise form, and generating recommendations based on the synthesised knowledge.
- **Executive Research Brief** — The fused knowledge is packaged into an executive research brief containing an executive summary, an engineering recommendation, identified risks, tradeoffs, references, and a suggested implementation plan.
- **Requesting Engine** — The research brief is delivered to the requesting engine, which may be the Strategic Engine, Workflow Engine, Execution Engine, Review Engine, Learning Engine, or any other authorised platform component.

---

## 13. Research Architecture

The Research Engine conducts structured investigation by gathering information from external sources and synthesising findings into actionable results.

### Internet Research Pipeline

When research requires information from internet-accessible sources, the following pipeline is used:

```
Research Request

↓

Query Planner

↓

Source Discovery

↓

Source Quality Ranking

↓

Content Retrieval

↓

Deduplication

↓

Knowledge Fusion

↓

Executive Research Brief

↓

Requesting Engine
```

- **Query Planner** — Decomposes the research request into a set of targeted queries designed to retrieve relevant information.
- **Source Discovery** — Identifies potential sources for each query, including web pages, documentation, repositories, and other online resources.
- **Source Quality Ranking** — Evaluates discovered sources for relevance, authority, and reliability, ranking them to prioritise high-quality information.
- **Content Retrieval** — Retrieves content from the highest-ranked sources.
- **Deduplication** — Removes duplicate or overlapping content to produce a concise information set.
- **Knowledge Fusion** — Fuses the deduplicated content into a coherent research output (as described in the Knowledge Architecture section).
- **Executive Research Brief** — The fused output is packaged as an executive research brief.
- **Requesting Engine** — The brief is delivered to the requesting engine, which may be the Strategic Engine, Workflow Engine, Execution Engine, Review Engine, Learning Engine, or any other authorised platform component.

### Connector Hierarchy

The Research Engine accesses external sources through the following connector hierarchy:

```
Research Engine

↓

Knowledge Router

↓

Source Connectors

↓

MCP Connector
Git Connector
Filesystem Connector
HTTP Connector
Database Connector
Vector Store Connector
GitHub Connector
ArXiv Connector
Documentation Connector
```

Each connector implements the standard connector contract and translates between the platform's internal protocols and the external source's native interface.

---

## 14. Memory Architecture

The Memory Engine manages multiple types of memory, each serving a distinct purpose in the platform. The Kernel may initiate memory operations throughout execution, including loading project context, retrieving previous execution history, persisting new memories, and updating long-term memory. Memory management remains entirely within the Memory Engine.

### Working Memory

Short-term, task-specific context that is active only during the current execution. Working memory contains the immediate state, inputs, and outputs of the task being performed. It is volatile and does not persist beyond the execution session.

### Project Memory

Persistent context scoped to a specific project. Project memory contains the project's requirements, architecture decisions, design documents, and execution history. It persists across executions within the same project and is available to all workers operating on that project.

### Long-Term Memory

Persistent knowledge that transcends individual projects. Long-term memory contains accumulated engineering knowledge, best practices, patterns, and lessons learned that are applicable across the entire platform. It is curated and versioned to maintain quality and relevance.

### Reflection Memory

Captures the outcomes of the reflection stage in the execution loop. Reflection memory stores what was learned during execution, what went well, what went wrong, and what could be improved. It feeds into the Learning Engine for pattern discovery and continuous improvement.

### Semantic Memory

Stores conceptual relationships and abstractions that enable reasoning across disparate pieces of information. Semantic memory supports the platform's ability to understand context, draw analogies, and apply knowledge from one domain to another.

---

## 15. Learning Architecture

The Learning Engine is the platform's continuous improvement system. It continuously learns from completed projects, failed projects, successful implementations, execution histories, review results, architectural decisions, workflow outcomes, engineering mistakes, tool usage, and model performance. Validated improvements are promoted into the Knowledge Engine and become reusable organisational knowledge that benefits every future execution.

The Learning Engine improves not only future projects but also AutoForge AI OS itself. By analysing how the platform is used and how it performs, the Learning Engine identifies improvements to the platform's own behaviour, making it a continuously self-learning and self-improving engineering platform.

The Kernel determines when the Learning Engine should be invoked as part of a project's lifecycle. The Learning Engine independently determines what patterns exist, what improvements should be extracted, and what knowledge should be promoted.

### Responsibilities

- **Execution Analysis** — Analyses execution histories, outcomes, and metrics to identify patterns and trends.
- **Pattern Discovery** — Discovers recurring patterns in successful and unsuccessful executions, including common failure modes and effective strategies.
- **Common Mistake Detection** — Identifies common mistakes and failure modes across projects and analyses their root causes.
- **Successful Strategy Extraction** — Extracts proven strategies and successful approaches from completed projects and formalises them as recommended practices.
- **Workflow Optimisation** — Identifies opportunities to optimise workflows for efficiency, reliability, and quality.
- **Architecture Improvement Recommendations** — Analyses architectural decisions and outcomes to recommend improvements to future architecture designs.
- **Prompt and Tool Usage Improvement** — Analyses how prompts and tools are used across executions and identifies opportunities for improvement.
- **Planning Quality Improvement** — Evaluates planning quality and identifies patterns that lead to more effective plans.
- **Model Routing Improvement** — Analyses model routing decisions and outcomes to recommend improvements to routing strategies.
- **Tool Selection Improvement** — Analyses tool usage patterns to recommend more effective tool selection strategies.
- **Connector Usage Improvement** — Analyses connector usage to identify opportunities for more effective external system integration.
- **Engineering Best Practice Extraction** — Extracts and formalises engineering best practices from successful implementations across the platform.
- **Execution Strategy Improvement** — Analyses execution outcomes to recommend improvements to execution strategies and approaches.
- **Review Strategy Improvement** — Analyses review outcomes to recommend improvements to review strategies and quality gates.
- **Knowledge Promotion** — Validated improvements are promoted into the Knowledge Engine, making them available to all future projects across the platform.
- **Platform Self-Improvement** — Identifies improvements to architectural patterns, workflow orchestration, planning quality, prompt engineering, model routing, tool selection, connector usage, engineering best practices, execution strategies, and review strategies. These improvements enhance AutoForge AI OS itself, making it a continuously self-learning and self-improving engineering platform.
- **Continuous Improvement** — Establishes a feedback loop in which insights from past executions inform and improve future executions across the platform.

---

## 16. Modular Engine Usage

Each major engine in AutoForge AI OS can operate independently when appropriate, enabling flexible deployment and usage patterns. The Kernel is responsible for composing execution pipelines from the available engines and Shared Platform Services based on the requirements of each incoming request. The following are illustrative examples only. The Kernel dynamically composes execution pipelines based on the requirements of each request.

### Example Pipelines

**Research**

```
User
↓
Kernel
↓
Knowledge Engine
↓
Strategic Engine
```

The Kernel invokes the Knowledge Engine and Strategic Engine when a request requires research and planning without implementation.

**Implementation**

```
User
↓
Kernel
↓
Memory Engine (retrieve)
↓
Workflow Engine
↓
Execution Engine
↓
Memory Engine (persist)
```

The Kernel invokes the Memory Engine to retrieve existing context, then the Workflow Engine and Execution Engine when an implementation blueprint already exists and only execution is required. After completion, the Kernel invokes the Memory Engine to persist new knowledge.

**Review**

```
User
↓
Kernel
↓
Review Engine
```

The Kernel invokes only the Review Engine when a pre-existing artifact requires quality evaluation.

**Full Autonomous Project**

```
User
↓
Kernel
↓
Knowledge Engine
↓
Strategic Engine
↓
Workflow Engine
↓
Execution Engine
↓
Review Engine
↓
Memory Engine
↓
Learning Engine
↓
Knowledge Promotion
↓
Artifact Manager
```

The Kernel invokes the full pipeline when a request requires strategic planning, implementation, review, learning, and artifact publication. The Kernel orchestrates the Knowledge Engine for initial research, the Strategic Engine for planning, the Workflow Engine and Execution Engine for implementation, the Review Engine for quality evaluation, the Memory Engine for persistence, the Learning Engine for continuous improvement, and the Knowledge Engine again for knowledge promotion.

### Engine Independence

- **Strategic Engine** — Can be used for research and planning only, producing an implementation-ready package without executing any implementation work.
- **Execution Engine** — Can be used for implementation only, receiving an externally produced implementation blueprint and executing it without performing strategic planning.
- **Review Engine** — Can be used for artifact validation only, evaluating pre-existing artifacts against quality criteria without involvement from other engines.
- **Learning Engine** — Can be used for organisational learning only, analysing execution data and producing insights without participating in active project execution.

The complete platform combines these engines into an autonomous software engineering system. The Kernel composes the appropriate pipeline for each request, invoking only the engines and services required for that specific execution.

---

## 17. Model Routing

AI execution in AutoForge AI OS follows a three-stage decision pipeline: capability discovery, model selection, and execution continuity. The Capability Registry supplies capability metadata describing every AI execution capability available to the platform. The Model Router selects the appropriate provider and model based on that metadata and the requirements of each request. The Execution Continuity Manager preserves execution when failures occur. These responsibilities are complementary but intentionally independent. The full AI Execution Architecture is described in Section 17.1.

### Routing Targets

The Model Router may dispatch requests to any of the following categories of models:

- **Strategic Reasoning** — Models optimised for high-level planning, analysis, and decision-making.
- **Coding** — Models specialised for code generation, refactoring, and analysis.
- **Review** — Models configured for evaluation, critique, and quality assessment.
- **Embeddings** — Models that produce vector representations of text for retrieval and similarity matching.
- **Speech** — Models that process audio input and output, including transcription and synthesis.
- **Vision** — Models that process image and video input for analysis and generation.
- **Local Models** — Models running on local infrastructure for latency-sensitive or offline operation.
- **Cloud Models** — Models accessed through remote endpoints for high-capacity or specialised capabilities.

The Model Router evaluates each request against model capabilities, cost, latency, availability, and policy constraints to make the optimal routing decision.

---

## 17.1 AI Execution Architecture

AutoForge AI OS executes AI workloads across local and cloud providers while remaining completely provider agnostic. The AI Execution Architecture describes how the platform selects providers, dispatches work, and maintains execution continuity across heterogeneous AI infrastructure.

### AI Execution Philosophy

AutoForge AI OS is:

- **provider agnostic** — The platform must never depend on any single AI provider.
- **local-first** — Local execution is preferred when capabilities permit, enabling low-latency, offline-capable operation.
- **cloud-capable** — Cloud providers are available for high-capacity or specialised capabilities that exceed local infrastructure.
- **execution-resilient** — Execution should continue whenever possible without requiring manual intervention.
- **capable of seamless provider failover** — When a provider fails, the platform transparently fails over to an alternative provider without losing execution context.

### AI Execution Architecture Diagram

The following diagram illustrates the conceptual AI Execution Architecture. It is conceptual only and does not imply implementation details.

```
                    AI Execution Layer

                  Capability Registry

                           │

                           ▼

              Intelligent Model Router

                           │

        ┌──────────────────┴──────────────────┐

        │                                     │

 Local Execution Providers        Cloud Execution Providers

        │                                     │

        └──────────────────┬──────────────────┘

                           ▼

          Execution Continuity Manager

                           │

        Automatic Retry

        Automatic Provider Failover

        Context Preservation

        Checkpoint Recovery

        Degraded Execution

        Seamless Execution Continuation
```

### Capability Registry

The Capability Registry is the authoritative AI infrastructure registry describing every AI execution capability available to AutoForge AI OS. It maintains metadata including:

- Provider
- Models
- Capabilities
- Supported Modalities
- Context Windows
- Latency Characteristics
- Throughput Characteristics
- Cost Characteristics
- Availability
- Reliability
- Deployment Characteristics
- Execution Characteristics
- Policy Constraints
- Supported Features
- Provider Health Metadata

The Capability Registry never selects models. It only exposes metadata.

### Supported Features

Supported features describe the capabilities that AI infrastructure may expose. Examples include:

- streaming
- structured output
- tool calling
- function calling
- vision
- image generation
- embeddings
- speech recognition
- speech synthesis
- multimodal reasoning
- reasoning models
- coding models

These are illustrative only. The registry is designed to accommodate future features as the AI ecosystem evolves.

### Intelligent Model Router

The Model Router is responsible only for model selection. It does not own retries or failover.

Responsibilities include:

- selecting the appropriate provider
- selecting the appropriate model
- evaluating capability
- evaluating latency
- evaluating cost
- evaluating availability
- evaluating policy constraints

### Local Execution Providers

The Capability Registry maintains metadata for local execution platforms including:

- Ollama
- llama.cpp
- LM Studio
- vLLM
- Future Local Providers

Deployment metadata identifies these providers as Local Execution.

### Cloud Execution Providers

The Capability Registry maintains metadata for cloud execution providers including:

- OpenAI
- Gemini
- Claude
- Groq
- OpenRouter
- DeepSeek
- Mistral
- Future Cloud Providers

Deployment metadata identifies these providers as Cloud Execution.

### Deployment Characteristics

The Capability Registry classifies execution infrastructure by deployment type. Deployment types include:

- Local
- Cloud
- Hybrid
- Distributed
- Edge
- Cluster

The architecture is intentionally designed to accommodate future deployment models without architectural redesign. The registry evolves as new deployment models emerge.

### Execution Continuity Manager

The Execution Continuity Manager is responsible for execution resilience. It is invoked whenever execution cannot continue normally.

Responsibilities include:

- automatic retries
- automatic provider failover
- execution checkpoint restoration
- execution resumption
- context preservation
- degraded execution
- timeout recovery
- provider outage recovery

The Execution Continuity Manager preserves execution continuity without changing engine behaviour.

### Separation of Responsibilities

AI infrastructure metadata, routing decisions, execution resilience, visibility, and presentation are intentionally separated:

- **Capability Registry** decides: "What AI infrastructure and capabilities currently exist?"
- **Model Router** decides: "Which provider and model should execute?"
- **Execution Continuity Manager** decides: "How should execution continue when execution cannot proceed normally?"
- **Observability** decides: "What is the observable state of AI execution infrastructure?"
- **Dashboard** decides: "How is AI execution infrastructure presented to human operators?"

These responsibilities remain intentionally separated to ensure that infrastructure metadata, model selection logic, execution resilience logic, observability, and presentation evolve independently without coupling.

---

## 18. Connector Layer

The Connector Layer provides standardised access to external systems through a uniform interface. It insulates the rest of the platform from the specifics of external system protocols and implementations.

### Connector Types

The platform supports the following connector types:

- **MCP** — Connectors that implement the Model Context Protocol for standardised tool and resource access.
- **Native Connectors** — Connectors built directly into the platform for commonly used external systems.
- **REST APIs** — Connectors that interact with HTTP-based RESTful services.
- **Filesystem** — Connectors that read from and write to the local filesystem.
- **Git** — Connectors that interact with Git repositories for version control operations.
- **GitHub** — Connectors that interact with the GitHub platform for repository management, issues, and pull requests.
- **Browser** — Connectors that automate web browser interaction for research and testing.
- **Docker** — Connectors that manage container lifecycle for execution environments.
- **Databases** — Connectors that interact with database systems for data storage and retrieval.
- **Vector Stores** — Connectors that interact with vector databases for semantic search and retrieval.
- **Cloud APIs** — Connectors that interact with cloud provider APIs for infrastructure management.

The platform must never depend on a single protocol. The Connector Layer is designed to accommodate multiple protocols and evolve as new integration patterns emerge.

---

## 19. Runtime Architecture

The Runtime State Manager maintains the canonical state of all tracked entities across the platform. It is the single source of truth for the current condition of every entity.

### State Categories

- **Project State** — The current status, configuration, and metadata of each project known to the platform.
- **Workflow State** — The current status, progress, and position within the lifecycle of each active workflow.
- **Execution State** — The current status, inputs, outputs, and lifecycle position of each execution session.
- **Worker State** — The availability, capacity, and current assignment of each worker in the workforce.
- **Queue State** — The contents, ordering, and priority of all pending work in the scheduling queue.

The Runtime represents the present. It is updated continuously as work progresses and is consulted by all subsystems to understand current conditions. State transitions are triggered by events, ensuring that the canonical state always reflects the accumulated history of platform activity.

---

## 20. Event Architecture

The Event System is the primary communication backbone of the platform. All subsystems communicate by producing and consuming events that conform to the Canonical Event Model.

### Canonical Event Model Principles

- **Immutable** — Events, once published, are never modified. They represent a permanent record of what happened.
- **Replayable** — The event history can be replayed to reconstruct past states, recover from failures, or analyse historical behaviour.
- **Observable** — All events are visible through the Observability system, enabling operators to understand platform activity.
- **Auditable** — Events provide a complete, tamper-evident audit trail of all significant platform activity.
- **Streamable** — Events can be consumed in real time as they are produced, enabling reactive behaviour and live monitoring.

Events describe facts. They record that something happened, when it happened, and what the relevant context was. Events never contain behaviour. Behaviour is the responsibility of the subsystems that produce and consume events.

---

## 21. Observability

The Observability system collects, processes, and exposes telemetry data from all platform components. It provides comprehensive visibility into platform behaviour without influencing the behaviour being observed.

### Observability Signals

- **Metrics** — Numerical measurements of platform behaviour, including rates, counts, durations, and utilisation.
- **Logs** — Structured, timestamped records of significant events, decisions, and state transitions.
- **Traces** — End-to-end records of request flows across subsystems, enabling latency analysis and dependency mapping.
- **Workflow Graph** — A visual representation of workflow structure, progress, and status.
- **Execution Graph** — A visual representation of execution state, task dependencies, and completion status.
- **Agent Activity** — Visibility into what each worker is doing, including current task, progress, and decisions.
- **Queue Health** — Metrics on queue depth, wait times, processing rates, and backlog.
- **Latency** — Measurements of execution time at every stage of the pipeline.
- **Token Usage** — Tracking of model token consumption across all model routing targets.
- **Cost** — Aggregation of operational costs including model usage, compute, and external service consumption.
- **Retries** — Tracking of retry attempts, success rates, and failure patterns.
- **Failures** — Recording of all failures, including error context, impact, and resolution status.

### Capability Telemetry

Observability collects and exposes AI infrastructure telemetry including:

- provider availability
- provider health
- registered providers
- registered models
- deployment inventory
- feature inventory
- capability inventory
- provider lifecycle
- provider additions
- provider deprecations
- model lifecycle
- capability changes
- deployment availability
- local execution availability
- cloud execution availability
- routing statistics
- provider utilisation
- provider failovers
- execution continuity events
- model selection metrics
- capability usage trends

This information is observational only. Observability never modifies platform behaviour.

---

## 22. Security & Governance Platform

Security and governance are cross-cutting capabilities that apply to every subsystem, boundary, and execution path across AutoForge AI OS.

### Security Mechanisms

- **Authentication & Identity** — Verification of entities, users, and internal service credentials with session boundaries.
- **Authorization & RBAC** — Role-based access control defining granular resource permissions and operational privileges.
- **Sandboxing & Isolation** — Confined execution environments with process isolation, filesystem sandboxing, and resource quotas to prevent unauthorized resource access or leakage.
- **Secrets & API Key Management** — Encrypted at-rest credential storage with dynamic, non-leaking injection; strictly redacted from logs, traces, and events.
- **Immutable Audit Trail** — Tamper-evident, structured audit logs capturing all security-relevant and administrative actions for compliance and forensic review.
- **Human Approval Gates (HITL)** — Enforceable approval gates for high-impact or consequential operations:
  - Technology-stack finalization
  - Modernization architecture approval
  - Migration cutover execution
  - Production deployment

---

## 23. Business Architecture & Commercial Model

AutoForge AI OS distinguishes strictly between the internal platform technology and the commercial go-to-market offering:

1. **AutoForge AI OS (Internal Engineering Engine)**:
   The foundational AI operating system, workforce, and execution runtime developed across Phases 1–25. It is NOT initially sold as standalone software.
2. **Modernization Service MVP (Initial Commercial Offering)**:
   We sell enterprise legacy modernization as a high-value managed service. AutoForge AI OS operates internally as our proprietary modernization engine.

### Commercial Go-To-Market Pipeline

```
Customer Legacy System Intake
  ↓
Modernization Service (Commercial Offering)
  ↓
AutoForge AI Workforce (23 Specialized Workers: 14 Greenfield + 9 Legacy Modernization)
  ↓
Modernization Pipeline (Discovery → Archaeology → Architecture Reconstruction → Migration → Validation)
  ↓
Validated Modernized System (Behavioral Parity & Performance Confirmed)
  ↓
Customer Deliverables (Target Codebase, Schemas, Architecture Specs, Test Suites, Runbooks)
```

---

## 24. Desktop Application & Multi-Node Hardware Topology

The AutoForge AI OS product architecture separates interface design from packaging and distribution:

- **Product Experience (Phase 16)**: The UI components, workspaces, visualizations, and read models.
- **Desktop Application & Distribution (Phase 21)**: The standalone local-first packaging, process supervision, embedded runtime, and multi-node hardware orchestration.

### Supported Hardware Topology

```
AutoForge Desktop (Local-First Application)
  ├── Node 1: local-m1 (Apple Silicon M1/M2/M3/M4)
  ├── Node 2: local-hp (HP Workstation x86_64)
  └── Node 3: local-mac-mini-m6 (Future Node Topology)
```

- **Hardware-Agnostic Workers**: Workers declare required capabilities and model profiles; adding or changing physical nodes requires only runtime configuration without code changes to workers.
- **Local-First & Offline Resilience**: Full execution operates locally without internet connectivity; optional cloud connectivity provides bursting when permitted.

---

## 25. Canonical Roadmap & Architecture Governance

This document is the canonical architectural specification for AutoForge AI OS. The canonical implementation roadmap comprises 25 phases:

- **Phase 1–14**: Core Architecture, Kernel, Runtime, Events, Knowledge, Memory, AI Infrastructure, Connectors, Workflows, Execution, Review, Artifacts, AI Workforce (23 Workers), and Observability Platform (FROZEN).
- **Phase 15**: Security & Governance Platform
- **Phase 16**: AutoForge Product Experience
- **Phase 17**: AI Runtime & Real Model Integration
- **Phase 18**: Autonomous Engineering & Modernization
- **Phase 19**: Continuous Learning & Self-Improvement
- **Phase 20**: Modernization Service MVP
- **Phase 21**: Desktop Application & Distribution
- **Phase 22**: Developer / Extension Platform
- **Phase 23**: Enterprise Platform
- **Phase 24**: Distributed AI Operating System
- **Phase 25**: Production Release (v1.0)

### Standing Governance Invariants

1. **AutoForge Authority**: AutoForge remains the primary architectural authority. External frameworks (Temporal, Langfuse) remain optional adapters; LangGraph, LangChain, and CrewAI remain excluded from the live path.
2. **AI Non-Authority**: AI does not own governance, policy, state, or HITL authority.
3. **UI Non-Authority**: The UI is strictly a presentation and control layer.
4. **Memory ≠ Learning**: Memory stores context; Learning synthesizes adaptations through the mandatory gated safety pipeline.
5. **Context Engineering**: Composes Knowledge and Memory without duplicating them.
6. **Centralized Model Allocation**: Workers declare requirements; `ModelAllocator` and `ModelRouterService` control selection.

Architectural modifications require an approved Architecture Decision Record (ADR) adhering to these invariants.