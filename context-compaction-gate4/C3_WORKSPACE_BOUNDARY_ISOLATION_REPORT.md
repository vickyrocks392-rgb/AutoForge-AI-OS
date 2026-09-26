# C-3 — Context Engineering Workspace Boundary Isolation

**Workstream:** 18-L Context Compaction
**Task:** C-3 — workspace-boundary isolation
**Date:** 2026-09-26
**Status:** ⚠️ **C-3 = PASS WITH CONDITIONS**
**Configuration at close:** Context Engineering = **ON** · Context Compaction = **OFF** · No commit · No push

---

## 1. Executive Summary

C-3 isolated the two systems at the workspace boundary. The feedback path was
reproduced from source, the leak was located to a single line, and the narrowest
possible exclusion was applied at **candidate eligibility**.

| Acceptance criterion (§23) | Result |
|---|---|
| Compaction persistence artifacts do not enter CE candidate discovery | ✅ PASS |
| Normal engineering artifacts remain discoverable | ✅ PASS |
| No candidate-set accumulation or fingerprint drift | ✅ PASS |
| Compaction artifacts fully available to `CompactionRecordStore` | ✅ PASS |
| Hash / version / idempotency guarantees intact | ✅ PASS (18-J 20/20) |
| Legitimate candidate provenance unchanged | ✅ PASS |
| No semantic regression for ordinary inputs | ✅ PASS (candidate sets identical) |
| No disproportionate scan overhead | ✅ PASS (+0.34 ms for 40 records) |
| No new unrelated failures | ✅ PASS (0 new) |
| Protected systems unchanged | ✅ PASS |

**Result before → after (same reproduction harness, 4 cycles):**

```
BEFORE  proj_files 4 → 5 → 6 → 7   fingerprint changed every cycle   LEAK
AFTER   proj_files 4 → 4 → 4 → 4   fingerprint identical every cycle  NO LEAK
```

### Newly discovered P1 durability defect (§18)

C-3 also exposed a **separate, pre-existing durability defect** that Gate 4 and
C-1 could not see. Because C-3 makes the compaction identity stable, retries now
land on the same durable artifact key, and the store raises
`ArtifactConflictError` on every subsequent write — because the serialized payload
contains two volatile fields (`duration_ms`, `provenance.acquired_at`) while the
record's own `content_digest()` is stable.

This is **pre-existing Gate 3 behaviour**, not caused by C-3, and fixing it would
require changing `CompactionRecordStore` semantics, which §18 protects. Per §25 it
is **reported, not repaired**. It is the single remaining condition.

---

## 2. C-3 Objective

> **Context Compaction persistence must not feed its own durable bookkeeping
> artifacts back into the canonical Context Engineering workspace
> candidate-discovery path** — while **normal engineering artifacts remain
> discoverable exactly as the existing contract requires.**

This is a **boundary-isolation task**, not a Context Engineering redesign. The
boundary was placed at candidate *eligibility*, not at ranking, budgeting, or
prompt assembly.

---

## 3. Original Feedback Path

```
CompactionRecordStore.save()
        ↓
<workspace>/artifacts/compaction_cmp_<id>      (durable artifact)
        ↑                                        (same tree)
EngineeringContextBuilder.assemble_context()  step 2 workspace scan
        ↓
context.project_files  ← compaction path appears here
        ↓
ContextItem(category=PROJECT, source=ContextSource("workspace", root))
        ↓   content-derived context_id
compaction fingerprint (source_ids include existing_items' context_ids)
```

Every production compaction therefore changed the inputs to the next compaction.

---

## 4. Reproduction Evidence

Reproduced **before** any edit, through the real production wiring
(`repro_c3_feedback.py`, evidence in `c3_candidate_inventory.json`):

```
cycle  cands  projfiles  items  compaction_id
 1      8          4       8   cmp_fb772b1adf2c2d3b
 2      8          5       8   cmp_9fc6dab8bdd33358
 3      8          6       8   cmp_baab11160cdcea97
 4      8          7       8   cmp_121d63c2d8157c3d

LEAK CONFIRMED:
  compaction artifacts inside CE project_files:
    ['artifacts/compaction_cmp_9fc6dab8bdd33358',
     'artifacts/compaction_cmp_baab11160cdcea97',
     'artifacts/compaction_cmp_fb772b1adf2c2d3b']
  new project_files after first persist: ['artifacts/compaction_cmp_fb772b1adf2c2d3b']
  workspace item context_id cycle1 -> cycle2: ctx_3d6516… -> ctx_0309c4…
  fingerprint changed cycle1 -> cycle2: True
ordinary artifacts still discovered:
  ['README.md', 'docs/design.md', 'src/service.py', 'tests/evidence.json']
```

