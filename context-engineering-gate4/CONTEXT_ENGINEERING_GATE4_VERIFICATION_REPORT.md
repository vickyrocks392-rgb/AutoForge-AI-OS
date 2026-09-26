# 18-L — CONTEXT ENGINEERING — GATE 4 VERIFICATION REPORT

**Gate:** 4 of 4 (Audit → Design → Implementation → Verification/Certification)
**Design implemented:** `context-engineering-gate2/CONTEXT_ENGINEERING_DESIGN_REPORT.md`
**Implementation:** `context-engineering-gate3/GATE_3_IMPLEMENTATION_REPORT.md`
**Governing contract:** `docs/adr/ADR-003-context-engineering-contract.md`
**Status:** VERIFIED — not committed, not pushed
**Final verdict:** **PASS** (with documented limitations and one out-of-scope
pre-existing defect newly made reachable — see §18/§19)

> Evidence is labelled by **kind**, and the kinds are never mixed:
> **[DET]** deterministic test evidence · **[BENCH]** runtime benchmark evidence ·
> **[SEM]** semantic/model-mediated evidence · **[ARCH]** architectural judgement ·
> **[LIMIT]** unresolved limitation.

---

## 1. Executive Summary

Gate 4 re-audited the Gate 3 implementation against source (not against the Gate 3
report), fixed five real defects, removed the Ollama production/runtime dependency
from the canonical AutoForge path, and produced the semantic A/B and
prompt-processing cost evidence Gate 3 explicitly deferred.

| Claim | Result | Kind |
|---|---|---|
| Context Engineering deterministic correctness | 12/12 mandated runtime checks; 73 CE tests pass | [DET] |
| MSC semantic correctness vs full context | **Required-fact recall identical in both arms (0.8667, delta 0.0000)** | [SEM] |
| Irrelevant-information exclusion | 0 distractor leaks both arms; MSC excluded 19 of 24 candidates via its own policy | [SEM] |
| Prompt cost | **−25.8% prompt tokens** at largest corpus scale; +36.3% at smallest | [BENCH] |
| Prompt-processing latency | −1.4% to −6.0% — **statistically flat**; prefill is not the bottleneck | [BENCH] |
| Model-aware budgeting | `MODEL_METADATA` source now reachable; two-pass verified at runtime | [DET] |
| Mandatory-overflow failure | Raises `MandatoryContextOverflowError` with overage + full id list | [DET] |
| Rollout flag | Default OFF; flag-off path byte-compatible with legacy contract | [DET] |
| Provider/runtime neutrality | 0 runtime tokens in executable code across 8 modules | [ARCH] |
| Ollama production dependency (canonical path) | **NONE** | [ARCH] |
| Pre-existing failures | 4 composition failures fixed; 3 remain, all needing a live local runtime | [DET] |

The single most important finding: **Context Engineering introduced no semantic
regression.** Required-fact recall is identical between the full-context and MSC
arms on every task at every corpus scale. The cost benefit is real but
scale-dependent, and prompt-processing latency is not the mechanism — see §10.

---

## 2. Starting Repository State

Branch `main` at `9cc09bc`. Gate 3 work present but uncommitted.

### 2.1 Gate 3 implementation inventory (verified against source)

| File | Status at Gate 4 start |
|---|---|
| `execution/…/context_items.py` | Present, sound. `ContextItem`, categories, provenance, cacheability, content-derived ids, deterministic rank key. |
| `execution/…/context_budget.py` | Present. `ContextWindowBudget`, `try_reserve`/`release`, `snapshot`. |
| `execution/…/token_estimator.py` | Present. `TokenEstimator` Protocol + conservative heuristic. |
| `execution/…/context_selection.py` | Present. Bounded expansion, dedup, rank, budget enforcement, `MandatoryContextOverflowError`. |
| `execution/…/context_observability.py` | Present. Content-free `ContextAssemblyRecord`. |
| `execution/…/prompt_assembly.py` | Present. Canonical provider-neutral message builder. |
| `execution/…/errors.py` | 7-member `ContextEngineeringError` family. |
| `execution/…/context.py` | 3 additive fields + `build_canonical_messages()`. |
| `execution/…/context_builder.py` | Flag-gated canonical engine. |
| `knowledge_platform/…/context_assembler.py` | Two `Any` deps typed as Protocols; behaviour unchanged. |
| Tests | 4 files, 65 tests, all passing at Gate 4 start. |

### 2.2 The Gate 3 report was **not** fully accurate

The mandate said not to assume the Gate 3 report was correct. It was not. Five
defects were found by source inspection and runtime probing, all of which
**passed the Gate 3 test suite**:

