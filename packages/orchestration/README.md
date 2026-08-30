# AutoForge Orchestration Platform — Phase 18

The Phase 18 orchestration layer for AutoForge AI OS. It makes the complete
autonomous engineering machinery real:

- **Greenfield:** Idea → Intent → Research → Planning → Architecture → Design
  → Implementation → Testing → Evaluation → Diagnosis → Repair →
  Reimplementation → Retesting → Review → Artifact → Deployment.
- **Legacy Modernization:** Discovery → Archaeology → Architecture
  Reconstruction → Business Rules Extraction → Dependency Analysis →
  Modernization Architecture → HITL → Migration → Testing → Equivalence
  Validation → Validation → Cutover → Deployment.

It composes the existing platform (23-worker workforce, model router,
review engine, artifact platform, security, observability, event platform)
with a durable project execution state machine, capability-driven worker
assignment, model/node routing provenance, bounded rectification loops,
evaluation gates, diagnosis, HITL gates, deployment truthfulness, and
project execution metrics.

Design invariants:
- UNKNOWN IS BETTER THAN WRONG.
- No fabricated worker/model/node/telemetry/artifact state.
- All important autonomous decisions carry provenance.
- Every autonomous loop is bounded; no infinite loops.
- No silent self-modification of AutoForge.
- The frozen UI is untouched.