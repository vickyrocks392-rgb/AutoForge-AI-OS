# PHASE 19B-3 — TEST REPORT

**Gate:** 19B3-39
**Date:** 2026-10-03
**Interpreter:** `.venv/bin/python` (CPython 3.12, aarch64-apple-darwin)

---

## 1. Learning Suite — **609 passed**

| Metric | Count |
|---|---:|
| Baseline at `81ec823` (pre-19B-3) | 297 |
| 19B-3 tests added | **295** |
| **Current total** | **609** |
| Failures | **0** |

### 1.1 New 19B-3 test files

| File | Tests | Gate coverage |
|---|---:|---|
| `test_19b3_adversarial.py` | 77 | Gate 39 — SECURITY, LEARNING, CODE, RECURSION, EXPERIMENTS, ISOLATION, RECOVERY |
| `test_19b3_codemod.py` | 42 | Gate 12 — ten mandatory gates, protected paths, reversibility |
| `test_19b3_activation_and_monitoring.py` | 38 | Gates 17/18 — atomic activation, rollback handles, regression detection |
| `test_19b3_transfer_and_governance.py` | 37 | Gates 20/29/31 — transfer policy, governance, PI-8 |
| `test_19b3_reward_and_optimization.py` | 37 | Gates 11/13/14 — reward normalization, hacking detection, bounded optimization |
| `test_19b3_experiments.py` | 18 | Gates 8/9 — A/B isolation, control contamination, budget |
| `test_19b3_continual.py` | 15 | Gate 22 — archive/supersede, no deletion |
| `test_19b3_e2e_learning.py` | 13 | **Gates 34–38** — end-to-end lifecycle |
| `test_19b3_models.py` | 12 | Immutability, evidence typing, scope isolation |
| `test_19b3_extraction.py` | 6 | Gate 3 — signal extraction, non-optimizable rejection |
| **Total** | **295** | |

---

## 2. Gates 34–38 End-to-End

These are the certification gates. Each drives real components rather than
mocks.

| Test | What it proves |
|---|---|
| `test_gate34_real_lifecycle_*` | The real store, real security gateway, real HITL, real promotion and real rollback work together on a real candidate |
| `test_gate34_the_first_candidate_check_still_passes_the_real_boundary` | The security gateway genuinely permitted this candidate — the flow is not bypassing the boundary |
| `test_gate35_source_change_is_isolated_diffed_and_evaluated` | A change prepared in an isolated workspace; the real `pytest` runs against the copy; production source is untouched; all ten gates pass; the diff is reversible |
| `test_gate35_a_protected_file_change_is_denied_before_any_workspace` | A change to `autoforge_security/authorization.py` is refused before any workspace is used |
| `test_gate36_multi_generation_learning_terminates_at_its_bound` | Generations 0→1→2 run, each observing its predecessor and linked by lineage, stopping exactly at `max_recursion_depth` |
| `test_gate36_recursion_stops_when_a_generation_cannot_improve` | A generation that cannot improve ends the loop |
| `test_gate36_recursion_cannot_exceed_its_experiment_budget` | Even with depth 9, the experiment budget of 2 wins |
| `test_gate36_recursion_never_widens_authority` | The prohibited learning→permission→learning loop is refused |
| `test_gate37_a_high_reward_cannot_override_deterministic_safety` | A reward of 0.99 with an invariant breach → `TERMINATED_ON_INVARIANT_BREACH`. The *identical* candidate without the breach → `SURVIVED`. The reward decided nothing. |
| `test_gate37_a_reward_conflicting_with_validation_is_clamped` | Reward aggregate clamps to 0.0 when deterministic validation fails |
| `test_gate38_automatic_rollback_restores_exact_prior_state` | Baseline promoted, second candidate promoted over it, latency regresses, detector fires, real rollback restores the **exact same `version_id` and `candidate_id`** |
| `test_gate38_a_catastrophic_regression_also_creates_a_follow_up` | Gate 17.9 — catastrophic regressions additionally create a follow-up candidate |
| `test_gate38_rollback_is_idempotent` | A repeated rollback reaches the same end state and retains both records |