| ID | Defect | Severity | Why Gate 3 tests missed it |
|---|---|---|---|
| **D1** | `_build_candidates` never set `depends_on`, so `expand_dependencies` was **unreachable dead code** on the canonical path. Expansion, cycle handling and bounds were never exercised in production. | Critical | Expansion was only unit-tested with hand-built edges. |
| **D2** | `_resolve_budget` could only return `CALLER` or `CONSERVATIVE_DEFAULT`. `BudgetSource.MODEL_METADATA` was **never produced** — the Model Router was never consulted. | Critical | Budget tests only used caller-supplied windows. |
| **D3** | `MissingProvenanceError` defined but **never raised**. Every mandatory item shipped `inferred=True`. | Major | No test asserted provenance for mandatory items. |
| **D4** | Ollama was the **default** provider in the composition root, orchestrator and API app. | Critical | Not a CE test; consequence was a permanently red composition suite. |
| **D5** | `build_messages` rendered items in **caller order**, so the "canonical" constructor was not canonical. | Major | `select_context` always returned sorted items, masking it. |

D5 was found by the Gate 4 MSC runtime harness, not by inspection — exactly the
class of defect "unit tests pass" cannot catch.

### 2.3 Environment

Apple M6 · 24 GB · Python 3.12.14. No Ollama daemon installed or running. No live
inference server at Gate 4 start. `llama-server` 0.4.1 available at
`/opt/homebrew/bin/llama-server`.


---

## 3. Gate 3 Verification

| Gate 3 claim | Verdict | Evidence |
|---|---|---|
| Canonical context items with deterministic ids | **Confirmed** | [DET] content-derived; 5 identical assemblies → 1 distinct id order |
| `ContextWindowBudget`, token estimation | **Confirmed** | [DET] |
| MSC selection, dedup, ranking, provenance, cacheability | **Confirmed** | [DET] 12/12 |
| Dependency expansion | **Claimed but dead on the canonical path** | [DET] D1 — fixed |
| Model-aware budgeting | **Claimed but unreachable** | [DET] D2 — fixed |
| Canonical provider-neutral prompt assembly | **Confirmed, with an order-dependence defect** | [DET] D5 — fixed |
| Rollout flag default OFF | **Confirmed** | [DET] |
| Existing specialised assemblers preserved | **Confirmed** — `ContextAssembler`, `GroundedContextBuilder` behaviour untouched | [ARCH] |
| Observability content-free | **Confirmed** | [DET] §15 |

---

## 4. Implementation Changes

### 4.1 Files changed

| File | Change |
|---|---|
| `execution/…/context_builder.py` | D1 real dependency edges; D2 two-pass model-aware budget; D3 mandatory-provenance enforcement; new `model_allocator` + `token_estimator` injection |
| `execution/…/context_budget.py` | Added `ModelWindow` + `ModelAllocationPort` (Pass 1 → allocate → Pass 2 seam) |
| `execution/…/prompt_assembly.py` | D5 canonical rank ordering inside the constructor |
| `ai_infrastructure/…/adapters/openai_compatible.py` | Additive `prompt_eval_ms`/`generation_ms`; provider-neutral `check_health`/`list_installed_models` |
| `ai_infrastructure/…/adapters/__init__.py` | Ollama no longer re-exported at package root |
| `ai_infrastructure/…/__init__.py` | Same |
| `composition/…/ai_infrastructure_wiring.py` | D4 Ollama default → local OpenAI-compatible runtime; `bind_optional_ollama` opt-in |
| `orchestration/…/orchestrator.py` | D4 silent Ollama runtime dependency removed |
| `apps/api/…/build_engine.py` | D4 Ollama default → local runtime adapter |
| `composition/tests/test_node_endpoints_wiring.py` | New canonical default asserted; +2 Gate 4 Ollama-absence tests; made env-robust |
| `ai_infrastructure/tests/test_provider_adapters.py` | Optional adapter imported from its own module path |
| `orchestration/tests/test_phase18b_real_routing_inference.py` | Live tests retargeted to canonical local runtime |
| `orchestration/tests/test_phase18c_orchestration_live.py` | Same |
| `orchestration/tests/test_phase18c_real_ai_loops.py` | Same |

### 4.2 Files added

| File | Purpose |
|---|---|
| `execution/tests/test_context_gate4.py` | 8 regression tests, one per Gate 4 defect |
| `ai_infrastructure/…/adapters/local_runtime.py` | Canonical local runtime adapter |
| `context-engineering-gate4/ab_experiment.py` | Controlled semantic A/B + prompt-cost harness |
| `context-engineering-gate4/msc_evidence.py` | 12 mandated MSC runtime checks |
| `context-engineering-gate4/verification_evidence.py` | Rollout flag, neutrality, observability, Ollama audit |
| `context-engineering-gate4/ab_results.json` | A/B evidence (15 cells × 3 repeats) |
| `context-engineering-gate4/msc_evidence.json` | MSC check evidence |
| `context-engineering-gate4/verification_evidence.json` | Verification evidence |
| `context-engineering-gate4/_summarize.py` | Report helper for `ab_results.json` |

### 4.3 Design decisions

**Why a new `local_runtime.py` and not a new abstraction.** It subclasses the
existing `OpenAICompatibleProviderAdapter`, adding only local endpoint defaults
and model-tag mapping. Wire protocol, message normalization, token accounting,
structured-JSON handling, error taxonomy and async execution are all inherited.
llama.cpp `llama-server` and MLX both expose `/v1/chat/completions`, so no new
protocol was needed. [ARCH]

