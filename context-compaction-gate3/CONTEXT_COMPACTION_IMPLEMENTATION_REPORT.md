# Context Compaction — Gate 3 Implementation Report

**Workstream:** 18-L — Context Compaction
**Gate:** 3 — Implementation
**Date:** 2026-09-26
**Status:** COMPLETE — implementation landed, disabled by default
**Not committed. Not pushed.**

**Governing design:** `context-compaction-gate2/CONTEXT_COMPACTION_DESIGN_REPORT.md`
**Audit input:** `context-compaction-gate1/CONTEXT_COMPACTION_ARCHITECTURE_AUDIT.md`

> **Production posture after Gate 3:** `Context Engineering = ON`,
> `Context Compaction = OFF`. No semantic certification, no global enablement,
> no performance certification is claimed here — those belong to Gate 4.

---

## 1. Executive Summary

Deterministic, provider-neutral Context Compaction is implemented and integrated
at the **single** point the Gate 2 design specified: inside
`EngineeringContextBuilder._build_candidates`, before `select_context`.

Three things this gate established with evidence rather than assertion:

1. **G-1 is fixed and proven.** Gate 1 measured that iteration history is
   structurally invisible to the model (`iteration_items_delivered_today: 0` at
   every scale). After Gate 3, compacted iterations reach the assembled prompt —
   `iterations_reached_prompt: 4`, `g1_resolved: true`.
2. **R-9 is resolved** as a *justified, tested scoped exception* — not a gap.
   The orchestrator wires no `EngineeringContextBuilder` at all, uses no canonical
   `ExecutionEngine`, and drives specialized workforce loops that consume a
   pre-built context. Routing it through the builder would attach an unrelated
   subsystem to a different execution model.
3. **Retain/threshold values are measured, not guessed.** Gate 2 §34 Q-1/Q-2
   marked them UNKNOWN; Gate 3 measured them (§17).

Reduction achieved deterministically, with **no model**: **82.7%** of estimated
tokens removed (1813 → 314) on a 7-iteration history.

---

## 2. Gate 2 Design Compliance

| Gate 2 decision | Status | Evidence |
|---|---|---|
| §21 Single integration point in `_build_candidates`, before `select_context` | **Implemented** | `context_builder.py:362`; `select_context`, `context_budget`, `context_selection`, `prompt_assembly`, `context_observability` all **unchanged** |
| §15 Deterministic-first, no model required | **Implemented** | Zero model/provider/runtime imports in the whole package (test-enforced) |
| §8 Reference substitution, not inline copy | **Implemented** | `DurableRef` has no `content` field; test-locked |
| §9 Artifact-backed storage, no new `EntityType` | **Implemented** | `storage.py`; `EntityType` untouched |
| §10 / §19 Artifact identity + 18-J idempotency | **Implemented** | Deterministic `compaction_id`; 18-J replay contract reused unchanged |
| §12 Content-free provenance | **Implemented** | `CompactionProvenance`, `CompactionAssemblyRecord`; test asserts no content leaks |
| §13 Deterministic-evidence precedence | **Implemented** | `proposed_root_cause:`, `authority: observed…` |
| §14 Approvals Irreplaceable | **Implemented** | `IRREPLACEABLE_SOURCE_KINDS`; test asserts `REJECTED` never becomes absence |
| §16 Model-mediated stage OFF, unimplemented | **Implemented** | `CompactionMethod.MODEL_MEDIATED` rejected by V-10 as unimplemented |
| §17 V-1…V-13 deterministic validation | **Implemented** | `compaction_validation.py` |
| §19 Idempotency via fingerprint | **Implemented** | Same sources+policy ⇒ same id; policy change ⇒ new id |
| §20 Versioning without migration | **Implemented** | Unsupported schema version ignored, never migrated |
| §29–§30 Rollback, default OFF | **Implemented** | `CompactionPolicy.enabled = False`; byte-identical test |

**No deviation required.** Gate 2 was implementable exactly as specified.

---

## 3. Exact Source Changes

**ADDED** (5 files, `packages/execution/src/autoforge_execution/compaction/`):

