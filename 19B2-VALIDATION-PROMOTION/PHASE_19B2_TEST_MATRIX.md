# Phase 19B-2 — Test Matrix

**Gate:** 19B-2 — Gates 14, 15, 17, 18, 23
**Result:** **296 tests passing** in `packages/learning/tests` (177 new).

| File | Tests | Covers |
|---|---:|---|
| `test_promotion_path.py` | 11 | The intended end-to-end flow (Gates 5–8) |
| `test_adversarial_evidence_evaluation.py` | 24 | Matrix **A** (evidence) + **B** (evaluation) |
| `test_adversarial_approval.py` | 18 | Matrix **C** (approval) |
| `test_adversarial_promotion.py` | 16 | Matrix **D** (rollback) + **E** (promotion) |
| `test_adversarial_security.py` | 29 | Matrix **F** (security) + Gate 12 authority |
| `test_adversarial_isolation.py` | 9 | Matrix **G** (project isolation) |
| `test_promotion_properties.py` | 11 | Gate 15 property/invariant implications |
| `test_store_durability_concurrency.py` | 16 | Gate 2 (store) + Gate 17 (failure injection) + Gate 18 (concurrency) |
| `test_telemetry_and_audit.py` | 9 | Gate 9 (audit) + Gate 16 (truthful telemetry) |
| `test_promotion_architecture.py` | 26 | Gates 13, 20, 21 (architecture + protected systems) |
| `test_architecture_integrity.py` (19B-1) | 33 | Carried forward, still green |
| `test_proposal_gateway_security.py` (19B-1) | 36 | Carried forward, still green |
| `test_learning_models.py` (19B-1) | 23 | Carried forward, still green |
| `test_evidence_and_signals.py` (19B-1) | 19 | Carried forward, still green |
| `test_production_learning_path.py` (19B-1) | 16 | Carried forward, still green |
| `conftest.py`, `helpers.py` | — | Fixtures building the **real** `SecurityPlatform` |

Every fixture constructs the certified `SecurityPlatform` (guardrails, HITL
manager, governance engine, audit engine) rather than a stub, so the tests
exercise the production boundary.

---

## A. Evidence (Gate 14A)

| Case | Test | Result |
|---|---|---|
| Missing evidence (none at all) | `test_no_evidence_evaluates_every_required_invariant_as_unavailable` | 8 invariants `UNAVAILABLE`, not promotable |
| Missing evidence (partial) | `test_partial_evidence_leaves_only_unmeasured_invariants_unavailable` | Only PI-2 `UNAVAILABLE`; the rest still evaluated |
| Malformed evidence | `test_malformed_evidence_is_rejected` | PI-1 blocked |
| Conflicting evidence | `test_conflicting_evidence_for_one_invariant_blocks` | PI-1 blocked |
| Stale evidence | `test_stale_evidence_blocks` | All 8 required `UNAVAILABLE` |
| Project mismatch | `test_evidence_from_another_project_is_rejected` | All 8 required `UNAVAILABLE` |
| Model (Q4) evidence | `test_model_generated_evidence_never_satisfies_an_invariant` | PI-1 `UNAVAILABLE` |
| Absent evidence is never a pass | `test_unknown_evidence_never_yields_pass` | No required invariant `PASS` |

## B. Evaluation (Gate 14B)

| Case | Test | Result |
|---|---|---|
| All nine pass | `test_all_nine_invariants_pass_yields_a_promotable_report` | promotable |
| One invariant fails (×10, parametrised) | `test_a_single_failing_invariant_blocks_promotion` | not promotable |
| Multiple invariants fail | `test_multiple_failing_invariants_are_all_reported` | all named |
| Invariant unavailable | `test_absent_invariant_metrics_report_unavailable_not_pass` | `UNAVAILABLE` |
| Malformed report (missing invariant) | `test_a_report_missing_an_invariant_cannot_be_constructed` | `ValidationError` |
| Report self-contradiction | `test_promotable_cannot_be_asserted_against_its_own_results` | `ValidationError` |
| Evaluator exception | `test_evaluator_exception_fails_closed` | `ERROR`, not promotable |
| Security violation despite gains | `test_security_violation_disqualifies_despite_gains_everywhere_else` | PI-1 blocks, PI-7 gain recorded but non-compensating |

