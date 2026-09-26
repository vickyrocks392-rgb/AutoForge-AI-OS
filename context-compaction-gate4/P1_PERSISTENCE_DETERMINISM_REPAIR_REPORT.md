# P1 — Persistence Determinism Repair

**Workstream:** 18-L Context Compaction
**Task:** P1 persistence determinism repair
**Date:** 2026-09-26
**Status:** ✅ **P1 PERSISTENCE DETERMINISM = PASS**
**Configuration at close:** Context Engineering = **ON** · Context Compaction = **OFF** · No commit · No push

---

## 1. Executive Summary

The P1 defect is repaired and verified. The root cause was a **concept conflation**:
`CompactionRecordStore.save()` decided a *logical* question ("are these the same
compaction result?") using a *physical* comparison ("are these the same bytes?").

Because two logically identical records differ in runtime-only fields
(`duration_ms`, `provenance.acquired_at`), every identical replay hashed
differently and was rejected as a conflict — violating the store's own documented
contract that identical content reuses the artifact.

| Acceptance criterion (§22) | Result |
|---|---|
| Determinism — same logical content, different runtime metadata, no conflict | ✅ PASS |
| Identity — different logical content ⇒ different identity | ✅ PASS |
| Isolation — different tasks remain isolated | ✅ PASS |
| Integrity — physical corruption still detected | ✅ PASS |
| Catalog consistency | ✅ PASS |
| Restart — logical record survives | ✅ PASS |
| Production wiring — real composition-root path | ✅ PASS |
| C-3 — workspace stable, bookkeeping excluded | ✅ PASS |
| Regression — no new unrelated failures | ✅ PASS (0 new) |
| Protection — 18-J / 18-K / CE / inference / router | ✅ PASS |

**Test evidence: 18 new unit tests + 4 new production-wiring tests; 109 focused
tests pass; 0 new failures across the whole suite.**

### The chosen repair in one line

The replay decision now uses a new **logical identity** digest, while the
catalog's `content_hash` **remains the raw-byte hash** — so the logical and
physical concepts are separated rather than weakened.

---

## 2. Defect Reproduction

Reproduced through the real production wiring, before the fix:

```
context compaction record cmp_e27ae479fef2c438 could not be persisted
  (Compaction record cmp_e27ae479fef2c438 already exists with different content;
   refusing to overwrite durable state.); continuing with the in-memory record
```

— repeated on every cycle after the first. Isolation of the varying fields:

```
SERIALIZED FIELDS THAT DIFFER between two logically identical compactions:
  duration_ms:            0.415  ->  0.408
  provenance.acquired_at: '…632028+00:00' -> '…632484+00:00'

SERIALIZED FIELDS THAT DIFFER: 2   (of 99 total)
same compaction_id  : True
same fingerprint    : True
same content_digest : True
```

Two of ninety-nine fields accounted for a false conflict on every replay.

---

## 3. Root Cause

```python
# BEFORE — a logical question answered with a physical comparison
if state.content_hash != _sha256(payload):
    raise ArtifactConflictError(...)
return str(state.artifact_id)
```

`state.content_hash` is the hash of the **stored bytes**; `_sha256(payload)` is the
hash of the **incoming bytes**. Equal hashes prove the bytes match. They say
nothing about whether the two records represent the same *logical* result — which
is the question the caller is asking, and the question the store's docstring
promises to answer.

Under C-3 the identity became stable, so retries finally landed on the same
artifact key and the latent mismatch became reachable. Before C-3 every iteration
had a different id, so the conflict branch was never entered — the defect was
**masked**, not absent.

---

## 4. Existing Contract Analysis

| Existing contract | Source | Verdict |
|---|---|---|
| "Identical content reuses the artifact; different content raises `ArtifactConflictError`" | `CompactionRecordStore` docstring | **This is the contract the code violated.** |
| `content_digest()` — stable digest of compacted content (Gate 2 V-8) | `compaction_schema.py` | Correct and already runtime-free; **left unchanged** (Gate 2 semantics). |
| `make_request_fingerprint(scope=…)` — logical scope in identity (Gate 4 P1-1) | `compaction_schema.py` | Correct; **preserved**. |
| Catalog `content_hash` = hash of stored bytes | `DurableArtifactCatalog` / `PhysicalArtifactStore.atomic_publish(expected_hash=…)` | Correct; **left unchanged** — it is the physical-integrity authority. |
| `COMMITTED` is never reopened (18-J) | `save()` | **Preserved.** Reuse returns the existing id; nothing is rewritten. |
| Load must reject byte/catalog mismatch (Gate 4 §3.2) | `load()` | **Preserved**, plus a new logical check. |
| Provider neutrality | all modules | **Preserved** — no I/O, model, or runtime added. |

**Conclusion:** the existing contracts fully support the required semantics. No
architectural change is needed; only the *decision input* in `save()` was wrong.

## 5. Identity vs Runtime Metadata

| Field | Class | Persisted? | Identity-bearing? |
|---|---|---|---|
| `duration_ms` | runtime metadata | ✅ yes | ❌ no |
| `provenance.acquired_at` | audit metadata | ✅ yes | ❌ no |
| `items`, `durable_refs`, `task_id`, `request_fingerprint`, `policy_version`, `logical_version`, `compaction_method`, `trigger`, … | **logical content** | ✅ yes | ✅ yes |

Declared explicitly and minimally:

```python
RUNTIME_ONLY_FIELDS = frozenset({"duration_ms", "acquired_at"})
```

**Per §13, nothing is deleted.** `duration_ms` and `acquired_at` are still written
to disk and still round-trip; they are simply not part of the *identity*. Verified
by `test_runtime_metadata_is_still_persisted`.

The identity is computed **fail-safe**: it covers every serialized field *except*
the two declared runtime ones, at any depth. A newly added field is
identity-bearing by default, so the identity can only ever become **stricter**,
never looser by accident. `test_negative_every_field_is_not_stripped` guards this.

---

## 6. Integrity vs Logical Identity

The two concepts are kept strictly separate and both are enforced:

| Layer | Hash | Answers | Enforced at |
|---|---|---|---|
| **Logical** | `logical_identity()` | "which compaction result is this?" | `save()` replay decision |
| **Content** | `content_digest()` (Gate 2 V-8, unchanged) | "what does its content hash to?" | existing consumers |
| **Physical** | catalog `content_hash` (raw bytes, unchanged) | "were the stored bytes modified?" | `load()` integrity check |

`load()` now performs **two** independent checks:

1. **Physical** — `sha256(raw)` vs the catalog's committed hash (Gate 4 §3.2, unchanged).
2. **Logical** — the record's stored `logical_identity` vs the value recomputed
   from its own content. A record claiming an identity its content does not
   support is refused (`test_forged_logical_identity_field_is_refused`).

Neither check was weakened to accommodate the other.

---

## 7. Chosen Repair

**A third option, distinct from the two pre-identified directions.** The brief
required distinguishing three concepts; forcing the fix into Option A (strip fields
from the payload) or Option B (use `content_digest()` as identity) would have
collapsed two of them.

| Option | Why rejected |
|---|---|
| **A — exclude volatile fields from the persisted payload** | **Destroys audit data.** §13 forbids deleting provenance to stabilise a hash. It also changes what `load()` returns, silently rewriting the record's history. |
| **B — use `content_digest()` as the content identity** | **Too weak.** It covers only `compaction_id`, `policy_version`, `logical_version`, items and refs — ignoring `task_id`, `request_fingerprint`, `compaction_method`, `trigger` and item provenance, so genuinely different records could collide. |
| **C — CHOSEN: a dedicated logical-identity digest** | Covers the **entire** serialized record except two declared runtime fields — strictly stronger than B, and preserves A's determinism. Runtime data stays on disk. Fail-safe by construction. |

### Implementation

**`compaction_schema.py`**
- `RUNTIME_ONLY_FIELDS`, `_strip_runtime_fields()` (depth-recursive, because
  `acquired_at` is nested inside `provenance`).
- `_sha256_of_stripped()` — canonical digest, also excluding the self-referential
  `logical_identity` field.
- `CompactedContextRecord.logical_identity()` — the new logical digest.
- `as_dict()` now carries `logical_identity` so a committed record states its result.

**`storage.py`**
- `save()` replay decision switched from byte-hash to logical identity, with the
  committed record's identity **recomputed from the stored bytes** (never trusted
  from the stored field), and `None` (unreadable) treated as a conflict — fail-safe.