**Note on Gate 34's rollback:** the detector produces the rollback-authorizing
verdict naturally from pre-registered thresholds and real measurements. The
test does not elevate severity to force it.

---

## 3. Gate 39 Adversarial Matrix — 77 tests

Every test asserts the **specific failure**, not merely that something raised.

### SECURITY

| Test | Result |
|---|---|
| `test_learning_cannot_request_any_forbidden_capability[x9]` | All nine capabilities denied by the real `AIGuardrailsEngine` |
| `test_learning_cannot_grant_itself_a_permission` | Denied by the real `ProposalGateway` |
| `test_learning_cannot_disable_authorization` | Denied structurally |
| `test_a_malformed_proposal_is_denied[4]` | `None`, dict, str, int — all denied |
| `test_the_guardrails_policy_surface_has_no_mutation_api` | No `set_policy`/`mutate`/`reload`/`update_policy` |
| `test_learning_cannot_reach_level_5` | Construction fails |
| `test_a_permitted_proposal_still_demands_human_authorization` | Permission to *propose* ≠ permission to *activate* |
### LEARNING

| Test | Result |
|---|---|
| `test_fake_evidence_cannot_be_manufactured` | A non-existent source cannot be recorded |
| `test_an_observation_needs_a_verifiable_content_hash` | A weak hash is rejected |
| `test_a_hypothesis_without_evidence_cannot_exist` | Evidence-free hypotheses are impossible |
| `test_a_reward_with_no_provenance_is_rejected` | Rejected at construction |
| `test_a_security_outcome_can_never_be_scored_as_reward` | A violation is refused as a reward entirely |
| `test_reward_inflation_cannot_escape_the_unit_interval` | `±1e9`, `±inf` all clamp to `[-1, 1]` |
| `test_poisoned_cross_project_feedback_cannot_become_a_proposal` | Foreign-project feedback yields zero hypotheses |
| `test_contradictory_feedback_is_detected` | A reward conflicting with a `fail` verdict is flagged |
| `test_selective_reporting_is_detected` | Replayed evidence is detected |
| `test_hallucinated_success_is_never_reported_as_survival` | Unmeasured arms → `INCONCLUSIVE` |
| `test_evaluator_manipulation_cannot_survive_an_invariant_breach` | Perfect metric + breach → terminated |

### CODE

| Test | Result |
|---|---|
| `test_malicious_code_cannot_skip_the_mandatory_gates[4]` | Backdoor, exfiltration, test deletion, benchmark edit — all blocked |
| `test_credential_exfiltration_is_denied_before_scoring` | Refused outright, before scoring |
| `test_every_protected_component_is_immutable_by_learning[19]` | Every protected path denied, alone and combined |
| `test_test_deletion_blocks_promotion` | Removal blocks `unit_tests` **and** `regression_tests` |
| `test_benchmark_modification_blocks_promotion` | Cannot redefine the judging criteria |
| `test_a_candidate_cannot_authorize_its_own_promotion` | `promotion_authorization` is non-skippable |

### RECURSION

| Test | Result |
|---|---|
| `test_recursive_authority_escalation_is_refused` | Capability widening refused |
| `test_recursion_widening_scope_is_refused` | Scope widening refused |
| `test_infinite_recursion_terminates` | A stage yielding nothing still terminates |
| `test_depth_overflow_raises` | `BudgetExhausted` at generation 999 |
| `test_resource_exhaustion_fails_safely` | Exhaustion raises, but `assert_core_path()` stays `True` |

### EXPERIMENTS

| Test | Result |
|---|---|
| `test_a_candidate_cannot_modify_its_own_success_criteria` | Threshold is frozen |
| `test_control_contamination_is_detected` | A mislabelled arm raises |
| `test_benchmark_gaming_via_missing_measurement_is_inconclusive` | Deleting the benchmark ≠ a pass |
| `test_cherry_picked_partial_runs_are_inconclusive` | Stopping early ≠ a refutation |
| `test_experiment_capabilities_are_declared_not_implied` | Exactly five; no network/FS/credentials/deployment |
| `test_an_experiment_without_a_rollback_target_cannot_be_designed` | No rollback → no design |