## C. Approval (Gate 14C)

| Case | Test | Result |
|---|---|---|
| No approval | `test_promotion_without_any_approval_is_refused` | refused, nothing active |
| Rejected approval | `test_a_rejected_approval_blocks_promotion` | refused |
| Expired approval (record) | `test_an_expired_approval_blocks_promotion` | refused |
| Expired gate | `test_an_expired_gate_is_recorded_as_expired` | durable `EXPIRED` |
| Revoked approval | `test_a_revoked_approval_blocks_promotion` | refused |
| Non-human revocation | `test_a_non_human_cannot_revoke_an_approval` | refused |
| Malformed (no HITL lineage) | `test_an_approval_without_hitl_lineage_is_refused` | refused |
| Forged resume token | `test_an_approval_with_a_bogus_resume_token_is_refused` | refused |
| Wrong candidate | `test_an_approval_for_another_candidate_is_refused` | refused |
| Wrong project | `test_an_approval_from_another_project_is_refused` | refused |
| Wrong scope | `test_an_approval_authorising_a_different_scope_is_refused` | refused |
| Model-generated fake approval | `test_an_approval_record_cannot_be_self_declared_approved` | `ValidationError` |
| Worker with governance role | `test_a_worker_cannot_approve_even_with_the_governance_role` | `SelfApprovalForbiddenError` |
| Service principal | `test_a_service_principal_cannot_approve` | `SelfApprovalForbiddenError` |
| Self-approval by a human | `test_self_approval_is_refused` | `SelfApprovalForbiddenError` |
| Duplicate decision | `test_a_second_decision_on_a_resolved_gate_is_refused` | refused |
| Approval over a failed evaluation | `test_a_failed_evaluation_cannot_request_approval` | refused |
| No security platform | `test_approval_is_impossible_without_the_security_platform` | boundary denies *and* coordinator refuses |

## D. Rollback (Gate 14D)

| Case | Test | Result |
|---|---|---|
| Missing handle | `test_rollback_with_a_missing_handle_is_refused` | refused |
| Tampered handle | `test_rollback_with_a_tampered_handle_is_refused` | integrity check fails |
| Wrong project | `test_rollback_from_another_project_is_refused` | refused |
| Handle bound to its own promotion | `test_a_handle_only_restores_its_own_candidates_state` | correct state restored |
| Repeated rollback | `test_repeated_rollback_is_idempotent` | same result |
| History retained | `test_repeated_rollback_preserves_history` | both records kept |
| After a failed promotion | `test_the_rollback_handle_survives_a_failed_promotion` | handle intact |
| Restore an earlier version | `test_rollback_restores_an_earlier_version_exactly` | exact version id restored |

## E. Promotion (Gate 14E)

| Case | Test | Result |
|---|---|---|
| Without evaluation | `test_promotion_without_an_evaluation_is_refused` | refused |
| With failed evaluation | `test_promotion_with_a_failed_evaluation_is_refused` | refused |
| Without HITL | `test_promotion_without_hitl_is_refused` | refused |
| Without rollback handle | `test_promotion_aborts_when_the_rollback_handle_cannot_be_written` | **hard invariant** |
| Handle read-back missing | `test_promotion_aborts_when_the_handle_readback_is_not_intact` | refused |
| Duplicate promotion | `test_duplicate_promotion_is_idempotent` | same record, version 1 |
| Conflicting promotion | `test_a_rolled_back_candidate_cannot_silently_reactivate_itself` | rejected |
| Partial-write simulation | `test_a_failed_active_state_write_leaves_the_prior_state_intact` | prior state intact |
| Failure recovery | `test_a_failed_promotion_is_recorded_not_swallowed` | `FAILED` retained |

## F. Security (Gate 14F)