- `load()` gains the logical-identity verification described in §6.

`content_digest()`, `make_request_fingerprint()`, `CompactionRecordStore.artifact_name()`,
the 18-J branch structure, and the catalog's `content_hash` are all **unchanged**.

---

## 8. Why Alternative Repairs Were Rejected

One property decided it: the fix must not be able to make two *genuinely
different* records look identical. Option A and Option B each risk that in a
different way — A by deleting the fields that distinguish records, B by hashing a
strict subset that omits `task_id`, `request_fingerprint` and item provenance. The
chosen construction fails safe: it hashes everything except two named fields, so
any future field strengthens identity by default.

## 9. Test Matrix

All in `TestP1PersistenceDeterminism` (18 tests) plus 4 production-wiring tests.

| # | §8 case | Result |
|---|---|---|
| 1 | Same content, `duration_ms` 0.400 vs 0.900 → same identity, idempotent reuse | ✅ |
| 2 | Same content, different `acquired_at` → same identity, reuse | ✅ |
| 3 | Both volatile fields differ → same identity, one artifact | ✅ |
| 4 | Different compacted content → different identity, distinct artifact | ✅ |
| 5 | Different task → different identity, distinct artifact | ✅ |
| 6 | Same content after restart → same identity, reload OK | ✅ |
| 7 | Physical corruption after save → integrity failure | ✅ |
| 8 | Catalog hash altered, bytes intact → integrity failure | ✅ |
| 9 | `content_digest` stable when only runtime metadata changes | ✅ |
| 10 | Meaningful field change → new identity | ✅ |
| + | Forged `logical_identity` field → refused | ✅ |
| + | Unreadable committed record → not reused (fail-safe) | ✅ |
| + | Catalog hash remains the raw-byte hash | ✅ |
| + | Runtime metadata still persisted and round-tripped | ✅ |

