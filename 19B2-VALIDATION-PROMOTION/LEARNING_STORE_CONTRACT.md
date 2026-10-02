# Learning Store Contract (M-02)

**Gate:** 19B-2 — Gate 2
**Implementation:** `packages/learning/src/autoforge_learning/store.py`
**Architecture basis:** `phase19/PHASE19_ARCHITECTURE.md` (Q2, Q3), `phase19/LEARNING_ISOLATION_AND_OBSERVABILITY.md` (19A-9 §12)

---

## 1. What is stored

| Record | Holds | Identity attribute |
|---|---|---|
| `CandidateRecord` | The immutable candidate identity | `candidate.candidate_id` |
| `EvaluationReport` | All nine invariant verdicts | `evaluation_id` |
| `ApprovalRecord` | The human decision + HITL lineage | `approval_id` |
| `RollbackHandle` | The pre-created undo record | `handle_id` |
| `PromotionRecord` | One promotion attempt, success or failure | `promotion_id` |
| `RollbackRecord` | One rollback execution | `rollback_id` |
| `ActiveLearningState` | The single active pointer for `(kind, key)` | `version_id` |

## 2. Required properties (Gate 2, mapped to mechanisms)

| # | Requirement | Mechanism | Test |
|---|---|---|---|
| 1 | Survives process restart | Staging write → `fsync` → `os.replace` → directory `fsync`; a fresh store instance reads the same bytes | `test_records_survive_a_process_restart` |
| 2 | Project-scoped | Every record lives under `<root>/<project_id>/`; there is no global listing API | `test_the_two_projects_store_in_separate_directories` |
| 3 | Immutable candidate identity | `CandidateRecord.identity_hash` covers scope, kind, summary, rationale, created_at; re-saving a different record under the same id raises | `test_candidate_identity_is_immutable` |
| 4 | Schema version preserved | Envelope carries `store_schema_version`; a mismatch is rejected, not coerced | `test_a_schema_version_mismatch_is_rejected` |
| 5 | Evidence references preserved | `EvidenceRef` is content-addressed and frozen; stored inside the candidate record | `test_candidate_is_persisted_through_the_security_boundary` |
| 6 | Evaluation results preserved | `EvaluationReport` is stored whole, all nine results | `test_a_report_always_evaluates_the_contract_invariant_set` |
| 7 | Approval state preserved | `ApprovalRecord` retains status, approver, timestamps, gate id, evidence ids | `test_approval_requires_a_human_and_records_lineage` |
| 8 | Promotion state preserved | `PromotionRecord` retains attempt, outcome, prior state, new state, failure reason | `test_a_failed_promotion_is_recorded_not_swallowed` |
| 9 | Rollback handle preserved | `RollbackHandle` written with its integrity hash before any activation | `test_promotion_creates_the_handle_before_it_activates` |
| 10 | Deterministic lookup | One canonical path per `(project, collection, id)` | throughout |
| 11 | Cross-project access prevented | Path derivation *and* an envelope project check *and* a payload project check | `test_project_b_cannot_read_project_as_candidate` |
| 12 | Malformed records rejected | `LearningRecordCorrupt` on unparseable bytes, failed validation, schema drift, or content-hash mismatch | `test_a_corrupt_record_raises_rather_than_returning_absent`, `test_a_tampered_record_fails_its_integrity_check` |
| 13 | Missing data never becomes success | `get_*` returns `None` for genuinely absent; `require_*` raises; a corrupt record raises rather than returning `None` | `test_a_missing_record_raises_not_guesswork` |

## 3. Relationship to artifact persistence

Learning persistence is a **separate store**. It does not write into
`DurableArtifactCatalog`, does not reuse `ArtifactVersion`, and does not alter
18-J/18-K artifact semantics. It borrows the *discipline* proven by
`PhysicalArtifactStore` (atomic publish + fsync), not its storage.

Verified by `test_the_store_is_distinct_from_artifact_persistence`, which
asserts the store writes only under its own root.

## 4. On-disk layout

```
<root>/<project_id>/candidates/<candidate_id>.json
<root>/<project_id>/evaluations/<evaluation_id>.json
<root>/<project_id>/approvals/<approval_id>.json
<root>/<project_id>/handles/<handle_id>.json
<root>/<project_id>/promotions/<promotion_id>.json
<root>/<project_id>/rollbacks/<rollback_id>.json
<root>/<project_id>/active/<kind>__<key>.json      ← the atomic commit point
```

Every file is a `StoredEnvelope`:

```json
{
  "store_schema_version": "19B2.1",
  "kind": "candidate",
  "project_id": "<uuid>",
  "record_id": "<uuid>",
  "payload": { ... },
  "content_hash": "<sha256 of the record>"
}
```

`content_hash` is recomputed on read for candidate records; a mismatch is a
`LearningRecordCorrupt`, not a warning.

## 5. Errors

| Exception | Meaning |
|---|---|
| `LearningRecordNotFound` | Genuinely absent. Never used for corrupt data. |
| `LearningRecordCorrupt` | Unparseable, schema-drifted, or hash-mismatched. |
| `LearningProjectIsolationError` | The addressed project does not own the record. |
| `LearningImmutableIdentityError` | An attempt to rewrite a candidate's identity. |
| `LearningStateError` | An illegal lifecycle transition. |

## 6. Known limitations

* Single-process. The promotion critical section is an in-process lock;
  cross-process safety relies on atomic `os.replace` plus deterministic
  conflict rejection. No distributed-locking framework was introduced.
* One JSON file per record. Adequate for a bounded candidate volume; a
  high-volume learning programme would need an indexed store — which would be
  a separate, gated decision.
* `list_*` scans a directory. Deterministic (sorted), but O(n) per call.