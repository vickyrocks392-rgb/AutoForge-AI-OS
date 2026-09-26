# 18-L — CONTEXT ENGINEERING — GATE 3 IMPLEMENTATION REPORT

**Gate:** 3 of 4 (Audit → Design → Implementation → Certification/verification)
**Design implemented:** `context-engineering-gate2/CONTEXT_ENGINEERING_DESIGN_REPORT.md`
**Governing contract:** `docs/adr/ADR-003-context-engineering-contract.md`
**Status:** IMPLEMENTED AND VERIFIED — not committed, not pushed

> Gate 3 is an **implementation** gate, not a certification gate. Semantic A/B
> validation is deliberately **not** claimed here; see Remaining Gate 4 requirements.

---

## 1. Files Changed

### New (6 source modules)

| File | Purpose | Gate 2 § |
|---|---|---|
| `execution/…/context_items.py` | Canonical `ContextItem`, categories, provenance, cacheability, deterministic ids, ranking | §2.1, §2.5, §2.7 |
| `execution/…/context_budget.py` | `ContextWindowBudget` (request-scoped, model-aware) | §3.1 |
| `execution/…/token_estimator.py` | `TokenEstimator` Protocol + conservative default heuristic | §3.4 |
| `execution/…/context_selection.py` | MSC policy: bounded expansion, rank, dedup, budget enforcement | §2.3, §2.4, §2.6 |
| `execution/…/context_observability.py` | Content-free `ContextAssemblyRecord` | §8 |
| `execution/…/prompt_assembly.py` | The single canonical provider-neutral prompt constructor | §4 |

### Modified (4 files)

| File | Change | Gate 2 § |
|---|---|---|
| `execution/…/errors.py` | Added 7-member `ContextEngineeringError` family | §9 |
| `execution/…/context.py` | Added 3 defaulted CE fields + `build_canonical_messages()` | §12.1 |
| `execution/…/context_builder.py` | Became the canonical engine behind a default-OFF flag | §1.2, §11 |
| `knowledge_platform/…/context_assembler.py` | Two `Any` deps typed as `Protocol`s; **behaviour unchanged** | §6.2 |

### New tests (4 files, 65 tests)

`test_context_selection.py` (20) · `test_context_budget.py` (19) ·
`test_prompt_assembly.py` (12) · `test_context_rollout.py` (14)

---

## 2. Architecture Implemented

```
EngineeringContextBuilder (canonical engine, flag-gated)
  ├─ _build_candidates   -> ContextItem (attributable; mandatory whitelist)
  ├─ _resolve_budget     -> ContextWindowBudget (two-pass window resolution)
  ├─ select_context      -> MSC policy (expand -> rank -> dedup -> budget)
  ├─ build_record        -> content-free observability
  └─ ExecutionContext.build_canonical_messages() -> prompt_assembly.build_messages
                                                    |
                              existing BaseProviderAdapter.normalize_messages
```

**Specializations preserved, never deleted:** `ContextAssembler` (typed, behaviour
unchanged) and `GroundedContextBuilder` (untouched). One canonical engine, two scoped
specializations — exactly the Gate 2 §6 architecture.

### Two real bugs found and fixed during implementation

Both were caught by tests I wrote, and both were silent correctness risks:

1. **Optional candidates were dropped entirely.** The admission pool was built from
   mandatory roots + expanded dependencies only, so every optional/evidence item was
   silently discarded — defeating Minimum Sufficient Context while still looking
   correct. Fixed by including the remaining candidate pool.
2. **Bound-truncated dependencies reported as unresolvable.** When the depth/item
   bound stopped expansion, an in-pool dependency was later flagged
   `unresolved_dependency`, raising `UnresolvableDependencyError` — a *false*
   correctness failure. Fixed by distinguishing "deferred by a bound" from
   "genuinely absent".

A third issue (`normalize_content` leaving one blank line in a run) was fixed to match
the Gate 2 §2.6 contract exactly.

---

## 3. Tests Executed and Results

| Suite | Baseline (pre-change) | After Gate 3 | Result |
|---|---|---|---|
| `execution` (full) | 71 passed, 8 skipped | **136 passed, 8 skipped** | +65, **0 regressions** |
| New CE tests | — | **65 passed** | all green |
| `ai_infrastructure` (router/adapters) | 97 passed | **97 passed** | unchanged |
| `composition` canonical builder test | 1 failed (pre-existing) | 1 failed (identical) | see below |

### Pre-existing failure — not caused by this work

`composition/tests/test_canonical_context_builder.py` fails on `main` **before** my
changes with `httpx.ConnectError: All connection attempts failed`: it needs a live
Ollama provider, unavailable here. I verified the exact wiring it guards still holds:

```
context_builder present:      True
is EngineeringContextBuilder: True
attached to dispatcher:       True
flag default OFF:             True
```

The failure mode is identical to baseline, so it is an environment limitation, not a
regression.


### The 12 required test areas