**Two of these corrected my own initial expectations**, and the corrections are
instructive:

- **Tests 4 and 5 do not raise a conflict.** Different histories and different
  tasks produce different `compaction_id`s, hence different artifact *keys*,
  hence separate artifacts. Isolation means "never collide", not "always
  conflict". The genuine conflict case is *same key, different content*, which is
  exactly the §10 negative control.
- `duration_ms` round-trips as its **3-decimal rounded** value, because
  `as_dict()` rounds for stable serialization.

---

## 10. Negative Controls

Guarding against a false fix that strips too much:

| Control | Expected | Result |
|---|---|---|
| Same task, same iterations, **different failure text** | different identity + **conflict** | ✅ |
| Different task, **identical item content** | different identity + distinct artifacts | ✅ |
| Policy version change | different identity | ✅ |
| Truncating the item list | different identity | ✅ |

The first is the load-bearing one: identical structure, identical id, different
content — and it still conflicts.

---

## 11. C-3 Regression

| Cycle | candidates | project_files | compaction_id | artifact id | conflict |
|---:|---:|---:|---|---|---|
| 1 | 8 | 4 | `cmp_596fc2c396726089` | set | none |
| 2 | 8 | 4 | `cmp_596fc2c396726089` | set | none |
| 3 | 8 | 4 | `cmp_596fc2c396726089` | set | none |
| 4 | 8 | 4 | `cmp_596fc2c396726089` | set | none |

