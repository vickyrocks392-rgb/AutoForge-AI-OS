# PHASE 19B-1 — IMPLEMENTATION TRACEABILITY MATRIX

**Gate:** 19B1-1 / 19B1-16
**Date:** 2026-10-02
**Basis HEAD:** `5d975bcfd3b32ab29ab0c8a69228913852af910f`

Gate 1 required confirming the Gate 19A definitions and tracing every decision
to an implementation location and a test. Terminology is preserved exactly from
19A; no term has been silently replaced.

---

## 1. Confirmed 19A Definitions (used verbatim)

| Term | 19A definition (source) | 19B-1 implementation |
|---|---|---|
| **experience** | Immutable, evidence-backed snapshot of one completed execution (`EXPERIENCE_MODEL.md` §3) | `ExperienceRecord` |
| **evidence** | Content-addressed pointer to an authoritative record; references not payloads (§3) | `EvidenceRef` |
| **learning signal** | Deterministic signal derived from experience; confidence computed from evidence (`LEARNING_SIGNAL_MODEL.md` §3) | `LearningSignal`, `derive_confidence()` |
| **learning candidate** | Bounded, inert proposal to change future behaviour | `LearningCandidate` |
| **authority level** | L0 observation ... L5 security/policy, no reachable edge (`LEARNING_AUTHORITY_MODEL.md` §2) | `LearningAuthority` |
| **proposal** | `LearningProposal` submitted to the certified boundary | `autoforge_security.LearningProposal` (reused, unchanged) |
| **validation** | Deterministic; authoritative; model never authoritative (`LEARNING_LIFECYCLE.md` §5.4) | `ValidationSummary`, `ValidationTruth`, `TestOutcome` |
| **promotion** | The gated lifecycle transition (NOT a memory write) — AMB-05 | **Not implemented** (Gate 11) |
| **rollback** | Deterministic pointer restore, no model reasoning (`ROLLBACK_AND_VERSIONING.md` RB-01) | **Not implemented** (deferred to 19B-2) |
| **hard constraint** | Disqualifying rule checked *before* scoring (`LEARNING_SIGNAL_MODEL.md` §2.3) | `SignalPolarity.DISQUALIFYING`, `tripped_constraints` |
| **security disqualifier** | Security outcome is never a signal; it voids the candidate (§1) | `LearningSignal.is_disqualifying` |

---

## 2. Traceability Matrix

| 19A Decision | 19B-1 Implementation Location | Test |
|---|---|---|
| **M-01** Immutable domain models | `packages/learning/src/autoforge_learning/models.py` | `test_learning_models.py` (23 tests) |
| **M-02** Durable store | **DEFERRED** — no persistence in 19B-1 (scope boundary) | — |
| **M-03** `EvidenceCollector` from real D1/D2 sources | `evidence.py::EvidenceCollector.collect` | `test_real_*`, `test_artifact_evidence_*` |
| **M-04** `ProposalGateway` → `evaluate_learning_proposal` | `gateway.py::ProposalGateway`; wired at `composition_root.py` step 9b | `test_production_path_invokes_evaluate_learning_proposal` |
| **M-05** SignalGenerator, hard constraints before scoring | `signals.py::disqualifying_signal` | `test_security_violation_is_disqualifying_*` |
| **M-06** Evidence-derived confidence (fixes GAP-06) | `signals.py::derive_confidence`; `learning_engine.py::_confidence_from_review_findings` | `test_confidence_is_zero_without_evidence`, `test_confidence_is_not_the_old_flat_constant` |
| **M-07** Deterministic `CandidateExtractor` | `learning_engine.py::_proposal_kind_for` | kinds asserted in `test_production_path_invokes_*` |
| **M-08** `RegressionEvaluator` | **DEFERRED** (no regression harness in 19B-1) | — |
| **M-09** `ExperimentHarness` | **DEFERRED / PROHIBITED** in 19B-1 | `test_8_learning_package_exposes_no_promotion_or_activation_api` |
| **M-10** `ApprovalCoordinator` via HITL | **DEFERRED** (Gate 11: no promotion) | — |
| **M-11** `PromotionResolver` atomic | **DEFERRED** (Gate 11) | — |
---

