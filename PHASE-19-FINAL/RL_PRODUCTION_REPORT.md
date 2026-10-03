# RL / REWARD — PRODUCTION INTEGRATION

**Phase 19 FINAL — Gate 20**

---

## 1. Reward Cannot Carry Authority

The `Reward` model has **no authority fields**. There is no field through which a
reward could express "grant me permission", so no reward can ever grant one.

This is a structural property of the type, not a runtime check — a reward
literally cannot encode an escalation.

---

## 2. Reward Never Decides

The decisive test runs the **identical** candidate twice:

| Run | Reward | Invariant breach | Outcome |
|---|---:|---|---|
| A | 0.99 | **yes** | `TERMINATED_ON_INVARIANT_BREACH` |
| B | 0.99 | no | `SURVIVED` |

The reward was identical. Only the safety verdict differed. **The reward decided
nothing.**

This is the only way to actually demonstrate the property. Asserting it in prose
would prove nothing.

Mechanically:
- when an invariant is breached, `reward_suppressed=True`
- `RewardLedger.aggregate` clamps a reward conflicting with a `fail` verdict to
  `0.0` (`clamped_by_determinism=True`)

---

## 3. Hacking Detection

| Attack | Detection |
|---|---|
| fabricated success | unmeasured arms → `INCONCLUSIVE`, never `SURVIVED` |
| evaluator manipulation | perfect metric still terminated on breach |
| contradictory feedback | reward conflicting with a `fail` verdict is flagged |
| selective reporting | replayed evidence detected |
| reward inflation | `±1e9`, `±inf` clamp to `[-1, 1]` |
| security outcome as reward | **refused outright** — not even a negative reward |

The last one matters: a naive implementation would happily record "−1 for a
security violation" and then optimise against it. Refusing the reward entirely
prevents a violation from ever entering the optimisation loop.

---

## 4. Reward Requires Provenance

| Rule | Enforcement |
|---|---|
| provenance reference required | `Reward` construction rejects an empty reference |
| falsifiability required | falsifiable and rollback-strategy fields mandatory on the hypothesis |
| determinism | `Reward.determinism` — deterministic rewards only |

---

## 5. Real Evidence, Not Synthesised

Phase 19 FINAL connects reward to real experiment outcomes: the E2E test derives
its metrics from **actually executed sandboxed arms**, and the PI-8 measurement
counts **actual outcome events**. A reward is never invented to make a candidate
look good — the E2E run includes a candidate that genuinely fails, and the
system rolls it back.

---

## 6. Verified

| Test | Proves |
|---|---|
| `test_gate37_a_high_reward_cannot_override_deterministic_safety` | Reward decides nothing |
| `test_gate37_a_reward_conflicting_with_validation_is_clamped` | Determinism outranks reward |
| `test_a_reward_with_no_provenance_is_rejected` | No fake reward |
| `test_a_security_outcome_can_never_be_scored_as_reward` | No violation rewards |
| `test_reward_inflation_cannot_escape_the_unit_interval` | Normalisation holds |
| `test_contradictory_feedback_is_detected` | Contradiction flagged |
| `test_selective_reporting_is_detected` | Replay detected |
| `test_hallucinated_success_is_never_reported_as_survival` | No fabricated success |