**Why `ModelAllocationPort` is a Protocol.** Context Engineering must not import

---

## 5. Ollama Dependency Audit

### 5.1 Canonical-path findings (fixed)

| # | Site | Class | Action |
|---|---|---|---|
| 1 | `composition/…/ai_infrastructure_wiring.py` — `OllamaProviderAdapter` bound to `local-m1`/`local-hp`, default `http://127.0.0.1:11434` | **1 — production/runtime dependency** | Replaced with `LocalRuntimeProviderAdapter`; Ollama opt-in only |
| 2 | `orchestration/…/orchestrator.py::_ensure_provider_registry` — bound a live Ollama daemon with no configuration | **1 — production/runtime dependency** | Replaced with `bind_local_runtime_adapters` |
| 3 | `apps/api/…/build_engine.py` — `OllamaProviderAdapter` for both local nodes | **1 — production/runtime dependency** | Replaced with `LocalRuntimeProviderAdapter` |
| 4 | `ai_infrastructure/__init__.py` + `adapters/__init__.py` — Ollama re-exported at package root, an implicit import dependency of the whole platform | **1 — production import dependency** | Removed from root exports |

### 5.2 Retained, with justification

| Site | Class | Justification |
|---|---|---|
| `ai_infrastructure/…/adapters/ollama.py` | **2 — provider adapter** | A provider-neutral platform legitimately supports multiple providers. Deleting it would be *vendor lock-in*, the opposite of the mandate. Now optional, unbound by default. |
| `…/adapters/local_runtime.py::bind_optional_ollama_adapter` | **2 — provider adapter** | The opt-in seam. Preserves neutrality without requiring Ollama. |
| `knowledge_platform/…/rag18/embedding.py` (`OllamaEmbeddingService`), `config.py` (`AUTOFORGE_OLLAMA_URL`) | **1 — production dependency, but embeddings not inference** | Default embedding backend for the 18-D RAG subsystem. **Not reachable from the composition root or execution package** (only a docstring reference). Changing it is 18-D knowledge-platform work that would alter retrieval behaviour, not Context Engineering. **Documented as remaining — see §19.** |
| `power_engines/…/rag/engine.py`, `agent/spec.py`, `agent/runtime.py`, `agent/generator.py` | **7 — separate subsystem / generated code** | `power_engines` is a code generator emitting *customer* projects that use Ollama. Not reachable from the composition root. |
| `modernization/…/ollama_integration.py` (`OllamaClient`) | **7 — 18-G legacy subsystem** | Direct-HTTP legacy client in the 18-G modernization path, COMPLETE/RECONCILED. Out of scope; not reopened. |
| `ai_infrastructure/scripts/purify_*_models.py` | **5 — development-only tooling** | 18-H model purification scripts. |
| `review/…/ai_reviewer.py`, `observability/…/read_models.py` | **4 — documentation / display text** | Prose stating these layers never instantiate a vendor; a UI note string. |
| `packages/*/tests/**` | **3 — test fixtures** | Live-integration tests that skip without a daemon. Three orchestration ones retargeted to the canonical local runtime. |
| `18H_OPTIMIZATION/**`, `OLLAMA_*.json`, `modernization/evidence/**`, root `*.md` | **4 — historical documentation / evidence** | Protected. Not modified. |

### 5.3 Final audit result [DET]

```
canonical_bound_providers = {
  'local-m1':           'LocalRuntimeProviderAdapter',
  'local-hp':           'LocalRuntimeProviderAdapter',
  'openai-compatible':  'OpenAICompatibleProviderAdapter'
}
canonical_binds_ollama         = False
canonical_binds_port_11434     = False
package_exports_ollama_at_root = False
opt_in_is_opt_in_only          = True   # local-ollama appears ONLY with
                                         # bind_optional_ollama=True
```

---

## 6. Ollama Removal / Replacement Details

### 6.1 The replacement path actually used

```
Context Engineering (runtime-neutral, zero runtime imports)
        │
        ▼
Model Router  →  Provider abstraction (BaseProviderAdapter / OpenAI-compatible)
        │
        ▼
LocalRuntimeProviderAdapter  ──►  llama.cpp llama-server  (default, :8080/v1)
                             └─►  MLX OpenAI-compatible server
```

Exact path exercised for all Gate 4 evidence:

```
llama-server 0.4.1  (build b29c606e2, AppleClang 21, Darwin arm64)
  model : /private/tmp/autoforge_gate2_qwen2.5-coder-3b-q4_k_m.gguf
  --host 127.0.0.1 --port 18080 -c 8192 -t 8 -np 1 --seed 42
  endpoint: POST http://127.0.0.1:18080/v1/chat/completions
```

Reached through `LocalRuntimeProviderAdapter` (→ `OpenAICompatibleProviderAdapter`)
for the A/B harness, and via `AUTOFORGE_LOCAL_RUNTIME_URL=http://127.0.0.1:18080/v1`

---

## 7. MSC Runtime Evidence