| File | Purpose |
|---|---|
| `__init__.py` | Package exports; provider-neutrality statement |
| `compaction_schema.py` | `CompactedContextRecord`, `CompactionProvenance`, `DurableRef`, `CompactionAssemblyRecord`, deterministic id/fingerprint |
| `compaction_policy.py` | Preservation classes, evidence-derived thresholds, `CompactionPolicy` triggers |
| `compactor.py` | `ContextCompactor`, `project_iteration`, `link_iteration_chain` |
| `compaction_validation.py` | V-1…V-13, three new error types |
| `storage.py` | `CompactionRecordStore`, `CatalogReferenceResolver` (artifact-backed) |

**MODIFIED** (1 file, additive only):

| File | Change |
|---|---|
| `packages/execution/src/autoforge_execution/context_builder.py` | + `compactor: Any \| None = None` kwarg (default `None`), + `last_compaction_record`, + compaction block in `_build_candidates`, + `_apply_compaction()` method, + `_optional_id()` helper. **No existing behaviour altered when `compactor is None`.** |

**Deliberately NOT modified:** `composition_root.py` (Gate 3 §30 — no global
enablement), `select_context`, `context_budget`, `prompt_assembly`,
`context_observability`, all of 18-J, 18-K, the Model Router, the inference lab.

## 4. Exact Test Changes

**ADDED:** `packages/execution/tests/test_context_compaction.py` — **51 tests**
covering every §25 area: deterministic extraction (7), preservation (4),
references (4), contradictions (4), idempotency (5), failure/recovery (10),
trigger/budget (6), CE integration (7), R-9 (4).

No existing test was modified.

## 5. Compaction Architecture Implemented

```text
LoopIterationRecord history (unbounded, in-process)
        ↓
[ trigger: deterministic policy predicate ]
        ↓
deterministic extraction (project_iteration)
        ↓
structured ContextItems + dependency chain + provenance
        ↓
reference resolution (optional, artifact-backed)
        ↓
V-1…V-13 deterministic validation  ← the only promotion gate
        ↓
CompactedContextRecord (bounded, versioned, content-free provenance)
        ↓
EngineeringContextBuilder._build_candidates  ← the ONE integration point
        ↓
select_context (MSC: rank, dedup, budget) — UNCHANGED
        ↓
ContextWindowBudget — UNCHANGED
        ↓
prompt_assembly.build_messages — UNCHANGED
        ↓
BaseProviderAdapter.normalize_messages → local runtime
```

**No model stage exists.** `CompactionMethod.MODEL_MEDIATED` is present in the
contract for forward compatibility and is explicitly **rejected** by V-10
(`v10_model_mediated_not_implemented`), so a future enablement cannot silently
inherit an unvalidated path.

## 6. Integration Point

`packages/execution/src/autoforge_execution/context_builder.py:362`, inside
`_build_candidates`, immediately before the existing mandatory-provenance check
(and therefore before `select_context`):

```python
compaction_record = None
if self.compactor is not None and self.compactor.enabled:
    try:
        compaction_record = self._apply_compaction(...)
        if compaction_record is not None:
            candidates = compaction_record.items
    except Exception as exc:  # noqa: BLE001 - compaction is fail-safe
        logger.warning("context compaction failed; continuing with "
                       "uncompacted candidates: %s", exc)
        compaction_record = None
```

This is the only production call site. Provenance of the placement:
`_build_candidates` is the method that already turns gathered sources into
`ContextItem`s, and it is the sole feeder of `select_context`. Compaction
therefore transforms the *candidate pool* and nothing downstream changes.

**Verified properties:**
- compaction runs before selection (test asserts compacted items appear in
  `ContextAssemblyRecord.selected` as `engineering_loop:iter-N`);
- budget computed once (`budget_source == "caller"`, one `available_for_context_tokens`);
- prompt assembly is the sole renderer (every message is `{"role","content"}`).

## 7. Iteration Representation (G-1 fix)

Each superseded iteration becomes an explicit, addressable `ContextItem` reusing
the existing identity scheme (Gate 2 §10):

