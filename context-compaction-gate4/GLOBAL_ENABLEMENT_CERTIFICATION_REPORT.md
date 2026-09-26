# Context Compaction — Global Enablement & Certification

**Workstream:** 18-L Context Compaction
**Gate:** Global Enablement & Certification
**Date:** 2026-09-26
**Status:** ✅ **CERTIFIED**
**Configuration:** Context Engineering = **ON** · Context Compaction = **ON** · No commit · No push

---

## 1. Previous Gate Status

| Gate | Status | Carried condition |
|---|---|---|
| Gate 1 — Architecture Audit | PASS | — |
| Gate 2 — Design | PASS | — |
| Gate 3 — Implementation | PASS | — |
| Gate 4 — Verification | PASS WITH CONDITIONS | C-1, C-2 |
| C-1 — Production composition-root wiring | **CLOSED** | — |
| C-2 — Historical record integrity | **CLOSED** | — |
| C-3 — Workspace boundary isolation | **VERIFIED** | P1 |
| P1 — Persistence determinism | **PASS** | — |

All prior conditions are resolved. This gate performed enablement and
post-enable certification only.

---

## 2. Exact Enablement Change

**One line changed.** The production default in
`packages/composition/src/autoforge_composition/composition_root.py`:

```python
# BEFORE
enable_context_compaction = bool(
    (config or {}).get("enable_context_compaction", False)   # OFF
)

# AFTER — 18-L global enablement
enable_context_compaction = bool(
    (config or {}).get("enable_context_compaction", True)    # ON
)
```

This mirrors exactly how Context Engineering was enabled in Gate 4B: the flag is
passed **explicitly** at the composition root, which remains the single readable
source of truth for the production posture.

**No second configuration system was introduced.** Verified: a repository-wide
search found the flag referenced in exactly one production location, with no
environment variables, YAML, TOML, or `.env` override anywhere.

**The documented rollback lever is preserved and proven:**

| Configuration | Context Engineering | Context Compaction |
|---|---|---|
| default (no config) | ON | **ON** |
| `{"enable_context_compaction": False}` | ON | OFF |
| `{"enable_context_compaction": True}` | ON | ON |

**Enablement introduced no dependency.** The compactor is deterministic and
CPU-only: no model, no provider, no runtime, no M6, no network, no Ollama, no
cloud. The canonical production path remains deterministic-first, and
model-mediated compaction remains explicitly rejected by validation (V-10).

---

## 3. Production Composition Proof

The C-1 object-identity contract is preserved under the enabled posture:

```
build_autoforge_system()
   ├─ 3b  PhysicalArtifactStore          (canonical substrate)
   ├─ 3b  DurableArtifactCatalog         (canonical catalog)
   ├─ 3c  CompactionRecordStore(catalog, physical_store)   ← owned here
   └─ 6b  EngineeringContextBuilder(compactor=…, compaction_store=…)
```

| Assertion | Result |
|---|---|
| Store's catalog **is** `system.durable_catalog` | ✅ |
| Store's physical store **is** `system.physical_store` | ✅ |
| Builder's store **is** the root's store | ✅ |
| **Exactly one** `CompactionRecordStore` on the system | ✅ |
| Compactor injected into the builder | ✅ |

No duplicate store, no second catalog, no alternate persistence path.

---

## 4. Canonical-Path Proof

Executed through `build_autoforge_system()` with **no config override** — the
globally enabled production posture.

| Stage | Evidence |
|---|---|
| Task intake | `TaskDefinition` accepted by the production builder |
| Context Engineering | `enable_context_engineering = True` |
| **Context Compaction** | trigger `iteration_boundary`; record produced |
| Persistence | durable artifact `compaction_cmp_30e912431d357038` on disk |
| MSC selection | 8 candidates considered, 8 selected |
| Budgeting | budget resolved |
| Prompt assembly | canonical messages built |
| Knowledge / Memory / Model allocation | unchanged; the compactor adds no dependency |
| Review / Verification / Completion | unchanged; outside the compaction boundary |

Canonical item kinds reaching the prompt: `evaluation`, `iteration`, `task`,
`workspace` — the `iteration` kind is the compaction output, proving compaction
participated in the real pipeline.