`project_files` grew by exactly one per cycle, the workspace candidate's
content-derived `context_id` changed, and the fingerprint changed with it.

## 5. Exact Leak Identification

| Property | Value |
|---|---|
| **Scanner** | `EngineeringContextBuilder.assemble_context`, step 2 workspace scan |
| **Leak line** | the eligibility filter in the `rglob("*")` loop |
| **Artifact path** | `<workspace>/artifacts/compaction_cmp_<hex>` |
| **Naming pattern** | `compaction_` + `cmp_` — defined by `CompactionRecordStore.artifact_name` |
| **Extension** | none (extensionless) |
| **Source classification** | none — an ordinary file to the scanner |
| **Candidate classification** | `ContextCategory.PROJECT`, `ContextSource("workspace", <root>)` |
| **Why it mattered** | the path list feeds that PROJECT item's **content**, which is **content-derived**, so its `context_id` changes, and `context_id`s feed the compaction fingerprint |

**Why the narrowest boundary is a filename predicate, not a path boundary.**
`artifact_root = root_dir / "artifacts"` is shared with *every* durable artifact
the system writes (`DurableArtifactStoreBridge`, the execution engine's artifact
pipeline). Excluding that directory would hide legitimate engineering artifacts.
Confirmed empirically by
`test_normal_artifact_inside_artifacts_dir_stays_discoverable` and
`test_exclusion_is_not_a_blanket_artifact_blackout`.

---

## 6. Boundary Design

```
Normal engineering artifact  → CE workspace scan → DISCOVERABLE
Compaction bookkeeping       → CE workspace scan → NOT DISCOVERABLE
```

The predicate lives **beside the writer**, in the compaction module, so the two
cannot drift:

```python
# autoforge_execution/compaction/storage.py
COMPACTION_ARTIFACT_PREFIX = "compaction_"
COMPACTION_ID_PREFIX      = "cmp_"

def is_compaction_bookkeeping_artifact(name: str) -> bool:
    return str(name).startswith(f"{COMPACTION_ARTIFACT_PREFIX}{COMPACTION_ID_PREFIX}")
```

Placement follows the §7 preference order: it extends the **existing inline
exclusion mechanism** already present in the scan loop (which excludes dot-dirs,
`__pycache__`, `venv`) — no new framework, no second discovery architecture, no
duplicated scanner logic, and no change downstream.

---

## 7. Implementation

**A. `compaction/storage.py`** — the predicate above, next to the constants it
derives from. `CompactionRecordStore` behaviour is **unchanged**.

**B. `context_builder.py`** — the scan loop:

```python
for p in workspace_root.rglob("*"):
    if not p.is_file():
        continue
    if any(part.startswith((".", "__pycache__", "venv")) for part in p.parts):
        continue
    if is_compaction_bookkeeping_artifact(p.name):   # ← C-3
        continue
    rel = str(p.relative_to(workspace_root))
    discovered_files.append(rel)
```

The import is placed **outside** the surrounding `try` on purpose: an import
failure must be loud rather than silently emptying the file inventory (the
pre-existing `except` swallows scan errors and would otherwise have turned a
broken import into a silent context regression).

**Not changed:** `select_context`, `context_budget.py`, `prompt_assembly.py`,
`context_selection.py`, the compaction algorithm, compaction policy, and
`CompactionRecordStore` semantics.

---

## 8. Normal Artifact Preservation

| Artifact class | Fixture | Discoverable |
|---|---|---|
| Source file | `src/service.py` | ✅ |
| Documentation | `README.md` | ✅ |
| Test/evidence | `tests/evidence.json` | ✅ |
| Normal durable artifact **inside `artifacts/`** | `artifacts/build_report.json` | ✅ |
| 5 further files in `artifacts/` | `artifacts/module_0..4.json` | ✅ all 5 |

---

## 9. Compaction Artifact Exclusion

Tested against a **genuine production artifact** produced through
`build_autoforge_system` + `CompactionRecordStore` — not a synthetic fixture.

| Property | Result |
|---|---|
| Artifact exists on disk | ✅ |
| Artifact is durable (catalog-committed) | ✅ `last_compaction_artifact_id` set |
| **Not returned as an ordinary CE candidate** | ✅ |
| **Remains loadable by `CompactionRecordStore`** | ✅ `load()` returns the record |
| **Remains integrity-verifiable** | ✅ `content_digest()` matches |
| **Remains available for compaction recovery** | ✅ after a full root restart |