| Field | Value |
|---|---|
| `source.kind` | `"iteration"` |
| `source.ref` | `"iter-N"` |
| `context_id` | existing content-derived `ctx_…` (Gate 2 E-2) — no parallel id system |
| `category` | `VERIFICATION` (failed) / `EXECUTION` (passed) — existing categories only |
| `required` | `True` only for the newest; older stay optional so MSC may still exclude them |
| `depends_on` | `ctx_…` of the immediately preceding iteration |
| `provenance` | `acquired_from="engineering_loop"`, `source_ref="iter-N"`, `inferred=False` |

Projected structure (measured **74%** smaller than the raw record, 311 → 81
tokens/iteration):

```text
iteration: 3
action_plan: iteration 3: adjust the backoff helper and re-run tests
changed_files: src/retry_3.py
result: failed
authority: observed:failed
observed_failures: test_sequence FAILED at iteration 3
proposed_root_cause: iteration 3: the clamp overrides doubling
proposed_correction: remove the clamp
status: superseded by iter-4
```

**Authority discipline (Gate 3 §12):** a diagnosis is rendered as
`proposed_root_cause`, never as verified; an outcome is `authority: observed…`,
distinguishing `observed_by_deterministic_checks:` from plain `observed:`. Model
inference never becomes a verified fact.

## 8. Information Preservation

Implemented via `classify_item`, keyed on real AutoForge structures:

| Class | Rule | Test |
|---|---|---|
| **Irreplaceable** | `TASK`/`SYSTEM`/`PROJECT`/`DECISION` categories, or source kinds `approval`/`governance`/`policy`/`user_instruction`. Carried through **verbatim**, never summarised or referenced away. | `test_irreplaceable_items_are_never_compacted_away` |
| **Reconstructable** | `EVIDENCE`/`VERIFICATION`/`EXECUTION`/`TOOL`/`TEST_OUTPUT`/`GIT` and anything else. Replaced by durable reference. | `test_unresolvable_reference_is_not_fabricated` |
| **Ephemeral** | Not separately dropped; duplicates are already deduplicated by `content_digest` upstream. | (covered by dedup) |
| **Historical** | Anything not reconstructable defaults here, never to Ephemeral. | `test_classification_covers_every_item` |

A rejection must never become absence:
`test_approvals_are_irreplaceable_and_never_become_absence` asserts a `REJECTED`
approval survives compaction with its content intact.

## 9. Durable Reference Strategy

`DurableRef` is **reference-only**: `artifact_id`, `content_hash`,
`logical_version`, `artifact_type`, `source_ref`. It has **no content field**
(test-enforced), so a compacted record can never masquerade as the content itself.

`CatalogReferenceResolver` resolves refs over the **existing**
`DurableArtifactCatalog`, read-only, and returns only **COMMITTED** artifacts —
a reference never points at an in-flight staging write.

Unresolvable or exploding resolvers are handled fail-safe:
`test_resolver_exception_does_not_break_compaction`,
`test_unresolvable_reference_is_not_fabricated`.

## 10. Storage Implementation

Gate 2 §9 recommendation (b) adopted: **artifact-backed**, no new `EntityType`.

`CompactionRecordStore` reuses `DurableArtifactCatalog` +
`PhysicalArtifactStore` unmodified. The artifact name is
`compaction_{compaction_id}` — a pure function of the record identity, which is
what makes retry idempotent through 18-J's existing contract.

`load()` returns `None` for an unsupported schema version rather than migrating
(Gate 2 §20), so stale meaning is never trusted.

## 11. Idempotency

Gate 2 §19 mechanism, reusing 18-J rather than duplicating it:

- `compaction_id = "cmp_" + sha256(source_scope + request_fingerprint)[:16]` —
  content-derived, mirroring `make_context_id` (Gate 2 E-2).
- `request_fingerprint = sha256(sorted(source_ids) + sorted(source_hashes) + policy_version)`
  — the same shape as `IdempotentOperationState.request_fingerprint` (Gate 2 E-14).
- `idempotency_key = "compact:{scope}:{task_id}:{execution_id}"`.
- The storage name `compaction_{compaction_id}` is a pure function of that
  identity, so a retry lands on the same artifact and 18-J's repaired contract
  decides: identical content reuses the durable artifact; differing content
  raises `ArtifactConflictError`. **18-J is reused, never modified.**

