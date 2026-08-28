# AutoForge Security & Governance Platform (`autoforge-security`)

Deterministic, authoritative security and governance subsystem for AutoForge AI OS (Phase 15).

## Core Architectural Invariant
Security & Governance sits strictly above all workers, workflows, execution engines, and models:
```
Human Authority
      ↓
Security & Governance Platform (autoforge-security)
      ↓
Deterministic Platform Policy
      ↓
Workflow & Execution Engines
      ↓
Workforce (23 Specialized Workers)
      ↓
AI Runtime & Models
```

AI models and autonomous workers are **never** security authorities. They cannot self-authorize, self-approve consequential actions, bypass HITL gates, weaken policies, or access secrets outside their granted scope.

## Key Subsystems
1. **Authentication & Identity**: Subject abstraction (`HUMAN`, `SERVICE`, `WORKER`), token issuance & validation, brute force defense.
2. **Authorization & RBAC**: Fine-grained permission model (`project.*`, `workspace.*`, `architecture.*`, `deployment.*`, `migration.*`, etc.) and canonical roles.
3. **Governance Policy Engine**: Deterministic policy evaluation (`ALLOW`, `DENY`, `REQUIRE_HITL`, `REQUIRE_ELEVATED_ROLE`, `REQUIRE_ADDITIONAL_CONTEXT`) gating consequential actions.
4. **HITL Gatekeeper**: Mandatory human-in-the-loop gating for consequential actions with replay protection, expiry, and resume tokens.
5. **Secrets & Credentials Management**: Centralized scoped access, automatic deep redaction from logs/telemetry/prompts, and pluggable encrypted storage adapters.
6. **Sandboxing Policies**: Workspace confinement, path traversal prevention, and dangerous command filtering.
7. **Audit Trail**: Immutable audit records correlated with project, workflow, task, worker, execution, and trace IDs.
8. **Workforce Guardrails**: Security profiles and enforcement across all 23 specialized workers.
