# ADR-005: Memory ≠ Learning Boundary (Specification Amendment)

**Date:** 2026-08-26

**Status:** Accepted (amendment to Memory Platform Specification v1.0 framing)

---

#### Context

The frozen Memory Platform Specification v1.0 contains wording that can blur
the distinction between Memory and Learning. The reconciliation audit warns
that casually rewriting frozen specifications is unacceptable, but leaving
the ambiguity in place risks a future Memory implementation that silently
extracts patterns or changes platform behaviour — i.e. Learning smuggled in
through the back door.

---

#### Decision

The four concepts are delimited as follows and ALL future specifications,
ADRs, and implementations MUST respect this boundary:

| Concept | Definition | Owner |
|---|---|---|
| **Memory** | Preserves and recalls experience/context | Memory Platform |
| **Learning** | Extracts patterns from experience and changes FUTURE BEHAVIOUR | Learning Engine (future) |
| **Model Training** | Changes model parameters (weights/adapters) | Model Training pipeline (future) |
| **Self-Improvement** | Evaluates candidate changes to AutoForge itself and ADOPTS measurable improvements through the gated pipeline: `candidate → evaluation → benchmark → regression → accept/reject → version → rollback` | Self-Improvement Engine (future) |

Specifically:

1. The **Memory Platform remains responsible for memory only**: retention
   policy, qualification, storage, recall. Any specification sentence that
   reads as "memory improves future behaviour" must be interpreted as
   *memory makes past experience AVAILABLE to future behaviour*, not that
   memory performs pattern extraction.
2. The **Learning Engine** (future) is the ONLY subsystem permitted to
   extract patterns and modify behaviour, consuming Engineering Experience
   read models (ADR-004) and memory recall as inputs.
3. **Model Training** operates on model parameters only; it never edits
   platform behaviour directly.
4. **Self-Improvement** never modifies behaviour without passing the gated
   pipeline with regression evidence; it is governed by the Kernel's
   approval flow for risky operations.
5. The **Kernel coordinates** all of these; it does not learn.

This ADR amends the interpretation of Memory Platform Specification v1.0
wording WITHOUT rewriting the frozen document.

---

#### Consequences

- Reviewers have a citable boundary when evaluating Memory/Learning PRs.
- Memory Platform implementation (future phase) has a crisp non-goal list:
  no pattern extraction, no behaviour modification, no parameter updates.

---

#### Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Rewrite the frozen Memory Platform Specification in place | Frozen specs must be amended via ADR, never silently rewritten |
| Leave the ambiguity and resolve it during implementation | Ambiguity would compound across Worker/Memory/Learning builds |