Tests: `test_same_source_and_policy_produce_the_same_record`,
`test_changed_policy_produces_a_new_identity`, `test_retry_does_not_duplicate_items`,
`test_fingerprint_is_deterministic_and_policy_sensitive`.

## 12. Conflict / Contradiction Handling

Reuses the repository's existing authority rule (Gate 2 E-12: *"Deterministic
checks ALWAYS take precedence over model confidence"*) rather than inventing a
truth hierarchy (Gate 3 §11).

- Contradicting iterations are **retained, not collapsed** —
  `test_conflicting_iterations_are_retained_not_collapsed`.
- A diagnosis is a **proposal**: `proposed_root_cause:` /
  `proposed_correction:`, never `verified_*`
  (`test_deterministic_evidence_takes_precedence_over_model_claim`).
- Outcomes carry an explicit `authority:` marker distinguishing
  `observed_by_deterministic_checks:` from `observed:`
  (`test_outcomes_are_marked_observed_not_verified_by_a_model`).
- A *passing* iteration is likewise `observed:passed`, never "verified correct by
  the model".

## 13. Provenance

`CompactionProvenance` is content-free by construction: `acquired_from`,
`source_ref`, `provider`, `acquired_at`, `inferred`, `source_context_ids`,
`source_artifact_refs`, `compaction_method`, `policy_version`. V-13 rejects a
provenance carrying a non-string id.

`CompactionAssemblyRecord` mirrors `ContextAssemblyRecord`'s discipline;
`test_observability_record_is_content_free` asserts the emitted blob contains
neither `"adjust the backoff helper"` nor `"clamp overrides"`.

Per-item provenance is the existing `ContextProvenance` with
`acquired_from="engineering_loop"`, `inferred=False` — one provenance per item,
not a parallel chain.

## 14. Dependency Preservation

`link_iteration_chain` links each iteration item to its predecessor using the
existing `ContextItem.depends_on` field, so the causal chain reuses established
identity machinery. A predecessor of a mandatory item is promoted to `required`,
mirroring `expand_dependencies` (Gate 2 E-7).

Edges are **copied, never re-derived**: compaction does not invent or resolve
dependencies; `select_context` still owns expansion. V-4 rejects any dangling
`depends_on` target (`test_dangling_dependency_is_rejected`).

## 15. R-9 Resolution

> **R-9: JUSTIFIED SCOPED EXCEPTION — traced, tested, and locked.**

**Traced evidence (Gate 3):**

| Question | Finding |
|---|---|
| Callers of `_build_execution_context` | `orchestrator.py:751` (stage execution) and `:923` (repair retry) only |
| Does the orchestrator wire an `EngineeringContextBuilder`? | **No** — no reference in the module |
| Does it use the canonical `ExecutionEngine`? | **No** — no `build_autoforge_system`, no `run_workflow_to_completion` |
| What consumes the context? | `WorkforceWorker.execute_task(context)` uses the passed-in context directly; it never calls `assemble_context` |
| Lifecycle / retry coupling | Stage state is persisted via `self._persist(state)` and re-read per attempt; the context is rebuilt per attempt, not checkpointed |

**Conclusion.** This is not "the canonical path bypassing compaction". It is a
*different execution model*: an orchestration-driven stage runner that builds a
context for a specialized workforce loop. Routing it through
`EngineeringContextBuilder` would (a) require wiring a builder the orchestrator
deliberately does not have, (b) change which items reach a specialized loop, and
(c) risk breaking its persist/retry lifecycle — architectural risk with no
correctness benefit. The exception is **preserved and documented**, exactly as
Gate 2 §34 R-9 anticipated.

**Locked by 4 tests** (`TestR9OrchestratorScopedException`) that *invert* if the
situation changes: if the orchestrator ever wires `EngineeringContextBuilder`,
calls `assemble_context`, or uses `run_workflow_to_completion`, they fail with a
message stating R-9 must be re-evaluated. The exception cannot be silently lost
or silently widened.

## 16. Trigger Design

Deterministic, pure-function triggers only (Gate 3 §16). No clock, no randomness,
no model.

| Trigger | Condition | Rationale |
|---|---|---|
| `iteration_boundary` | `iteration_count >= 4` | Measured: ≥1 iteration guaranteed to compact (§17) |
| `budget_pressure` | `remaining < 2048` | Fires before MSC excludes optional items |
| `candidate_pressure` | `candidates >= 12` | Measured normal assembly is 4 candidates |