## 10. Fingerprint Stability

Verified by comparing the **actual candidate inputs Context Engineering
consumed**, not the raw directory listing (§10).

| Signal | Before C-3 | After C-3 |
|---|---|---|
| `project_files` | 4 → 5 → 6 → 7 | **4 → 4 → 4 → 4** |
| workspace candidate `context_id` | changed each cycle | **identical** |
| full candidate `context_id` set | changed | **identical** |
| `request_fingerprint` | changed each cycle | **identical** |
| `compaction_id` | new each cycle | **identical** |

---

## 11. Repeatability Results

Four complete cycles (scan → compact → persist), exceeding the §11 minimum of 3:

| Cycle | candidates | project_files | workspace ctx id | fingerprint | records |
|---:|---:|---:|---|---|---:|
| 1 | 8 | 5* | ctx_d5e0… | stable | 1 |
| 2 | 8 | 4 | ctx_d5e0… | stable | 1 |
| 3 | 8 | 4 | ctx_d5e0… | stable | 1 |
| 4 | 8 | 4 | ctx_d5e0… | stable | 1 |

\* cycle 1 is measured before its own persist lands; cycles 2+ see the record.

- Compaction artifacts never become candidates ✅
- Normal engineering artifacts remain candidates ✅
- Candidate identity stable ✅ · Compaction projection stable ✅
- **No accumulation** ✅ · **No progressive fingerprint drift** ✅

`test_no_candidate_accumulation_from_compaction_bookkeeping` drives 6 assemblies
and asserts the discovered count is unchanged.

---

## 12. Negative Control

| Scenario | Expected | Result |
|---|---|---|
| `artifacts/build_report.json` present | **included** | ✅ included |
| `artifacts/compaction_cmp_<id>` present | **excluded** | ✅ excluded |
| Both present simultaneously | normal in, compaction out | ✅ |
| 5 unrelated files in `artifacts/` | all included | ✅ all 5 |

**A test where both were excluded would be invalid; both were not.**

---

## 13. Provenance Verification

C-3 changes **eligibility**, not the meaning of legitimate candidates:

| Property | Value (unchanged) |
|---|---|
| `source.kind` | `workspace` |
| `source.ref` | `<workspace_root>` |
| `category` | `project` |
| `context_id` | `ctx_…` (content-derived) |
| `provenance.acquired_from` | `workspace_filesystem` |
| `provenance.provider` | `workspace` |
| `provenance.inferred` | `False` |
| `relevance` | `0.5` |
| `content` | contains all ordinary artifacts |

---

## 14. Semantic Regression

Deterministic candidate-set equality is the acceptance signal; **no LLM was used**
(§15). The question "did the ordinary candidate set change?" is fully decidable by
comparison, so invoking M6 would add cost and variance without adding signal.

| Arm | Condition | Candidates | `project_files` |
|---|---|---:|---|
| A | identical workspace, no compaction record present during the scan | 8 | 5 |
| B | **same** workspace, same code path, real compaction record present | 8 | 5 |

- **Candidate sets equal: ✅ True**
- **Project files equal: ✅ True**
- Compaction artifacts in candidate set: **`[]`**
- LLM used: **No**

Both arms deliberately use the **identical code path** (compaction enabled); they
differ only in whether a durable record physically exists when the scan runs. An
earlier draft compared "compaction off" against "compaction on" and was
**discarded as invalid**, because compaction itself legitimately expands the raw
pool into structured `iter-N` items — that would have conflated compaction's
intended behaviour with C-3's boundary isolation.

---

## 15. Performance

Compaction is **disabled in both timing arms**, so the delta isolates the
exclusion rather than compaction execution. 40 durable records were used — an
exaggerated stress (≈20× a realistic per-workspace count) — so the marginal cost
resolves above noise.

| Condition | mean | median |
|---|---:|---:|
| No compaction artifact | 0.833 ms | 0.738 ms |
| 40 compaction artifacts | 1.177 ms | 1.115 ms |
| **Delta** | **+0.344 ms** | +0.377 ms |

**Honest attribution:** this +0.344 ms is dominated by `rglob` traversing 40
additional directory entries — a cost the system would pay *with or without* the
exclusion. The exclusion's own marginal cost is **one `str.startswith` per
discovered entry**: no I/O, no new traversal, no allocation. Against Gate 4's
measured compaction cost of ≤0.99 ms, this is not disproportionate.

