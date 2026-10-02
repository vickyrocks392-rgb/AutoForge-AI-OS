# PHASE 19B-1 — IMPLEMENTATION REPORT

**Gate:** 19B1-16
**Date:** 2026-10-02
**Basis HEAD:** `5d975bcfd3b32ab29ab0c8a69228913852af910f`
**Status:** PASS

---

## 1. What Was Implemented

| Area | Location | Detail |
|---|---|---|
| **Immutable models** | `packages/learning/src/autoforge_learning/models.py` | `LearningBase` (frozen, `extra="forbid"`, `schema_version`), `LearningScope`/`LearningScopeKind`, `LearningAuthority`, `EvidenceRef`/`EvidenceSource`/`EvidenceQuality`, `ValidationSummary`/`ValidationTruth`/`TestOutcome`, `ExperienceRecord`, `LearningSignal`/`SignalPolarity`, `LearningCandidate`/`ValidationState`/`ApprovalState` |
| **Evidence collection** | `evidence.py` | `EvidenceCollector.collect()` reads real completion, final-review, deterministic-validation and durable-artifact records |
| **Signals** | `signals.py` | `derive_confidence()` — evidence-derived, replacing the tautological constant |
| **ProposalGateway** | `gateway.py` | `ProposalGateway`, `ProposalDecision`, `ProposalOutcome`, `GatewayDenialReason` (9 reasons) |
| **Production call site** | `composition_root.py` step 9b | Gateway built from `SecurityPlatform.guardrails` |
| **Engine integration** | `learning_engine.py` | `_build_experience()`, `_propose_through_gateway()`, `_confidence_from_review_findings()` |
| **Dead-branch repair** | `kernel.py` | `_authoritative_review_findings()` |
| **Telemetry repair** | `apps/api/.../service.py`, `models.py` | GAP-12 closed |

### Structural properties (not conventions)

| Property | Mechanism |
|---|---|
| Immutable | `ConfigDict(frozen=True)` — 4 dedicated mutation-rejection tests |
| Schema identity | `schema_version` on every model, asserted by test |
| Deterministic serialization | `canonical_json()` (sorted keys) + `record_hash()`; round-trip verified |
| No fabricated values | `ValidationTruth.UNAVAILABLE`, `TestOutcome(total=None)`; absence never rendered as zero/pass |
| Mandatory scope | `LearningScope.project_id` required; 4 kinds only, no security scope |
| L5 unreachable | `LearningCandidate` validator **rejects** an L5 authority value |
| Model text non-authoritative | `model_annotation_authoritative: Literal[False]` — cannot be asserted true |
| Evidence is a reference | `EvidenceRef` carries `content_hash`, never the payload |

---

## 2. What Was Deliberately NOT Implemented

Explicitly out of scope per the 19B-1 instructions and Gate 11:

* automatic promotion, autonomous production activation, full optimizer
* reinforcement learning, experiment scheduler/harness
* continuous background learning daemon, distributed learning
* model training infrastructure, source-code self-modification
* Phase 20, Brain, Commercial Power Engine changes, Security reopening,
  inference topology changes

Also deferred from the 19A MUST list (each requires a later gate): durable
store (M-02), regression evaluator (M-08), approval coordinator (M-10),
promotion resolver (M-11), rollback (M-12), artifact versioning (M-13), audit
emission (M-14), first learning target (M-17).
---

## 3. Actual Production Call Graph

```
Kernel.execute_project(project_id)                       kernel.py
  |- Step 5  completion_module.finalize_project(...)
  |            \_ produces final_review{approved, validation, evidence_files}
  \_ Step 6  learning_engine.reflect_and_learn(...)        kernel.py
              |- review_findings = _authoritative_review_findings(finalize_result)
              |- _build_experience() -> ExperienceRecord   (real D1/D2 evidence)
              |- extract ReusableLessons
              |- _propose_through_gateway()                 learning_engine.py
              |    \_ for each lesson:
              |         LearningCandidate(scope=PROJECT, kind=<approved kind>)
              |         \_ ProposalGateway.evaluate(candidate)          gateway.py
              |              |- L5 / missing scope   -> deny
              |              |- capability deny-list -> deny
              |              |- kind allow-list      -> deny
              |              \_ _call_boundary()                        gateway.py
              |                   \_ AIGuardrailsEngine
              |                        .evaluate_learning_proposal()  <== BOUNDARY
              |                            ai_guardrails.py:611
              |                   \_ fail-closed ProposalDecision
              |         \_ permitted -> _promoted_candidate_ids (telemetry)
              |            denied    -> retained, NEVER promoted
              |- memory store (all lessons)
              |- knowledge promote (ONLY permitted AND confidence >= 0.90)
              \_ publish PROJECT_COMPLETING {extracted, permitted}
```

---

## 4. ProposalGateway Enforcement Point

