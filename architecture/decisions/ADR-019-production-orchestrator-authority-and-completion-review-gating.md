# ADR-019: Production Orchestrator Authority and Completion Review Gating

**Status:** Accepted
**Date:** 2026-09-28
**Authors:** AutoForge AI Platform Team
**Supersedes:** nothing. **Amends:** the completion-validation behaviour implemented in `packages/kernel/src/autoforge_kernel/completion.py`
**Gate:** P-1 (post-Brain-cleanup production review-gating defect repair)
**Re-verified:** 2026-10-02 against `2c5c950`. All architectural decisions (D-1,
D-2, D-3, the review contract, and the evidence contract) were confirmed
**current against live source**. No architectural decision was altered. The only
stale content was point-in-time measurement in the *Verification* section and a
few line references that point at *historical* defect sites; both are now
labelled as such.

---

## Context

The repository contains **three** orchestration-capable implementations:

| ID | Class | Location | Status |
|---|---|---|---|
| **O-1** | `autoforge_orchestration.OrchestrationEngine` | `packages/orchestration/src/autoforge_orchestration/orchestrator.py` | Real, certified, tested — **production-unwired** |
| **O-2** | `autoforge_kernel.orchestration.DefaultOrchestrationEngine` | `packages/kernel/src/autoforge_kernel/orchestration.py` | **Production-authoritative** |
| **O-3** | `autoforge_api.build_engine.AutonomousBuildEngine` | `apps/api/src/autoforge_api/build_engine.py` | Production API path, parallel to the Kernel |

`build_autoforge_system()` (`packages/composition/src/autoforge_composition/composition_root.py`)
constructs only **O-2**. A constructor search across all non-test production
source returns no instantiation of O-1; it is exercised exclusively by its own
test suites and by two independent live certifications
(`docs/reports/PHASE-18-B-FORENSIC-CERTIFICATION.md`, `PHASE-18-D-LIVE-CERTIFICATION.md`).

Git history establishes that O-1 is **layered, not competing**: Kernel v1.0 was
frozen in `02ab81e` (2026-07-31), and O-1 was created in `b1b9709` (2026-08-30),
a month later, to deliver Phase 18-A..18-F capability. `git merge-base
--is-ancestor 02ab81e b1b9709` returns true.

### The defect

The production completion path was:

*(Line numbers below are as observed at decision time. The defect sites have
since moved; the defect was repaired and the repair is described under
*Decision* below.)*

```
Kernel.execute_project()                     kernel.py:464
  -> completion_module.finalize_project()     completion.py
     -> validate_completion()                 (pre-existing criteria)
     -> review_engine.review_project(...)     completion.py:217
        -> verdict DISCARDED                  completion.py:218
        -> `except Exception: pass`           completion.py:219-221
     -> transition_state("Finished")          unconditional
```

The final review was therefore **advisory**. `review_project` was the only
review invocation in `packages/kernel/src/`, its result was assigned to a local
variable and never read again, and exceptions were swallowed.

This contradicted the canonical architecture:

- `architecture/ARCHITECTURE.md:686` — the Review Engine "**is the quality gate
  of the platform**".
- `architecture/ARCHITECTURE.md:698` — artifacts that fail review are returned
  to the originating worker; those that pass are forwarded.
- `docs/subsystems/kernel/KERNEL_SPECIFICATION.md:620` — the Completion Module
  owns a "**Quality Gate Enforcer**" that "Ensures all quality gates passed".
- `KERNEL_SPECIFICATION.md:628` — the Completion Module "Invokes Review Engine
  for final review".
- `KERNEL_SPECIFICATION.md:2917-2920` — completion requires "**All quality gates
  passed / All reviews approved / All tests passed**".
- `KERNEL_SPECIFICATION.md:2952-2956` — on validation failure, remediate and
  repeat validation.
- `architecture/MANIFEST.md:17` — an implementation that deviates from the
  specification is incorrect until the specification is amended through the
  proper review process.

This gate **restores the existing contract**. It does not introduce a new review
model.


---

## Decision

### D-1 — Production orchestrator and enforcement point

**O-2 (`DefaultOrchestrationEngine`) remains the sole production-authoritative
orchestrator.** The completion review gate is enforced at the existing Kernel
completion boundary, `DefaultCompletionModule.finalize_project`.

