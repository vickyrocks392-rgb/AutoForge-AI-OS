# Context Engineering — Gate 4B Global Production / Default Enablement

**Workstream:** 18-L — Context Engineering Workstream
**Gate:** 4B — Global Production / Default Enablement
**Status:** COMPLETE — Context Engineering is globally enabled
**Date:** 2026-09-26
**Not committed. Not pushed.** (per §16 Absolute Stop)

---

## 1. Objective

Context Engineering passed Gate 4 implementation, semantic, runtime,
provider-neutrality and acceptance verification, but was deliberately left
**off by default**: `enable_context_engineering = False`.

Gate 4B exists solely to make Context Engineering the **canonical default
behaviour of AutoForge production execution**, to remove the accidental legacy
bypasses that would otherwise have made that default cosmetic, to re-run the
regression suites with CE actually ON, and to prove the canonical path end to
end at runtime.

The target flow:

```text
Canonical AutoForge execution
        ↓
Context Engineering
        ↓
MSC selection / dependency expansion / budgeting
        ↓
Canonical prompt assembly
        ↓
Model Router / Allocation
        ↓
Provider Adapter
        ↓
llama.cpp / MLX / other supported runtime
```

---

## 2. Pre-change Configuration (Audit Map)

Repository-wide audit performed before any modification. There is **one** flag
declaration, not many — but there were **three** ways to bypass it downstream.

| # | Location | Role | Pre-change state |
|---|---|---|---|
| 1 | `execution/context_builder.py:71` | **Sole flag declaration** | `enable_context_engineering: bool = False` |
| 2 | `composition/composition_root.py:275` | Composition root | Built the builder **without** passing the flag → silently inherited `False` |
| 3 | `execution/dispatcher.py:141` | Canonical dispatch (base) | Called builder when injected |
| 4 | `workforce/dispatch.py:142` | Canonical dispatch (workforce) | Called builder when injected |
| 5 | `execution/dispatcher.py:150` | **BYPASS A** | `else:` → `ExecutionContext.from_task_definition()` |
| 6 | `workforce/dispatch.py:151` | **BYPASS B** | `else:` → `ExecutionContext.from_task_definition()` |
| 7 | `execution/ai_adapter.py` (4 methods) | **BYPASS C (critical)** | Hand-built f-string prompts via `format_reasoning_prompt()`; `build_canonical_messages()` **never called in production** |
| 8 | `composition/execution_wiring.py:191` | Dispatcher wiring | `context_builder=None` default → no builder, therefore no CE |
| 9 | Environment-variable override | — | **None exists.** No `AUTOFORGE_*_CONTEXT*` var was added; none was needed. |
| 10 | Alternate engine construction | `build_execution_engine()` | Accepts an injected builder; composition root is the only canonical caller |
| 11 | Test fixtures | `test_context_rollout.py` | Asserted default **OFF** |

### The decisive finding

`build_canonical_messages()` — the single canonical prompt constructor verified
at Gate 4 — had **zero production call sites**. Every model-bound prompt in
`ai_adapter.py` was assembled by hand. Flipping the boolean alone would have
produced a system that *computed* budgeted, selected, attributed context and
then **threw it away**, sending a legacy f-string prompt to the model instead.
Gate 4B therefore had to converge the adapter, not just the flag.

---

## 3. Configuration Architecture

Single mechanism, no duplication:

- The flag lives in exactly one place: the `EngineeringContextBuilder`
  constructor keyword argument.
- `build_autoforge_system(config=...)` is the **canonical composition-root
  source of truth** and reads `config["enable_context_engineering"]`,
  defaulting to `True`.
- The constructor default was also flipped to `True`, so a directly constructed
  builder behaves like the production one (no split-brain defaults).
- No second mechanism (env var, global singleton, per-call-site hard-coding)
  was introduced.

---

## 4. Global Enablement Change

### Files changed

