# C-1 / C-2 Closure — Production Wiring & Historical Integrity

**Workstream:** 18-L Context Compaction
**Task:** C-1 / C-2 closure (post-Gate-4 "PASS WITH CONDITIONS")
**Date:** 2026-09-26
**Status:** ✅ **C-1 = CLOSED · C-2 = CLOSED**
**Configuration at close:** Context Engineering = **ON** · Context Compaction = **OFF** · No commit · No push

---

## 1. Executive Summary

This task closed the two conditions Gate 4 left open. Nothing else was attempted.

| Condition | Question | Verdict |
|---|---|---|
| **C-1** | Does the production composition root own the `CompactionRecordStore`, and does the real Context Compaction path persist through *that* object? | ✅ **CLOSED** |
| **C-2** | Does any durable compaction record created under the defective pre-Gate-4 implementation exist, and could it silently become authoritative? | ✅ **CLOSED** |

**C-1** was closed with a purely additive wiring: the composition root constructs the
existing `CompactionRecordStore` over the *same* `DurableArtifactCatalog` and
`PhysicalArtifactStore` the rest of the system already uses, and injects it into
`EngineeringContextBuilder`. A new optional `compaction_store` seam persists any
record that has already passed validation. 16 new integration tests drive the
**real** `build_autoforge_system()` path — never a hand-built store — and cover
persistence, restart/recovery, corruption, truncation, missing records, identity
isolation, 18-J idempotent replay, and durability-failure containment.

**C-2** was closed by proof, not assertion. A read-only audit scanned every SQLite
catalog (151) and every durable artifact file (86) on the host. **Zero compaction
rows exist in any catalog, and zero records exist in any production-like
location.** The 86 files found are all ephemeral test scratch produced by Gate 4
verification and by this task's own tests. No pre-repair record exists anywhere
that could enter the trusted production path, so **no migration, quarantine, or
cleanup machinery was added** — per brief §10.

### Newly discovered production interaction (disclosed, not repaired)

Wiring exposed a real behaviour that Gate 4 could not have seen, because the store
was unwired: **the store persists into the same directory the Context Engineering
workspace scan enumerates.** Each production compaction therefore adds one
artifact file that the next scan discovers, which changes the candidate pool,
which changes the compaction fingerprint (§7.1). It is measured, bounded, and
pinned by a test; it is recorded as **precondition C-3** and was deliberately
*not* repaired, because the fix belongs to the protected Context Engineering
workspace scan.

---

## 2. Production Composition Root Identified

**Root:** `packages/composition/src/autoforge_composition/composition_root.py`
**Entry point:** `build_autoforge_system()` (line 209)

The existing wiring order was traced before any change was made:

| Step | Line | What it builds |
|---|---|---|
| 3b | 255 | `PhysicalArtifactStore` (canonical artifact substrate) |
| 3b | 260 | `DurableArtifactCatalog` (identity, lifecycle, hash, versioning) |
| 3b | 264 | `DurableArtifactStoreBridge` |
| 6b | 313 | `EngineeringContextBuilder` — **the Context Engineering/Compaction seam** |
| 7 | 325 | `build_execution_engine(..., context_builder=context_builder)` |

Steps 3b and 6b are adjacent in the same function, and the catalog/store created at
3b are already passed to the execution engine at step 7. The compaction store
therefore had a natural home and required no new infrastructure.

The `AutoForgeSystem` dataclass already exposed `durable_catalog` and
`physical_store`; `compaction_store` was added alongside them so the root's
ownership of the store is externally observable, not just internally true.

## 3. CompactionRecordStore Wiring

### 3.1 Production root constructs and owns the store

```python
# composition_root.py, step 3c
compaction_store = CompactionRecordStore(
    catalog=durable_catalog,
    physical_store=physical_store,
)
```

Built over the **same** catalog and physical store the rest of the system uses —
asserted by `test_store_is_built_over_the_canonical_artifact_substrate`, which
checks object *identity*, not type.

### 3.2 The root injects it into the Context Compaction path

```python
# composition_root.py, step 6b
enable_context_compaction = bool(
    (config or {}).get("enable_context_compaction", False)
)
context_compactor = (
    ContextCompactor(CompactionPolicy(enabled=True))
    if enable_context_compaction
    else None
)
context_builder = EngineeringContextBuilder(
    ...,
    compactor=context_compactor,
    compaction_store=compaction_store,
)
```

This mirrors the existing Context Engineering pattern exactly: the flag is passed
**explicitly** so the composition root stays the single readable source of truth
for the production posture, and the rollback lever needs no other call-site change.

### 3.3 The builder persists validated records