**4 → 4 → 4 → 4**, identical identity, **no `ArtifactConflictError`**, and
`test_p1_c3_boundary_still_holds_after_repair` asserts the candidate count does
not drift and no `compaction_cmp_*` path ever appears.

---

## 12. Production-Wiring Verification

Driven through `build_autoforge_system()`, never a hand-built store:

| Assertion | Result |
|---|---|
| `context_builder.compaction_store is system.compaction_store` | ✅ (C-1 identity preserved) |
| store's catalog **is** the system's `durable_catalog` | ✅ |
| store's physical store **is** the system's `physical_store` | ✅ |
| 5 repeated compactions ⇒ exactly **one** artifact id | ✅ |
| Every replay recognised (artifact id set each cycle) | ✅ |

The object-identity assertion is the load-bearing one: an `isinstance` check would
pass even if the builder held a private store.

---

## 13. Restart / Recovery

| Property | Result |
|---|---|
| Save → new composition root → load | ✅ record recovered |
| Logical identity preserved across restart | ✅ |
| `content_digest()` preserved | ✅ |
| No duplicate record | ✅ exactly one |
| No conflict on restart-replay | ✅ |
| Runtime metadata may differ on a new execution | ✅ (not identity-bearing) |
| Authoritative record remains recoverable | ✅ |

---

## 14. Provenance Verification

| Field | Class | Retained on disk | Identity-bearing |
|---|---|---|---|
| `acquired_from`, `source_ref`, `provider`, `inferred` (item-level) | provenance | ✅ | ✅ |
| `acquired_at` (record-level) | audit metadata | ✅ | ❌ |
| `duration_ms` | runtime | ✅ | ❌ |

`test_runtime_metadata_is_still_persisted` asserts the timestamp and duration are
present in the payload and survive a round-trip. **No provenance was deleted.**

## 15. 18-J Protection

| Check | Result |
|---|---|
| `packages/runtime/tests/test_18j_defect_repair.py` | ✅ 20/20 |
| 18-J source files modified | ❌ none |
| State-transition definitions modified | ❌ none |
| Artifact replay logic (`COMMITTED` never reopened) | ✅ unchanged — reuse returns the existing id |
| Artifact conflict semantics | ✅ preserved, now decided on the correct input |

The repair operates entirely **within** existing durable artifact semantics: it
changes only *which comparison* decides reuse, never the state machine.

---

## 16. Context Engineering Protection

`select_context`, `context_budget.py`, `context_selection.py`, `prompt_assembly.py`
and `context_observability.py` — **none modified** (verified by `git diff`
returning empty). Context Engineering remains globally ON (6/6 tests). The C-3
boundary fix is untouched.

---

## 17. Regression Results

| Package | Baseline | Post-repair | Delta |
|---|---|---|---|
| **execution** | 207 passed, 18 skipped | **225 passed, 18 skipped** | **+18 (P1 tests)** |
| **composition** | 3 failed, 77 passed | **3 failed, 81 passed** | **+4 (P1 wiring tests)** |
| runtime | 268 passed | 268 passed | 0 |
| artifacts / orchestration / workflows / kernel / review / observability | unchanged | identical | 0 |
| persistence / events / event_platform / connectors / security / ai_infrastructure | unchanged | identical | 0 |
| modernization | 375 passed, 59 skipped | identical | 0 |
| **18-J suite** | 20 passed | **20 passed** | 0 |
| **Context Engineering global** | 6 passed | **6 passed** | 0 |
| **Context Compaction** | 58 passed | **76 passed** | +18 |

**New failures: 0.**

**Pre-existing failures (unchanged, explicitly identified):**
- **Composition — 3 failed**, identical test IDs: `test_canonical_context_builder_invoked_in_execution_path`,
  `test_canonical_durable_artifact_wiring`, `test_execution_platform_integration`.
  Cause unchanged: they request `qwen2.5-coder-7b` from `127.0.0.1:8080`, which
  serves the M6 30B model. **The inference lab was not modified.**
- **Workforce — 1 collection error**: imports the removed `OllamaProviderAdapter`.

