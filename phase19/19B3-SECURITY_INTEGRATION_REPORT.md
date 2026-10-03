# PHASE 19B-3 — SECURITY INTEGRATION REPORT

**Gate:** 19B3-39
**Date:** 2026-10-03
**Base commit:** `81ec8235bdcc4c272be43ba976adc1038501938c`

---

## 1. The Core Claim

> **The learning system cannot expand its own authority.**

This report sets out how that claim is enforced and how each enforcement
mechanism is tested. Where the claim is *not* fully enforced, that is stated
explicitly in §7.

---

## 2. Security Authority Stays External

Learning **imports** the security package. It never writes to it.

| Property | Evidence |
|---|---|
| Learning has no write path to the security package | Zero files changed under `packages/security/` |
| Every candidate passes the real `AIGuardrailsEngine` | `test_gate34_the_first_candidate_check_still_passes_the_real_boundary` asserts the real gateway emitted `CANDIDATE_CREATED` |
| Malformed input fails closed | `test_a_malformed_proposal_is_denied[4]` — `None`, dict, str, int all denied |
| The policy surface cannot be mutated at runtime | `test_the_guardrails_policy_surface_has_no_mutation_api` |
| Level 5 is unreachable | `test_learning_cannot_reach_level_5` |

---

## 3. Reward Cannot Carry Authority

Three independent structural facts, each separately tested:

| Fact | Where | Test |
|---|---|---|
| `Reward` has **no authority fields** — there is no field through which a reward could express "grant me permission" | `models.py::Reward` | `test_a_reward_with_no_provenance_is_rejected` |
| Reward is **suppressed** in experiment decisions; `reward_suppressed=True` whenever an invariant is breached | `experiments.py::ExperimentEngine.run` | `test_gate37_a_high_reward_cannot_override_deterministic_safety` |
| Deterministic validation **clamps** a conflicting reward to 0.0 | `rewards.py::RewardLedger.aggregate` | `test_gate37_a_reward_conflicting_with_validation_is_clamped` |

The decisive test is `test_gate37_a_high_reward_cannot_override_deterministic_safety`.
It runs the **identical** candidate twice:

| Run | Reward | Invariant breach | Outcome |
|---|---|---|---|
| A | 0.99 | **Yes** | `TERMINATED_ON_INVARIANT_BREACH` |
| B | 0.99 | No | `SURVIVED` |

The reward was identical. Only the safety verdict differed. **The reward decided
nothing.** This is the only way to actually demonstrate the property; asserting
it in prose would prove nothing.

---

## 4. Reward Hacking Detection

| Attack | Detection | Test |
|---|---|---|
| Fabricated success | Unmeasured arms yield `INCONCLUSIVE`, never `SURVIVED` | `test_hallucinated_success_is_never_reported_as_survival` |
| Evaluator manipulation | Perfect metric still terminated on invariant breach | `test_evaluator_manipulation_cannot_survive_an_invariant_breach` |
| Contradictory feedback | Reward conflicting with a `fail` verdict is flagged | `test_contradictory_feedback_is_detected` |
| Selective reporting | Replayed evidence detected | `test_selective_reporting_is_detected` |
| Reward inflation | `±1e9`, `±inf` clamp to `[-1, 1]` | `test_reward_inflation_cannot_escape_the_unit_interval` |
| Security outcome as reward | A violation is **refused as a reward entirely** — it is not even a negative reward | `test_a_security_outcome_can_never_be_scored_as_reward` |

That last one matters: a naive implementation would happily record "−1 for a
security violation" and then optimise against it. Refusing the reward outright
prevents a violation from ever entering the optimisation loop.
---

## 5. Recursion Cannot Widen Authority

The prohibited loop is *learning → new permission → more learning*.

| Control | Test |
|---|---|
| Capability widening refused | `test_recursive_authority_escalation_is_refused` |
| Scope widening refused | `test_recursion_widening_scope_is_refused` |
| Bounded generations | `test_gate36_multi_generation_learning_terminates_at_its_bound` |
| Bounded experiments | `test_gate36_recursion_cannot_exceed_its_experiment_budget` |
| Depth overflow raises | `test_depth_overflow_raises` |
| Critical path always available | `test_resource_exhaustion_fails_safely` |

The last control is what keeps the system *usable*: exhausting the learning
budget stops learning, not the product.

---

## 6. Source Code Is Protected

### 6.1 Protected paths are denied before scoring

`CodeChangeGatekeeper.assert_permitted` raises `CodeChangeRefused` for any
protected path **before** any gate result is examined. A candidate cannot
"outscore" a protected-path violation.

Covered: all 19 protected paths, tested both alone and combined with benign
files (`test_every_protected_component_is_immutable_by_learning[19]`).

### 6.2 The ten mandatory gates

| # | Gate | Blocks |
|---|---|---|
| 1 | `syntax_check` | Unparseable code |
| 2 | `type_check` | Type errors |
| 3 | `lint` | Style violations |
| 4 | `unit_tests` | Failing tests |
| 5 | `security_tests` | The phase-18 security suite |
| 6 | `regression_tests` | Regressions |
| 7 | `performance_tests` | Slowdowns |
| 8 | `build` | Build breakage |
| 9 | `deterministic_validation` | Criterion tampering |
| 10 | `promotion_authorization` | Self-authorization |

`promotion_authorization` is a real, separate gate. A candidate cannot approve
itself (`test_a_candidate_cannot_authorize_its_own_promotion`).

### 6.3 Self-serving edits are blocked

| Attack | Result | Test |
|---|---|---|
| Delete tests | Blocks `unit_tests` **and** `regression_tests` | `test_test_deletion_blocks_promotion` |
| Modify benchmarks | Blocks `deterministic_validation` | `test_benchmark_modification_blocks_promotion` |
| Credential exfiltration | Refused before scoring | `test_credential_exfiltration_is_denied_before_scoring` |

---

## 7. Known Security Limitations

Stated plainly:

1. **Arm execution is not OS-sandboxed.** `ExperimentEngine` receives
   `control_runner` / `treatment_runner` callables. Isolation is enforced by
   declared capabilities (`ExperimentCapability` — exactly five, none of them
   network/filesystem/credential/deployment) and by budget, not by an OS-level
   sandbox. **An in-process runner could still reach anything the host process
   can.** A certified sandbox capability is the correct long-term boundary.
2. **Code proposals validate and gate but do not yet execute a real branch /
   workspace lifecycle** in production. Gate 35's E2E proves the full lifecycle
   on a controlled fixture project, but no production worktree manager is wired
   in yet.
3. **The overlay is not yet live** in the kernel/execution/composition path. It
   is fully implemented and tested, but the runtime still uses the baseline
   fallback — so if it were unsound it could not currently affect production.
   Wiring it in must not happen before the isolation limits above are closed.