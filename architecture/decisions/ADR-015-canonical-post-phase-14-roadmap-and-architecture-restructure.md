# ADR-015: Canonical Post-Phase-14 Roadmap and Architecture Restructure

## Status
Proposed

## Context
At the completion of Phase 14 (Observability Platform), the historical foundation of AutoForge AI OS (Phases 1–14) is complete and frozen. This encompasses:
- Core Architecture & Foundation (Phase 1)
- Kernel & Runtime State Manager (Phases 2–3)
- Event Platform & Knowledge Platform (Phases 4–5)
- Memory Platform & AI Infrastructure (Phases 6–7)
- Connector Platform & Workflow Platform (Phases 8–9)
- Execution Platform & Review Platform (Phases 10–11)
- Artifact Platform & AI Workforce (23 specialized workers, Phases 12–13)
- Observability Platform (Phase 14)

Prior roadmap drafts contained an initial 22-phase trajectory. However, strategic analysis revealed missing architectural layers and essential commercial requirements:
1. **Top-Level Human Interface (Product Experience)**: Needs explicit architectural definition where the UI is strictly a presentation and control layer, NOT an authoritative state holder.
2. **AI Runtime & Real Model Integration**: Needs to bridge Phase 13 model policy and capacity allocation abstractions to real local and cloud inference runtimes across multi-node hardware topologies (`local-m1`, `local-hp`, and future `local-mac-mini-m6`).
3. **Continuous Learning Gated Pipeline**: Needs a mandatory verification pipeline (`Candidate → Evaluation → Benchmark → Regression → Accept/Reject → Version → Rollback → Activate`) to prevent silent self-modification.
4. **Commercial Modernization Offering**: Clarification that our initial business model is selling Legacy Modernization as a Service (with AutoForge as the internal engine), rather than selling retail software.
5. **Desktop Packaging & Distribution**: Must be distinct from UI interface design (Phase 16), packaging the complete local-first operating system (Phase 21).

To integrate these layers without losing original roadmap capabilities, creating duplicate phases, or altering historical records, a canonical 25-phase roadmap is established.

## Decision

1. **Adopt the Canonical 25-Phase Roadmap**:
   - **Phase 15**: Security & Governance Platform (Authentication, RBAC, Sandboxing, Secrets, Audit Trail, Consequential HITL Gates)
   - **Phase 16**: AutoForge Product Experience (Command Center, Workspaces, Observability UX, Self-Improvement Center)
   - **Phase 17**: AI Runtime & Real Model Integration (Live Local/Cloud Inference Adapters, Hardware Node Topologies, Zero Worker Model Hardcoding)
   - **Phase 18**: Autonomous Engineering & Modernization (Full Greenfield & Legacy Pipelines, 23 Specialized Workers, Epistemic Evidence Separation)
   - **Phase 19**: Continuous Learning & Self-Improvement (Learning Engine, Reflection, Mandatory Gated Safety Pipeline, Memory ≠ Learning)
   - **Phase 20**: Modernization Service MVP (Commercial Legacy Modernization Offering, Intake-to-Deliverables Pipeline)
   - **Phase 21**: Desktop Application & Distribution (Local-First Packaging, Process Supervision, Embedded Storage, Multi-Node Desktop)
   - **Phase 22**: Developer / Extension Platform (Plugin, Connector, Worker SDKs, Extension APIs, Marketplace)
   - **Phase 23**: Enterprise Platform (SSO, Multi-User, Enterprise RBAC, SIEM Audit, Compliance)
   - **Phase 24**: Distributed AI Operating System (Cluster Scaling, Swarm Execution, Hybrid Edge-Cloud)
   - **Phase 25**: Production Release (Optimization, Hardening, Validation, v1.0 Release)

2. **Reconciliation Mapping from Original 22-Phase Roadmap**:
   - Original Phase 15 (Security) → New Phase 15 (Security & Governance Platform)
   - Original Phase 16 (MVP Integration) → Logically partitioned across New Phases 16–20 (Product Experience, Real AI Runtime, Autonomous Engineering, Continuous Learning, Modernization Service MVP)
   - Original Phase 17 (Autonomous Engineering) → New Phase 18 (Autonomous Engineering & Modernization)
   - Original Phase 18 (Continuous Learning) → New Phase 19 (Continuous Learning & Self-Improvement)
   - Original Phase 19 (Developer Platform) → New Phase 22 (Developer / Extension Platform)
   - Original Phase 20 (Enterprise Platform) → New Phase 23 (Enterprise Platform)
   - Original Phase 21 (Distributed AI OS) → New Phase 24 (Distributed AI Operating System)
   - Original Phase 22 (Production Release) → New Phase 25 (Production Release v1.0)

3. **Standing Governance & Architectural Invariants**:
   - **UI Authority Invariant**: UI is presentation/control only; authoritative state resides in Runtime State Manager and platform services.
   - **External Framework Containment**: Temporal is an optional durable adapter; WorkflowEngine is domain authority; LangGraph/LangChain/CrewAI are excluded; Langfuse is an optional telemetry export adapter.
   - **AI Non-Authority Invariant**: AI models do not own governance, policy, state authority, HITL gates, or determinism.
   - **Centralized Model Allocation**: Workers declare capability profiles (`WorkerModelProfile`); models are selected centralized by `ModelAllocator` and `ModelRouterService`.
   - **Epistemic Separation**: Legacy analysis strictly classifies findings into `FACT`, `INFERENCE`, `HYPOTHESIS`, and `UNKNOWN`.
   - **Safety Gated Learning**: Learning Engine enforces `Candidate → Evaluation → Benchmark → Regression → Accept/Reject → Version → Rollback → Activate`.

4. **Business Architecture Invariant**:
   - AutoForge AI OS is our internal operating platform.
   - The commercial go-to-market offering is Legacy Modernization as a Service.

## Consequences

- **Positive**: Provides a single, unified, coherent roadmap with clear phase boundaries and explicit dependencies.
- **Positive**: Retains all original roadmap capabilities while formally introducing the Product Experience, Real AI Runtime, Modernization Service MVP, and Desktop Distribution layers.
- **Positive**: Protects the architecture from framework bloat, accidental state authority leaks into UI, or unverified AI self-modification.
- **Positive**: Completely preserves historical integrity of frozen Phases 1–14 and Phase 0 governance addendum.