`should_compact()` returns `(bool, trigger|None)` and is a pure function —
test-locked for all three triggers and for the disabled case.

## 17. Retention Evidence (Gate 3 §15)

Gate 2 §34 Q-1/Q-2 were UNKNOWN. Measured in
`context-compaction-gate3/measure_growth.py`:

| Measurement | Value |
|---|---|
| Mean raw `LoopIterationRecord` | **311.3** estimated tokens |
| Mean structured projection | **80.7** estimated tokens |
| **Deterministic reduction** | **0.741 (74%)** |
| **G-1 confirmed** | `iteration_items_delivered_today == 0` at 1/2/3/6/9/12 iterations |
| Delivered tokens vs history | flat at 73–96 regardless of history size |

**Derived policy** (deterministic, bounded, configurable, explainable):

| Parameter | Value | Derivation |
|---|---|---|
| `retention_window` | **3** | 3 × 311.3 ≈ 934 tokens ≈ **2.9%** of a 32k window; preserves the active attempt→failure→correction loop |
| `iteration_count_trigger` | **4** | one beyond retention ⇒ at least one iteration always compacted |
| `budget_pressure_floor_tokens` | **2048** | below one full raw iteration (311) ⇒ fires before MSC excludes |
| `candidate_count_trigger` | **12** | ~3× the measured normal candidate count (4) |
| `max_record_tokens` | **8192** | ≈26 raw iterations; a hard bound on a single record |

`policy_version` is part of the fingerprint, so changing any of these yields a
new identity rather than silently reinterpreting old records (Gate 2 §20).

## 18. Performance Measurements

Measured on the real canonical path (7-iteration history, `verify_wiring.py`):

| Metric | Value |
|---|---|
| Source estimated tokens | **1813** |
| Compacted record estimated tokens | **314** |
| **Reduction ratio** | **0.8268 (82.7%)** |
| Compaction duration | sub-millisecond (CPU-only, deterministic) |
| Per-iteration projection reduction | 74% |

**Not claimed:** production performance improvement, latency/throughput effect, or
semantic benefit. Gate 3 §28 forbids it, and no inference-lab or large-scale
experiment was run (Gate 3 §15).

## 19. Failure / Recovery

| Scenario | Behaviour | Test |
|---|---|---|
| Compaction raises | Uncompacted candidates used; work continues | `test_compaction_failure_keeps_uncompacted_candidates` |
| Record invalid | Rejected at validation; uncompacted candidates used | `test_rejected_record_keeps_uncompacted_candidates` |
| Reference unresolvable | Recorded `partial_unresolvable`; **never fabricated** | `test_unresolvable_reference_marks_the_record_incomplete` |
| Resolver raises | Logged; compaction continues without the ref | `test_resolver_exception_does_not_break_compaction` |
| Process crash | Durable only after validation; nothing partial promoted | (structural, §10) |
| Retry | Idempotent — same id, no duplicate items | `test_retry_does_not_duplicate_items` |
| Partial completion | Cannot become authoritative | `test_rejected_record_keeps_uncompacted_candidates` |

Three new error types extend `ContextEngineeringError` (Gate 2 E-28):
`CompactionValidationError`, `CompactionReferenceUnresolvableError`,
`CompactionPolicyVersionError`.

## 20. Versioning

Three independent, minimal versions (Gate 3 §24):

| Field | Meaning | Effect of change |
|---|---|---|
| `compaction_schema_version` | Record layout | Newer is refused (`SUPPORTED_SCHEMA_VERSION = 1`); **ignored and re-derived, never migrated** |
| `policy_version` | Classification/trigger rules | Changes the fingerprint ⇒ new identity and `logical_version` |
| `logical_version` | Monotonic per idempotency key | Lineage via `supersedes` |

Locked by `test_unsupported_schema_version_is_rejected_not_migrated` and
`test_changed_policy_produces_a_new_identity`.

## 21. Observability

