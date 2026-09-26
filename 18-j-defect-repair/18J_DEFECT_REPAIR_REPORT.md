# 18-J Defect Repair Report

**Workstream:** 18-L — Context Engineering Workstream
**Task:** Part A — 18-J durable-execution state-transition defect repair
**Date:** 2026-09-26
**Status:** PASS — defect repaired, verified, 18-J re-frozen
**Not committed. Not pushed.**

---

## 1. Original Failure

`committed → staging` raised:

```
InvalidTransitionError: Invalid artifact transition committed → staging:
Invalid artifact transition: <DurableArtifactStatus.COMMITTED: 'committed'>
-> <DurableArtifactStatus.STAGING: 'staging'>
details: {'artifact_id': '...', 'current_status': 'committed', 'target_status': 'staging'}
```

Reproduced on the re-materialisation / resume path. Two production callers were
affected: `ArtifactPipeline.record_artifact` (execution) and
`DurableArtifactStoreBridge.store_version` (artifacts).

The defect was previously dormant because the canonical execution path could not
reach the affected re-materialisation. Context Engineering did not cause it; it
made the canonical path capable of reaching it.

## 2. Root Cause — the reported fix was NOT applied

The task reported the fix as adding `COMMITTED → STAGING` to
`validation.py:665`. **That fix was investigated and rejected on evidence.**

Three pieces of evidence established the real cause:

1. **The state machine is correct.** `DurableArtifactStatus` documents the
   18-J lifecycle as `committed -> retired`, with `STAGING` meaning "physical
   content written but *not yet* durably committed". Re-entering STAGING from
   COMMITTED would un-commit content that is already physically verified and
   hash-checked — destroying the exact durability guarantee 18-J exists to
   provide.

2. **An existing test already asserts the transition is illegal.**
   `test_invalid_transition_committed_to_staging` (pre-existing, unmodified)
   requires `InvalidTransitionError`. Adding the transition would have broken an
   intentional invariant.

3. **The real bug is in the caller.** `register_artifact` is *deliberately*
   idempotent — the 18-J contract states "a retry does NOT mint a new logical
   artifact identity". On replay it returns the **existing** record unchanged,
   which may already be COMMITTED. Both callers **ignored the returned status**
   and called `begin_staging()` unconditionally.

> Root cause: *the callers assumed `register_artifact` always returns a freshly
> CREATED record, and did not honour the idempotent-replay contract.*

## 3. State-Machine Semantics

| State | Meaning | Legal exits |
|---|---|---|
| `CREATED` | Catalog record exists, no physical content | `STAGING`, `FAILED` |
| `STAGING` | Physical write in progress; crash window | `COMMITTED`, `FAILED` |
| `COMMITTED` | Catalog **and** physical content durably complete, hash-verified | `RETIRED` |
| `FAILED` / `RETIRED` | terminal | — |

`STAGING` exists specifically so crash recovery can detect the window between
physical write and catalog commit (`reconcile_on_startup`,
`find_orphaned_staging`). A COMMITTED artifact has already passed that window.
Returning it to STAGING would re-open a crash window for content that is already
durable, and would make recovery treat verified content as an in-flight write.

**The transition table was not modified. It is byte-identical.**

## 4. Exact Files Changed

Two source files, plus one new test file:

| File | Change |
|---|---|
| `packages/execution/src/autoforge_execution/artifacts.py` | `record_artifact` now honours the idempotent-replay contract |
| `packages/artifacts/src/autoforge_artifacts/durable_bridge.py` | `store_version` now honours the same contract |
| `packages/runtime/tests/test_18j_defect_repair.py` | **NEW** — 20 focused regression tests |

Explicitly **not** changed: `validation.py`, `artifact_catalog.py`,
`models.py`, `physical_artifact_store.py`, all Context Engineering files, the
Model Router, the inference runtime, and 18-K.

## 5. Exact Repair

Minimal and semantic, in both callers:

```
durable_state = register_artifact(...)      # idempotent; may return COMMITTED

if durable_state.status is COMMITTED:
    if incoming content hash == committed hash:
        -> idempotent replay: reuse the durable artifact, mutate nothing
    else:
        -> raise ArtifactConflictError  (never silently overwrite durable state)
else:
    -> existing CREATED/STAGING -> STAGING -> COMMITTED path, unchanged
```

This satisfies the `DurableArtifactState` contract verbatim: *"An existing key
reused with a differing hash is rejected with a conflict error (unless it
represents a legitimate new version)."*