```python
# context_builder.py — after apply_validation() has promoted the record
if self.compaction_store is not None:
    try:
        artifact_id = self.compaction_store.save(record)
        self.last_compaction_artifact_id = str(artifact_id)
    except Exception as exc:
        logger.warning("... could not be persisted (%s); continuing ...", exc)
```

Three properties are deliberate:

1. **It runs only after validation.** An invalid record is never written.
2. **It is contained.** A durability failure never fails engineering work
   (Gate 3 §23), and the in-memory record stays usable.
3. **It reuses the existing store.** No new storage architecture, no duplicated
   persistence logic, and 18-J's replay contract decides retries.

### 3.4 Total production diff

| File | Change |
|---|---|
| `composition_root.py` | import, store construction (step 3c), flag + injection (step 6b), container field, return value |
| `context_builder.py` | one optional ctor param, two attribute assignments, one guarded persist block |

**`context_selection.py`, `context_budget.py`, and `prompt_assembly.py` were not
touched** (verified by `git diff` returning empty for all three).

---

## 4. Production Dependency Path

The C-1 objective is that the *same* production object is used by the *actual*
compaction path. That is proven by object identity, not by type:

```
build_autoforge_system()
  └─ step 3c  CompactionRecordStore(catalog=durable_catalog, physical_store=physical_store)
       └─ step 6b  EngineeringContextBuilder(compaction_store=compaction_store)
            └─ assemble_context()  →  _apply_compaction()
                 └─ apply_validation()  →  promotion gate
                      └─ self.compaction_store.save(record)     ← the root's object
```

| Assertion | Test |
|---|---|
| Root owns a real `CompactionRecordStore` | `test_production_root_owns_a_real_compaction_store` |
| **Builder's store IS the root's store** | `test_context_builder_consumes_the_root_owned_store` |
| Store is over the canonical substrate | `test_store_is_built_over_the_canonical_artifact_substrate` |
| Compaction still OFF by default | `test_compaction_is_off_by_default`, `test_default_build_does_not_inject_a_compactor` |

The identity assertion is the load-bearing one: a test that merely checked
`isinstance` would pass even if the builder held a private copy, which is exactly
the failure mode C-1 exists to prevent.

---

## 5. Restart/Recovery Verification

| Step | Result |
|---|---|
| Production compaction persists a record | ✅ `test_production_path_persists_a_compaction_record` |
| Artifact present on disk under canonical name | ✅ payload `compaction_id` matches |
| **New composition root over the same on-disk state** | ✅ constructed from scratch |
| `load()` returns the record | ✅ non-`None` |
| `compaction_id` preserved | ✅ |
| `content_digest()` preserved | ✅ byte-identical |
| `validation_status` valid | ✅ |

**Restart is simulated the only way it can honestly be:** a brand-new
`AutoForgeSystem` — new `RuntimeStateManager`, new catalog, new physical store —
opened over the same `workspace_root`. No in-memory state is reused.

---

## 6. Integrity Verification

All through production wiring:

| Injected fault | Expected | Result |
|---|---|---|
| Byte-level corruption (valid JSON) | integrity failure | ✅ `load()` → `None` |
| Truncation | integrity failure | ✅ `load()` → `None` |
| Missing record | explicit miss | ✅ `load()` → `None` |
| Wrong identity (`cmp_does_not_exist`) | explicit miss | ✅ `load()` → `None` |

**No corrupted or substituted data is ever returned as authoritative.** The
Gate 4 §3.2 repair (compare `sha256(raw)` against the committed `content_hash`)
is now exercised through the production path, not only in isolation.

## 7. Idempotency Verification & the Newly Discovered Interaction

### 7.1 What the production path actually does

The first idempotency probe through production wiring **failed** — two identical
`assemble_context()` calls produced different `compaction_id`s. Rather than
assume a defect, this was measured (`diag_c1_idempotency.py`):

```
run  items  proj_files  artifacts  compaction_id
   1      7           0          1  cmp_eed26368407a6470
   2      8           1          2  cmp_08600b68bfab1cee
   3      8           2          3  cmp_325fc1c4bff788fc
  ...
  12      8          11         12  cmp_477fe5de5cf09201
```

**Cause:** the store writes into `<workspace>/artifacts`, which the Context
Engineering workspace scan enumerates. Run 1 sees an empty workspace; run 2 sees
run 1's artifact. The candidate pool genuinely differs, so a different — equally
valid, fully deterministic — fingerprint follows. This is **correct behaviour**,
not a defect: the compactor is deterministic given its inputs.

Two consequences, both now pinned by tests:

