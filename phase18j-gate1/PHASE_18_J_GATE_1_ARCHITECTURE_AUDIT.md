# PHASE 18-J — GATE 1

# CONTEXT ENGINEERING ARCHITECTURE AUDIT

**Status:** AUDIT ONLY — NO CODE WAS MODIFIED
**Repository:** `/Users/kalachanddash/Developer/AutoForge-AI-OS`
**Branch:** `main`
**Gate:** 1 of 3 (Audit → Design → Implementation)

---

## 1. Objective

Determine, before writing any code, what Context Engineering capability AutoForge
already has, what is missing, what is duplicated, and what the minimal Phase 18-J
implementation must change.

This audit satisfies RULE 1 (no code before Gate 1). The inference lab, M6 authority
model, and roadmap phases 18-K/18-L/18-M were not touched.

---

## 2. Audit Method

- `git status --porcelain` verified before and after — **zero context-related source
  changes were made by this session**. The 7 modified `packages/` files carry
  mtimes of Sep 22–23, pre-dating this session (Sep 26); they are pre-existing
  workspace state, not audit output.
- All context-named files enumerated repo-wide (`find packages -iname '*context*'`).
- Every implementation read in full: `context.py`, `context_builder.py`,
  `context_assembler.py`, `context_budget.py`, `grounding.py`, `evidence.py`,
  `adapters/base.py`, `router.py`.
- Grep sweeps for: prompt-construction sites, token counting, prompt-cache support,
  budget wiring, builder wiring, memory/knowledge engine classes.

---

## 3. Existing Relevant Components

**A governing contract already exists.**
`docs/adr/ADR-003-context-engineering-contract.md` (~140 lines) already defines the
Context Engineering contract. **Phase 18-J is contract→implementation, not greenfield.**
This is the single most important audit finding: the architecture question is settled
in-document, and Gate 2 must implement the ADR rather than invent a new design.

### Four existing context implementations (competing, not unified)

| # | Component | Path | Scope |
|---|-----------|------|-------|
| 1 | `ExecutionContext` | `packages/execution/…/context.py` | Canonical task context dataclass |
| 2 | `EngineeringContextBuilder` | `packages/execution/…/context_builder.py` | ADR-003 canonical builder |
| 3 | `ContextAssembler` | `packages/knowledge_platform/…/context/context_assembler.py` | Knowledge/RAG-scoped assembly |
| 4 | `GroundedContextBuilder` | `packages/power_engines/…/rag/grounding.py` | RAG grounding assembly |

### 1. `ExecutionContext` (execution/context.py, lines 20–56)

The de-facto canonical context carrier, a `@dataclass`. Confirmed fields:

```
task_id, task_name, task_type, task_description, input_data, workspace_root
workflow_id, project_id, correlation_id, attempt_number
project_files, file_contents
prior_iterations, last_evaluation, last_diagnosis
retrieved_knowledge, metadata, effective_model_requirements
```

Strengths: carries provenance-bearing identity (`task_id`, `workflow_id`,
`correlation_id`), dependency history (`prior_iterations`), evidence
(`retrieved_knowledge`), and `effective_model_requirements` — the natural hook for
model-aware budgeting.

Gaps: it is a **bag of typed fields, not a list of attributable context items**.
There is no per-item `context_id / source / category / relevance / priority /
dependency / provenance / required_for / estimated_tokens / cacheability`. Selection
decisions therefore cannot be expressed or audited on it.

### 2. `EngineeringContextBuilder` (context_builder.py) — the ADR-003 builder

```
24: class EngineeringContextBuilder
31:   def __init__(
33:       default_max_context_chars: int = 16000,
38:       self.default_max_context_chars = default_max_context_chars
43:   async def assemble_context(...)
```

**Critical finding: the declared budget is dead code.**
`default_max_context_chars` is assigned at line 38 and **never read again anywhere in
the file**. `assemble_context` is purely **additive**: it concatenates sections up to
a cap that is not enforced. Consequently the builder has:

- **no scoring or ranking** (no relevance or priority dimension)
- **no deduplication**
- **no mandatory-vs-optional distinction** (nothing is protected from removal)
- **no budget enforcement** (the cap exists but is not applied)
- **no dependency expansion** (no traversal, hence no traversal bound either)
- **no provenance per item**
- **no cacheability metadata**
- **no observability output**