Constraints honoured: no validation weakened, no exception suppressed, no
generic fallback, no state-machine bypass, no unvalidated assignment, no silent
state mutation, no duplicate execution, no loss of durable state.

## 6. Tests Added/Modified

20 new tests in `packages/runtime/tests/test_18j_defect_repair.py`, covering
every item in task §6:

| §6 requirement | Class | Count |
|---|---|---|
| A. previously failing path | `TestResumeAndReplay` | 5 |
| B. valid transitions still work | `TestValidTransitionsStillWork` | 4 |
| C. invalid transitions still rejected | `TestInvalidTransitionsStillRejected` | 4 |
| D. idempotency | `TestIdempotency` | 3 |
| E. resume | `TestResumeAndReplay` | (above) |
| F. persistence | `TestPersistence` | 2 |
| G. event consistency | `TestEventConsistency` | 2 |

**No existing test was modified.** The pre-existing
`test_invalid_transition_committed_to_staging` still passes unchanged.

### Negative-control proof (the tests are not vacuous)

The naive "fix" was temporarily applied to the state machine to confirm the new
tests actually catch it:

```
FAILED ...::test_committed_to_staging_is_still_illegal
FAILED ...::test_transition_table_unchanged_by_repair
2 failed, 18 passed
```

The state machine was then restored and verified byte-identical via
`git diff` (empty). The new tests reject a wrong repair.

## 7. Full Regression Results

Baseline captured **before** the repair, then re-run after.

| Suite | Baseline (pre-repair) | After repair | Delta |
|---|---|---|---|
| runtime | 248 passed | **268 passed** | **+20** (new defect tests) |
| artifacts | 14 passed | **14 passed** | — |
| execution | 149 passed, 18 skipped | **149 passed**, 18 skipped | — |
| composition | 3 failed, 48 passed | **3 failed, 48 passed** | — |
| workflows | 218 passed | **218 passed** | — |
| kernel | 100 passed | **100 passed** | — |
| review | 114 passed | **114 passed** | — |
| orchestration | 53 passed, 6 skipped | **53 passed**, 6 skipped | — |

- **Existing tests:** all pass; no existing test was modified.
- **New defect regression tests:** 20 passed.
- **Skipped:** 24 (18 execution, 6 orchestration) — unchanged, environment-gated.
- **Pre-existing failures:** 3 (composition), byte-identical failure set.
- **Newly introduced failures:** **0**.

The 3 composition failures remain the pre-existing "no local runtime on
`127.0.0.1:8080`" condition documented in Gate 4B, verified as an identical set
before and after (`grep '^FAILED' | sort`).

**A green new test was not treated as sufficient** — the full suites were run,
and the pre-existing `test_durable_artifact_catalog.py` (including its assertion
that `committed -> staging` is illegal) passes unchanged.

## 8. Original Workflow Reproduction

`18-j-defect-repair/repro_18j_defect.py` (pre/post) and
`18-j-defect-repair/verify_e2e_resume.py` (full canonical workflow).

**Pre-repair:** pass 2 raised `InvalidTransitionError`.

**Post-repair:**
```
pass 1: first materialisation  -> status: committed
pass 2a: IDENTICAL content     -> same artifact_id: True
                                -> status: committed
                                -> RESULT: idempotent replay OK
pass 2b: DIFFERENT content     -> RESULT: ArtifactConflictError (correct)
                                -> committed state preserved: committed 51b216bad1ad
```

Bridge path: `v1 stored -> committed`, `v1 replay -> committed` (no error),
`v2 stored -> committed` (new version takes the normal path).

### Full end-to-end resume across process restarts

The real canonical path — default-configuration system, Context Engineering ON,
real engineering workflow, **system torn down and rebuilt against the same
durable database, then the same task re-submitted**:

```
round 0: initial engineering execution + artifact creation + commit -> completed
round 1: restart + re-materialisation / resume  -> completed
round 2: restart + re-materialisation / resume  -> completed
round 3: restart + re-materialisation / resume  -> completed

all_artifacts_committed            : true
earlier_hashes_never_lost          : true
durable_state_stable_across_resume : true
committed_content_preserved        : true
all_rounds_completed               : true
VERDICT: PASS
```

This is the actual canonical path, not a fabricated sequence. Count growth
(3 → 6 → 9 → 12) is **correct**: each run mints a new `execution_id`, yielding a
new deterministic artifact key, so each round legitimately materialises new
logical artifacts. The invariants that matter — nothing stranded in STAGING,
earlier committed hashes never lost or overwritten — hold in every round.

## 9. Idempotency Verification

- `test_repeated_replay_does_not_mutate_state` — 5 replays, `state_version` set
  size is 1: **no state mutation on replay**.