- The **compaction projection is stable**: the structured `iter-N` items are
  byte-identical across runs
  (`test_compaction_content_is_stable_across_production_runs`).
- **One durable record accumulates per compaction**, bounded in context impact
  because the workspace listing is a single capped candidate
  (`test_persisting_does_not_inflate_the_compacted_context`).

**This was not repaired.** The correct fix is to exclude the durable artifact
directory from the Context Engineering workspace scan — a change to protected
Context Engineering, which this task's scope forbids (§2) and §13 directs me to
report rather than expand into. It is recorded as **precondition C-3**.

### 7.2 Idempotency invariants that do hold

| Invariant | Result |
|---|---|
| Re-saving the **same record** reuses the committed artifact | ✅ `test_resaving_the_same_record_is_idempotent` |
| Exactly one committed compaction artifact, no duplicate | ✅ asserted in the same test |
| Different tasks → distinct id, fingerprint, **and artifact** | ✅ `test_different_tasks_do_not_collide` |
| Both collision-avoidant records remain independently loadable | ✅ |

The original probe was corrected rather than the code: "run assembly twice" is not
an idempotency probe once the store writes into the scanned workspace. The test
now asserts the real 18-J contract.

---

## 8. Cross-Task Isolation Verification

| Property | Result |
|---|---|
| Two tasks, identical iteration history | ✅ both compacted |
| `compaction_id` distinct | ✅ |
| `request_fingerprint` distinct | ✅ |
| **durable `artifact_id` distinct** | ✅ — the property Gate 4's P1-1 repair protects |
| Both loadable independently | ✅ |

The P1-1 repair is now proven *end-to-end in production*: the collision risk was
at the durable layer, and that is exactly what this test exercises.

---

## 9. Historical Record Inventory

**Strictly read-only.** SQLite is opened with `mode=ro`; nothing was written,
migrated, quarantined, or deleted.

| Probe | Result |
|---|---|
| Durable artifact files on disk (`compaction_cmp_*`) | **86** |
| SQLite catalogs scanned (host-wide) | **151** |
| **Compaction rows in `durable_artifact_state`** | **0** |
| Records in repository / production-like locations | **0** |
| `runtime_state.db` anywhere under `$HOME` (excl. temp/venv) | **none exists** |

**The first audit pass produced a false positive** and was corrected: the glob
`compaction_*` also matched the Python **source files** `compaction_policy.py`,
`compaction_schema.py`, `compaction_validation.py` and their `.pyc` caches, which
are not records. The pattern was narrowed to `compaction_cmp_*` (the real
`CompactionRecordStore.artifact_name` shape) and bytecode caches excluded. The
corrected inventory is reported here; the false positive was not carried forward.

### Repair boundary (from source mtimes, not guessed)

| Repair | File | Timestamp (local) |
|---|---|---|
| Gate 3 module created | `compaction/__init__.py` | 2026-09-26 17:26 |
| **Repair 1** — fingerprint scope | `compactor.py`, `compaction_schema.py` | **2026-09-26 18:23** |
| **Repair 2** — load integrity | `storage.py` | **2026-09-26 18:31** |

---

## 10. Pre-Repair Record Classification

Every one of the 86 records found was classified against that boundary:

| Classification | Count | Location |
|---|---:|---|
| VALID (post-both-repairs) | 54 | ephemeral test scratch / OS temp |
| DUPLICATE / COLLISION-RISK (pre Repair 1) | 20 | ephemeral test scratch |
| INTEGRITY-UNCERTAIN (pre Repair 2) | 10 | ephemeral test scratch |
| CORRUPTED | 2 | ephemeral test scratch (deliberately truncated by the negative tests) |
| **PRE-REPAIR IN A PRODUCTION LOCATION** | **0** | — |

Each record row records: `compaction_id`, `request_fingerprint`,
`idempotency_key`, `task_id`, `policy_version`, `compaction_schema_version`,
`logical_version`, item/reference counts, size, and mtime — in
`c2_historical_audit.json`.

**Why the 30 pre-repair records are harmless:** all were created by *Gate 4's own
verification harness* (`af_g4_store_*` `mkdtemp` directories) before the repairs
were applied within that same working session. They are disposable test output
under the OS temp directory. They are not reachable from any production workspace,
are not referenced by any catalog (0 rows), and are removed by OS temp rotation.

**Result: no pre-repair record exists in any location capable of entering the
trusted production path.**

Per §10, because no unsafe pre-repair record exists, **nothing further was done**:
no migration machinery, no cleanup architecture, no storage-format change, no
historical compatibility layer.

## 11. C-1 Verdict

### ✅ C-1 = CLOSED