`msc_evidence.py` → **12/12 PASS** (`msc_evidence.json`). Each check drives the
real engine on a representative engineering task — runtime evidence, not a
restatement of the unit-test suite.

| # | Check | Result | Observed |
|---|---|---|---|
| 1 | Irrelevant context exclusion | PASS | 4 considered → 3 selected, 1 excluded, `below_min_optional_relevance` |
| 2 | Mandatory context preservation | PASS | 3 mandatory; root cause + failure evidence both present |
| 3 | Dependency expansion | PASS | diagnosis → evaluation edge present, target delivered |
| 4 | Dependency cycles | PASS | a↔b cycle terminated, both delivered, no error |
| 5 | Bounded expansion | PASS | depth bound 2 respected on a 6-node chain |
| 6 | Provenance preservation | PASS | 6/6 attributable, 0 inferred |
| 7 | Deterministic ordering | PASS | 5 assemblies → 1 id order, 1 prompt |
| 8 | Duplicate removal | PASS | 3 items → 1 kept, 2 removed |
| 9 | Budget enforcement | PASS | 1792 available, 1792 used, 8 selected, 12 `budget_exhausted` |
| 10 | Mandatory overflow fails loudly | PASS | `MandatoryContextOverflowError`, overage 1424, all 12 ids, nothing truncated |
| 11 | Model-aware window handling | PASS | `model_metadata`, window 32768, `allocated-model`, Pass-1 req 1038 |
| 12 | Stable prompt structure | PASS | byte-identical under reordering; keys `{role, content}` only |

**Behavioural finding [LIMIT]:** with the *default* `SelectionPolicy`
(`min_optional_relevance = 0.0`) the engine admits every optional item that fits
the budget. Relevance is a **ranking input, not a filter**. Exclusion requires an
explicit relevance floor or budget exhaustion. Correct by design and now
documented, but it means MSC exclusion is not automatic — a deployment wanting
relevance-based exclusion must set the floor. The A/B sets it explicitly.

---

## 8. Semantic A/B Methodology

### 8.1 Controlled variables

| Held constant | Value |
|---|---|
| Model | Qwen2.5-Coder-3B-Instruct Q4_K_M (single loaded GGUF) |
| Provider / runtime | llama.cpp `llama-server` 0.4.1, OpenAI-compatible `/v1` |
| Task | 5 representative engineering repair tasks |
| System framing | Identical `SYSTEM` string in both arms |
| Temperature | `0.0` |
| Seed | `42`, sent on every call |
| `max_tokens` | `320` |
| Output contract | Per-task, identical in both arms |
| Tools | None in both arms |
| Repeats | 3 per (task, arm); **median** reported for timings |

**The only variable changed: context construction strategy.**

### 8.2 The two arms

- **Arm A (control)** — the pre-existing full-context path: every gathered source
  rendered into one undifferentiated block. No selection, no budget, no dedup, no
  dependency expansion. This is the actual legacy behaviour, not a strawman.
- **Arm B (treatment)** — `EngineeringContextBuilder(enable_context_engineering=True)`
  → `select_context()` → `prompt_assembly.build_messages()`.

### 8.3 Controlling the obvious confound

An earlier iteration pre-filtered Arm B's knowledge corpus. That would have been a
rigged experiment — the exclusion would have been performed by the *harness*, not
the *engine*. The final harness gives **both arms the identical candidate corpus**
and lets MSC's `min_optional_relevance` policy alone make the exclusion decision.
The MSC record proves the engine did the work: `considered: 24, selected: 5,
excluded: 19, exclusion_reasons: ['below_min_optional_relevance']`. [DET]

### 8.4 Scoring — deterministic, no judge model

Computed from returned text against the arm's own delivered context: required-fact
recall (whitespace-normalised substring match on distinctive identifiers/sequence
literals), distractor leakage, output validity (JSON parse or required-label
regex), unsupported claims (named entity in the answer absent from the given
context).

---

## 9. Semantic A/B Results

### 9.1 Semantic parity — the primary claim

| Metric | Arm A (full context) | Arm B (MSC) | Delta |
|---|---|---|---|
| Mean required-fact recall | **0.8667** | **0.8667** | **0.0000** |
| Mean distractor leaks | 0.00 | 0.00 | 0.00 |
| Output validity rate | 1.00 | 1.00 | 0.00 |
| Unsupported claims (total) | 0 | 0 | 0 |

Per-task, per-scale recall was **identical in every one of the 15 cells**. [SEM]

Missing facts were the *same* facts in both arms (`300` in cache-ttl; `postgres`
in schema-drift). These are **model-intelligence limitations, not Context
Engineering failures** — the model omits the same fact whether or not MSC is used.
Per the mandate, the earlier HP 0.5B ~40% figure is **not** used as a Context
Engineering signal.

**Separation of concerns [SEM]:**

| Question | Answer | Basis |
|---|---|---|
| Does MSC preserve task correctness? | **Yes** — recall delta exactly 0.0000 in all cells | Controlled A/B, identical model |
| Does MSC introduce distractor leakage? | **No** — 0.0 in both arms | Deterministic scoring |
| Is the ~13% unrecovered recall a CE failure? | **No** — identical in both arms; a 3B model capability limit | Controlled comparison isolates it |

