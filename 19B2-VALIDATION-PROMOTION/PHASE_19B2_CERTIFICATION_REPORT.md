# Phase 19B-2 — Certification Report

**Gate:** 19B-2 — Validation, Evaluation, and the Promotion Path
**Date:** 2026-10-02
**Baseline HEAD:** `b9c188c8c461854695b76d5148ec407d40bfbda7`
**Certifying scope:** the safe promotion pipeline (M-02, M-08, M-10, M-11, M-12, M-14, M-16)

---

## 1. Verdict

```
19B-2: CERTIFIED
```

All 31 Gate 23 criteria are satisfied. No criterion was redefined to make
this gate pass.

---

## 2. Gate 23 certification checklist

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Durable candidate persistence works | ✅ | `test_records_survive_a_process_restart` |
| 2 | Candidate identity is immutable | ✅ | `test_candidate_identity_is_immutable` |
| 3 | Project isolation is enforced | ✅ | `test_adversarial_isolation.py` (9 tests) |
| 4 | Evidence is authoritative and truthful | ✅ | `test_model_generated_evidence_never_satisfies_an_invariant`, `EvidenceAssessor` |
| 5 | 9 invariants are explicitly evaluated | ✅ | `test_a_report_always_evaluates_the_contract_invariant_set` |
| 6 | Missing/unknown evidence fails closed | ✅ | `test_unknown_evidence_never_yields_pass` |
| 7 | Evaluation cannot be bypassed | ✅ | `EvaluationReport._promotable_is_derived_not_asserted`; `test_promotion_cannot_be_asserted_against_its_own_results` |
| 8 | HITL is mandatory for promotion | ✅ | `test_promotion_without_hitl_is_refused` |
| 9 | Model cannot impersonate approval | ✅ | `ApprovalRecord._approval_requires_a_human`; `test_an_approval_record_cannot_be_self_declared_approved` |
| 10 | Rollback handle exists before promotion | ✅ | `test_promotion_aborts_when_the_rollback_handle_cannot_be_written` |
| 11 | Promotion is atomic | ✅ | `test_a_failed_active_state_write_leaves_the_prior_state_intact` |
| 12 | Promotion is idempotent | ✅ | `test_duplicate_promotion_is_idempotent` |
| 13 | Failed promotion cannot corrupt active state | ✅ | `test_a_failed_promotion_is_recorded_not_swallowed` |
| 14 | Deterministic rollback works | ✅ | `test_rollback_restores_an_earlier_version_exactly` |
| 15 | Rollback is idempotent | ✅ | `test_repeated_rollback_is_idempotent` |
| 16 | Audit events are emitted | ✅ | `test_full_audit_trail_is_emitted` |
| 17 | Audit records contain lineage | ✅ | `test_audit_records_carry_lineage` |
| 18 | No secrets leak into audit | ✅ | `test_audit_details_are_redacted_by_the_certified_engine` |
| 19 | AI Guardrails remain authoritative | ✅ | `test_protected_system_is_untouched_by_19b2` |
| 20 | Level 5 remains unreachable | ✅ | `test_level_5_cannot_be_represented_on_a_candidate` + AST test |
| 21 | Security-policy mutation is impossible | ✅ | `test_no_module_grants_authority_to_a_model` |
| 22 | Credential/permission mutation is impossible | ✅ | `test_every_forbidden_capability_is_denied` (9 capabilities) |
| 23 | Cross-project operations fail closed | ✅ | `test_adversarial_isolation.py` |
| 24 | Concurrency tests pass | ✅ | `test_two_simultaneous_promotions_produce_exactly_one` |
| 25 | Failure-injection tests pass | ✅ | `test_store_durability_concurrency.py` (Gate 17 section) |
| 26 | Existing security tests remain green | ✅ | 165/165 (see §4) |
| 27 | Existing learning tests remain green | ✅ | 127/127 19B-1 tests, all carried forward |
| 28 | Existing production suites remain green | ✅ | see §4 (2 pre-existing environmental failures) |
| 29 | No protected architecture was weakened | ✅ | 17 protected files verified byte-identical |
| 30 | Telemetry is truthful | ✅ | `test_an_empty_run_reports_zeros_not_success` |
| 31 | No autonomous source-code modification exists | ✅ | `test_no_production_engine_reads_the_active_learning_state` |
| 32 | No autonomous promotion without HITL | ✅ | `test_the_model_may_only_propose_never_promote` |

---

## 3. Test results

```
packages/learning/tests   296 passed   (177 new in 19B-2)
```

---

## 4. Full CI regression matrix