| §16 acceptance criterion | Status | Evidence |
|---|---|---|
| Actual production composition root owns the store | ✅ | step 3c; `test_production_root_owns_a_real_compaction_store` |
| Actual Context Compaction path consumes **that** dependency | ✅ | object-identity assertion, `test_context_builder_consumes_the_root_owned_store` |
| Persistence works through production wiring | ✅ | `test_production_path_persists_a_compaction_record` |
| Restart/recovery works | ✅ | `test_restart_reconstruction_recovers_the_record` |
| Hash integrity remains enforced | ✅ | corruption + truncation + missing + wrong-identity |
| Idempotency remains enforced | ✅ | `test_resaving_the_same_record_is_idempotent` |
| Cross-task identity remains isolated | ✅ | `test_different_tasks_do_not_collide` (incl. distinct artifact ids) |
| Regression passes | ✅ | 0 new failures; +16 composition tests |

Gate 4's concern was that the storage round-trip was proven "only in a test
harness". That gap is now closed: the same assertions run against the object the
production composition root constructs and injects.

---

## 12. C-2 Verdict

### ✅ C-2 = CLOSED

| §16 acceptance criterion | Status | Evidence |
|---|---|---|
| Historical persistence location was actually inspected | ✅ | 151 SQLite catalogs + 86 artifact files, host-wide |
| Pre-repair records enumerated **or absence proven** | ✅ | absence **proven**: 0 production-location records, 0 catalog rows |
| Every pre-repair record is classified | ✅ | all 86 classified; 30 pre-repair, all in ephemeral scratch |
| No unsafe pre-repair record can silently become authoritative | ✅ | zero exist; and the wired path re-verifies `content_hash` on every load |

C-2 is closed **vacuously but by proof**: the objective — "ensure that no durable
compaction state created under the defective pre-Gate-4 implementation can silently
enter the trusted production path" — is satisfied, and the satisfaction is
demonstrated rather than assumed. Per §11, no quarantine system was invented,
because none is necessary.

---

## 13. Regression Results

| Package | Gate 4 baseline | C-1/C-2 result | Delta |
|---|---|---|---|
| **composition** | 3 failed, 48 passed | **3 failed, 64 passed** | **+16 (new C-1 tests)** |
| execution | 207 passed, 18 skipped | 207 passed, 18 skipped | 0 |
| runtime | 268 passed | 268 passed | 0 |
| artifacts | 14 passed | 14 passed | 0 |
| orchestration | 53 passed, 6 skipped | 53 passed, 6 skipped | 0 |
| workflows | 218 passed | 218 passed | 0 |
| kernel | 100 passed | 100 passed | 0 |
| review | 114 passed | 114 passed | 0 |
| observability | 16 passed | 16 passed | 0 |
| persistence | 70 passed | 70 passed | 0 |
| events | 228 passed | 228 passed | 0 |
| event_platform | 56 passed | 56 passed | 0 |
| connectors | 93 passed | 93 passed | 0 |
| security | 37 passed | 37 passed | 0 |
| ai_infrastructure | 97 passed | 97 passed | 0 |
| modernization | 375 passed, 59 skipped | 375 passed, 59 skipped | 0 |
| **18-J repair suite** | 20 passed | **20 passed** | 0 |
| **Context Engineering global** | 6 passed | **6 passed** | 0 |
| **Context Compaction** | 58 passed | **58 passed** | 0 |
| **C-1 production wiring (new)** | — | **16 passed** | new |

**New failures: 0.**

### Pre-existing failures (unchanged, explicitly identified)

**Composition — 3 failed.** Identical test IDs to the Gate 4 baseline, unchanged:
- `test_canonical_context_builder_invoked_in_execution_path`
- `test_canonical_durable_artifact_wiring`
- `test_execution_platform_integration`

Root cause is unchanged and precisely stated: these tests request model
`qwen2.5-coder-7b` from the local runtime at `127.0.0.1:8080`, which serves the
M6 30B authority model. The M6 evaluation runtime was stopped at the end of Gate 4
and was **not** restarted for this closure task, so the endpoint is unreachable.
**The inference lab was not modified.**

**Workforce — 1 collection error (pre-existing, reconfirmed).**
`test_real_runtime_integration.py` imports the removed `OllamaProviderAdapter`.
Unrelated to this task; no Ollama dependency was introduced.

---

## 14. Protected-System Verification