> A full multi-agent workflow to completion requires a live model endpoint, which
> is not available on this host. Per §4, the **smallest real production
> composition path that exercises the enabled compaction boundary** was used:
> the actual `EngineeringContextBuilder` from the actual composition root.
> **No mocked compaction implementation was substituted** — the compactor that
> ran is the production one.

## 5. Determinism Verification (Part 5 A)

Five identical production cycles, no configuration:

| Property | Result |
|---|---|
| Identical `compaction_id` | ✅ all 5 equal |
| Identical `request_fingerprint` | ✅ all 5 equal |
| Identical artifact id | ✅ all 5 equal |
| No false `ArtifactConflictError` | ✅ every replay recognised |

---

## 6. Cross-Task Isolation (Part 5 B)

| Property | Result |
|---|---|
| Distinct `compaction_id` | ✅ |
| Distinct logical identity | ✅ |
| Distinct durable artifact | ✅ |
| No collision | ✅ |

The Gate 4 P1-1 cross-task repair remains intact under enablement.

---

## 7. Physical-Integrity Verification (Part 5 C)

| Property | Result |
|---|---|
| Corrupted persisted bytes rejected | ✅ |
| Restored record loads again | ✅ |

The P1 physical-integrity contract was **not** weakened by enablement: the
catalog's `content_hash` remains the raw-byte hash and is still verified on load.

---

## 8. Runtime Metadata Verification (Part 5 D)

| Property | Result |
|---|---|
| Logical identity stable under `duration_ms` / `acquired_at` change | ✅ |
| `content_digest()` stable | ✅ |
| Replay accepted (no false conflict) | ✅ |
| `duration_ms` still persisted | ✅ |
| `provenance.acquired_at` still persisted | ✅ |

Runtime metadata remains audit data on disk; it is simply not identity-bearing.

---

## 9. C-3 Bookkeeping Isolation (Part 5 E)

| Property | Result |
|---|---|
| `project_files` per cycle | `[3, 3, 3, 3, 3]` |
| Identical file list across cycles | ✅ |
| Compaction paths in candidates | **`[]`** |
| No leak | ✅ |

The C-3 boundary invariant holds under global enablement — compaction
bookkeeping never becomes an ordinary engineering candidate.

---

## 10. Restart/Recovery (Part 5 F)

| Property | Result |
|---|---|
| Record reloaded after a new composition root | ✅ |
| Same logical identity | ✅ |
| Same `content_digest()` | ✅ |
| No duplicate artifact | ✅ |
| Physical integrity verified on load | ✅ |

## 11. Bypass Audit (Part 7)

A bounded search of every production path that can construct context:

| Path | Governed? | Evidence |
|---|---|---|
| `EngineeringContextBuilder` (composition root) | ✅ **governed** | compactor injected |
| `ExecutionEngine` dispatcher (primary) | ✅ **governed** | `_context_builder` injected; `dispatcher_uses_root_builder = True` |
| `Workforce` dispatch (primary) | ✅ **governed** | same injected builder |
| `Composition root` | ✅ **governed** | owns store + compactor |
| `ExecutionEngine` dispatcher (fallback) | ⚠️ **documented exception** | `dispatcher.py:158` |
| `Workforce` dispatch (fallback) | ⚠️ **documented exception** | `dispatch.py:158` |
| Orchestrator | ✅ governed by R-9 | R-9 exception documented in Gate 3/4 |

**The two fallback paths are pre-existing (Gate 4B), not introduced by
enablement.** They construct a bare `EngineeringContextBuilder()` — which has
Context Engineering ON (its own default) but **no compactor** — and they execute
**only when no context builder was injected** into the dispatcher.

**Verified not reached in production:** the audit measured
`fallback_reached_in_production = False` and `dispatcher_uses_root_builder = True`
against the real composed system, because the composition root always injects the
builder (`composition_root.py`, step 7).

Per §7 these were **documented, not changed** — altering the dispatcher would be
a redesign outside this gate's scope. They remain a legitimate finding for a
future hardening pass: a dispatcher constructed *without* a builder would run
without compaction.

**No accidental bypass was introduced by enablement.**

---

## 12. Regression Results (Part 6)