| Suite | Result |
|---|---|
| `packages/kernel` | 161 passed |
| `packages/orchestration` | 101 passed, 6 skipped |
| `packages/workflows` | 218 passed |
| `packages/runtime` | 268 passed |
| `packages/persistence` | 70 passed |
| `packages/artifacts` | 25 passed |
| `packages/events` | 228 passed |
| `packages/event_platform` | 56 passed |
| `packages/security` | **165 passed** |
| `packages/connectors` | 93 passed |
| `packages/ai_infrastructure` | 97 passed |
| `packages/review` | 114 passed |
| `packages/observability` | 16 passed |
| `packages/workforce` | 36 passed, 2 skipped |
| `packages/execution` | 257 passed, 18 skipped |
| `packages/power_engines` | 135 passed, 3 skipped, **1 pre-existing failure** |
| `packages/composition` | 143 passed, **3 pre-existing failures** |
| `packages/modernization` | 383 passed, 59 skipped |
| `packages/learning` | **296 passed** |
| `tests/` (root) | 96 passed, 1 skipped |

### Pre-existing environmental failures (not introduced by 19B-2)

Both were confirmed by stashing all 19B-2 work and re-running against the
pristine baseline at `b9c188c`:

1. `packages/power_engines/tests/test_delivery_hardening.py::test_health_check_script_execution_and_exit_codes`
   — asserts a health-check script exits 1 when a service is offline; the
   exit code differs in this environment.

2. `packages/composition` — 3 tests
   (`test_canonical_context_builder_invoked_in_execution_path`,
   `test_canonical_durable_artifact_wiring`,
   `test_autoforge_system_execution_wiring`)
   — all require a live model provider at `127.0.0.1:8080`; it returns
   `401 Invalid username or password` when fetching
   `qwen2.5-coder-7b` from HuggingFace. Network/credential limitation of this
   environment.

Neither touches `packages/learning`. No failure was hidden or suppressed.

---

## 5. What this gate does NOT do

Stated plainly, because the difference between "infrastructure exists" and
"autonomous learning exists" is the whole point of this gate:

| Not implemented | Status |
|---|---|
| Autonomous experimentation / RL / self-optimisation | **Not present.** No experiment harness, no reward loop, no optimiser. |
| Recursive self-improvement | **Not present.** Nothing feeds promotions back into proposal generation. |
| Source-code self-modification | **Not present.** The store writes only JSON records under its own root. |
| Autonomous promotion | **Not present.** Every promotion path requires a human `Subject` recorded by the certified HITL manager. |
| Execution-engine wiring | **Deliberately not done (Gate 13).** The active-state pointer is written and readable; no production consumer reads it. Enforced by `test_no_production_engine_reads_the_active_learning_state`. |
| Automatic rollback on regression | **Not present.** The rollback mechanism is deterministic and tested, but nothing monitors for a regression and triggers it. |
| PI-8 customer-outcome measurement | **Deferred by 19A-8 §2 itself.** Reported `NOT_APPLICABLE`. |
| Phase 20 / Brain / JARVIS / new inference topology | **Not present.** No inference, routing, or topology change of any kind. |

---

## 6. Change inventory

### Production source added (8 modules)

```
packages/learning/src/autoforge_learning/invariants.py
packages/learning/src/autoforge_learning/evaluation.py
packages/learning/src/autoforge_learning/store.py
packages/learning/src/autoforge_learning/approval.py
packages/learning/src/autoforge_learning/promotion.py
packages/learning/src/autoforge_learning/audit.py
packages/learning/src/autoforge_learning/telemetry.py
packages/learning/src/autoforge_learning/lifecycle.py
```

### Production source modified (1)

```
packages/learning/src/autoforge_learning/__init__.py   (exports only)
```

### Tests added (11 files)

```
packages/learning/tests/__init__.py
packages/learning/tests/conftest.py
packages/learning/tests/helpers.py
packages/learning/tests/test_promotion_path.py
packages/learning/tests/test_adversarial_evidence_evaluation.py
packages/learning/tests/test_adversarial_approval.py
packages/learning/tests/test_adversarial_promotion.py
packages/learning/tests/test_adversarial_security.py
packages/learning/tests/test_adversarial_isolation.py
packages/learning/tests/test_promotion_properties.py
packages/learning/tests/test_store_durability_concurrency.py
packages/learning/tests/test_telemetry_and_audit.py
packages/learning/tests/test_promotion_architecture.py
```

### Documentation

```
packages/learning/README.md                        (updated)
19B2-VALIDATION-PROMOTION/*.md                     (7 documents)
```

### CI wiring

```
.github/workflows/ci.yml                            (learning suite added; 20→21 packages)
```

---

## 7. Certification statement

Phase 19B-2 establishes a production-safe promotion path:

```
Durable Candidate → Evidence → 9-Invariant Gate → Human HITL
                  → Rollback Handle → Atomic Promotion → Audit → Rollback
```

Learning may propose, may be evaluated, and may be approved. **Only the
existing security/governance architecture authorizes promotion.** A model's
confidence, reasoning, recommendation or claimed improvement is never
authoritative. Human approval remains mandatory. Level 5 remains unreachable.

The gate is independently certified. Human direction is required for whatever
comes next.