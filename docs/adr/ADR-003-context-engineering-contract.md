# ADR-003: Context Engineering Contract (Architecture Only)

**Date:** 2026-08-26

**Status:** Accepted (contract only — no implementation in Phase 0)

---

#### Context

Context Engineering is a first-class future AutoForge capability. The
Knowledge Platform already contains a knowledge-scoped `ContextAssembler`,
and the frozen Memory Platform specification describes memory recall
capabilities. Without an explicit contract, a future Context Engine could
accidentally duplicate Knowledge or Memory responsibilities, or become a
second retrieval/trust/storage authority.

Phase 0 explicitly forbids implementing the Context Engine. This ADR fixes
the minimum architectural contract so the future Worker implementation
composes capabilities instead of duplicating them.

---

#### Decision

The future **Context Engine** is defined as a STATELESS-ISH ASSEMBLY SERVICE
with exactly these responsibilities:

1. **Gathers candidate context** from capability providers.
2. **Scores and selects relevance** for the current task/stage.
3. **Removes redundancy** across sources (deduplication).
4. **Respects context/token budgets** (model-aware budgeting).
5. **Preserves critical errors** (failures are never silently dropped from
   context).
6. **Tracks provenance** of every included item.
7. **Is model-aware** (token limits, formatting preferences).
8. **Produces structured model context** as its output artifact.

It CONSUMES capabilities from (and must not re-implement):

| Source | Capability consumed |
|---|---|
| Knowledge Platform | knowledge retrieval, trust scoring, fusion, citation |
| Memory Platform | memory storage, qualification, recall |
| Repository Intelligence | repository index/symbols/diffs/test discovery |
| Tool / terminal observations | normalized tool results |
| Runtime / task state | authoritative state reads via Runtime interfaces |
| Git state | repository status through tooling |
| Test / compiler output | verification observations |

It MUST NOT own: knowledge retrieval infrastructure, trust scoring, memory
storage or retention policy, repository state, runtime state, or model
implementation.

---

#### Consequences

- The Knowledge Platform's existing assembler remains the
  knowledge-scoped slice; the Context Engine composes it rather than
  replacing it.
- Future Worker code requests `context.assemble(stage=...)` instead of
  reaching into Knowledge/Memory internals directly.
- Any future implementation must preserve provenance and budgets in its
  output contract to be compliant with this ADR.

---

#### Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Build the full Context Engine now | Explicitly out of Phase 0 scope |
| Extend the Knowledge Platform to cover general context | Would blur knowledge vs general model-context ownership (audit §16) |