| Case | Test | Result |
|---|---|---|
| Every forbidden capability (9, parametrised) | `test_every_forbidden_capability_is_denied` | denied |
| Unknown capability | `test_an_unknown_capability_is_treated_as_an_escalation_attempt` | denied |
| Level 5 attempt | `test_level_5_cannot_be_represented_on_a_candidate` | unrepresentable |
| No L5 assignment (AST) | `test_the_learning_package_contains_no_level_5_assignment` | none |
| Guardrail mutation | `test_the_guardrail_engine_exposes_no_policy_mutation_surface` | no surface |
| Learning mutates policy | `test_the_learning_package_never_writes_guardrails_policy` | none |
| Authorization / credential mutation | `test_security_authorization_and_credential_mutation_are_unreachable` | denied |
| HITL / validation / audit bypass | `test_hitl_validation_and_audit_bypass_are_unreachable` | denied |
| Kind allow-list not widened | `test_only_the_five_certified_proposal_kinds_exist` | 5 kinds |
| Unknown proposal kinds | `test_unknown_proposal_kinds_are_denied` | denied |
| Invariant set cannot shrink | `test_the_nine_invariants_cannot_be_reduced` | 9 |
| No self-authorization surface | `test_the_learning_package_defines_no_self_authorization_surface` | none |
| No parallel security/audit component | `test_no_parallel_security_or_audit_component_is_created` | none |

## G. Isolation (Gate 14G)

| Case | Test | Result |
|---|---|---|
| Same candidate id, other project | `test_project_b_cannot_read_project_as_candidate` | not found |
| Listings disjoint | `test_project_b_listing_never_includes_project_a` | disjoint |
| Separate directories | `test_the_two_projects_store_in_separate_directories` | structural |
| Cross-project evidence | `test_project_b_evidence_cannot_validate_project_as_candidate` | not promotable |
| Cross-project approve | `test_project_b_cannot_approve_project_as_candidate` | refused |
| Cross-project promote | `test_project_b_cannot_promote_project_as_candidate` | refused |
| Misfiled active state | `test_a_misfiled_active_state_is_refused` | refused |
| Cross-project rollback | `test_project_b_cannot_rollback_project_as_promotion` | refused |
| Independent rollbacks | `test_each_project_rolls_back_independently` | A only |

## Gate 15 — Property / invariant tests

| Implication | Test |
|---|---|
| promotion ⇒ evaluation ∧ approval ∧ handle ∧ boundary | `test_promotion_implies_evaluation_approved_handle_and_boundary` |
| every promotion has a matching intact handle | `test_every_promotion_in_the_store_has_a_matching_handle` |
| promotion ⇏ model authority | `test_no_promoted_record_names_a_non_human_approver` |
| rollback ⇒ valid handle ∧ correct project ∧ correct candidate | `test_rollback_implies_a_valid_handle_in_the_right_project` |
| unknown evidence ⇏ pass | `test_unknown_evidence_never_yields_pass` |
| missing approval ⇏ promotion | `test_missing_approval_never_implies_promotion` |
| missing handle ⇏ promotion | `test_a_handle_cannot_exist_without_its_promotion_record` |
| all nine always evaluated | `test_a_report_always_evaluates_the_contract_invariant_set` |
| baseline pinned | `test_baseline_is_pinned_to_the_evaluation` |

## Gate 17 — Failure injection

| # | Injected failure | Result |
|---|---|---|
| 1 | candidate persistence | raised; working store uncorrupted |
| 3 | evaluation | fail-closed; approval impossible |
| 4 | approval persistence | raised; no approval record |
| 7 | audit emission | `PromotionAuditError`; record says `PROMOTED` **and** `audit_failure_reason` — never a clean success |
| 8 | rollback write | raised; active state intact; `ROLLBACK_FAILED` audited |

## Gate 18 — Concurrency / idempotency

| Case | Test | Result |
|---|---|---|
| Two simultaneous promotions | `test_two_simultaneous_promotions_produce_exactly_one` | one record, one version |
| Concurrent handle reads | `test_concurrent_promotions_do_not_lose_a_rollback_handle` | no lost handle |
| Concurrent rollbacks | `test_concurrent_rollbacks_are_idempotent` | consistent |
| Promotion + rollback race | `test_promotion_and_rollback_race_leaves_a_consistent_state` | state always complete/valid |