`finalize_project` is the canonical enforcement point because it is the only
Kernel boundary that (a) already invokes the final review per
`KERNEL_SPECIFICATION.md:628`, (b) already has a failure return contract
(`{"success": False, ...}`) consumed by `Kernel.execute_project` at
`kernel.py:465`, and (c) already owns the transition to the `Finished` state.
Enforcing there required no new state model, no new adapter layer, no new
dependency, and **no change to any Kernel ABC**.

Explicitly **not** done: O-1 is not wired into production, is not made to
implement the Kernel ABCs, and `composition_root.py` is not rewired to O-1.

### D-2 — Disposition of O-1

O-1 **remains production-unwired, intact, and undeleted**. It is a real,
certified parallel orchestration implementation. Its
`KernelReviewEngineAdapter.review(artifact, criteria)` versus
`review(request)` arity mismatch (audit finding **R-2**) is **confined to O-1**,
is therefore **non-production**, and is **intentionally deferred**. It is not
repaired here because O-1 is not on the production path, and repairing it would
be speculative cleanup of a certified subsystem.

R-5 — the existence of O-1 as a production-unwired parallel orchestrator —
remains a **deliberate architectural follow-up requiring a separate ADR**, not an
implementation change. Neither retention, deprecation, nor merge is decided here.

### D-3 — Quality-gate absence semantics

The generic `state["quality_gates"]` list is **not** the platform quality gate;
`ARCHITECTURE.md:686` assigns that role to the Review Engine. A blanket "all gates
must exist" rule would therefore have contradicted legitimate gate semantics
(most projects record no generic gate list) and broken existing behaviour.

The vacuous-success risk is instead closed where it is real:

- `validate_completion` now reports `quality_gates_vacuous` (true when no gate
  evidence exists) and `final_review_required`, so an empty list can no longer
  read as real gate evidence.
- The **mandatory** gate is the final review, enforced in `finalize_project`.
  Absence of a configured review engine fails closed, because the mandatory
  evidence is then absent.

### Review contract

`KernelReviewEngineAdapter.review_project` returns a `dict` with `approved`,
`decision`, `status`, `findings`, and `findings_count`. `evaluate_final_review_result`
normalises that contract (and an equivalent object shape) to
`(approved, reason)`. No new enum is introduced; the existing
`autoforge_review.models.ReviewDecision` values are used as literals so the
Kernel keeps its ADR-002 dependency direction and does not import
`autoforge_review`.

**Only an explicit approval permits completion.** `rejected`,
`changes_requested`, and `requires_hitl` block it. `None`, malformed results, a
non-boolean approval flag, a contradictory result, a raised exception, and a
missing review engine all **fail closed**.

Failures participate in the existing `{"success": False, ...}` completion-failure
contract; the project does not reach `Finished` and no `project.finished` event
is published.

### Scope limits

This ADR does **not** authorize or begin: Brain, Phase 19, inference topology
changes, Context Engineering, Context Compaction, 18-J, 18-K, provider or
commercial-engine redesign, or model-routing changes. Phase 19 remains strictly
gated on 18-L per `architecture/ROADMAP.md:1248`.

---

## Consequences

**Positive.** Production completion now honours the documented quality gate.
A failed, missing, or uninterpretable final review can no longer produce a
successful completion. The invariant is pinned by
`packages/kernel/tests/test_completion_review_gate.py`.

**Compatibility.** Three existing tests asserted successful completion without a
real approving review and encoded the defective advisory behaviour. They were
updated to supply the now-mandatory explicit approval. No assertion was weakened
and no production path was weakened.

**Follow-up.** O-1's disposition (D-2 / R-5) requires a separate architectural
decision. R-2 remains deferred and non-production.

---

## Verification

Re-verified 2026-10-02 against `2c5c950`. The **architectural** claims above are
all confirmed current. The **counts** below are the measurements taken at
decision time and are labelled as such; current values are given alongside.

- `packages/kernel/tests/test_completion_review_gate.py` — 35 tests covering
  approval, every non-approving decision, exception, `None`, malformed results,
  missing review engine, quality-gate absence, preserved failure semantics, and
  the O-2-authoritative / O-1-unwired invariants.
  **Re-verified: still 35 passed** — the invariant is pinned exactly as claimed.
- `packages/kernel/tests/` — 135 passed *(at decision time)*.
  **Currently 161 passed** (the suite has grown; the gate itself is unchanged).