| File | Change |
|---|---|
| `packages/execution/src/autoforge_execution/context_builder.py` | Constructor default `False` → **`True`**; docstring updated |
| `packages/composition/src/autoforge_composition/composition_root.py` | Passes `enable_context_engineering` explicitly from `config` (default `True`); wires router-backed allocator; builder moved after AI Infrastructure |
| `packages/composition/src/autoforge_composition/context_allocation.py` | **NEW** — `RouterModelAllocationPort` |
| `packages/execution/src/autoforge_execution/ai_adapter.py` | **Bypass C removed** — all four AI methods use the canonical constructor |
| `packages/execution/src/autoforge_execution/dispatcher.py` | **Bypass A removed** |
| `packages/workforce/src/autoforge_workforce/dispatch.py` | **Bypass B removed** |

### The exact configuration change

```python
# packages/execution/src/autoforge_execution/context_builder.py
enable_context_engineering: bool = True,   # was False
```

```python
# packages/composition/src/autoforge_composition/composition_root.py
context_builder = EngineeringContextBuilder(
    runtime=runtime,
    memory_engine=kernel_memory_engine,
    knowledge_engine=kernel_knowledge_engine,
    enable_context_engineering=bool(
        (config or {}).get("enable_context_engineering", True)
    ),
    model_allocator=RouterModelAllocationPort(ai_infra.router),
)
```

### Model-aware budgeting

Gate 4 §7 defined a two-pass `ModelAllocationPort` seam but left it unwired, so
`BudgetSource.MODEL_METADATA` was dead in production and every operation fell
back to the conservative 8192-token default. `RouterModelAllocationPort` closes
that seam over the **existing** `ModelRouterService` — it reports only the
allocated model's declared window, never executes, never selects a runtime, and
never raises (a budget hint must not fail an engineering operation). Runtime
evidence confirms `budget_source: "model_metadata"` with a 32768-token window.

---

## 5. Canonical Execution-Path Audit

| Path | Mechanism | Reaches CE? |
|---|---|---|
| Normal engineering execution | `ExecutionEngine` → `WorkforceDispatcher.dispatch_task` → `assemble_context` | **Yes** (verified at runtime) |
| Orchestration-driven execution | `DefaultOrchestrationEngine` → `KernelExecutionEngineAdapter` → same engine | **Yes** (same singleton builder) |
| API-triggered execution | `apps/api/.../build_engine.py` → `build_autoforge_system` | **Yes** (delegates to composition root; no separate context construction in `apps/`) |
| Composition-root-created engines | `build_execution_engine(context_builder=context_builder)` | **Yes** — dispatcher holds the *same* object (identity-asserted) |
| Model allocation path | `_build_routing_request` → `ModelRouterService` / `CapacityAwareRouter` | **Yes** — and now also feeds Pass-1 budget allocation |
| Provider execution path | `ExecutorRegistry` → `LocalRuntimeProviderAdapter` → `normalize_messages` | **Yes** — consumes the canonical `messages` list unchanged |
| Workforce dispatch | `WorkforceDispatcher.dispatch_task` | **Yes** (bypass B removed) |
| Dispatcher with no injected builder | `WorkerDispatcher.dispatch_task` `else` branch | **Yes** (bypass A removed) |

### Scoped specializations intentionally left outside CE

These are **not** bypasses; each is a deliberate specialization the Gate 2 design
(§6) classified as such. None was forced into the canonical engineering path for
superficial uniformity:

| Component | Why it remains separate |
|---|---|
| `ContextAssembler` (knowledge_platform) | ADR-003 §Consequences designates it the knowledge-scoped slice the Context Engine **composes**, not replaces. Its citations are mapped into `ContextProvenance` on the way in. |
| `GroundedContextBuilder` (power_engines RAG) | Serves customer-facing RAG grounding and answer attribution (`CitationReference`, numeric-contradiction verification) — a different concern from engineering task context. |
| `TransformationContextAssembler` (modernization) | Deterministic migration-transformation prompt assembly; modernization is protected and out of scope. |
| `StandaloneAgentRuntime.assemble_context` | Customer-agent session memory (bounded history) for a delivered product, not engineering task context. |

---

## 6. Legacy Bypass Audit — Found and Fixed

### BYPASS C (critical, fixed): direct prompt construction in `ai_adapter.py`

| Method | Pre-change prompt source |
|---|---|
| `generate_plan` | f-string + `format_reasoning_prompt(1)` |
| `generate_implementation` | f-string with `Context: {context.format_reasoning_prompt(1)}` |
| `diagnose_failure` | f-string |
| `generate_repair` | f-string with `diagnosis.model_dump_json()` |

