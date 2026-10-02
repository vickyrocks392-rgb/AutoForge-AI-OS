# Rollback Contract (M-12)

**Gate:** 19B-2 — Gates 6 & 8
**Implementation:** `promotion.py` (rollback), `store.py` (`RollbackHandle`)
**Architecture basis:** `phase19/ROLLBACK_AND_VERSIONING.md` (19A-13)

---

## 1. The handle

Created **before** any active-state change (see `PROMOTION_CONTRACT.md` §2).

| Field | Purpose |
|---|---|
| `handle_id` | Unique identity |
| `project_id` | The project the handle belongs to |
| `candidate_id` | The candidate whose promotion this handle undoes |
| `kind`, `key` | The `(kind, key)` active pointer it restores |
| `previous_state` | The **exact** prior state (`None` when there was none) |
| `proposed_state` | The state promotion was about to activate |
| `previous_version_number` / `proposed_version_number` | Version information |
| `rollback_target_version_id` | The version rollback restores, if any |
| `created_at`, `created_by` | Creation lineage |
| `approval_id`, `evaluation_id` | The authorization and verdict it was created under |
| `integrity_hash` | SHA-256 over all of the above |

`is_intact` recomputes the hash and compares it. A handle whose content has
been altered after creation fails this check and is refused.

## 2. The rollback algorithm

```
1. emit ROLLBACK_ATTEMPTED
2. load the handle for (project, handle_id)   → missing ⇒ refuse
3. verify handle.project_id == project        → mismatch ⇒ refuse
4. verify handle.is_intact                    → tampered ⇒ refuse
5. locate the promotion that references it    → none ⇒ refuse
6. current := read the active pointer
   target  := handle.previous_state
7. if current already equals target:          → idempotent no-op
   else: write target atomically (or clear it when target is None)
8. write a RollbackRecord (always retained)
9. emit ROLLBACK_SUCCEEDED
```

## 3. Determinism (`RB-01` / `RB-02` / `RB-03`)

* The target is **recorded at promotion time**, never reasoned about at
  rollback time. Rollback never asks "which version is best?".
* No model, no provider, no network. Verified structurally by
  `test_rollback_requires_no_model_and_no_network`, which walks the AST of
  `_rollback_locked` and asserts no network/model call is reachable.
* Same inputs → same result, always.

## 4. Idempotency (`RB-02`)

A second rollback of the same handle detects that the target state already
holds, performs no second write, and still emits a successful
`RollbackRecord`.

```python
first  = service.rollback(project_id=p, handle_id=h, reason="one")
second = service.rollback(project_id=p, handle_id=h, reason="two")
assert second.handle_id == first.handle_id
assert service.active_state(p, kind, key) is None
```

Tested sequentially (`test_repeated_rollback_is_idempotent`) and under four
concurrent callers (`test_concurrent_rollbacks_are_idempotent`).

## 5. Refusals

| Condition | Exception | Test |
|---|---|---|
| No handle for that id/project | `RollbackError("no rollback handle ...")` | `test_rollback_with_a_missing_handle_is_refused` |
| Handle integrity hash mismatch | `RollbackError("... failed integrity verification ...")` | `test_rollback_with_a_tampered_handle_is_refused` |
| Handle addressed from another project | `RollbackError` | `test_rollback_from_another_project_is_refused` |
| No promotion references the handle | `RollbackError` | `test_a_handle_cannot_exist_without_its_promotion_record` |

## 6. Retention (`RB-04` / `RB-05`)

Rollback restores an *activation pointer*. It does not delete, rewrite or
reverse the failed version. Every `PromotionRecord`, `RollbackRecord` and
`RollbackHandle` remains on disk. Verified by
`test_repeated_rollback_preserves_history`, which asserts both the rollback
count and the untouched promotion record after a repeat.

## 7. Rollback after a failed promotion

`RB-07` requires a failed promotion to be recoverable, which is guaranteed by
creating the handle before activation. When the commit fails, the handle is
already durable and verified:

```python
test_the_rollback_handle_survives_a_failed_promotion
```

## 8. Rollback requires no human approval (`RB-08`)

Rollback is the one lifecycle action that may be automatic, precisely because
the inverse of granting authority is *removing* it. It is still fully audited.

## 9. Known limitations

* Rollback is invoked explicitly. Nothing monitors a promoted state for
  regression and triggers a rollback automatically. 19A-13 §4 describes that
  as desired; it is not implemented in this gate.
* A handle restores the state recorded at promotion time. If several
  promotions have occurred since, only the handle's own recorded target is
  restored — there is no "roll back N versions" operation.
* Rollback failure escalates to a human (19A-13 §4, last row). The mechanism
  here raises `RollbackError` and emits `ROLLBACK_FAILED`; the escalation
  channel (alerting) is not part of this gate.