| Package | P1 baseline | Post-enablement | Delta |
|---|---|---|---|
| execution | 225 passed, 18 skipped | 225 passed, 18 skipped | 0 |
| runtime | 268 passed | 268 passed | 0 |
| artifacts / workflows | 14 / 218 passed | identical | 0 |
| orchestration | 53 passed, 6 skipped | 53 passed, 6 skipped | 0 |
| kernel / review / observability | 100 / 114 / 16 passed | identical | 0 |
| persistence / events / event_platform | 70 / 228 / 56 passed | identical | 0 |
| connectors / security / ai_infrastructure | 93 / 37 / 97 passed | identical | 0 |
| modernization | 375 passed, 59 skipped | identical | 0 |
| **Context Compaction** | 76 passed | 76 passed | 0 |
| **C-1 production wiring** | 16 passed | **17 passed** | +1 (see below) |
| **C-3 boundary** | 17 passed | 17 passed | 0 |
| **18-J suite** | 20 passed | 20 passed | 0 |
| **Context Engineering global** | 6 passed | 6 passed | 0 |
| **composition (full)** | 3 failed, 81 passed | 3 failed, 82 passed | +1 |

**New failures: 0.**

### One test was updated — it encoded the pre-enable posture

`test_default_build_does_not_inject_a_compactor` failed after enablement because
it asserted the *old* default. It was **replaced, not deleted**, by two tests
that encode the certified posture and the rollback lever:

- `test_default_build_injects_an_enabled_compactor` — default is ON, CE still ON,
  store still root-owned.
- `test_rollback_lever_disables_compaction_without_touching_ce` —
  `config={"enable_context_compaction": False}` disables compaction, leaves CE on.

This is a legitimate posture update, not a weakening: the test's *intent* (the
production posture is explicit and single-sourced) is preserved and now asserted
in **both** directions.

### Pre-existing failures — proven unchanged, not asserted

**Composition — 3 failed**, with the **same test IDs** recorded in every prior gate:

- `test_canonical_context_builder_invoked_in_execution_path`
- `test_canonical_durable_artifacts::test_canonical_durable_artifact_wiring`
- `test_execution_platform_integration::test_autoforge_system_execution_wiring`

Proof they are unchanged and unrelated to enablement:

1. Identical test IDs to the recorded baseline.
2. Root cause reproduced directly: `ConnectionRefusedError [Errno 61]` to
   `127.0.0.1:8080` — the M6 evaluation runtime, stopped at the end of Gate 4 and
   deliberately not restarted. The endpoint is confirmed **DOWN**, matching the
   baseline exactly.
3. **Zero occurrences of "compaction"** in these tests' failure output — they
   fail before reaching the compaction boundary at all.

**Workforce — 1 collection error**: imports the removed `OllamaProviderAdapter`
(pre-existing since an earlier gate; no Ollama dependency introduced).

---

## 13. Performance Sanity (Part 8)

| Metric | Value |
|---|---|
| assemble-with-compaction mean | 1.337 ms |
| assemble-with-compaction max | 2.121 ms |
| compacted tokens (mean) | 253 |
| durable artifacts after 6 cycles | 6 |
| runaway persistence | **none** — 6 artifacts for 6 *distinct* logical tasks, 1 each |
| context growth | **bounded** — 253 tokens, stable |
| model calls | **none** |
| network dependency | **none** |

Repeated identical cycles reuse the same artifact, so persistence does not grow
with iteration count. Enablement adds no model, network, or M6 dependency.

---

## 14. Protected-System Verification (Part 9)

| System | Status | Evidence |
|---|---|---|
| **18-J** durable execution | PROTECTED / RE-FROZEN | 20/20; no 18-J file modified |
| **18-K** runtime/packaging | PROTECTED | no packaging change |
| **Inference Lab** | PROTECTED | not started, not modified; M6 runtime still stopped |
| **M6 authority model** | PROTECTED | no configuration change |
| **Model Router** | PROTECTED | no router configuration touched |
| **Context Engineering architecture** | PROTECTED | `context_selection.py`, `context_budget.py`, `prompt_assembly.py`, `context_observability.py` — `git diff` empty |
| **Context selection / budgeting / prompt assembly** | PROTECTED | unmodified |
| **Reference wiring** | PROTECTED (still unwired) | `CatalogReferenceResolver` has no production wiring; Gate 4 §6 decision intact |
| Model-mediated compaction | still rejected | V-10 contract unchanged |
| No cloud / Ollama dependencies | ✅ | grep clean |