`CompactionAssemblyRecord` is content-free and answers every Gate 3 §21 question:
occurred (`compaction_id`), why (`trigger`), scope (`source_scope`),
source/retained/compacted counts, reference count, reduction
(`source_estimated_tokens` → `estimated_tokens`, `reduction_ratio`), policy and
schema version, validation status + reasons, duration, failure category
(`validation_reasons`), loss classification, reconstructability.

Logged at INFO by `_apply_compaction` with counts only.

## 22. Security

| Concern | Handling |
|---|---|
| Task isolation | Scope carried on the record; no cross-task merge path |
| Provenance spoofing | Derived from the gathering source, not caller-supplied |
| Reference substitution | V-3 requires a verifiable `content_hash`; only COMMITTED artifacts resolve |
| Prompt injection | Compacted items are ordinary `ContextItem`s on the same prompt path — no new surface |
| False authority | `proposed_*` / `authority: observed` markers (§12) |
| Approval boundary | Irreplaceable; a `REJECTED` approval can never become absence |
| Privilege escalation | Compaction grants nothing; governance runs at the point of action |
| Content in logs | `test_observability_record_is_content_free` |

## 23. Context Engineering Integration

Ownership unchanged from Gate 2 §21, each verified by test:

| Concern | Owner | Verified by |
|---|---|---|
| Ranking | `select_context` | `test_no_double_budgeting_or_ranking` |
| Budgeting | `ContextWindowBudget` | `test_no_double_budgeting_or_ranking` |
| Prompt assembly | `prompt_assembly` | `test_canonical_prompt_path_is_preserved` |
| Mandatory admission | `select_context` | unchanged files + green suite |

`select_context`, `context_budget`, `context_selection`, `prompt_assembly` and
`context_observability` are **byte-unchanged**.

## 24. Memory / Knowledge Integration

Compaction reads **neither** Memory nor Knowledge as a substrate, per Gate 2 §22
(G-2: Memory is an in-process dict). The authoritative reconstruction substrate
is durable artifacts via `CatalogReferenceResolver`. No restart-safe Memory
persistence is claimed anywhere in the implementation.

## 25. Provider Neutrality

**Structural, not aspirational.** No module in
`autoforge_execution/compaction/` imports or names `ollama`, `llama.cpp`, `mlx`,
`openai`, `gemini`, `anthropic`, `torch` or `requests` — enforced by
`test_no_model_provider_or_runtime_is_imported`, which greps every file in the
package. No worker model was selected; no inference experiment was run.

## 26. Regression Results

Baseline captured before Gate 3; same suites re-run after.

| Suite | Baseline | Post-Gate-3 | Delta |
|---|---|---|---|
| execution | 149 passed, 18 skipped | **200 passed**, 18 skipped | **+51** (new compaction tests) |
| ai_infrastructure | 97 passed | **97 passed** | — |
| composition | 3 failed, 48 passed | **3 failed, 48 passed** | — |
| orchestration | 53 passed, 6 skipped | **53 passed**, 6 skipped | — |
| review | 114 passed | **114 passed** | — |
| workflows | 218 passed | **218 passed** | — |
| kernel | 100 passed | **100 passed** | — |
| runtime | 268 passed | **268 passed** | — |
| artifacts | 14 passed | **14 passed** | — |
| observability | 16 passed | **16 passed** | — |

**Pre-existing failures (unchanged, not hidden):** the same 3 composition tests,
verified by literal `grep '^FAILED' | sort` comparison:

```
test_canonical_context_builder.py::test_canonical_context_builder_invoked_in_execution_path
test_canonical_durable_artifacts.py::test_canonical_durable_artifact_wiring
test_execution_platform_integration.py::test_autoforge_system_execution_wiring
```

All three fail with `ProviderUnavailableError: ... 127.0.0.1:8080 ... Connection
refused` — no local runtime listening. Environmental, pre-existing, identical
before and after.

**Newly introduced failures: 0.**

## 27. End-to-End Wiring Evidence

`context-compaction-gate3/verify_wiring.py` — implementation-level only, **not**
Gate 4 semantic certification.

**Default posture (compaction OFF, CE ON):**
```
context_engineering_enabled: true
compactor_injected: false
compaction_record: true   (i.e. no record produced)
selected_items: 4
```