**Fix.** Added `_canonical_payload()`, which calls
`ExecutionContext.build_canonical_messages()` and emits the
`{"role", "content"}` message list that `BaseProviderAdapter.normalize_messages`
already consumes. No provider adapter change was required and no
provider-specific formatting was introduced.

Each method now supplies only its *operation-specific directive* (e.g. "Return
JSON in this shape") as a final user turn, while the **context body comes
exclusively from the canonical, budgeted, attributed selection**. Each also
records content-free observability via `_prompt_assembly_observability()`.

This is convergence onto the Gate-4-certified implementation, not a redesign:
`prompt_assembly` is untouched and remains the single prompt constructor.

### BYPASS A and BYPASS B (fixed): dispatcher fallback

`else: context = ExecutionContext.from_task_definition(...)` meant that merely
failing to inject a dependency silently disabled Context Engineering. Both
branches now construct the canonical engine instead. Lazy imports keep the
existing module import graph intact.

### Retained, by design (not bypasses)

- `ExecutionContext.format_reasoning_prompt()` still exists. It is the explicit
  CE-OFF/rollback body and remains covered by contract tests. When CE is ON the
  canonical messages take precedence, since `normalize_messages` checks
  `"messages"` first.
- Per-operation `extras` keys (`task`, `plan`, `evidence`, `diagnosis`) are
  retained for rollback compatibility; they are ignored whenever canonical
  `messages` are present.

---

## 7. Test Configuration Changes

Tests were updated to reflect the new default — **not** to paper over failures.
The pre-existing content-free observability assertions (Gate 3 §5/§8) were left
intact.

| Test | Before | After |
|---|---|---|
| `test_flag_defaults_off` | asserted `False` | replaced by `test_flag_defaults_on` asserting `True` |
| `test_default_construction_does_not_activate_the_engine` | asserted default `False` | `test_default_construction_activates_the_engine` asserting `True` |
| `test_flag_off_preserves_previous_behaviour` | used default construction | `test_explicit_off_preserves_previous_behaviour` — now explicitly OFF, still asserting the exact pre-Gate-3 contract |
| — | — | new: `test_default_construction_populates_selection_and_record` |
| — | — | new: `test_explicit_off_remains_available_as_rollback` |
| — | — | new: `test_dispatch_without_injected_builder_still_runs_context_engineering` (locks bypass A/B) |
| — | — | new: `test_ai_adapter_uses_canonical_prompt_when_engine_is_on` (locks bypass C) |
| — | — | new: `test_ai_adapter_falls_back_to_legacy_only_when_engine_is_off` |

New file `packages/composition/tests/test_context_engineering_global.py` (6
tests) pins the production posture at the composition root, including the
supported rollback lever `config={"enable_context_engineering": False}`.

---

## 8. Regression Results with CE ON

Baseline captured **before** modification, then re-run after. Per-package runs
are required because identically-named `conftest.py` files collide in a single
pytest invocation.

| Package | Baseline (CE OFF) | After (CE ON) | Delta |
|---|---|---|---|
| execution | 144 passed, 18 skipped | **149 passed**, 18 skipped | +5 (new tests) |
| ai_infrastructure | 97 passed | **97 passed** | — |
| composition | 3 failed, 42 passed | **3 failed, 48 passed** | +6 (new tests) |
| orchestration | 53 passed, 6 skipped | **53 passed**, 6 skipped | — |
| review | 114 passed | **114 passed** | — |
| workflows | 218 passed | **218 passed** | — |
| kernel | 100 passed | **100 passed** | — |
| runtime | 248 passed | **248 passed** | — |
| workforce | 35 passed, 2 skipped | **35 passed**, 2 skipped | — |

### Pre-existing failures (identical before and after — zero new failures)

| Test | Root cause | Newly exposed? |
|---|---|---|
| `test_canonical_context_builder.py::test_canonical_context_builder_invoked_in_execution_path` | `ProviderUnavailableError` — no local runtime on `127.0.0.1:8080` | No |
| `test_canonical_durable_artifacts.py::test_canonical_durable_artifact_wiring` | Same — requires a live local runtime | No |
| `test_execution_platform_integration.py::test_autoforge_system_execution_wiring` | Same | No |

All three fail identically at baseline and after, because they perform **real**
model execution against the canonical local runtime, which is not running here.
This is exactly the condition the Gate 4B E2E harness (§9) addresses by standing
up a real local runtime.

Failure sets were compared literally (`grep '^FAILED' | sort`) and are identical.
**No test was modified to make the new default pass.**

### Pre-existing collection error (unrelated, pre-dating this gate)

`packages/workforce/tests/test_real_runtime_integration.py` fails to import
`OllamaProviderAdapter` from `autoforge_ai_infrastructure.adapters`. This is a
**stale test left behind by the Gate 4 Ollama cleanup** (the export was removed
in the uncommitted Gate 4 working-tree changes; this test was not updated). It is
not caused by Gate 4B, was excluded from the workforce run, and is recorded here
rather than silently dropped.

---

## 9. End-to-End Runtime Evidence

`context-engineering-gate4b/e2e_ce_global.py` runs a **default-configuration**
system with a real Model Router, the real `LocalRuntimeProviderAdapter`, and a
real local-runtime HTTP server on a real socket speaking the OpenAI-compatible
`/v1/chat/completions` dialect that `llama-server` and MLX expose. Only token
generation is stubbed; the transport is genuine.

```
context_engineering_enabled: true
model_allocator_wired: RouterModelAllocationPort
dispatcher_shares_canonical_builder: true
provider_adapter: LocalRuntimeProviderAdapter
local_runtime_reachable: true
direct_provider_round_trip_ok: true
workflow_status: completed

prompt_observability:
  context_engineering_enabled: true
  prompt_assembly_path: canonical_context_engineering
  selected_context_count: 2
  budget_source: model_metadata
  context_window_tokens: 32768

model_executions: 2
last_allocation: {model_id: qwen2.5-coder-7b, provider_id: local-m1,
                  attempts: 1, failovers: 0, latency_ms: 0.78}

local_runtime_chat_calls: 3
runtime_received_turns: 3
runtime_received_roles: [system, user, user]
runtime_saw_canonical_sections: ["# Task:", "## Project Context", "## Task"]
canonical_context_reached_runtime: true
artifact_root_exists: true
durable_artifacts_registered: 3
```

Chain proven: request → orchestration → Context Engineering → canonical prompt
assembly → model allocation → provider adapter → local runtime → execution →
3 durable artifacts.

`runtime_saw_canonical_sections` is captured **server-side**, so it is direct
proof that the canonical CE sections crossed the provider boundary, not merely
that the adapter claimed to build them.

### Observability safety

All emitted observability is content-free: counts, budget provenance, window
size, category breakdown, context ids, and the assembly path. No prompt text is
logged to prove the path. `ContextAssemblyRecord` remains structurally
content-free — it has no field capable of holding a payload.

---

## 10. Ollama Dependency Verification

| Invariant | Result |
|---|---|
| No Ollama production dependency | **Held.** `bind_optional_ollama: bool = False` is the default in both `bind_default_provider_adapters` and `build_ai_infrastructure`. |
| No default Ollama binding | **Held.** `build_ai_infrastructure(bind_adapters=True).executor_registry.bound_providers()` → `['local-hp', 'local-m1', 'openai-compatible']`. No Ollama provider bound. |
| No `11434` production default | **Held.** Canonical local runtime default is `http://127.0.0.1:8080/v1`. `11434` survives only inside the opt-in `bind_optional_ollama_adapter` and the standalone `adapters/ollama.py`, neither on the canonical path. |
| No root export dependency | **Held.** `OllamaProviderAdapter` is absent from `adapters/__init__.py` and the package `__init__.py` exports. |
| Local runtime remains `LocalRuntimeProviderAdapter` | **Held.** Confirmed at runtime. |
| Local runtime based on existing OpenAI-compatible architecture | **Held.** It subclasses `OpenAICompatibleProviderAdapter`; only endpoint defaults and model-tag mapping are supplied. |
| llama.cpp / MLX remain runtime implementations behind the provider boundary | **Held.** Neither is imported by any provider-neutral layer; the router routes by `provider_id`. |
| CE imports zero inference runtimes | **Held.** No import of `llama`, `mlx`, `torch`, `transformers`, or `ollama` in any CE module or in `context_allocation.py` (verified by grep). |

---

## 11. Rollback Verification

`context-engineering-gate4b/verify_rollback.py` exercises all three postures
through the real composition root.

| Posture | Flag | Record | Selected | Messages | Files discovered |
|---|---|---|---|---|---|
| **Default** (`config=None`) | `true` | present | 2 | 1 | 1 |
| **Explicit ON** (`config={"enable_context_engineering": True}`) | `true` | present | 2 | 1 | 1 |
| **Explicit OFF** (rollback) | `false` | absent | 0 | 0 | 1 |

Rollback remains a **single argument / single config key**. It is now the
*rollback / compatibility mode*, not the normal production mode. The legacy
`format_reasoning_prompt()` payload keys are identical in all three postures
(`description, input_data, iteration, known_files, project_files, task_id,
task_name, task_type`), confirming the pre-Gate-3 contract is preserved exactly.
No data migration, state change, or redeploy is required.

---

## 12. 18-J Issue — Triage Only

**Reproduced with CE globally enabled. Not fixed. Not suppressed.**

`context-engineering-gate4b/triage_18j_defect.py`:

```json
{
  "normal_lifecycle_committed": true,
  "raises_invalid_transition": true,
  "reproduction": {
    "exception_type": "InvalidTransitionError",
    "message": "Invalid artifact transition committed → staging: Invalid artifact
                transition: <DurableArtifactStatus.COMMITTED: 'committed'>
                -> <DurableArtifactStatus.STAGING: 'staging'>",
    "details": {"artifact_id": "5cf4e0d7-...",
                "current_status": "committed", "target_status": "staging"}
  },
  "classification": "pre-existing 18-J defect (durable artifact lifecycle)",
  "fixed_in_gate4b": false,
  "validation_weakened": false
}
```

**Reproduction path:** `register_artifact` (CREATED) → `begin_staging` (STAGING)
→ `commit_artifact` (COMMITTED) → `begin_staging` again. The second
`begin_staging` is rejected.

**Root cause:** `packages/runtime/src/autoforge_runtime/validation.py:665`
declares `COMMITTED: {RETIRED}` with no path back to `STAGING`, so a retry or
re-materialisation of an already-committed artifact cannot re-enter staging.

**Classification: pre-existing 18-J defect.** Unrelated to Context Engineering —
CE never touches artifact lifecycle state — and it reproduces identically with CE
on and off. It is **not** a newly introduced defect and **not** an integration
exposure.

**Impact on eventual full 18-L certification:** any 18-L scenario that
re-materialises a committed artifact (retry, re-delivery, version bump) will fail
with `InvalidTransitionError` rather than degrading. This is a known blocker for
full 18-L certification and should be scheduled as a dedicated 18-J work item.
Per §11 and §16, **18-J was not modified**: `validation.py` and
`artifact_catalog.py` are byte-unchanged, the error is not suppressed, and
transition validation was not weakened.

---

## 13. Protected-System Verification

| System | Status |
|---|---|
| M6 authority model | Unmodified |
| M1 / HP inference configuration | Unmodified |
| Inference lab | Unmodified |
| Gate 2.3 evidence | Unmodified |
| 61.923 tok/s qualification | Unmodified |
| llama.cpp inference-server configuration | Unmodified |
| Worker-model experiments | Unmodified — none started |
| 18-J implementation | Unmodified — `validation.py`, `artifact_catalog.py` byte-unchanged |
| 18-K implementation | Unmodified |
| `modernization/context_budget.py` | Unmodified (verified) |
| `grounding.py` (power_engines) | Unmodified |
| Context Compaction | Not started |
| AutoForge Brain | Not started |

Verified with `git diff --quiet HEAD` against each protected path.

Also not done, per §16: no commit, no push.

---

## 14. Acceptance Matrix

| # | Criterion | Result | Evidence |
|---|---|---|---|
| A | Default production execution has CE = ON | **PASS** | Constructor default `True`; composition root passes `True`; `test_flag_defaults_on`, `test_production_default_has_context_engineering_enabled` |
| B | Normal engineering execution passes through canonical CE | **PASS** | `test_canonical_flow_reaches_the_context_builder`; E2E `workflow_status: completed` with `prompt_assembly_path: canonical_context_engineering` |
| C | No canonical engineering path silently bypasses CE | **PASS** | Bypasses A, B, C identified and fixed; each locked by a regression test |
| D | Relevant existing tests pass with CE ON | **PASS** | 1,014 passed / 26 skipped; 3 failures identical to baseline; 0 new failures |
| E | At least one representative E2E workflow completes with CE ON | **PASS** | Full E2E with real provider round trip, 3 durable artifacts |
| F | CE remains runtime/provider neutral | **PASS** | Zero runtime imports in CE modules; allocator reports constraints only; canonical `messages` reuse the existing provider contract |
| G | Ollama is not restored as a production/default dependency | **PASS** | `bound_providers()` contains no Ollama; `bind_optional_ollama=False`; default URL `:8080` |
| H | Explicit CE OFF remains available for rollback/testing | **PASS** | `verify_rollback.py` — single config key; exact pre-Gate-3 contract preserved |
| I | 18-J issue documented but not modified | **PASS** | Reproduced, classified pre-existing, `fixed_in_gate4b: false`, files byte-unchanged |
| J | No protected inference/architecture systems modified | **PASS** | `git diff --quiet` verification |

---

## 15. Remaining Limitations

1. **Three pre-existing composition tests still fail.** They require a live local
   runtime on `127.0.0.1:8080`. Unchanged by this gate and failing identically at
   baseline. They will pass wherever a real runtime is listening.
2. **One stale test left by the Gate 4 Ollama cleanup**
   (`workforce/tests/test_real_runtime_integration.py`) still imports the removed
   `OllamaProviderAdapter` export. Pre-existing and out of scope; it should be
   updated or removed in a follow-up.
3. **The E2E local runtime is transport-real but generation-stubbed.** The HTTP
   round trip, message normalization and provider adapter are genuine; token
   generation is not real model inference. Full-fidelity inference evidence
   belongs to the later worker-inference workstream.
4. **`RouterModelAllocationPort` uses a single routing request.** It does not
   attempt multi-candidate window negotiation; if no model satisfies the Pass-1
   declared window it returns `None` and the builder applies its labelled
   conservative default rather than failing the operation.
5. **18-J `committed → staging` remains open**, blocking scenarios that
   re-materialise a committed artifact.
6. **Only the engineering execution path is canonicalized.** The scoped RAG,
   knowledge and customer-agent assemblers remain separate by design (§5).
7. **Gate 4 scripts under `context-engineering-gate4/` were not re-run.** They
   exercise the feature in isolation; Gate 4B's purpose is the production
   default, covered by the new harnesses and suites.

---

## 16. Final Verdict

All ten acceptance criteria pass.

> **Context Engineering is COMPLETE and GLOBALLY ENABLED in the AutoForge
> production/default configuration.**

The canonical AutoForge execution path now runs:

```text
Canonical AutoForge execution
        ↓
Context Engineering  (ON by default)
        ↓
MSC selection / dependency expansion / budgeting
        ↓
Canonical prompt assembly
        ↓
Model Router / Allocation
        ↓
Provider Adapter
        ↓
llama.cpp / MLX / other supported runtime
```

Context Engineering is no longer opt-in, feature-flagged, or available-only.
It is the default behaviour of the system.

**GLOBAL DEFAULT = ON**

Rollback remains available as a single constructor argument or a single
composition-root config key. Ollama remains removed as a production dependency.
Context Engineering remains runtime- and provider-neutral. The 18-J transition
defect is documented, reproduced, and left untouched.

Per §16, this work stops here: no Context Compaction, no worker-model
experiments, no worker-fleet finalization, no AutoForge Brain, no full 18-L
certification, no 18-J or 18-K modification, no commit, no push.

**Next workstream: Context Compaction.**

---

## Appendix — Artifacts Produced

| File | Purpose |
|---|---|
| `CONTEXT_ENGINEERING_GLOBAL_ENABLEMENT_REPORT.md` | This report |
| `e2e_ce_global.py` | End-to-end runtime verification harness |
| `verify_rollback.py` | Three-posture (default / ON / OFF) verification |
| `triage_18j_defect.py` | 18-J reproduction and triage (no fix) |
| `e2e_runtime_evidence.json` | Captured E2E evidence |
| `rollback_evidence.json` | Captured posture evidence |
| `triage_18j.json` | Captured 18-J triage evidence |