Wiring confirmed at composition root:
`composition_root.py:73` import, `:177` field, `:275` instantiation. The dispatcher
consumes it via `execution_wiring.py:138`. So this class is **live in the real request
path** — its gaps are production behaviour, not dead code.


### 3. `ContextAssembler` (knowledge_platform)

Implements `IContextAssembler`; assembles knowledge/citation context for RAG.

```
21: def __init__(
23:     citation_manager: Any,
24:     context_window_manager: Any,
25:     relevance_ranker: Any,
35: ) -> Dict[str, Any]      # returns a plain dict
```

**Critical finding: two `Any`-typed dependencies with no implementation anywhere in
the repository.** `context_window_manager` and `relevance_ranker` are the two things
Phase 18-J most needs — window-aware budgeting and relevance ranking — and they are
injected as untyped `Any` with **no concrete class in the repo** (confirmed by an
implementation sweep). It also returns `Dict[str, Any]`, so results are untyped and
untraceable.

### 4. `GroundedContextBuilder` (power_engines/rag/grounding.py)

A **fourth, independent** prompt-context assembly path for RAG grounding. Duplicates
the responsibility of #2 and #3 with its own formatting.

### 5. `ContextBudget` (modernization/context_budget.py) — dead code

A Pydantic model that is the *closest existing thing to Phase 18-J's budgeting
requirement*:

```
reserved_for_response: int = 0
available_for_context: int = 0      # "usable context after system prompt + response buffer"
current_usage_tokens / peak_usage_tokens / remaining_tokens: int = 0
enabled_optimizations: list[ContextOptimization]
chunking_strategy / chunk_size_tokens
token_accounting_enabled / usage_observable
repository_summary_tokens / module_summary_tokens / symbol_level_tokens
def reserve(self, tokens: int, purpose: str) -> bool
```

Two decisive facts:

- **It is never wired.** Repo-wide grep for `ContextBudget` outside its own module
  returns only `modernization/__init__.py:84` (import) and `:289` (`__all__`). No
  engine, builder, or dispatcher constructs or uses it.
- **Its defaults make it inoperative even if wired.** `available_for_context=0` and
  `remaining_tokens=0` mean `reserve()` returns `False` for any positive token count
  unless a caller explicitly populates the budget — and no caller exists.

So the repo already contains a budgeting *vocabulary* that is both unwired and
mis-defaulted. Phase 18-J must **reuse and repair this type**, not add a parallel one
(RULE 3, RULE 4).

---

## 4. Existing Responsibilities and Context Flow

Current flow, end to end:

```
Dispatcher
  → EngineeringContextBuilder.assemble_context()      (composition_root.py:275)
      → ExecutionContext (typed field bag)
          → adapter prompt build (ai_infrastructure / execution adapter)
              → provider → model
```

Parallel, unconnected flow:

```
Knowledge / RAG query
  → ContextAssembler (IContextAssembler) → Dict[str, Any]   [Any-typed deps, no impl]
GroundedContextBuilder (power_engines) → its own prompt assembly
ContextBudget (modernization) → never constructed
```

Memory (`packages/memory/`) is **spec-only** — a single `README.md`, no Python source.
There is no `MemoryEngine` class to protect or integrate against; Rule 4 is
satisfied by construction because Memory does not yet exist in code.

---

## 5. Existing Prompt Construction