## 16. Regression Results

| Package | Pre-C-3 | Post-C-3 | Delta |
|---|---|---|---|
| **composition** | 3 failed, 64 passed | **3 failed, 77 passed** | **+13 (C-3 tests)** |
| execution | 207 passed, 18 skipped | 207 passed, 18 skipped | 0 |
| runtime | 268 passed | 268 passed | 0 |
| artifacts | 14 passed | 14 passed | 0 |
| orchestration | 53 passed, 6 skipped | 53 passed, 6 skipped | 0 |
| workflows / kernel / review / observability | 218 / 100 / 114 / 16 passed | identical | 0 |
| persistence / events / event_platform | 70 / 228 / 56 passed | identical | 0 |
| connectors / security / ai_infrastructure | 93 / 37 / 97 passed | identical | 0 |
| modernization | 375 passed, 59 skipped | identical | 0 |
| **18-J repair suite** | 20 passed | **20 passed** | 0 |
| **Context Engineering global** | 6 passed | **6 passed** | 0 |
| **Context Compaction** | 58 passed | **58 passed** | 0 |
| **C-1 production wiring** | 16 passed | **16 passed** | 0 |
| **C-3 workspace boundary** | — | **13 passed** | new |

**New failures: 0.**

### One C-1 test was corrected, not weakened