**The only production change in this gate is the single default value.** No
compaction algorithm, policy, selection, budgeting, prompt assembly, 18-J, 18-K,
inference, or routing code was touched.

## 15. Final Configuration State

Verified by `verify_final_state.py` against a freshly composed production system:

```json
{
  "context_engineering": "ON",
  "context_compaction": "ON",
  "compactor_enabled": true,
  "compaction_store_owned_by_root": true,
  "builder_consumes_root_store": true,
  "catalog_is_canonical": true,
  "physical_store_is_canonical": true,
  "git_head": "9cc09bc",
  "commits_ahead_of_origin": "0",
  "committed_this_gate": false,
  "pushed": false
}
```

---

## 16. Remaining Known Limitations

1. **Two dispatcher fallback paths run without compaction** (§11). Pre-existing
   Gate 4B behaviour, unreachable in production, documented rather than changed.
   A future hardening pass could inject the builder there.
2. **Reference resolution remains deliberately unwired** (Gate 4 §6). Inline
   projection is semantically safe and bounded; wiring would add a catalog
   dependency to prompt assembly for a token optimization only.
3. **Budget-pressure trigger remains inert** (Gate 4 §9), classified ACCEPTABLE:
   the deterministic iteration-count trigger bounds context growth first.
4. **Pre-existing Gate 1 G-1 gap** for histories below the trigger (Gate 4
   §12.3) — orthogonal to compaction, unchanged, tracked under Context Engineering.
5. **Full end-to-end workflow to completion was not executed**, because it requires
   a live model endpoint unavailable on this host. The smallest real production
   composition path exercising the enabled boundary was used instead (§4).
6. **Three composition tests and one workforce collection error** remain, all
   proven pre-existing and unrelated to compaction (§12).

---

## 17. Final Verdict

### ✅ CERTIFIED — Context Compaction is GLOBALLY ENABLED, VERIFIED, CERTIFIED

Every acceptance criterion is met:

| Criterion | Result |
|---|---|
| Context Engineering = ON | ✅ |
| Context Compaction = ON | ✅ |
| P1 Persistence = PASS | ✅ |
| C-1 Production Wiring = CLOSED | ✅ |
| C-2 Historical Integrity = CLOSED | ✅ |
| C-3 Workspace Isolation = VERIFIED | ✅ |
| Logical identity deterministic | ✅ 5/5 cycles identical |
| Runtime metadata preserved | ✅ persisted and round-trips |
| Physical integrity independently verified | ✅ corruption rejected |
| Cross-task isolation preserved | ✅ distinct ids and artifacts |
| Restart/recovery = PASS | ✅ |
| Bookkeeping isolation = PASS | ✅ `3,3,3,3,3`, zero leak |
| Regression = 0 new failures | ✅ |
| Production composition = PASS | ✅ object identity proven |
| No accidental bypass | ✅ fallbacks documented, unreachable |
| No new dependency | ✅ no model, network, M6, cloud, Ollama |

```text
Context Engineering:       ON
Context Compaction:        ON

Context Compaction:
  GLOBALLY ENABLED
  VERIFIED
  CERTIFIED

18-J:          PROTECTED / RE-FROZEN
18-K:          PROTECTED
Inference Lab: PROTECTED

No commit
No push
```

**Enablement was a one-line default flip.** The capability had already been
proven by Gate 1–4, C-1, C-2, C-3 and P1; this gate turned it on and confirmed
the enabled production path behaves exactly as that verified design specifies.

### Files changed by this gate

| File | Nature |
|---|---|
| `packages/composition/src/autoforge_composition/composition_root.py` | **the enablement**: default `False` → `True` (+ comment) |
| `packages/composition/tests/test_compaction_production_wiring.py` | posture test replaced with certified default + rollback-lever tests |
| `context-compaction-gate4/verify_enablement.py`, `verify_canonical_path.py`, `verify_enablement_invariants.py`, `verify_final_state.py` + JSON evidence | evidence |

### Evidence artifacts

| File | Contents |
|---|---|
| `enablement_state.json` | default posture, rollback lever, composition proof |
| `enablement_canonical_path.json` | canonical pipeline stages + bypass audit |
| `enablement_invariants.json` | Part 5 A–F invariants + Part 8 performance |
| `enablement_final_state.json` | certified final configuration |