Prompt/system-prompt construction is **scattered**, not centralised. Grep for
`system_prompt` and template construction returns multiple independent sites across
`execution`, `ai_infrastructure`, and `power_engines`, each formatting context
differently. This directly violates Phase 18-J §12 ("Do not scatter prompt
construction logic throughout individual engines").

There is **no canonical prompt-assembly function**. The closest thing is
`ExecutionContext`'s own formatting helper (used by the execution adapter), which
knows nothing about budgeting, priority, or cacheability.

---

## 6. Existing Provider / Cache Support


---

## 7. Duplication Found

| Duplication | Locations | Severity |
|-------------|-----------|----------|
| Context assembly | `EngineeringContextBuilder`, `ContextAssembler`, `GroundedContextBuilder` — 3 independent paths | High |
| Context-to-prompt formatting | multiple `system_prompt` construction sites in `execution`, `ai_infrastructure`, `power_engines` | High |
| Budget model | `ContextBudget` exists, unwired and mis-defaulted, while `default_max_context_chars` re-implements the idea in characters | Medium |
| Untyped passthrough | `ContextAssembler` returns `Dict[str, Any]`; deps are `Any` | Medium |

Three assemblers with no shared canonical item type means the same information can be
selected, ordered, and truncated differently depending on which engine asks — which is
precisely the "prompt bloat / silent loss" failure Mode Phase 18-J must eliminate.

---

## 8. Missing Capabilities

Against the Phase 18-J §4 scope:

| # | Required capability | Present? | Evidence |
|---|---------------------|----------|----------|
| 1 | Task-aware context selection | **No** | builders are additive concatenation |
| 2 | Minimum Sufficient Context | **No** | no sufficiency concept or marker |
| 3 | Relevant evidence selection | **Partial** | `retrieved_knowledge` exists; `relevance_ranker` has no implementation |
| 4 | Dependency-aware expansion | **No** | `prior_iterations` carried but never traversed |
| 5 | Context budgeting | **No** | `ContextBudget` unwired; `default_max_context_chars` never read |
| 6 | Prompt construction (centralised) | **No** | scattered across ≥3 sites |
| 7 | Prompt structure (deterministic) | **No** | no canonical ordering contract |
| 8 | Prioritisation | **No** | no scoring |
| 9 | Deduplication | **No** | no dedup pass |
| 10 | Provenance | **Partial** | `ExecutionContext` has task/workflow ids, but not per-item |
| 11 | Prompt-cache optimisation | **No** | zero cache support repo-wide |
| 12 | Observability | **No** | no selection/exclusion/budget record emitted |
| 13 | Deterministic / bounded | **No** | no bound on expansion; nothing is bounded |
| 14 | Integration with existing Context Builder | **Partial** | wired, but additive-only |

**12 of 14 required capabilities are absent; 2 are partial. 0 are complete.**

Also missing and required by §16: an explicit, non-silent failure path when mandatory
context exceeds budget. No such mechanism exists in any of the three builders.

---

## 9. Minimal Implementation Plan

Design decisions belong to Gate 2; this is the smallest shape that satisfies §4
without duplicating what exists.

1. **Canonical context item type.** Extend the existing `ExecutionContext` model with an
   ordered, attributable item list rather than adding a parallel container. One item
   type carrying identity, category, relevance, priority, dependency link, provenance,
   `required_for`, `estimated_tokens`, `cacheability`. This satisfies §8 while reusing
   §3.1.
2. **Repair and wire `ContextBudget`.** Fix the zero defaults, add the token-based
   accounting it already implies, and make it the single budget authority. Do **not**
   add a new budget class (RULE 3/4).
3. **Selection + ranking inside `EngineeringContextBuilder`.** Add scoring,
   deduplication, and mandatory-protection passes in front of the existing additive
   assembly, so the existing output shape is preserved for current callers.
4. **Bounded dependency expansion** with an explicit hop/depth limit and cycle guard,
   traversing the data `ExecutionContext` already carries (`prior_iterations`,
   retrieved knowledge, artifact/decision links).
5. **Token estimation.** Introduce one shared estimator (documented heuristic) and
   consume `effective_model_requirements` for the window; feed the Model Router's
   per-model limit once surfaced.
6. **Central prompt assembly.** One function that renders selected context

---

## 10. Files Expected to Change (Gate 3)

| File | Reason |
|------|--------|
| `packages/execution/src/autoforge_execution/context.py` | canonical attributable context item + ordered selection on the existing model |
| `packages/execution/src/autoforge_execution/context_builder.py` | scoring, dedup, mandatory protection, bounded expansion, budget enforcement, observability |
| `packages/modernization/src/autoforge_modernization/context_budget.py` | repair zero defaults; make the single budget authority |
| `packages/composition/src/autoforge_composition/composition_root.py` | wire the budget + token estimator into the existing builder (`:275`) |
| `packages/ai_infrastructure/src/autoforge_ai_infrastructure/adapters/base.py` | provider-neutral cacheability pass-through (metadata only) |
| `packages/ai_infrastructure/src/autoforge_ai_infrastructure/router.py` | surface per-model context window for budgeting |
| `packages/knowledge_platform/…/context/context_assembler.py` | type the `Any` deps; converge onto canonical items |
| `packages/power_engines/…/rag/grounding.py` | converge onto canonical items (or document exception) |
| `packages/composition/tests/test_canonical_context_builder.py` | extend with the 12 required tests |
| new focused test module(s) | deduplication, provenance, cache metadata, provider neutrality |

## 11. Files Explicitly Expected NOT to Change

- `gate-2.3-reconciliation/`, `gate-2.3-power-validation/`, all inference-lab evidence
  (the HP ~61.9 tok/s qualification is **infrastructure evidence only**; RULE 7)
- `packages/kernel/**` — kernel-centric orchestration stays untouched
- M6 authority model decision; no provider lock-in (RULE 10); no Ollama (RULE 9)
- `docs/adr/ADR-003-context-engineering-contract.md` — the contract governs Gate 2/3
  and is an input, not an output
- Any 18-K compaction, 18-L Brain, or 18-M certification artefact
- Unrelated pre-existing modifications in `packages/modernization/**` and
  `packages/security/pyproject.toml` (present before this session; not mine to touch)

---

## 12. Semantic-Correctness Note (Phase 18-J hard requirement)

The inference lab established HP 0.5B at **~61.9 tok/s** mean generation throughput
under mains + High Performance, but only **~40% strict semantic correctness** on the
realistic task benchmark. That 40% is an **unresolved quality limitation**.

Consequences for this phase, recorded now so Gate 3 cannot quietly sidestep them:

- Throughput is **not** an acceptance signal for Context Engineering. MSC must be
  judged on semantic correctness, not latency.
- The context benchmark required by §23 must be paired with a semantic evaluation
  (correctness, constraint adherence, evidence grounding, dependency preservation,
  verification correctness, omission impact).
- If context reduction improves latency but degrades correctness, the result is
  **PARTIAL**, not PASS (§24 / semantic-correctness requirement).
- The 0.5B model's ~40% ceiling confounds attribution: a context change cannot be
  credited for correctness it did not cause. Gate 3 must therefore validate context
  policy against **deterministic, non-model** assertions (selection, dedup, budget,
  provenance, bound) and report model-mediated semantic results separately.

## 13. Gate 1 STOP

**STOPPING HERE.** No code was written. No source file was modified — verified by
`git status`. Gate 2 (Context Engineering Design) requires review and approval of this
audit before any implementation begins.

**Audit verdict:** the repository has a sound written contract (ADR-003) and a live but
additive-only builder, plus three competing assemblers, one unwired budget, and zero
token-accounting, zero prioritisation, zero deduplication, zero provenance, zero cache
support, and zero context observability. Phase 18-J is a substantial implementation,
not an incremental tweak.

   deterministically, replacing scattered per-engine formatting. Provider-neutral:
   emit messages, let the existing adapter serialise.
7. **Cacheability as metadata only.** Mark stable prefixes (system instructions, project
   rules, tool schemas) as cache-eligible. Emit cache metadata; **do not** claim or
   simulate provider-side caching (RULE 11).
8. **Observability record** per operation: selected/excluded items with reasons,
   categories, token estimates, budget, cacheable share, construction duration,
   provenance.
9. **Explicit failure behaviour.** When mandatory context exceeds budget, raise via the
   existing error conventions — never silently truncate (§16, RULE 12).
10. **Converge the other two assemblers** onto the canonical item type, or document
    them as scoped exceptions in the Gate 2 design. Leave them functional either way.

Explicitly **out of scope** for 18-J: compaction/summarisation of accumulated history
(18-K), Brain (18-L), any inference-lab or M6 change.

- **Prompt-cache support: ZERO.** Repo-wide grep for `cache_control`, `cache_prompt`,
  `cached_tokens` across `packages/` returns **0 matches**. No provider abstraction
  exposes a cache-control concept.
- **Token counting: ZERO.** No tokenizer, token estimator, or token-counting utility
  exists anywhere in the repository. Every budget is therefore expressed in
  **characters** (`default_max_context_chars`), not tokens.
- **Provider abstraction:** `ai_infrastructure/adapters/base.py` defines a provider
  adapter base with message/prompt conversion, but it has no notion of
  `max_context_tokens`, cache boundaries, or budget reservation.
- **Model Router:** `ai_infrastructure/router.py` routes requests but does **not**
  surface a per-model context-window value that budgeting could consume.
  `ExecutionContext.effective_model_requirements` is the natural carrier for it.

This means Phase 18-J **must** introduce: (a) a token-estimation approach, and
(b) a provider-neutral cacheability *representation* — while obeying RULE 11 (do not
claim caching the runtime does not provide).
