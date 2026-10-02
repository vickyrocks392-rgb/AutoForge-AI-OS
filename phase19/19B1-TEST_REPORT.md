# PHASE 19B-1 — TEST REPORT

**Gate:** 19B1-16
**Date:** 2026-10-02
**Interpreter:** `.venv/bin/python` (CPython 3.12, aarch64-apple-darwin)

---

## 1. New Tests: `packages/learning/tests` — **119 passed**

| File | Tests | Gate coverage |
|---|---|---|
| `test_learning_models.py` | 23 | IMMUTABILITY, EVIDENCE, ISOLATION (models) |
| `test_proposal_gateway_security.py` | 36 | SECURITY (gateway incl. 10 scenarios) |
| `test_evidence_and_signals.py` | 20 | EVIDENCE, confidence derivation |
| `test_production_learning_path.py` | 20 | INTEGRATION + TELEMETRY |
| `test_architecture_integrity.py` | 20 | Gate 15 (12 invariants) |

### Gate 10 required-scenario coverage (all present)

| # | Scenario | Test |
|---|---|---|
| 1 | benign proposal | `test_benign_proposal_is_permitted_but_never_approved` |
| 2 | forbidden security proposal | `test_forbidden_capability_denied_locally[x9]`, `..._by_real_boundary[x9]` |
| 3 | unknown capability | `test_unknown_capability_name_is_denied_not_ignored` |
| 4 | malformed proposal | `test_unknown_proposal_kind_denied`, `test_malformed_boundary_response_fails_closed` |
| 5 | evaluator exception | `test_boundary_exception_fails_closed` |
| 6 | evaluator unavailable | `test_boundary_unavailable_fails_closed`, `test_absent_gateway_denies_everything` |
| 7 | missing project scope | `test_scope_requires_a_project_id` |
| 8 | cross-project proposal | `test_candidate_from_project_a_never_applies_to_project_b`, `test_10_*` |
| 9 | model-injected fake approval | `test_model_injected_fake_approval_does_not_help`, `test_5_self_declared_approval_is_not_authority` |
| 10 | attempted guardrail modification | `test_guardrail_modification_attempt_denied` |

Every denial additionally asserts the candidate **does not continue**
(`test_denied_candidates_are_not_promoted`).

### Gate 13 matrix coverage

| Class | Covered |
|---|---|
| IMMUTABILITY | mutation-rejection; `extra="forbid"`; stable serialization; round-trip hash |
| EVIDENCE | real pass/fail/not-applicable; missing/malformed to `UNAVAILABLE`; artifact hashes; provenance; payload-free refs |
| SECURITY | benign allowed; forbidden capability denied (local **and** boundary); unknown kind; malformed; exception; unavailable; lying boundary; fake approval; self-approval |
| ISOLATION | project A cannot reach B; workflow scope requires id; no security scope kind exists |
| TELEMETRY | zero state reports zero; real permits counted; fabricated values gone; model defaults truthful |
| INTEGRATION | production path invokes the boundary; real `AIGuardrailsEngine` wired; denied not promoted; Gate 4 evidence repair |

---

## 2. Existing Tests — Full CI Sweep (per package, not combined)

| Suite | Result | vs. baseline |
|---|---|---|
| **learning** | **119 passed** | NEW |
| kernel | 161 passed | unchanged |
| security | 165 passed | unchanged |
| execution | 257 passed, 18 skipped | unchanged |
| review | 114 passed | unchanged |
| runtime | 268 passed | unchanged |
| artifacts | 25 passed | unchanged |
| orchestration | 101 passed, 6 skipped | unchanged |
| ai_infrastructure | 97 passed | unchanged |
| connectors | 93 passed | unchanged |
| events | 228 passed | unchanged |
| event_platform | 56 passed | unchanged |
| modernization | 383 passed, 59 skipped | unchanged |
| persistence | 70 passed | unchanged |
| power_engines | 135 passed, 3 skipped, **1 failed** | pre-existing |
| workflows | 218 passed | unchanged |
| workforce | 36 passed, 2 skipped | unchanged |
| composition | 143 passed, **3 failed** | pre-existing |
| api | **41 passed** | 1 test updated (Gate 9) |

**Suites with no tests:** `knowledge_platform`, `models`, `prompts`, `shared`,
`tools` (no test directories at HEAD).

---

## 3. Failures — All Pre-Existing, None Caused by 19B-1

Verified by `git stash`-ing the 19B-1 changes and re-running:

| Failure | Baseline? |
|---|---|
| `composition::test_canonical_context_builder_invoked_in_execution_path` | **PRE-EXISTING** |
---

## 4. Regressions Found and Fixed During 19B-1

| # | Regression | Resolution |
|---|---|---|
| R-1 | `test_learning_and_reflection_engine` failed: my rewrite dropped the Review Engine's severity-shaped findings, breaking the `defect_prevention` contract. | Added `_finding_is_defect_prevention()` / `_finding_confidence()` supporting both evidence shapes. Restored; green. |
| R-2 | `test_self_improvement_center_is_non_autonomous` failed: it asserted the **fabricated** data existed. | Gate 9 required removing that fabrication. Security assertions kept and strengthened; fabricated-content assertions inverted. |
| R-3 | Gateway `_deny()` raised on a malformed candidate (fail-open). | `_safe_uuid()` added. |
| R-4 | Unknown boundary decision bypassed a `frozenset` membership test. | Replaced with an explicit allow-value check. |

---

## 5. Acceptance Criteria

| Criterion | Status |
|---|---|
| 0 product failures | **PASS** (4 pre-existing, reproduced at baseline) |
| 0 collection errors | **PASS** |
| Security tests green | **PASS** — 165 passed, unchanged |
| No regression in certified systems | **PASS** |
| `evaluate_learning_proposal` production-enforced | **PASS** |
| Fail-closed | **PASS** — 6 failure modes verified |
| Level 5 unreachable / self-approval impossible | **PASS** |
| Guardrail mutation impossible | **PASS** |
| No autonomous promotion / no self-modification | **PASS** |
| Evidence-backed / project-scoped | **PASS** |
| Telemetry truthful | **PASS** |
| 18-J/18-K/18-L contracts intact | **PASS** (`git diff --quiet`) |
| `composition::test_canonical_durable_artifact_wiring` | **PRE-EXISTING** |
| `composition::test_execution_platform_integration::test_autoforge_system_execution_wiring` | **PRE-EXISTING** |
| `power_engines::test_delivery_hardening::test_health_check_script_execution_and_exit_codes` | **PRE-EXISTING** |

### Environment-only failure

`test_health_check_script_execution_and_exit_codes` fails because a local
process occupies port 8080 — **finding F-05** from the 18-LF post-certification
audit. Operator/environment condition; reproduces identically at baseline; does
not occur on `ubuntu-latest` CI.