**Compaction enabled (7-iteration history):**
```
compaction_record_present: true
compaction_id: cmp_fa7957514129bcc5
validation_status: valid
trigger: iteration_boundary
policy_version: 1
compaction_method: deterministic
iteration_items: 4            (iter-1 .. iter-4)
dependency_chain: [[], [ctx_…], [ctx_…], [ctx_…]]
selected_items: 8
prompt_messages_assembled: 1
reduction_ratio: 0.8268
source_estimated_tokens: 1813
estimated_tokens: 314
iterations_reached_prompt: 4
g1_resolved: true
```

The chain is proven connected: context accumulation → trigger → structured
compacted representation → Context Engineering → MSC selection → canonical prompt
assembly. `iterations_reached_prompt: 4` with `g1_resolved: true` is the direct
proof that Gate 1's G-1 gap is closed.

## 28. Rollback

| Question | Answer |
|---|---|
| Can compaction be disabled? | Yes — omit the `compactor` kwarg, or pass `CompactionPolicy(enabled=False)` |
| Byte-identical pre-Gate-3 behaviour? | **Proven** by `test_default_build_is_byte_identical_to_pre_gate3` |
| Already-compacted records? | Retained but ignored; uncompacted path used |
| Can the source be reconstructed? | Yes — a record is derived; sources are untouched |
| Configuration-only? | **Yes** — no schema change, no new `EntityType`, no migration |
| CE rollback still works? | Yes — `test_context_engineering_rollback_still_works` |

## 29. Known Limitations

1. **Storage is implemented but not exercised end-to-end against a live catalog
   in this gate.** `CompactionRecordStore` reuses 18-J unchanged, but no full
   store → reload → reconstruct round-trip was run. Gate 4 should add it.
2. **Reference resolution is optional and unwired at the composition root.**
   `CatalogReferenceResolver` exists, but Gate 3 §30 forbids changing production
   defaults, so reference counts are 0 until Gate 4 wires it.
3. **Compacted history is inline-projected, not yet referenced.** The projection
   is the primary mechanism (74% reduction); reference substitution is available
   but unused until a resolver is injected. Honest consequence: reconstructability
   is 1.0 by the no-refs case.
4. **Semantic benefit is unproven.** 82.7% token reduction is measured; that it
   *helps* a real model solve a real task is Gate 4's job, not this gate's.
5. **Thresholds are measured on synthetic iteration records**, not production
   traces. Documented, deterministic and configurable, but Gate 4 should
   re-measure against real multi-iteration runs.
6. **R-9 remains a scoped exception** by design (§15), not a closed gap.
7. **`budget_pressure` never triggers in production today**, because
   `_apply_compaction` passes `remaining_budget_tokens=None` — the budget is
   resolved *after* candidate construction, per Gate 2 §7. The trigger is
   implemented and tested; wiring it to a real budget would require reordering
   budget resolution, which the design places after selection. Deliberate.

## 30. Deviations From Gate 2

**None required.** Every Gate 2 decision was implementable as specified (§2).

Two *notes* rather than deviations:
- The **storage decision** Gate 2 deliberately left open was resolved as
  recommended: artifact-backed, no new `EntityType` (§10).
- **Retention/trigger values** Gate 2 marked UNKNOWN were measured, not invented
  (§17), which is what Gate 3 §15 required.

## 31. Protected Systems Verification

| System | Status |
|---|---|
| 18-J durable execution / state machine | **Unmodified** (`validation.py`, `artifact_catalog.py`, `models.py`, `execution_store.py` all `git diff` clean) |
| 18-J tests | **Unmodified** |
| Artifact replay / idempotency semantics | **Unmodified** — reused via `CompactionRecordStore` |
| 18-K runtime / packaging / delivery | **Unmodified** |
| `context_selection.py` / `context_budget.py` | **Unmodified** |
| `prompt_assembly.py` / `context_observability.py` | **Unmodified** |
| `context_items.py` | **Unmodified** — compaction reuses `ContextItem` |
| Model Router (`router.py`) | **Unmodified** |
| `composition_root.py` | **Unmodified by Gate 3** (its diff is from the prior Gate 4B task; contains no compaction reference) |
| Inference lab / M6 / M1 / HP | **Unmodified**; no experiments |
| Durable state / event model | **Unmodified** — no new `EntityType` |