| Requirement | Test | Status |
|---|---|---|
| Relevant selected | `test_relevant_context_is_selected` | pass |
| Irrelevant excluded | `test_irrelevant_context_excluded_by_relevance_floor` | pass |
| Mandatory preserved | `test_mandatory_context_survives_when_optional_is_trimmed` | pass |
| Dependency expansion | `test_dependency_of_mandatory_item_is_expanded` | pass |
| Dependency bound | `test_dependency_depth_is_bounded`, `…item_count_is_bounded`, `…cycles_terminate` | pass |
| Budget enforcement | `test_selection_never_exceeds_budget` | pass |
| Oversized mandatory fails | `test_mandatory_overflow_raises_and_does_not_truncate` | pass |
| Deduplication | `test_duplicate_content_is_excluded_with_auditable_reason` | pass |
| Provenance | `test_prompt_is_attributable`, `test_selected_items_carry_provenance` | pass |
| Deterministic prompt | `test_identical_inputs_produce_identical_messages` (10 repeats) | pass |
| Cache metadata | `test_no_provider_cache_directive_is_emitted` | pass |
| Provider neutrality | `test_core_modules_contain_no_provider_specific_identifiers` | pass |
| Rollout flag | `test_flag_defaults_off`, `…_off_preserves_previous_behaviour` | pass |
| Model awareness | `test_smaller_model_window_causes_explicit_failure` | pass |

---

## 4. Rollback Procedure

One constructor argument. No data migration, no event-schema change, no serialized
artifact change.

```python
EngineeringContextBuilder(enable_context_engineering=False)   # already the default
```

`assemble_context` keeps its exact signature (new parameters are keyword-only with
defaults), the dispatcher call site at `dispatcher.py:141` is unchanged, and
`ExecutionContext`'s new fields all have defaults, so the ADR-003 output contract is
valid in both states. Steps 1 and 4 of the Gate 2 plan (new modules; assembler typing)
are pure additions, independently revertible.

---

## 5. Known Limitations

1. **Token estimation is a heuristic, not a tokenizer.** No tokenizer exists in the
   repo and adding one is a new dependency. A 10% conservative margin plus the
   retained 16000-char backstop guard against under-counting. The `TokenEstimator`
   Protocol lets a real tokenizer be injected without touching selection logic.
2. **Exact-match deduplication only.** Near-duplicate detection needs embedding
   infrastructure that does not exist here and is a precision risk on a
   correctness-critical path. Documented, not silently omitted.
3. **No `ContextAssembler` instantiation possible.** It remains abstract (six
   unimplemented interface methods) — **pre-existing at HEAD**, verified with
   `git show`. My change only typed its dependencies. Fixing it is knowledge-platform
   work outside this scope.
4. **Candidates derive from the four sources the existing builder already gathers.**
   Wiring Knowledge/Memory platform ports as candidate providers is the next increment.
5. **Semantic correctness is unmeasured.** See section 7.

---

## 6. Deviations from Gate 2

| Design | Deviation | Reason |
|---|---|---|
| 12.1 "type the two `Any` deps" | Also gave all three params a `None` default | The class is abstract and never instantiated, so no caller exists to break; this makes the protocols usable without changing behaviour |
| 3.1 sibling budget | Named `ContextWindowBudget`, module `context_budget.py` in `execution` | Identical to design; named to avoid confusion with the modernization `ContextBudget` of the same filename |
| 12.1 test list | Four test files instead of three | Split selection/budget/prompt/rollout for clarity; same coverage |

No architectural deviation. No new field, error type, or concept beyond the design.

---

## 7. Remaining Gate 4 Verification Requirements

**Not** satisfied by this gate, and the substance of Gate 4:

1. **Semantic A/B validation** (12.4): full-context vs minimum-sufficient-context at
   **identical model, seed, and temperature**. Measure semantic correctness, strict
   correctness, constraint adherence, evidence grounding, dependency preservation,
   verification correctness, and omission impact.
2. **Prompt-processing cost measurement**: confirm reduced prefill without
   correctness loss. Throughput alone is never sufficient.
3. **Enable the flag in composition root** and validate on the real path with a live
   provider (that test cannot run in this environment).
4. **The ~40% HP 0.5B correctness figure remains an unresolved model limitation** —
   neither improved nor blamed by this work, and per the mandate it must not be used
   as a Context Engineering success signal.

**Gate 4 will be PARTIAL at best until (1) and (2) produce evidence.**

---

## 8. Protected Boundaries Confirmed

Verified by `git status` and mtime inspection:

- **Inference lab** (`gate-2.3-reconciliation/`, `gate-2.3-power-validation/`) — untouched
- **M6 authority model** — untouched; no M6-specific constants in production code
- **18-J / 18-K** — untouched
- **`adapters/base.py`, `router.py`** — untouched (97 tests still pass)
- **`modernization/context_budget.py`** — untouched (empty diff), as Gate 2 3.1 required
- **`power_engines/.../grounding.py`** — untouched
- **Pre-existing `modernization/**` + `security/pyproject.toml` changes** (mtimes
  Sep 22–23) — left exactly as found, not cleaned up
- **No Context Compaction, no AutoForge Brain, no deliberation** — asserted by
  `test_no_compaction_or_brain_concepts_introduced`
- **Feature flag defaults OFF** — asserted by two tests

---

## 9. Gate 3 STOP

Implementation complete and verified. **STOPPING.**

Not committed. Not pushed. No Gate 4 work, no Context Compaction, no AutoForge Brain,
no roadmap change. Awaiting explicit approval.