- `packages/orchestration/tests/` — 71 passed, 6 skipped *(at decision time)*.
  **Currently 101 passed, 6 skipped** — unchanged by O-1 remaining intact.

### Known open consequence (STOP CONDITION 7 — see gate report)

Making the gate authoritative exposed a **pre-existing latent defect** that the
advisory review had been masking: the production final review is invoked with
**no evidence**, so `KernelReviewEngineAdapter._execute_review` injected a
synthetic placeholder file. *(Line reference `kernel_adapters.py:334-335` is as of
decision time; the site has since moved and the placeholder has since been
removed — see the Addendum below.)*
`{"manifest.json": "{}"}`. That placeholder defeats the Review Engine's own
explicit vacuous-pass branch (`engine.py:180-201`, which returns
`APPROVED`/`no_target` for genuinely empty evidence) and instead produces a real
`high / documentation / "Required Files"` finding, yielding
`decision=changes_requested`.

Consequently two certified end-to-end tests now correctly fail closed:

- `packages/composition/tests/test_architecture_reconciliation_e2e.py::test_end_to_end_kernel_request_lifecycle`
- `packages/composition/tests/test_canonical_learning_lifecycle.py::test_canonical_learning_lifecycle_wired_and_invoked`

The gate is behaving as specified; the defect is that the final review is not
being given the project's real artifacts. Resolving this requires a deliberate
decision about **what evidence the final project review must evaluate and from
which authoritative source**, and is therefore **out of scope for this gate**
(it would alter the review evidence contract, and any fix touching artifact
collection would reach 18-K territory). It is recorded as **DEF-P1-EVIDENCE**
and must be resolved before 18-L.

---

## Addendum — DEF-P1-EVIDENCE Resolution (subsequent gate)

DEF-P1-EVIDENCE is **RESOLVED**. The findings above are superseded by the
evidence contract established below; they are retained for traceability.

### Evidence contract

The final review is given the project's **real, durable artifacts**:

- **Authoritative source:** the existing 18-K `DurableArtifactCatalog` +
  `PhysicalArtifactStore` (staged write -> SHA-256 -> atomic publish -> commit).
  No second artifact system and no new persistence model was introduced; the
  catalog is only *read* via `find_by_workflow`.
- **Correlation:** execution artifacts carry `workflow_id` in their provenance.
  The Kernel now persists its planned workflow identity into the authoritative
  Runtime state through the **already-declared** `RuntimeStateManager.update_project`
  API (`interfaces.py:211`), which projects `project.metadata` into
  `ProjectState.configuration`. Previously the correlation existed only in the
  Kernel's in-memory `active_projects` map and was lost on restart, so no
  project-scoped evidence could ever be resolved.
- **Collection boundary:** `FinalReviewEvidenceCollector` in
  `packages/kernel/src/autoforge_kernel/completion.py`. It returns
  `{artifact_name: content}` for **COMMITTED** artifacts only, so staged or
  failed artifacts are never presented as deliverables.
- **Placeholder removed:** `KernelReviewEngineAdapter._execute_review` no longer
  manufactures `{"manifest.json": "{}"}`. Genuinely empty evidence now reaches
  the Review Engine unmodified, so its own explicit `no_target` branch runs.

### Review semantics were NOT weakened

Verified empirically against the real `ReviewEngine`:

| Evidence | Decision |
|---|---|
| Real deliverable with `README.md` + code + tests | **`approved`** |
| Real deliverable without `README.md` | `changes_requested` (`Required Files`) |
| Genuinely empty evidence | `approved` / `no_target` (documented branch) |

The `Required Files` / documentation check still functions, and a project that
fails it still blocks completion.

### Verification

- `packages/composition/tests/test_final_review_evidence_e2e.py` — 9 end-to-end
  tests over the real path.
- `packages/composition/tests/review_evidence_helpers.py` — registers a real
  deliverable through the authoritative 18-K durable artifact API.
- Full CI matrix green: **0 failures, 0 collection errors** *(at decision time)*.

  *Re-verification note (2026-10-02): the architectural invariant is unchanged,
  and both suites this ADR cites still pass in full (`packages/kernel` 161 passed;
  `packages/orchestration` 101 passed, 6 skipped). The repository now carries 4
  environment-only failures caused by an unrelated local process on
  `127.0.0.1:8080`; these reproduce at pristine baseline and are not product
  defects.*