**Incident disclosed:** during implementation a mis-targeted edit **created** a
stray file at `packages/execution/src/autoforge_runtime/artifact_catalog.py`
(inside the *execution* package, not runtime). It was detected, inspected, and
removed; the real 18-J `artifact_catalog.py` was confirmed intact at 924 lines
with an empty `git diff`, and the full regression was re-run afterwards with
identical results. **No protected file was ever modified.**

## 32. Gate 4 Readiness Assessment

**Ready for Gate 4 verification.** The deterministic substrate Gate 4 needs exists
and is proven wired. Gate 4 should focus on what Gate 3 explicitly cannot claim:

| Gate 4 must verify | Why Gate 3 could not |
|---|---|
| S-1 future-task correctness | Needs a real local runtime (Gate 3 §28) |
| S-2 history reconstruction | Needs a live store round-trip |
| S-3 iteration understanding | Needs real model inference |
| S-4/S-5 decision + recovery continuity | Needs multi-attempt real runs |
| S-6 absence of unsupported claims | Needs model output to inspect |
| Real-run threshold re-measurement | Synthetic records only (§29.5) |
| Store → reload → reconstruct round-trip | Not run (§29.1) |
| Reference resolution against a live catalog | Resolver unwired (§29.2) |
| Negative control: disabling restores exact behaviour | Implemented, needs full-suite proof |

**Preconditions already met:** deterministic core, single integration point,
13 validation checks, idempotency, rollback, content-free observability,
provider neutrality, and 0 new regressions.

## 33. Final Verdict

> **CONTEXT COMPACTION GATE 3 — COMPLETE**
>
> Implementation: **COMPLETE** (deterministic, provider-neutral, default-off)
> Tests: **51 new tests passing; full regression clean; 0 new failures**
> R-9: **JUSTIFIED SCOPED EXCEPTION** (traced, tested, locked against silent drift)
> Context Engineering: **ON / PROTECTED** (core byte-unchanged)
> Context Compaction: **OFF** (not globally enabled)
> 18-J: **PROTECTED / RE-FROZEN** (reused, never modified)
> 18-K: **PROTECTED**
> Inference Lab: **PROTECTED**
> Commit: **NO** · Push: **NO**

Mandatory Gate 3 outcomes are met: deterministic-first compaction implemented;
integration occurs before `select_context`; no duplicate budget/ranking/prompt
system; structured iteration representation exists and **G-1 is proven resolved**;
information, provenance, dependencies and contradictions are preserved under the
existing authority rules; model inference never becomes a verified fact;
idempotency, durability, failure-safety and rollback are implemented and tested;
R-9 is resolved with evidence; retention thresholds are evidence-derived;
Context Engineering remains globally ON and Context Compaction remains globally
OFF.

**Not claimed, per Gate 3 §28:** semantic correctness, production readiness,
global enablement, or final performance improvement. Those are Gate 4's.

**NEXT CONTROLLED STEP:**
**18-L Context Compaction — Gate 4 Verification**

---

## Appendix — Changed Files

**ADDED**
- `packages/execution/src/autoforge_execution/compaction/__init__.py`
- `packages/execution/src/autoforge_execution/compaction/compaction_schema.py`
- `packages/execution/src/autoforge_execution/compaction/compaction_policy.py`
- `packages/execution/src/autoforge_execution/compaction/compactor.py`
- `packages/execution/src/autoforge_execution/compaction/compaction_validation.py`
- `packages/execution/src/autoforge_execution/compaction/storage.py`
- `packages/execution/tests/test_context_compaction.py` (51 tests)

**MODIFIED**
- `packages/execution/src/autoforge_execution/context_builder.py` (additive only)

**DOCUMENTATION / EVIDENCE**
- `context-compaction-gate3/CONTEXT_COMPACTION_IMPLEMENTATION_REPORT.md`
- `context-compaction-gate3/measure_growth.py` + `growth_measurements.json`
- `context-compaction-gate3/verify_wiring.py` + `wiring_evidence.json`
- `context-compaction-gate3/smoke_compaction.py`
- `context-compaction-gate3/diag_two_failures.py`