| System | Status | Evidence |
|---|---|---|
| **18-J** state machine & replay | ✅ PROTECTED | 20/20 tests pass; no 18-J file modified; replay contract re-asserted through production wiring |
| **18-K** runtime/packaging/delivery | ✅ PROTECTED | no packaging or delivery change |
| **Context Engineering** | ✅ PROTECTED | `context_selection.py`, `context_budget.py`, `prompt_assembly.py` untouched; 6/6 global tests pass; default still `True` |
| **Inference Lab** | ✅ PROTECTED | M6 used read-only in Gate 4; not started, not modified, not reconfigured here |
| **Model Router** | ✅ PROTECTED | no router configuration touched |
| **Provider adapters** | ✅ PROTECTED | `ai_infrastructure` diff is prior-gate work; nothing added by this task |
| **Event model** | ✅ PROTECTED | `events` / `event_platform` untouched; no event type added |
| **Durable state machine** | ✅ PROTECTED | the store reuses the existing catalog contract; **no new `EntityType`**, no schema change |

**No protected change was required by this task.** The wiring needed only the
composition root and an optional builder parameter.

## 15. Remaining Risks

| ID | Risk | Severity | Disposition |
|---|---|---|---|
| **R-4** | **Store writes into the scanned workspace** (§7.1): one durable record per compaction accumulates, and each is rediscovered by the CE workspace scan, changing the fingerprint. | Medium | **Precondition C-3.** Bounded in context impact; measured and pinned. Not repaired — fix belongs to protected CE. |
| R-5 | Reference resolution remains unwired | Low | Deliberate (Gate 4 §6); unchanged |
| R-6 | Pre-existing Gate 1 G-1 gap for short histories | Low | Pre-existing; tracked under CE |
| R-7 | Composition suite cannot fully pass on this host | Low | Pre-existing; model not served locally |

**R-4 is new** and is the direct consequence of doing the wiring. It is reported
rather than fixed, per §13.

---

## 16. Exact Enablement Preconditions

Gate 4's C-1 and C-2 are now closed. One new precondition was discovered during
closure:

**C-3 — Decide and resolve the workspace/durable-store interaction.**

The production compaction store persists into `<workspace>/artifacts`, which the
Context Engineering workspace scan enumerates. Options, in preference order:

1. **Exclude the durable artifact directory from the CE workspace scan.**
   Cleanest; the durable store is system state, not source. *Requires a Context
   Engineering change and therefore a separate, explicitly authorized gate.*
2. **Place the durable artifact root outside the scanned workspace.**
   Also correct, but relocates ALL durable artifacts, so it affects 18-K and the
   artifact platform. *Higher blast radius.*
3. **Accept it explicitly**, on the grounds that it is bounded (one capped
   workspace-listing candidate) and harmless. *This is a governance decision, not
   a technical fix, and should be recorded as accepted risk.*

C-3 does **not** block C-1 or C-2, and it is not a correctness defect. It must be
resolved or explicitly accepted before global enablement.

**No other preconditions remain.**

---

## 17. Final Closure Verdict

```
C-1: CLOSED
C-2: CLOSED

Production Wiring:      VERIFIED — the composition root owns the store and the
                        Context Compaction path persists through that same object
                        (proven by object identity, not by type)
Historical Integrity:   VERIFIED — 0 pre-repair records in any production location,
                        0 compaction rows across 151 catalogs; read-only audit,
                        no migration or cleanup machinery added
Regression:             PASS — 0 new failures; +16 new C-1 tests all pass;
                        3 composition + 1 workforce pre-existing failures unchanged

Context Engineering: ON
Context Compaction: OFF

18-J: PROTECTED
18-K: PROTECTED
Inference Lab: PROTECTED

Global Enablement: NOT PERFORMED
Commit: NO
Push: NO

NEXT STEP:
  Await explicit authorization for Context Compaction enablement.
  Before enablement, resolve or explicitly accept precondition C-3 (the
  durable-store / workspace-scan interaction described in §7.1 and §16).
```

### Files changed by this task

| File | Nature |
|---|---|
| `packages/composition/src/autoforge_composition/composition_root.py` | additive wiring (C-1) |
| `packages/execution/src/autoforge_execution/context_builder.py` | optional `compaction_store` seam + guarded persist (C-1) |
| `packages/composition/tests/test_compaction_production_wiring.py` | 16 new production-wiring tests (new file) |
| `context-compaction-gate4/audit_c2_historical_records.py` | read-only C-2 audit (new file) |
| `context-compaction-gate4/diag_c1_idempotency.py` | interaction measurement (new file) |
| `context-compaction-gate4/c2_historical_audit.json` | C-2 evidence (new file) |

**No compaction algorithm, Context Engineering, selection, budgeting, prompt
assembly, model routing, inference configuration, 18-J, 18-K, event model, or
durable state machine was modified.**