- `test_repeated_replay_creates_no_extra_files` — artifact root identical after
  3 replays: **no duplicate physical writes**.
- `test_register_artifact_remains_idempotent` — the underlying 18-J guarantee
  is intact.
- `test_replay_creates_no_duplicate_durable_record` — exactly one catalog record
  per logical artifact after replay.
- `test_bridge_replay_of_same_version_is_idempotent` — bridge obeys the same
  contract.

## 10. Resume/Recovery Verification

- `test_replay_with_identical_content_no_longer_raises` — the exact previously
  failing call now succeeds.
- `test_bridge_replay_of_same_version_is_idempotent` — same for the artifact
  platform.
- `test_new_version_still_takes_the_normal_path` — a genuine new version (v2)
  still goes CREATED → STAGING → COMMITTED, so the repair did not collapse
  versioning into replay.
- `test_committed_artifact_is_not_left_in_staging` — no artifact stranded in
  STAGING, no orphans.
- End-to-end: 3 restart/resume rounds all `completed`.

## 11. Persistence Verification

- `test_state_survives_a_fresh_catalog_instance` — the record is readable from
  an **independent** `PersistenceLayer` handle on the same SQLite file (the
  fixture uses a real file, not `:memory:`), with matching status, content hash
  and on-disk content.
- Physical content verified by reading the file back, not just by metadata.
- `reconcile_on_startup` / `find_orphaned_staging` paths unaffected.

## 12. Event/State Verification

- `test_event_emitted_only_after_durable_commit` — the durable record is
  COMMITTED by the time the artifact event is published, preserving the 18-K
  ordering guarantee "durable state is committed BEFORE events are emitted".
- `test_replay_creates_no_duplicate_durable_record` — replay does not create a
  second durable record.
- The conflict path leaves the committed record and its hash untouched.

## 13. Protected Systems

| System | Status |
|---|---|
| `runtime/validation.py` (18-J state machine) | **Unmodified** — `git diff` empty |
| `runtime/artifact_catalog.py` | Unmodified |
| `runtime/models.py` | Unmodified |
| `runtime/physical_artifact_store.py` | Unmodified |
| Context Engineering architecture | Unmodified by Part A |
| Global CE default ON | **Verified still ON** |
| `prompt_assembly.py` | Unmodified |
| `local_runtime.py` / inference runtime | Unmodified |
| Model Router | Unmodified |
| 18-K | Unmodified |
| M6 / M1 / HP / inference lab | Unmodified |
| Worker experiments / AutoForge Brain | Not started |

`context_builder.py` and `composition_root.py` appear in `git diff` **only**
because of the prior Gate 4B task; Part A did not touch them. The CE default was
re-verified as `True` after the repair.

## 14. Acceptance Gate (§9)

| Criterion | Result |
|---|---|
| Root cause is understood | **PASS** — caller bug, not state-machine bug |
| Repair is minimal | **PASS** — 2 callers, contract honoured, no redesign |
| State-machine semantics remain explicit | **PASS** — table byte-identical |
| Invalid transitions remain rejected | **PASS** — incl. `committed → staging` |
| Original failing path succeeds | **PASS** |
| Resume/recovery semantics remain valid | **PASS** |
| Idempotency remains valid | **PASS** |
| Persistence remains valid | **PASS** |
| Event/state consistency remains valid | **PASS** |
| Full relevant regression passes | **PASS** — 0 new failures |
| No unrelated architecture changed | **PASS** |

## 15. Final 18-J Verdict

> **18-J is COMPLETE and the durable-execution state-transition defect is
> REPAIRED.**

The defect was a caller contract violation, not a state-machine error. The
`committed → staging` transition remains illegal by design and is now proven
illegal by an explicit negative test. Resume and re-materialisation work
correctly and idempotently across process restarts, with durable state preserved
and no silent corruption.

**18-J is re-frozen.** No further 18-J changes are authorised by this task.

Proceeding to Part B — Context Compaction Gate 1 (audit/design only).

---

## Appendix — Artifacts

| File | Purpose |
|---|---|
| `18J_DEFECT_REPAIR_REPORT.md` | This report |
| `repro_18j_defect.py` | Pre/post reproduction of the failing call |
| `probe_bridge_path.py` | Second affected caller (artifact bridge) |
| `verify_e2e_resume.py` | Full canonical resume workflow across restarts |
| `e2e_resume_evidence.json` | Captured resume evidence |
| `../packages/runtime/tests/test_18j_defect_repair.py` | 20 regression tests |