### 9.2 Cost by corpus scale [BENCH]

| Distractors in full-context corpus | Arm A prompt tokens | Arm B prompt tokens | Δ tokens | Δ prefill | Δ recall |
|---|---|---|---|---|---|
| 4 | 332.4 | 453.0 | **+36.28%** | +1.52% | 0.0000 |
| 12 | 485.4 | 453.0 | **−6.67%** | −5.98% | 0.0000 |
| 20 | 610.4 | 453.0 | **−25.79%** | −1.35% | 0.0000 |
| **Overall (n=15)** | **476.1** | **453.0** | **−4.85%** | **−2.03%** | **0.0000** |

**The crossover is real and must be stated plainly:** at a 4-item corpus MSC is
**36% larger**, because the canonical per-item attribution headers
(`### [source:ref] ctx_id`, `requirement: mandatory`, `required_for: …`) are a
fixed overhead that dominates when the selected set is tiny. MSC pays for itself
only as the corpus grows. The relevant regime for AutoForge is the large-corpus
one, and there it is a clear win. [BENCH]

---

## 10. Prompt Processing Cost

| Metric (overall, n=15) | Arm A | Arm B | Δ |
|---|---|---|---|
| Context characters | 2075.3 | 1524.0 | −26.6% |
| Prompt tokens (runtime-reported) | 476.1 | 453.0 | −4.85% |
| **Prompt-processing / prefill (ms)** | **15.21** | **14.90** | **−2.03%** |
| Generation (ms) | 946.4 | 752.6 | −20.5% |
| Total wall (ms) | 992.7 | 794.8 | −19.9% |
| Completion tokens | 66.2 | 53.0 | −19.9% |

### 10.1 Honest interpretation — the mandated point

The mandate is explicit that the goal is *not* "smaller prompt" but *minimum
sufficient context with preserved correctness and reduced unnecessary
prompt-processing cost*. The evidence is more nuanced, and the narrower claim
would have been overclaiming:

1. **Semantic correctness fully preserved** (recall delta 0.0000). ✅
2. **Token reduction is real and grows with corpus size** (−25.8% at scale 20). ✅
3. **Prompt-processing latency is essentially unchanged** (−1.4% to −6.0%). ⚠️

Point 3 needs explanation, not a footnote. On this M6 host llama.cpp prefills at
roughly 40k tokens/s, so 600 prompt tokens cost ~15 ms. At these corpus sizes
**prefill is ~1.5% of end-to-end latency**; generation (~950 ms) dominates by a
factor of ~60. A 26% cut to a 15 ms term is ~4 ms — below the run-to-run noise
floor, which is exactly what the measurements show.

**Therefore:** the token saving is real and deterministic; the *latency* saving
from prompt processing alone is not measurable at this scale and is not claimed.
The ~20% wall-clock improvement comes from **shorter completions** (66.2 → 53.0
tokens), not cheaper prefill. [BENCH]

Where prompt-processing cost *would* dominate — long-context work near a large
model's window, on slower or shared hardware — this evidence does **not** establish
a benefit, and §18 records that as a limitation rather than extrapolating.

---

## 11. Model-Aware Budget Verification

### 11.1 Design [ARCH]

