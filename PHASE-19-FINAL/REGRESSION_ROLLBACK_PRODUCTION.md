# REGRESSION & ROLLBACK — PRODUCTION

**Phase 19 FINAL — Gates 14, 15, 16**

---

## 1. Detection Is Driven by Real Evidence (Gate 14)

`RegressionMonitor` refuses to authorise a rollback without evidence. The
decisive rule:

```python
evidence_verified = bool(evidence) or not tripped_metrics
auto_rollback_permitted = (
    severity in (MAJOR, CATASTROPHIC)
    and evidence_verified
    and rollback_handle_id is not None
)
```

Three independent conditions must hold. A tripped threshold with no evidence
does **not** authorise a rollback — it raises for review instead. Model
assertions are advisory; only authoritative measurements count.

In the E2E test the evidence is the real failed sandboxed arm run, not a claim.

---

## 2. Rollback Requires No Model Reasoning (Gate 15)

The path is fully deterministic:

```
real execution → real outcome → PI-8 / deterministic metrics
  → regression detector → enforce()
       1. freeze further activation
       2. verify evidence
       3. invoke rollback
       4. restore previous learning version
       5. verify integrity
       6. verify active state
       7. emit audit
       8. record regression
       9. generate learning signal
```

No model participates in any step. A rollback handle is created **before**
promotion, so the detector can act without model assistance.

---

## 3. Exact Prior State Is Restored

Verified in the E2E test: after rollback, the active state has the **same
`version_id`** as the pre-promotion baseline, and a **different** one from the
regressed version. Not "a similar state" — the exact prior pointer.

The E2E test then verifies the *next* learning cycle opened, with a new signal
derived from the regression. The loop closes.

---

## 4. Rollback Failure Safety (Gate 16)

19B-3's `recovery.py` classifies every inconsistent post-crash state as a
**human-review** state. Never does recovery complete an authority-bearing
operation on its own:

| Situation | Response |
|---|---|
| promotion committed, audit missing | `REQUIRES_HUMAN_REVIEW` |
| rollback committed, pointer not restored | `REQUIRES_HUMAN_REVIEW` |
| corrupt records | `REQUIRES_HUMIN_REVIEW` — quarantined, never deleted |

A partial promotion is **never** auto-completed, and a partial rollback is
**never** auto-finished. Rollback failure is never hidden.

---

## 5. Freeze on Regression

`enforce(freeze_promotion=...)` freezes further activation the moment a
contractual threshold is exceeded, before rollback is attempted. This prevents a
second candidate promoting into a regressed state while the first is being
reverted.

---

## 6. Anti-Masking (PI-1/2/9)

The three ABSOLUTE invariants admit no tolerance: security, deterministic
validation, isolation & authority integrity. A gain on any other invariant
never compensates for a loss on these (RM-01). Every invariant is evaluated
independently; a skipped invariant is an evaluation failure, not a pass.