**`autoforge_learning.gateway.ProposalGateway._call_boundary`** is the single
production call site of `evaluate_learning_proposal`. It is reached only from
`ProposalGateway.evaluate()`, which is reached only from
`EngineeringLearningEngine._propose_through_gateway()`.
## 6. Telemetry Source

`get_self_improvement_center()` reads `kernel.learning_engine._promoted_candidate_ids`
— the candidate ids the **security boundary actually permitted**.

| Metric | Source | With no learning |
|---|---|---|
| `learned_heuristics_count` | length of `_promoted_candidate_ids` | `0` |
| `candidate_improvements_count` | same | `0` |
| `last_regression_status` | no harness exists | `"UNAVAILABLE"` |
| `regression_results` | no harness exists | `[]` |
| `learned_heuristics` / `learned_items` | no promoted artifacts | `[]` |

Removed: `learned_heuristics_count=14`, `ALL_PASSING (1119/1119)`, two
fabricated heuristics with invented `evidence_runs`/`confidence`, and the
`{"suite": ..., "passed": 1135, "status": "green"}` block. The response model's
own defaults were corrected so an unset response cannot carry a false claim.

Retained (they are true): `is_autonomous_active=False`,
`gated_policy_enforced=True`, `safety_gating_mode="STRICT_HUMAN_IN_THE_LOOP"`.

---

## 7. Authority Boundary

| Level | Reachable by learning in 19B-1? |
|---|---|
| L0 Observation | Yes — `ExperienceRecord` |
| L1 Insight | Yes — `LearningSignal` |
| L2 Candidate | Yes — `LearningCandidate` |
| L3 Validated artifact | No (deferred: M-08) |
| L4 Approved operational | **No** — requires human approval; not implemented |
| L5 Security/policy | **No** — unconstructable on a candidate; no transition exists |

`ProposalOutcome.PERMITTED` means *"may proceed to the next controlled learning
stage"* only. `ProposalDecision.is_approved` is hardcoded `False`, and the
boundary's own `promotion_requires` always includes `human_authorization`.

---

## 8. Test Results

**New:** 119 passed (`packages/learning/tests`).
**Existing:** all certified suites match baseline.
**Full CI:** 18 package suites + `apps/api`, run separately per the canonical
convention (not `pytest packages tests`).

The only failures are 4 **pre-existing** ones, confirmed by `git stash` and
re-run. See `19B1-TEST_REPORT.md` §3 for the environment-only F-05 port-8080
failure.

---

## 9. Regressions

Four were introduced during implementation and **all fixed before commit**
(R-1..R-4 in the test report). Two were security-relevant and were caught by the
new adversarial tests: a fail-open `_deny()` path and a decision-membership
bypass. No regression remains in a certified system.

---

## 10. Remaining Work for 19B-2

**Next gate: 19B-2 — Validation, Evaluation, and the Promotion Path.**

1. **Durable append-only learning store (M-02)** — currently RAM-only.
2. **Regression evaluator (M-08)** — 9 protected invariants vs a pinned baseline.
3. **Approval coordinator (M-10)** — `HITLManager` + `GovernancePolicyEngine`, human-only.
4. **Promotion resolver (M-11)** — atomic, rollback handle before activation.
5. **Deterministic rollback (M-12)** + artifact-based versioning (M-13).
6. **Audit emission (M-14)** — via the existing `AuditEngine`.
7. **Remove the legacy `confidence >= 0.90` threshold** once M-11 owns promotion.
8. **Close GAP-04** — supply real `repair_records`.
9. **First learning target (M-17)** — `DefaultStrategicEngine`, advisory and bounded.

**Non-negotiable for 19B-2:** promotion remains human-approved, Level 5 remains
unreachable, and the ProposalGateway remains on every candidate path.

There is no second path: `test_2_gateway_calls_boundary_at_runtime` and
`test_production_path_invokes_evaluate_learning_proposal` prove the boundary is
invoked, and `test_denied_candidates_are_not_promoted` proves a denial stops
continuation.

**Uniqueness verified:** at Gate 19A this method had zero production callers.
It now has exactly one, and `packages/security` is unmodified.

---

## 5. Evidence Sources

| Source | How it is read | Determinism |
|---|---|---|
| Completion gate | `finalize_result["success"]` | D1 |
| Final review verdict | `finalize_result["final_review"]["approved"]` | D2 |
| Deterministic validation | `finalize_result["final_review"]["validation"]` (`required`/`passed`/`test_results`), plus the failure path's top-level `validation` | **D1** |
| Durable artifacts | `DurableArtifactState.content_hash` / `status` / `workflow_id` | D1 |

Never used as evidence: model self-report, model confidence, UI counts,
`KernelMemoryEngineAdapter` (unfiltered / fail-open — AMB-01/02).

---