### ISOLATION

| Test | Result |
|---|---|
| `test_the_same_fingerprint_in_another_project_is_distinct` | Isolation is structural |
| `test_cross_project_activation_is_refused` | Refused |
| `test_cross_project_transfer_without_a_policy_is_refused` | `REFUSED` even with all six checks green |
| `test_cross_project_rollback_is_impossible` | Owner sees it; another project sees nothing; a relocated record still trips the ownership check |

### RECOVERY

| Test | Result |
|---|---|
| `test_a_partial_promotion_never_auto_completes` | Requires human review |
| `test_a_partial_rollback_never_auto_completes` | Requires human review |
| `test_corrupt_records_are_quarantined_not_deleted` | Two findings, both human review |
| `test_recovery_preserves_candidate_and_lineage_state` | Nothing is lost |
| `test_the_real_store_survives_a_restart` | A new store instance restores the exact pointer |
| `test_a_corrupt_record_is_rejected_not_returned_as_absent` | Tampering raises rather than looking like absence |

---

## 4. Defects Found and Fixed by These Tests

These are real defects the adversarial matrix exposed, now fixed:

| # | Defect | Fix |
|---|---|---|
| 1 | Protected-path matching used exact equality, so `packages/security/` did not protect the files beneath it — a whole subsystem could be edited by naming a file inside it | `_is_protected` now matches by prefix |
| 2 | `get_active_state` did not verify record integrity on read; tampering surfaced as a valid state | Store now recomputes and compares `record_hash()` |
| 3 | `get_rollback_handle` had no ownership check on the returned record | Now raises `LearningProjectIsolationError` on mismatch |
| 4 | `PI8_CONTRACT["measurement_source"]` did not match the authoritative contract text verbatim | Aligned to the exact contract string |
---

## 5. Repository Regression — Baseline Preserved

Every package is run individually (the packages share a `tests` package name, so
a single combined invocation collides on collection — pre-existing, unrelated).

| Package | Result |
|---|---|
| learning | **609 passed** |
| security | **165 passed** |
| execution | 257 passed, 18 skipped |
| kernel | 161 passed |
| runtime | 268 passed |
| workflows | 218 passed |
| modernization | 383 passed, 59 skipped |
| review | 114 passed |
| orchestration | 101 passed, 6 skipped |
| ai_infrastructure | 97 passed |
| connectors | 93 passed |
| persistence | 70 passed |
| event_platform | 56 passed |
| workforce | 36 passed, 2 skipped |
| artifacts | 25 passed |
| events | 228 passed |
| observability | 16 passed |
| **composition** | 3 failed, 143 passed — **baseline** |
| **power_engines** | 1 failed, 135 passed, 3 skipped — **baseline** |

**Zero new failures.** The four failures are byte-for-byte the baseline ones
recorded before any 19B-3 work began:

```
composition/test_canonical_context_builder.py::test_canonical_context_builder_invoked_in_execution_path
composition/test_canonical_durable_artifacts.py::test_canonical_durable_artifact_wiring
composition/test_execution_platform_integration.py::test_autoforge_system_execution_wiring
power_engines/test_delivery_hardening.py::TestDeliveryHardening::test_health_check_script_execution_and_exit_codes
```

---

## 6. Verification Scripts

All seven exit `0`:

| Script | Covers |
|---|---|
| `_verify_19b3_pipeline.py` | Full observation→signal→hypothesis pipeline |
| `_verify_19b3_experiments.py` | Experiment lifecycle, refutation, rerun |
| `_verify_19b3_rewards.py` | Reward rejection paths (2 rejections demonstrated) |
| `_verify_19b3_optimization.py` | Budget enforcement (`True`) |
| `_verify_19b3_recursion.py` | Cross-project refusal (`True`) |
| `_verify_19b3_continual.py` | Capability regression detection |
| `_verify_19b3_pi8.py` | PI-8 reconciliation against the authoritative document |

---

## 7. Result

**609 passed, 0 failed, 0 new regressions.** All of Gates 34–39 certified.