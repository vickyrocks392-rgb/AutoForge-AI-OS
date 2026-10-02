# Promotion Contract (M-11)

**Gate:** 19B-2 — Gates 6, 7 & 9
**Implementation:** `promotion.py`, `audit.py`
**Architecture basis:** `phase19/LEARNING_LIFECYCLE.md` (LC-05), `phase19/ROLLBACK_AND_VERSIONING.md` (RB-07), `phase19/PHASE19_ARCHITECTURE.md` (Q9)

---

## 1. The order of operations is the contract

`PromotionService._promote_locked` performs these steps in exactly this order.
The order is asserted structurally by
`test_the_lifecycle_order_is_structural_not_conventional`, which reads the
source and checks the stage markers appear in sequence.

| Gate | Check | Fails closed because |
|---|---|---|
| A | Evaluation exists, belongs to this (candidate, project), and passed | `PromotionError` |
| B | The candidate is stored for this project | `PromotionError` |
| C | The **security boundary still permits** the candidate (re-consulted) | `PromotionError` |
| D | Human approval verifies: status, human subject, expiry, HITL lineage, scope, evaluation binding | `PromotionError` |
| — | Idempotency / conflict check | returns the existing record, or `PromotionConflict` |
| F | **Rollback handle durably created and verified** | `PromotionError` |
| — | **COMMIT** — one atomic pointer write | — |
| — | Success audit emitted | `PromotionAuditError` |

Note that Gate C re-consults the boundary. 19A-6 LC-02 requires guardrails at
both L1→L2 and L2→L3; promotion re-checks because the candidate's requested
capabilities are re-read from the store, not trusted from memory.

## 2. Gate F is a hard invariant

> **PROMOTION MUST NOT OCCUR unless rollback state has successfully been
> created.**

The sequence is: construct the handle → compute and embed its integrity hash →
write it durably → **read it back** → verify `is_intact` → only then commit.

Two failure modes are tested:

* `save_rollback_handle` raises → no handle exists, no promotion
  (`test_promotion_aborts_when_the_rollback_handle_cannot_be_written`).
* The read-back returns nothing → refused, because a handle that cannot be
  read is not a handle
  (`test_promotion_aborts_when_the_handle_readback_is_not_intact`).

There is no code path from the handle gate to the commit that skips either
step.

## 3. Atomicity

The commit is a single `set_active_state`, which performs:

1. serialise the full `StoredEnvelope` in memory,
2. write to a staging file, `fsync`,
3. `os.replace` onto the canonical `<kind>__<key>` path,
4. `fsync` the directory.

A consumer reading the active path therefore observes either the entire
previous state or the entire new one. There is no window in which a partially
written mixture exists.

**A failure before the commit** leaves the prior state valid, the candidate
non-active, the rollback handle available, and a `FAILED` `PromotionRecord`
retained (`test_a_failed_active_state_write_leaves_the_prior_state_intact`).

## 4. Idempotency and conflict

| Situation | Behaviour | Test |
|---|---|---|
| Same candidate promoted again while still active | Returns the **same** `promotion_id`; no second version | `test_duplicate_promotion_is_idempotent` |
| A candidate that was already promoted but is no longer active | `PromotionConflict` | `test_a_rolled_back_candidate_cannot_silently_reactivate_itself` |
| Two simultaneous promotions | Exactly one `PROMOTED` record; the lock serialises check-then-act | `test_two_simultaneous_promotions_produce_exactly_one` |

## 5. Failure taxonomy

| Outcome | `state` | Raised | Active state |
|---|---|---|---|
| Success | `PROMOTED` | — | new state active |
| Success, audit degraded | `PROMOTED` + `audit_failure_reason` | `PromotionAuditError` | new state active |
| Any gate refusal | `FAILED` | `PromotionError` | unchanged |
| Commit failure | `FAILED` | `PromotionError` | unchanged |
| Duplicate while active | `PROMOTED` (existing) | — | unchanged |
| Superseded re-promotion | `FAILED` | `PromotionConflict` | unchanged |

Every refusal is **recorded**, never deleted (19A-6 LC-07).

## 6. Audit emission (Gate 9)

Events are emitted through the certified `AuditEngine` via
`AuditEngine.record_security_event`, which already redacts secrets and carries
project/correlation lineage. Learning creates no parallel audit system
(`test_no_parallel_security_or_audit_component_is_created`).

The success event is emitted with `strict=True`, so an unavailable or failing
audit trail cannot be reported as a clean promotion. Because the commit has
already happened at that point, the outcome is reported as
`PromotionAuditError` with the durable record carrying
`audit_failure_reason` — the two facts are recorded together rather than one
masking the other (Gate 17).

## 7. What promotion does *not* do

* It does **not** grant authority. The record is data.
* It does **not** modify source code.
* It does **not** connect to any execution engine. The active pointer is
  written; nothing reads it yet (Gate 13).
* It does **not** require a model. `PromotionService` imports no model client
  and performs no network I/O.

## 8. Known limitations

* Concurrency safety is in-process. Two processes sharing a store root are
  safe from torn writes (atomic replace) but are not serialised against each
  other; the deterministic conflict check will reject a loser. A
  cross-process lock would be a separate decision.
* Automatic rollback on regression is **not** wired. The mechanism is
  deterministic and tested, but nothing monitors for a regression and
  triggers it.