---

## 18. Performance

| Stage | mean | max |
|---|---:|---:|
| `logical_identity()` computation | 0.0991 ms | 0.3141 ms |
| `content_digest()` (unchanged, for comparison) | 0.0092 ms | 0.0593 ms |
| `as_dict()` serialization | 0.0525 ms | 0.2704 ms |
| First save (full write path) | 0.5822 ms | 2.4700 ms |
| **Replay save (identity comparison)** | **0.4384 ms** | 0.5863 ms |
| Load incl. integrity verification | 0.2031 ms | 0.4303 ms |

No disproportionate overhead. The replay path trades one payload hash for one
small file read plus one parse — sub-millisecond either way, and it now *succeeds*
instead of raising. `logical_identity()` costs ~0.1 ms because it canonically
serializes the whole record; that is the price of hashing everything, which is
what makes the identity fail-safe.

## 19. Remaining Risks

| ID | Risk | Severity | Disposition |
|---|---|---|---|
| R-1 | Logical identity hashes the **entire** record; a future volatile field would cause false conflicts unless added to `RUNTIME_ONLY_FIELDS` | Low | Fails **safe** (conflict, not silent reuse). Constant documented and tested. |
| R-2 | Replay save reads and parses the committed artifact | Low | 0.44 ms measured; acceptable at compaction frequency |
| R-3 | `logical_identity` is a new persisted field | Low | Absent in pre-repair records; the check is `if claimed is not None`, so old records still load. C-2 proved no such records exist. |
| R-4 | Reference resolution still unwired | Low | Gate 4 §6 decision, unchanged |
| R-5 | Pre-existing G-1 gap for short histories | Low | Pre-existing, tracked under CE |
| R-6 | Composition suite cannot fully pass on this host | Low | Pre-existing |

---

## 20. Final Verdict

### ✅ P1 PERSISTENCE DETERMINISM = PASS

All §22 acceptance criteria are met:

- **Determinism** — identical logical content with different runtime metadata no
  longer conflicts; the replay is recognised and the artifact reused.
- **Identity** — different logical content produces a different identity.
- **Isolation** — different tasks remain isolated, and their identities differ
  even when their item content is byte-identical.
- **Integrity** — physical corruption and catalog/byte mismatch are both still
  detected; neither was weakened.
- **Catalog consistency** — the catalog's `content_hash` remains the raw-byte hash.
- **Restart** — the logical record survives a full process restart.
- **Production wiring** — verified through `build_autoforge_system()` with
  object-identity assertions preserved.
- **C-3** — 4 → 4 → 4 → 4, bookkeeping still excluded, no drift.
- **Regression** — 0 new failures; 22 new tests.
- **Protection** — 18-J (20/20), 18-K, Context Engineering architecture,
  inference lab and Model Router all unchanged.

**No outstanding condition.** All prior gates are closed:

| Gate | Status |
|---|---|
| Gate 4 verification | ✅ PASS |
| C-1 production composition-root wiring | ✅ CLOSED |
| C-2 historical record integrity | ✅ CLOSED |
| C-3 workspace boundary isolation | ✅ VERIFIED |
| **P1 persistence determinism** | ✅ **PASS** |

**Context Compaction is now fully verified end to end. It remains OFF; global
enablement requires separate explicit authorization.**

### Files changed by this task

| File | Nature |
|---|---|
| `packages/execution/src/autoforge_execution/compaction/compaction_schema.py` | `logical_identity()`, `RUNTIME_ONLY_FIELDS`, stripping/canonicalisation, `as_dict()` carries the identity |
| `packages/execution/src/autoforge_execution/compaction/storage.py` | replay decision on logical identity; load-time logical verification |
| `packages/execution/tests/test_context_compaction.py` | +18 P1 tests |
| `packages/composition/tests/test_c3_workspace_boundary.py` | +4 production-wiring P1 tests |
| `context-compaction-gate4/diag_p1_identity.py`, `p1_performance.py`, `p1_performance.json` | evidence |




