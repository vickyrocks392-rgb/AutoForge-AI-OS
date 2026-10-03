# PHASE 19B-3 — TRACEABILITY MATRIX

**Gate:** 19B3-39
**Date:** 2026-10-03
**Base commit:** `81ec8235bdcc4c272be43ba976adc1038501938c`

---

## 1. Gate → Implementation → Test

| Gate | Requirement | Implementation | Tests |
|---|---|---|---|
| **34** | End-to-end learning lifecycle | `lifecycle.py` (19B-2) + `learning_system.py` | `test_gate34_*` (3) |
| **35** | Source-code self-improvement | `codemod.py` | `test_gate35_*` (2) + `test_19b3_codemod.py` (42) |
| **36** | Bounded multi-generation recursion | `recursion.py`, `runtime.py` | `test_gate36_*` (4) |
| **37** | RL / reward-driven experiments | `rewards.py`, `experiments.py` | `test_gate37_*` (2) |
| **38** | Automatic rollback | `monitoring.py`, `activation.py` | `test_gate38_*` (3) |
| **39** | Adversarial matrix | all modules | `test_19b3_adversarial.py` (77) |

---

## 2. Module → Test Coverage

| Module | Lines | Primary test file | Tests |
|---|---:|---|---:|
| `experience.py` | 266 | `test_19b3_models.py`, adversarial | 12 + |
| `extraction.py` | 263 | `test_19b3_extraction.py` | 6 |
| `hypothesis.py` | 222 | `test_19b3_models.py`, adversarial | 12 + |
| `experiments.py` | 388 | `test_19b3_experiments.py` | 18 |
| `rewards.py` | 318 | `test_19b3_reward_and_optimization.py` | 37 |
| `optimization.py` | 223 | `test_19b3_reward_and_optimization.py` | (shared) |
| `recursion.py` | 226 | `test_gate36_*`, adversarial | 4 + |
| `codemod.py` | 274 | `test_19b3_codemod.py` | 42 |
| `activation.py` | 266 | `test_19b3_activation_and_monitoring.py` | 38 |
| `monitoring.py` | 282 | `test_19b3_activation_and_monitoring.py` | (shared) |
| `continual.py` | 330 | `test_19b3_continual.py` | 15 |
| `transfer.py` | 214 | `test_19b3_transfer_and_governance.py` | 37 |
| `effectiveness.py` | 282 | `test_19b3_transfer_and_governance.py` | (shared) |
| `runtime.py` | 231 | adversarial | (shared) |
| `recovery.py` | 193 | adversarial | (shared) |
| `governance.py` | 178 | `test_19b3_transfer_and_governance.py` | (shared) |
| `learning_system.py` | 228 | `test_19b3_e2e_learning.py` | 13 |
| **Total** | **4 058** | | **295** |

---

## 3. Security Invariant → Enforcement Point → Test

