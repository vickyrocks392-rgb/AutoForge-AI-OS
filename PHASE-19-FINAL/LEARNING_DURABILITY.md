# LEARNING DURABILITY

**Phase 19 FINAL — Gates 8, 9, 27**

---

## 1. The Problem Being Closed

19B-3 reported that several learning and experiment services still held state in
memory. A process restart lost that state.

`lifecycle_store.py::DurableLearningLifecycleStore` closes this for the whole
learning lifecycle.

---

## 2. What Is Now Persisted

| Record | Collection |
|---|---|
| `ExecutionObservation` | `observations/` |
| `LearningSignal` | `signals/` |
| `Hypothesis` | `hypotheses/` |
| `Experiment` | `experiments/` |
| `ExperimentRun` | `experiment_runs/` |
| `ActivationRecord` | `activations/` |
| `RegressionReport` | `regressions/` |
| `LearningLineage` | `lineage/` |
| `CustomerOutcomeMeasurement` (PI-8) | `pi8/` |

Deliberately **not** persisted: an in-flight experiment's stdout buffer, cached
metrics. Those are safe to lose. Everything that governs an authority-bearing
decision is durable.

---

## 3. Reused Discipline, Not a New Framework

AutoForge already has a durable, atomically-published filesystem boundary in
`PhysicalArtifactStore`. This store adopts that exact discipline rather than
inventing a second storage abstraction:

1. write to a staging name
2. `fsync` the file
3. `os.replace` into place
4. `fsync` the directory

A reader therefore only ever observes a fully written record.

Learning persistence stays distinct from artifact persistence: 18-J/18-K/18-L
artifact semantics are untouched.

---

## 4. Guarantees

| Property | Enforcement |
|---|---|
| **Survives restart** | A brand-new store instance recovers everything |
| **Append-only** | Re-saving identical content is idempotent; different content under the same id raises `LearningImmutableIdentityError` |
| **Project isolation** | Records live under a per-project directory; there is no global listing API that could leak across projects |
| **Fail closed** | Corruption raises. It is never converted into an empty-but-successful read |
| **No silent loss** | `verify_complete(project_id)` reports a count for every record kind |

---

## 5. Corruption Handling (Gate 27)

| Corruption | Behaviour |
|---|---|
| wrong content hash | `LifecycleIntegrityError` |
| malformed JSON | `LearningRecordCorrupt` |
| truncated file | `LearningRecordCorrupt` |
| stale schema version | `LearningRecordCorrupt` |
| wrong project on the envelope | `LearningProjectIsolationError` |
| genuinely absent | returns `None` — distinguishable from corruption |

Two properties are load-bearing and directly tested:

1. **Corruption is never an empty success.** A tampered record raises; it never
   reads as "no learning installed".
2. **Listing never skips silently.** `list()` aborts on an unreadable record
   rather than returning a partial set that would look healthy.

---

## 6. Crash Recovery (Gate 9)

`verify_complete()` makes recovery explicit:

```python
counts = DurableLearningLifecycleStore(root).verify_complete(project_id)
# {'observation': 12, 'signal': 4, 'hypothesis': 2, 'experiment': 2,
#  'experiment_run': 2, 'activation': 1, 'regression': 1, 'lineage': 2, 'pi8': 2}
```

A gap is reported rather than assumed healthy. Combined with the 19B-3
`RecoveryReconciler`, a partial promotion or partial rollback after a crash
remains a **human-review** state — recovery never auto-completes an
authority-bearing operation.

---

## 7. Versioning

`LIFECYCLE_SCHEMA_VERSION = "19F.1"` is a separate, versioned namespace from the
19B-2 store (`"19B2.1"`). An older reader can never silently mis-parse a newer
envelope; a version mismatch is rejected outright.

---

## 8. Verified

| Test | Proves |
|---|---|
| `test_every_lifecycle_record_survives_a_process_restart` | Restart safety |
| `test_history_cannot_be_rewritten` | Append-only |
| `test_a_tampered_record_fails_integrity` | Corruption detected |
| `test_a_corrupt_record_is_never_returned_as_empty` | No silent success |
| `test_a_truncated_record_is_rejected` | Truncation detected |
| `test_a_stale_schema_record_is_rejected` | Version mismatch rejected |
| `test_a_wrong_project_record_is_refused` | Project isolation |
| `test_verify_complete_reports_every_kind` | No silent loss |
| `test_pi8_measurements_survive_a_restart` | PI-8 is durable |