## 3. Gate 19A Gap Closure

| Gap | 19A finding | 19B-1 status | Evidence |
|---|---|---|---|
| **GAP-03** | `validation_result.get("findings", [])` — key never exists; branch permanently dead | **CLOSED** | `kernel.py::_authoritative_review_findings` reads the *real* `final_review.validation` / `final_review.approved`. Test: `test_kernel_extracts_real_review_evidence` |
| **GAP-04** | `repair_records` never supplied in production | **STILL OPEN** (out of 19B-1 scope; needs a repair-record producer) | Recorded as 19B-2 work |
| **GAP-06** | `confidence` hardcoded; `>= 0.90` gate is a tautology | **PARTIALLY CLOSED** | `derive_confidence()` is now evidence-derived, and the learning engine's per-finding confidence is evidence-derived (0.81 deterministic / 0.62 review / 0.0 none). Full removal of the legacy `>= 0.90` promotion threshold belongs to M-11 (promotion), deferred |
| **GAP-07 / AMB-01 / AMB-02** | Cross-project + fail-open memory retrieval | **AVOIDED, not fixed** | Phase 19 learning does **not** read through `KernelMemoryEngineAdapter`. The underlying adapter defect is untouched and remains a latent risk outside 19B-1 |
| **GAP-12** | Fabricated telemetry: 14 heuristics, `ALL_PASSING (1119/1119)` | **CLOSED** | `test_7_no_hardcoded_learning_metrics_remain`, `test_telemetry_*` |
| **Guardrails 0 callers** | `evaluate_learning_proposal` had **zero production callers** | **CLOSED — the gate objective** | `test_production_path_invokes_evaluate_learning_proposal` |

---

## 4. Gate-by-Gate Implementation Map

| 19B-1 Gate | Requirement | Location | Status |
|---|---|---|---|
| 0 | Baseline | `phase19/19B1-BASELINE.md` | DONE |
| 1 | Re-read 19A; traceability | this document | DONE |
| 2 | Immutable models | `models.py` | DONE |
| 3 | Evidence-backed experience | `evidence.py` | DONE |
| 4 | Fix dead extraction | `kernel.py::_authoritative_review_findings` | DONE |
| 5 | ProposalGateway, fail-closed | `gateway.py` | DONE |
| 6 | Authority invariants; no L5 | `LearningAuthority`; `LearningCandidate._never_security_authority`; gateway | DONE |
| 7 | Trust boundary; wording ≠ authority | typed `model_annotation`; `is_approved` always False | DONE |
| 8 | Project isolation | `LearningScope` mandatory `project_id` | DONE |
| 9 | Truthful telemetry | `service.py`, `models.py` | DONE |
| 10 | Test the real production path | `test_production_learning_path.py` | DONE |
| 11 | No promotion yet | gateway has no promotion API | DONE |
| 12 | Regression protection | full CI sweep | DONE |
| 13 | Test matrix | 119 tests | DONE |
| 14 | Full validation | 18 package suites + api | DONE |
| 15 | Architecture integrity | `test_architecture_integrity.py` (12 invariants) | DONE |
| 16 | Documentation | 4 reports | DONE |
| **M-12** Deterministic rollback | **DEFERRED** (Gate 11) | — |
| **M-13** Versioning on `packages/artifacts` | **DEFERRED** with M-11 | — |
| **M-14** Audit + redaction | **DEFERRED** — existing `AuditEngine` untouched; no parallel audit created | `test_12_completion_artifact_review_contracts_untouched` |
| **M-15** Project-scoped reads only | `LearningScope` (mandatory `project_id`) | `test_project_a_scope_never_matches_project_b` |
| **M-16** Truthful telemetry (fixes GAP-12) | `service.py::get_self_improvement_center`; `models.py::SelfImprovementResponse` | `test_telemetry_*` (4 tests) |
| **M-17** First learning target | **DEFERRED** (needs L3/L4 gates first) | — |
| **M-18** Full test suite | `packages/learning/tests/` (119 tests) | all |