| Invariant | Enforcement point | Test |
|---|---|---|
| Authority is external | `ProposalGateway` → `AIGuardrailsEngine` | `test_learning_cannot_grant_itself_a_permission` |
| Forbidden capabilities denied | `AIGuardrailsEngine.evaluate_learning_proposal` | `test_learning_cannot_request_any_forbidden_capability[x9]` |
| Reward carries no authority | `Reward` model shape | `test_a_reward_with_no_provenance_is_rejected` |
| Reward suppressed in decisions | `ExperimentEngine.run` | `test_gate37_a_high_reward_cannot_override_deterministic_safety` |
| Deterministic validation outranks reward | `RewardLedger.aggregate` | `test_gate37_a_reward_conflicting_with_validation_is_clamped` |
| Recursion cannot widen scope | `assert_no_authority_expansion` | `test_recursion_widening_scope_is_refused` |
| Recursion cannot widen capability | `assert_no_authority_expansion` | `test_recursive_authority_escalation_is_refused` |
| Protected paths immutable | `CodeChangeProposal._is_protected` | `test_every_protected_component_is_immutable_by_learning[19]` |
| Protected denial precedes scoring | `CodeChangeGatekeeper.assert_permitted` | `test_credential_exfiltration_is_denied_before_scoring` |
| No self-authorization | `MANDATORY_GATES[promotion_authorization]` | `test_a_candidate_cannot_authorize_its_own_promotion` |
| Test deletion blocked | gate evaluation | `test_test_deletion_blocks_promotion` |
| Benchmark tampering blocked | gate evaluation | `test_benchmark_modification_blocks_promotion` |
| Project isolation is structural | `LearningScope.project_id` | `test_the_same_fingerprint_in_another_project_is_distinct` |
| Cross-project rollback impossible | `DurableLearningStore.get_rollback_handle` | `test_cross_project_rollback_is_impossible` |
| Transfer requires human policy | `TransferEvaluator` | `test_cross_project_transfer_without_a_policy_is_refused` |
| Rollback is deterministic | `LearningLifecycleService.rollback` | `test_gate38_automatic_rollback_restores_exact_prior_state` |
| Rollback is idempotent | same | `test_gate38_rollback_is_idempotent` |
| Recovery never auto-completes authority | `RecoveryReconciler` | `test_a_partial_promotion_never_auto_completes` |
| Records are never deleted | `ContinualLearner` | `test_19b3_continual.py` (15) |
| Record integrity verified on read | `DurableLearningStore.get_active_state` | `test_a_corrupt_record_is_rejected_not_returned_as_absent` |
| Security outcomes are not optimizable | `RewardLedger.record` | `test_a_security_outcome_can_never_be_scored_as_reward` |
| Evidence cannot be fabricated | `ExecutionObservation` validation | `test_fake_evidence_cannot_be_manufactured` |
| Hallucinated success is not success | `ExperimentEngine` | `test_hallucinated_success_is_never_reported_as_survival` |
---

## 4. PI Traceability

| Invariant | Class | Measured by | Test |
|---|---|---|---|
| PI-1 Security | ABSOLUTE | `RegressionMonitor` + `AIGuardrailsEngine` | `test_a_security_outcome_can_never_be_scored_as_reward` |
| PI-2 Deterministic validation | ABSOLUTE | `LearningLifecycleService.evaluate` | `test_gate37_a_reward_conflicting_with_validation_is_clamped` |
| PI-3 Review acceptance | CRITICAL | HITL `record_decision` | `test_gate38_*` (approval chain) |
| PI-4 Completion success | CRITICAL | `finalize_project` | inherited from 19A |
| PI-5 Correctness | CRITICAL | `RegressionMonitor` | `test_gate38_automatic_rollback_restores_exact_prior_state` |
| PI-6 Reliability | HIGH | `record_execution_failed` | `test_19b3_activation_and_monitoring.py` |
| PI-7 Latency & resources | HIGH | `RegressionPolicy.thresholds` | `test_gate38_*` (latency_ms) |
| **PI-8 Customer outcomes** | **DEFERRED** | `measure_effectiveness` | `test_the_pi8_contract_is_transcribed_not_redefined`, `_verify_19b3_pi8.py` |
| PI-9 Isolation & authority | ABSOLUTE | `assert_no_authority_expansion` | `test_recursive_authority_escalation_is_refused` |

**PI-8 remains DEFERRED per `phase19/REGRESSION_PROTECTION.md` §2.** It reports
`NOT_APPLICABLE` and never silently passes.

---

## 5. Verification Script Traceability

| Script | Gate | Exit |
|---|---:|---:|
| `_verify_19b3_pipeline.py` | 3, 4 | 0 |
| `_verify_19b3_experiments.py` | 8, 9 | 0 |
| `_verify_19b3_rewards.py` | 11, 13 | 0 |
| `_verify_19b3_optimization.py` | 14 | 0 |
| `_verify_19b3_recursion.py` | 15, 16 | 0 |
| `_verify_19b3_continual.py` | 22 | 0 |
| `_verify_19b3_pi8.py` | 29 | 0 |

---

## 6. Coverage Summary

| Dimension | Status |
|---|---|
| Gates 34–39 | **All certified** |
| New tests | **295** |
| Learning suite | **609 passed, 0 failed** |
| New repository regressions | **0** |
| Verification scripts | **7/7 exit 0** |
| PI-8 | Faithfully deferred per contract |