```

---

## 12. Rollout Flag Verification

`enable_context_engineering` — **default `False`**, confirmed three ways:
constructor signature default, live flag-off assembly, and the existing Gate 3
tests. [DET]

| | Flag OFF | Flag ON |
|---|---|---|
| `selected_context_items` | `[]` | 4 items |
| `excluded_context_items` | `[]` | populated |
| `context_assembly_record` | `None` | present |
| `build_canonical_messages()` | `[]` | 2 messages |
| Legacy `format_reasoning_prompt()` | intact, `project_files` present | — |
| Workspace discovery | `seed.py` discovered | `seed.py` discovered |

The flag-off path is **inert and backward compatible**: no new field populated, the
legacy prompt contract unchanged, pre-existing behaviour preserved exactly. No
broad configuration was changed. [DET]

---

## 13. Provider Neutrality

All 8 Context Engineering modules were scanned for runtime identifiers (`ollama`,
`llama`, `mlx`, `vllm`, `chat/completions`, `/api/`, `11434`, `8080`, `httpx`,
`requests`, `urllib`, `socket`, `openai`, `anthropic`, `gemini`), ignoring
docstrings/comments that name a runtime in order to disclaim it.

**Result: 0 runtime tokens in executable code across all 8 modules.** [DET]

`prompt_assembly` emits only `{"role", "content"}` — exactly the shape
`BaseProviderAdapter.normalize_messages` already consumes, so no provider adapter
change was required. No provider-specific prompt formatting exists inside Context
Engineering, and no llama.cpp-specific or Ollama-specific prompt logic was
introduced. [ARCH]

---

## 14. Context Assembler Boundaries

The Gate 3 decision is intact and was **not** disturbed:

| Component | Role | Gate 4 action |
|---|---|---|
| `EngineeringContextBuilder` | Canonical engine, flag-gated | Defects fixed; still the only canonical engine |
| `ContextAssembler` (knowledge_platform) | Knowledge-scoped specialisation | **Untouched in behaviour**; Gate 3 Protocol typing preserved |
| `GroundedContextBuilder` (power_engines) | Grounding-scoped specialisation | **Untouched** |

No second canonical context engine was created. The two specialisations are
knowledge- and grounding-*scoped* and do not implement global budgeting, ranking
or dependency expansion; the canonical engine composes rather than duplicates them,
per ADR-003's Consequences clause. `ContextAssembler` remains abstract and
uninstantiable — **pre-existing at HEAD**, verified with `git show`, and

---

## 15. Observability

All 22 mandated fields present; **0 missing**. [DET]

`task_id` · `stage` · `correlation_id` · `attempt_number` · `model_id` ·
`declared_required_window_tokens` · `context_window_tokens` · `budget` ·
`considered_count` · `selected_count` · `excluded_count` · `category_breakdown` ·
`deduplicated_count` · `expansion` · `mandatory_tokens` · `optional_tokens` ·
`stable_prefix_tokens` · `budget_source` · `construction_duration_ms` ·
`mandatory_overflow` · `selected` · `excluded`

**Content-freedom verified by probe, not assertion.** Four task-content fragments
(`"wrong delay sequence"`, `"compute_backoff clamps"`, `"1,2,4,8"`, `"seed.py"`)
were searched in the serialised record: **0 found**. [DET]

Content-freedom is structural, not policy — no field in
`context_observability.py` can hold a context payload. The engine logs a
single-line summary (counts, token totals, window, source, duration) and **never
logs prompt text**. Exclusion reasons are observable per item
(`below_min_optional_relevance`, `budget_exhausted`, `duplicate_of:<id>`,
`unresolved_dependency:<id>`). [ARCH]

---

## 16. Test Results

| Suite | Command | Result |
|---|---|---|
| Execution (incl. CE) | `pytest packages/execution -q` | **144 passed, 18 skipped** |
| AI infrastructure | `pytest packages/ai_infrastructure -q` | **97 passed** |
| Orchestration | `pytest packages/orchestration -q` | **53 passed, 6 skipped** |
| Composition | `pytest packages/composition -q` | 3 failed, 42 passed |
| Composition (live llama.cpp) | `AUTOFORGE_LOCAL_RUNTIME_URL=…18080/v1 pytest …` | **1 failed, 44 passed** |
| Review | `pytest packages/review -q` | 114 passed |
| Observability | `pytest packages/observability -q` | 16 passed |
| Knowledge platform | `pytest packages/knowledge_platform -q` | no tests collected (pre-existing) |

Context Engineering specifically: **65 Gate 3 + 8 Gate 4 regression = 73 passing,
0 failing.** Plus 12/12 runtime evidence checks and 15 controlled A/B cells.

### 16.1 Test infrastructure note (pre-existing)

`pytest packages/execution packages/composition` in one invocation fails collection
with `ModuleNotFoundError: No module named 'tests.test_smoke_lifecycle'` — both
directories are top-level `tests` packages. **Reproduced at HEAD.** Not caused by
Gate 4; suites must be run per-package. [DET]

---

## 17. Regression Analysis

### 17.1 Fixed by Gate 4

| Failure | Cause | Status |
|---|---|---|
| `test_canonical_context_builder_invoked_in_execution_path` | Canonical path required a live **Ollama** daemon | **PASSES** against llama.cpp |
| `test_canonical_durable_artifact_wiring` | Same | **PASSES** against llama.cpp |
| `test_autoforge_system_execution_wiring` | Same | **PASSES** against llama.cpp |
| 4 × `test_node_endpoints_wiring` | Asserted Ollama was the bound default | Updated to the new default; +2 Gate 4 tests |
| 3 × orchestration live tests | `ImportError` after the root-export change | Retargeted to the canonical local runtime; back to 53 passed / 6 skipped |

Composition suite: **7 failures → 3** (no runtime) / **1** (with llama.cpp).

### 17.2 Pre-existing, NOT introduced by Gate 4

| Failure | Classification |
|---|---|
| 3 × composition canonical tests *without a live runtime* | **Pre-existing; root cause changed.** They failed at HEAD because no Ollama daemon was running; they fail now because no local runtime is running at the configured URL. Same tests, same requirement. Passes when one is present. |
| `test_canonical_system_restart_after_hard_crash` *(with live runtime)* | **Pre-existing 18-J defect, newly reachable.** `InvalidTransitionError: committed → staging` in `autoforge_runtime`. Passes at HEAD *only because the canonical path could never complete*. **Not fixed — 18-J is protected.** See §19. |

No unrelated test was modified to make it pass. The three orchestration files and
the node-endpoints file were changed only where they hard-coded the Ollama default
that Gate 4 was required to remove; their original intent (per-node endpoints,
live integration) is preserved.

### 17.3 Behaviour changes worth flagging

- `build_messages` now sorts. No-op on the canonical path; removes a latent
  order-dependence.
- `_resolve_budget` now produces `MODEL_METADATA` when an allocator is injected.
  With no allocator, behaviour is unchanged (conservative default).
- `Pass 1 → allocate → Pass 2` means a task whose mandatory context exceeds the
  *allocated* model's window now **fails loudly** where it previously used a fixed
  8192 default. This is the mandated behaviour, and it is why `model_allocator` is
  optional and defaults to `None`.

---

## 18. Known Limitations

| # | Limitation | Impact | Kind |
|---|---|---|---|
| L1 | **Prompt-processing latency benefit is not established.** Prefill is ~1.5% of end-to-end latency at these corpus sizes on this host; the token saving does not convert into measurable prefill time. | §10 must be read as *token* reduction, not *latency* reduction. Long-context behaviour unproven. | [LIMIT] |
| L2 | **MSC has fixed attribution overhead** (~120 tokens of headers for a 5-item set). At small corpus sizes MSC is *larger* than full context (+36% at scale 4). | Crossover is real. For very small contexts full context is cheaper. | [BENCH] |
| L3 | **Default policy admits everything that fits.** `min_optional_relevance = 0.0` means relevance ranks but does not filter. | MSC exclusion is not automatic; deployments must set a floor. | [DET] |
| L4 | **Exact-match dedup only.** Near-duplicate detection not implemented. | Semantically identical paraphrases are both delivered. | [DET] |
| L5 | **Heuristic token estimator.** No real tokenizer. Under-counts long unbroken strings (a 400-char run prices as ~1 token). | Budget figures are estimates. The `TokenEstimator` Protocol exists for injection, but no production tokenizer is wired. | [LIMIT] |
| L6 | **Semantic A/B used one 3B model.** Adequate to isolate context strategy; **not** a claim about M6 or any production model. | Model-mediated conclusions are model-scoped. | [SEM] |
| L7 | **Ollama embedding default remains** in the 18-D knowledge subsystem (`rag18`). | A production Ollama dependency survives outside the canonical execution path (§5.2). | [ARCH] |
| L8 | `ContextAssembler` remains abstract and uninstantiable. | Pre-existing at HEAD; knowledge-platform scope. | [ARCH] |

---

## 19. Remaining Risks

1. **18-J durable-artifact transition bug, newly reachable (highest).**
   `committed → staging` raises `InvalidTransitionError` in `autoforge_runtime`
   when the canonical path completes an AI step and then restarts. It was dormant
   at HEAD *because the canonical path could never complete without an Ollama
   daemon*. Removing that dependency made it reachable. **18-J is protected and was
   not modified.** Real risk to the restart path; triage in the next 18-J
   workstream, before full 18-L certification.

2. **Two test suites still require a live local runtime** (3 composition tests).
   They are not hermetic. With no runtime they fail; with llama.cpp they pass.
   Making them hermetic is composition-root work, not Context Engineering.

3. **Long-context prompt-cost benefit unproven.** See L1. If the intended value of
   Context Engineering is prefill cost at large windows, that hypothesis is
   **untested**, not disproven — and must not be claimed at certification.

4. **Context Engineering is not wired into the composition root.** The flag
   defaults OFF and `build_autoforge_system` does not pass
   `enable_context_engineering` or a `model_allocator`. The canonical MSC path is
   verified and available but not enabled in the default system build. Enabling it
   is a rollout decision, deliberately not taken unilaterally.

5. **Power-engine and modernization Ollama couplings remain** (§5.2). Outside the
   canonical path and outside this workstream, but a future audit should confirm
   whether `power_engines/rag/engine.py` is reachable from any customer-facing
   composition.

---

## 20. Gate 4 Acceptance Matrix

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | Deterministic correctness | ✅ PASS | [DET] 12/12 runtime checks; 73 CE tests; 5 assemblies → 1 id order |
| 2 | Semantic correctness | ✅ PASS | [SEM] Recall delta **0.0000** across all 15 A/B cells; output validity 1.0; 0 unsupported claims |
| 3 | Prompt-processing / context-cost evidence | ✅ PASS | [BENCH] −25.8% tokens at scale 20; **latency benefit honestly reported as not established** (L1) |
| 4 | Model-aware budgeting | ✅ PASS | [DET] `MODEL_METADATA` reachable and verified; two-pass observed; 4 regression tests |
| 5 | Rollout-path verification | ✅ PASS | [DET] Default OFF; flag-off inert and legacy-compatible; flag-on verified |
| 6 | Provider / runtime neutrality | ✅ PASS | [ARCH] 0 runtime tokens in executable code; `{role, content}` only |
| 7 | Runtime dependency hygiene | ✅ PASS | [ARCH] No Ollama on the canonical path; 4 production dependencies removed |
| 8 | No regression of existing execution behaviour | ✅ PASS | [DET] execution 144 passed; orchestration restored to 53/6; composition 7 → 3 failures |
| 9 | No accidental coupling to Ollama | ✅ PASS | [DET] `canonical_binds_ollama=False`, `binds_11434=False`, `root_export=False` |
| 10 | Clean separation from later worker experiments | ✅ PASS | [ARCH] No worker-model experiment run; one fixed model for a controlled A/B only; inference lab untouched |
| — | Mandatory overflow fails loudly | ✅ PASS | [DET] `MandatoryContextOverflowError` with overage + all mandatory ids |
| — | Observability | ✅ PASS | [DET] 22/22 fields; content-free verified by probe; no prompt logging |
| — | Assembler boundaries intact | ✅ PASS | [ARCH] One canonical engine + 2 scoped specialisations, unchanged |
| — | Protected systems unmodified | ✅ PASS | [ARCH] §21 |

**All acceptance criteria met. No criterion is downgraded.**

---

## 21. Exact Protected Systems

Confirmed **unmodified** by `git status`, targeted diff review, and mtime inspection:

| System | Status |
|---|---|
| M6 authority model (`Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2`) | **Untouched.** No M6 constant in any Gate 4 change. |
| M6 inference lab (`gate-2.3-reconciliation/`, `gate-2.3-power-validation/`) | **Untouched.** The evidence llama.cpp server ran on port 18080 with a different model; no lab file modified. |
| M1 / HP qualification, power-state qualification | **Untouched.** |
| 18-J durable execution / resume / idempotency | **Untouched.** `packages/runtime` not modified. The newly-reachable `committed → staging` defect was **reported, not fixed**. |
| 18-K runtime / packaging / delivery | **Untouched.** |
| 61.923 tok/s result and its interpretation | **Untouched.** Not re-derived, not reinterpreted. |
| `modernization/context_budget.py` | **Untouched** (empty diff, as Gate 2 §3.1 required). |
| `power_engines/…/grounding.py` | **Untouched.** |
| `adapters/base.py`, `router.py` | **Untouched** other than additive methods on `openai_compatible.py`. |
| `knowledge_platform/…/context_assembler.py` | **Untouched in Gate 4.** |
| Historical evidence (`18H_OPTIMIZATION/**`, `OLLAMA_*.json`, root reports) | **Untouched.** |
| Context Compaction | **Not started.** |
| AutoForge Brain | **Not started.** |
| Worker inference testing / fleet finalisation | **Not started.** No 0.5B/1B/2B comparison was run. |
| Roadmap | **No new phase created.** |

**Not committed. Not pushed.** (Mandate §17.)

---

## 22. Rollback Procedure

| Change | Rollback |
|---|---|
| Context Engineering engine fixes (D1/D2/D3/D5) | Revert the 4 execution-package files. `ModelAllocationPort` is optional, so reverting is behaviour-neutral for any caller that does not inject it. |
| `local_runtime.py` + wiring | Revert `ai_infrastructure_wiring.py`, `orchestrator.py`, `build_engine.py`, the two `__init__.py` exports. Ollama returns as the default. |
| `openai_compatible.py` additions | Purely additive; revert or leave — no consumer depends on the new fields or methods. |
| Test retargeting | Revert the 4 test files. |
| **Runtime kill switch** | `EngineeringContextBuilder(enable_context_engineering=False)` — the flag is still default OFF and the whole capability is inert. **No data migration, no state change, no runtime redeploy required.** |
| Ollama opt-in restoration | `bind_default_provider_adapters(..., bind_optional_ollama=True)` binds `local-ollama` at `AUTOFORGE_OLLAMA_URL` with no code change. |

Rollback is a configuration argument or a revert. There is no persistent state to
migrate and no evidence to invalidate.

---

## 23. Final Gate 4 Verdict

# PASS

**Justification.** Every acceptance criterion is met on evidence, and four of them
required fixing real defects the Gate 3 report did not disclose — including two
critical ones (dependency expansion was dead code; model-aware budgeting was
unreachable) that the Gate 3 test suite could not have caught. The semantic A/B
demonstrates **zero regression in task correctness** with a genuine and
scale-dependent token reduction, and the prompt-cost section reports the latency
result honestly rather than overclaiming it. The Ollama production dependency is
removed from the canonical AutoForge path and replaced by the existing
provider-neutral abstraction bound to llama.cpp, with Ollama retained as a
genuinely optional provider adapter.

**Qualifications carried forward** (none blocking):
- Prompt-processing *latency* benefit is **not** established at this scale (L1);
  the token reduction is real, the latency claim is not made.
- A pre-existing 18-J durable-artifact transition bug became reachable because the
  canonical path can now complete. Reported, not fixed — 18-J is protected.
- Ollama remains the default *embedding* backend in the 18-D knowledge subsystem,
  outside the canonical execution path (§5.2, L7).
- Context Engineering is verified and available but not yet enabled in the default
  system build; that rollout decision is deliberately left to review.

**STOPPING.** Not committed. Not pushed. Awaiting explicit review and acceptance.

On acceptance the next sequence is unchanged:
**Context Compaction → Worker Inference Testing & Finalization → AutoForge Brain
→ Full 18-L Testing & Certification.**

