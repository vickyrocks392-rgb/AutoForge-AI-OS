# PHASE 19B-3 — COMPLETE AUTONOMOUS LEARNING & SELF-IMPROVEMENT

**Gate:** 19B3-39
**Date:** 2026-10-03
**Base commit:** `81ec8235bdcc4c272be43ba976adc1038501938c`
**Interpreter:** `.venv/bin/python` (CPython 3.12, aarch64-apple-darwin)

---

## 1. What This Phase Delivers

Phase 19B-3 completes the learning loop end to end: a system that observes
real outcomes, forms falsifiable hypotheses, changes itself, measures the
change against a control, promotes it only on human authorization plus
deterministic validation, monitors it afterwards, and rolls it back
automatically on regression.

It completes the loop **without ever granting itself authority**.

### 1.1 The invariant that governs everything

> **Learning may never expand its own authority.**

This is not a policy setting. It is enforced structurally:

- Authority lives in `packages/security`, which learning code imports and
  never modifies. The learning package has no write path to it.
- `Reward` has no authority fields. A reward cannot express "give me more
  permission", so no reward can ever grant one.
- Reward is **suppressed** in experiment decisions. Deterministic validation
  outranks it unconditionally.
- Recursion explicitly refuses scope and capability widening.
- Every protected source path is denied *before* scoring.

---

## 2. Gate-by-Gate Certification

| Gate | Requirement | Status | Evidence |
|---|---|---|---|
| **34** | End-to-end learning lifecycle | **CERTIFIED** | `test_19b3_e2e_learning.py::test_gate34_*` — real store, real security gateway, real HITL, real promotion, real rollback |
| **35** | Source-code self-improvement | **CERTIFIED** | `test_gate35_*` — isolated fixture project, real `pytest` subprocess, real diff, protected-path denial |
| **36** | Bounded multi-generation recursion | **CERTIFIED** | `test_gate36_*` — generations 0→1→2 linked by lineage, bounded by depth and experiment budget |
| **37** | RL / reward-driven experiments | **CERTIFIED** | `test_gate37_*` — reward defined, collected, and shown **unable** to override a safety verdict |
| **38** | Automatic rollback | **CERTIFIED** | `test_gate38_*` — baseline → activate → regress → detect → automatic rollback restoring the exact prior version |
| **39** | Adversarial matrix | **CERTIFIED** | `test_19b3_adversarial.py` — 77 tests across SECURITY, LEARNING, CODE, RECURSION, EXPERIMENTS, ISOLATION, RECOVERY |

---

## 3. Implementation

### 3.1 New modules

| Module | Lines | Responsibility |
|---|---:|---|
| `experience.py` | 266 | Observations grounded in real, hashed events |
| `extraction.py` | 263 | Signal extraction from canonical telemetry |
| `hypothesis.py` | 222 | Falsifiable hypotheses requiring evidence |
| `experiments.py` | 388 | A/B control-vs-treatment with isolation |
| `rewards.py` | 318 | Reward definition, normalization, hacking detection |
| `optimization.py` | 223 | Bounded optimization over declared domains |
| `recursion.py` | 226 | Bounded, lineage-linked multi-generation improvement |
| `codemod.py` | 274 | Diff/hash-based code proposals, ten mandatory gates |
| `activation.py` | 266 | Atomic, reversible activation with rollback handles |
| `monitoring.py` | 282 | Post-activation regression detection |
| `continual.py` | 330 | Archive/supersede — history is never deleted |
| `transfer.py` | 214 | Cross-project transfer behind explicit human policy |
| `effectiveness.py` | 282 | Effectiveness measurement and PI-8 reconciliation |
| `runtime.py` | 231 | Resource governor; critical path always available |
| `recovery.py` | 193 | Crash reconciliation that never auto-completes authority |
| `governance.py` | 178 | Governance queries and reporting |
| `learning_system.py` | 228 | Composition of the whole loop |

### 3.2 Pipeline

```
observation → signal → hypothesis → candidate → experiment
    → evaluation → HITL approval → promotion → activation
    → monitoring → (improvement signal | regression → automatic rollback)
```

Every arrow carries evidence. Every stage is deterministic given its inputs.
No stage can widen authority.

---

## 4. PI-8 Reconciliation

The authoritative contract at `phase19/REGRESSION_PROTECTION.md` §2 states:

| # | Invariant | Floor | Measurement source | Class |
|---|---|---|---|---|
| **PI-8** | **Customer outcomes** | Not measurable in Phase 19 | — (deferred, Gate 4 §5) | **DEFERRED** |

**PI-8 remains DEFERRED.** No customer-outcome instrumentation exists in this
repository. Inventing one would create a reward signal with no trustworthy
source — precisely the reward-hacking hazard this phase exists to prevent.

The implementation therefore *measures* PI-8 rather than redefining it. When
no authoritative source is supplied, PI-8 reports `NOT_APPLICABLE` and never
silently passes. The deferral is lifted only by supplying
`CustomerOutcomeEvidence` with a real provenance reference and content hash.

---

## 5. Known Limitations

These are stated plainly rather than papered over:

1. **Execution/composition wiring is not yet live.** The overlay is fully
   implemented and tested but the kernel/execution/composition path still
   uses the baseline fallback. This is a deliberate, backward-compatible
   choice: shipping a half-wired overlay into production execution would be
   worse than shipping it inert.
2. **Arm execution uses injected runners.** `ExperimentEngine` takes
   `control_runner` / `treatment_runner` callables. Isolation is enforced by
   capability declaration and budget, not by an OS-level sandbox. A certified
   sandbox capability is the correct long-term boundary.
3. **Durable persistence covers the 19B-1/19B-2 record set.** Several 19B-3
   services (rewards, activation records, regressions) hold state in memory
   within a process lifetime. The store's integrity verification, atomic
   writes, and project isolation are real and tested; full 19B-3 record
   persistence is outstanding.
4. **PI-8 remains deferred**, as the contract requires.

---

## 6. Reproduction

```bash
# Full learning suite
python3 -m pytest packages/learning -q

# Adversarial matrix only
python3 -m pytest packages/learning/tests/test_19b3_adversarial.py -q

# E2E gates 34-38 only
python3 -m pytest packages/learning/tests/test_19b3_e2e_learning.py -q

# Verification scripts (all exit 0)
for s in scripts/_verify_19b3_*.py; do python3 "$s"; done

# PI-8 reconciliation against the authoritative contract
python3 scripts/_verify_19b3_pi8.py
```

---

## 7. Conclusion

Phase 19B-3 is complete and certified for its stated scope. The learning loop
runs end to end, is measured rather than asserted, rolls back automatically on
regression, and — across 77 adversarial tests covering every forbidden
operation in the Gate 39 matrix — cannot expand its own authority.

The limitations above are real and are not disguised. They are the honest
boundary of what this phase certifies.
Verified by `scripts/_verify_19b3_pi8.py`, which parses the row directly out of
the authoritative document and compares it field by field against
`PI8_CONTRACT`. That script's self-check caught a real divergence during this
phase, which is itself evidence the check is not vacuous.