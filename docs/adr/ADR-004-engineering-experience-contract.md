# ADR-004: Engineering Experience Contract (Read Model)

**Date:** 2026-08-26

**Status:** Accepted (contract only — no implementation in Phase 0)

---

#### Context

AutoForge's long-term vision requires learning from engineering trajectories:

> AUTONOMOUS ENGINEERING → ENGINEERING EXPERIENCE → MEMORY → EVALUATION →
> LEARNING → GATED SELF-IMPROVEMENT

"Engineering Experience" is a new architectural concept. Without a canonical
definition there is a risk of building a giant Experience database/subsystem,
or of Runtime absorbing experience ownership, or of premature trajectory
storage designed before any consumer exists.

Phase 0 forbids implementing Learning, model training, or a trajectory
database. This ADR defines the minimum canonical READ-MODEL contract.

---

#### Decision

An **Engineering Experience** is a read-oriented, provenance-aware,
correlation-aware composition representing one engineering trajectory:

```
Task → Repository State → Context → Plan/Decision → Tool Actions
     → Code/Artifact Changes → Tests → Failures → Diagnosis
     → Repairs → Final Outcome → Metrics
```

Properties:

1. **Read-oriented** — experiences are projections; nothing writes to
   authoritative stores through this concept.
2. **Composable from existing authoritative sources**:
   - canonical events (`autoforge_events` history)
   - Runtime state transition history and checkpoints
   - artifacts and execution records
   - test results and failure records
   - metrics
3. **Provenance-aware** — every element references its source record(s).
4. **Correlation-aware** — elements are grouped by canonical correlation IDs
   so one task/attempt/repair chain reconstructs deterministically.
5. **Export-friendly** — serializable to self-contained records suitable for
   future evaluation harnesses and trajectory datasets.
6. **Suitable for evaluation** — outcomes and metrics must be attributable
   to decisions and actions.

Ownership:

- **Runtime does NOT own Engineering Experience.**
- No trajectory database is created in Phase 0.
- A future subsystem (post-Learning-roadmap) may materialize experiences;
  until then the contract exists so event/state/artifact producers emit
  sufficiently correlated, provenance-rich records.

---

#### Consequences

- Producers today already satisfy most requirements: canonical events carry
  correlation/causation; runtime keeps transition history and checkpoints;
  failures carry structured records.
- Gaps identified for future phases: durable event persistence, richer
  artifact/execution linkage. These belong to later roadmap work, NOT
  Phase 0.

---

#### Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Create an Experience database now | Premature storage without consumers; explicit scope creep |
| Let Runtime own experience projection | Violates ownership boundaries (Runtime = state authority only) |
| Fold experience into Memory Platform | Memory preserves/recalls; it must not become a training-data pipeline (see ADR-005) |