`test_persisting_does_not_inflate_the_compacted_context` **failed** after C-3
because it had pinned the *buggy* pre-C-3 behaviour ("one more artifact file per
compaction"). C-3 removes the cause, so the test now pins the corrected
invariant: the identity is stable, so the durable record count does **not** grow.
A duplicate workspace-`context_id` assertion was moved to the C-3 suite, where it
is measured against the correct object (`ExecutionContext` — the compaction
record itself carries only projected iteration items).

### Pre-existing failures (unchanged, explicitly identified)

**Composition — 3 failed.** Identical test IDs to the Gate 4 / C-1 baseline:
`test_canonical_context_builder_invoked_in_execution_path`,
`test_canonical_durable_artifact_wiring`, `test_execution_platform_integration`.

Root cause unchanged: these request model `qwen2.5-coder-7b` from
`127.0.0.1:8080`, which serves the M6 30B authority model. The M6 evaluation
runtime was stopped at the end of Gate 4 and was **not** restarted here. **The
inference lab was not modified.**

**Workforce — 1 collection error (pre-existing, reconfirmed).**
`test_real_runtime_integration.py` imports the removed `OllamaProviderAdapter`.

---

## 17. Protected-System Verification

| System | Status | Evidence |
|---|---|---|
| **18-J** | ✅ PROTECTED | 20/20 tests; no 18-J file touched; conflict branch behaves as designed |
| **18-K** | ✅ PROTECTED | no packaging/delivery change |
| **Context Compaction algorithm** | ✅ PROTECTED | `compactor.py` untouched; only a predicate added to `storage.py` |
| **CompactionRecordStore semantics** | ✅ PROTECTED | `save()`/`load()`/`artifact_name()` unchanged; only a new public predicate |
| **Compaction policy** | ✅ PROTECTED | `compaction_policy.py` untouched |
| `select_context` | ✅ PROTECTED | not modified |
| `context_budget.py` | ✅ PROTECTED | not modified |
| `prompt_assembly.py` | ✅ PROTECTED | not modified |
| `context_selection.py` | ✅ PROTECTED | not modified |
| **Context Engineering (rest)** | ✅ PROTECTED | only the §2 scan eligibility filter changed; 6/6 global tests pass; default still `True` |
| **Inference Lab** | ✅ PROTECTED | not started, not modified |
| **Model Router** | ✅ PROTECTED | no router configuration touched |
| No Ollama / `11434` | ✅ | grep confirms none |

The only production modification is the minimum workspace-boundary change plus
the predicate it calls, as §18 requires.

## 18. Remaining Limitations

### L-1 (P1, newly discovered) — durable replay conflict on identical retries

**Classification per §25: P1 durability defect. Reported, not repaired.**

**What happens.** With C-3 the compaction identity is now stable, so a retry maps
to the same durable artifact key. `CompactionRecordStore.save()` then compares
`content_hash` against the **raw serialized payload**, which contains two volatile
fields:

```
SERIALIZED FIELDS THAT DIFFER between two logically identical compactions:
  duration_ms:            0.415  ->  0.408
  provenance.acquired_at: '…632028+00:00' -> '…632484+00:00'

same compaction_id  : True
same fingerprint    : True
same content_digest : True      ← the record's own digest IS stable
```

Because the payload bytes differ, `save()` raises `ArtifactConflictError` on every
subsequent write of the same logical record. The builder contains it (engineering
continues with the in-memory record), but:

- the durable record is effectively frozen at its first version;
- a warning is logged on every iteration;
- the store's own documented contract — *"identical content reuses the artifact;
  different content raises `ArtifactConflictError`"* — is violated, because this
  **is** identical content by the record's own digest.

**Why it is not repaired here.** Fixing it means changing what `save()` hashes or
serializes — i.e. `CompactionRecordStore` semantics, which §18 protects, and
storage architecture, which §3 forbids. §25 directs me to stop and report.

**Smallest future change (separate authorized gate required):** one of —
(a) omit the volatile fields (`duration_ms`, `provenance.acquired_at`) from the
persisted payload, since identity-bearing content is already covered by
`content_digest()`; (b) have the store hash the record's `content_digest()` plus
identity rather than raw bytes; or (c) normalize volatile fields before the
conflict comparison.

**Does it block C-3?** No. C-3's boundary isolation is complete and verified. This
is an independent, pre-existing durability limitation that C-3 *exposed* by making
identity stable. It does block **global enablement**: under enablement, every
iteration after the first would log a conflict and never update the durable
record.

### L-2 — Reference resolution remains unwired (unchanged from Gate 4 §6)
### L-3 — Pre-existing Gate 1 G-1 gap for short histories (unchanged)
### L-4 — Composition suite cannot fully pass on this host (pre-existing)

---

## 19. C-3 Verdict

### ⚠️ C-3 = PASS WITH CONDITIONS

C-3's own objective is **fully met**. Every §23 acceptance criterion passes, the
feedback path was reproduced before the change and eliminated after it, and the
negative control confirms ordinary artifacts remain discoverable.

The condition is **L-1**, a P1 durability defect that C-3 *exposed* rather than
caused. It is not a C-3 failure — the boundary is isolated — but it is a real
defect in `CompactionRecordStore` that must be closed before enablement.

---

## 20. Enablement Recommendation

**Do not globally enable Context Compaction yet.** All boundary work (Gate 4,
C-1, C-2, C-3) is complete, and the single outstanding item is L-1.

**Required next action — a narrowly scoped, separately authorized gate:**

> Decide and apply the `CompactionRecordStore` payload-determinism fix (L-1):
> make the persisted payload exclude volatile timing fields, or hash the record's
> stable `content_digest()` instead of raw bytes. Re-run the C-1 production
> wiring suite and confirm an identical retry now reuses the committed artifact
> without raising `ArtifactConflictError`.

That gate touches only `CompactionRecordStore`; it requires no change to Context
Engineering, the compaction algorithm, 18-J, 18-K, or the inference lab.

**Once L-1 is closed, no further preconditions remain** and Context Compaction
global enablement may be authorized.

### Condition status summary

| Condition | Status |
|---|---|
| Gate 4 semantic / deterministic verification | ✅ PASS |
| C-1 production composition-root wiring | ✅ CLOSED |
| C-2 historical record integrity | ✅ CLOSED |
| C-3 workspace boundary isolation | ✅ PASS (this task) |
| **L-1 durable replay determinism** | ⚠️ **OUTSTANDING — blocks enablement** |

---

## Appendix — Evidence Artifacts

| File | Contents |
|---|---|
| `c3_candidate_inventory.json` | before/after candidate inventories, leak paths, per-cycle fingerprints |
| `c3_semantic_regression.json` | Arm A / Arm B candidate-set equality |
| `c3_performance.json` | scan timing with and without compaction records |
| `repro_c3_feedback.py` | the reproduction harness (run before and after the fix) |
| `diag_c3_payload_diff.py` | isolates the volatile fields behind L-1 |
| `c3_evidence.py` | produces the semantic + performance evidence |
| `packages/composition/tests/test_c3_workspace_boundary.py` | 13 C-3 tests |

### Files changed by this task

| File | Nature |
|---|---|
| `packages/execution/src/autoforge_execution/context_builder.py` | **the C-3 boundary** — scan eligibility filter |
| `packages/execution/src/autoforge_execution/compaction/storage.py` | additive predicate (store semantics unchanged) |
| `packages/composition/tests/test_c3_workspace_boundary.py` | 13 new tests (new file) |
| `packages/composition/tests/test_compaction_production_wiring.py` | 1 test corrected to the post-C-3 invariant |




