# CONTEXT ENGINEERING DESIGN REPORT

**Workstream:** 18-L — Full Autonomous Engineering Certification (Context Engineering capability)
**Gate:** 2 of 3 (Audit → Design → Implementation)
**Governing contract:** `docs/adr/ADR-003-context-engineering-contract.md`
**Input:** Gate 1 architecture audit (findings valid, relabelled out of "Phase 18-J")
**Status:** DESIGN ONLY — no source code, tests, dependencies, or roadmap files were modified

> **Labelling correction honoured.** 18-J (Durable Execution / Resumability / Idempotency)
> and 18-K (Runtime / Packaging / Delivery) are untouched, not reopened, not renumbered.
> Context Engineering is scoped here as a **capability inside the 18-L certification flow**.

---

## 1. Architecture

### 1.1 What ADR-003 already fixes (not re-litigated here)

ADR-003 is binding. The design implements it rather than replacing it:

- The Context Engine is a **stateless-ish assembly service** with exactly 8 responsibilities
  (gather, score/select, dedup, budget, preserve critical errors, track provenance,
  model-aware, emit structured output).
- It **consumes** Knowledge Platform (retrieval, trust, fusion, citation), Memory Platform,
  Repository Intelligence, tool/terminal observations, Runtime/task state, Git, test output.
- It **MUST NOT own** knowledge retrieval infrastructure, trust scoring, memory storage or
  retention, repository state, runtime state, or model implementation.
- Consequences it mandates: the Knowledge Platform's assembler **remains the knowledge-scoped
  slice** and the Context Engine **composes rather than replaces** it; future worker code
  requests `context.assemble(stage=...)`; provenance and budgets are preserved in the
  **output contract**.

### 1.2 Component shape

One cohesive unit inside the existing canonical package, plus repair of the live builder.
No new package, no new service, no dependency inversion.

```
packages/execution/src/autoforge_execution/
  context.py               (MODIFIED) ExecutionContext + selected-items field
  context_items.py         (NEW)      ContextItem, categories, provenance, cacheability
  context_budget.py        (NEW)      ContextWindowBudget (request-scoped, model-aware)
  token_estimator.py       (NEW)      TokenEstimator protocol + default heuristic impl
  context_selection.py     (NEW)      deterministic expand → rank → dedup → bound
  prompt_assembly.py       (NEW)      THE canonical provider-neutral prompt constructor
  context_observability.py (NEW)      ContextAssemblyRecord (content-free)
  context_builder.py       (MODIFIED) EngineeringContextBuilder — now the single engine
  errors.py                (MODIFIED) ContextEngineeringError family
```

Capability providers (Knowledge, Memory, RAG, tool results, runtime state, git, tests) are
**called as ports**; the engine never re-implements them. This is the ADR-003 "compose, do
not duplicate" rule expressed as code.

### 1.3 Data flow (single canonical path)

```
Task + stage
  → [1] gather candidates         (ports: knowledge, memory, repo, tools, runtime, git, tests)
  → [2] declare required window   (deterministic estimate — two-pass, §1.4)
  → [3] resolve model window      (ModelMetadata.context_window_tokens)
  → [4] dependency expansion      (bounded BFS, §2.4)
  → [5] rank + tie-break          (deterministic total order, §2.5)
  → [6] deduplicate               (exact normalized content hash, §2.6)
  → [7] budget enforcement        (mandatory-first, §3)
  → [8] assemble ordered context  (ContextItem list, provenance intact)
  → [9] canonical prompt assembly (prompt_assembly.build_messages)
  → [10] emit observability      (ContextAssemblyRecord)
  → provider adapter (normalize_messages) → model
```

Steps 1–8 produce the **structured model context artifact** (ADR-003 output contract).
Step 9 is the **only** place prompt text is shaped. Step 10 is content-free by construction.

### 1.4 The two-pass window problem (resolves a circularity)

Budget depends on the model's context window; but a window-aware Router may want to know how
much context a task needs *before* choosing a model. Resolved explicitly, not by guessing:

- **Pass 1 — declare.** The engine computes a *required window* estimate from task type,
  stage, prior-iteration evidence, and tool-schema size. Pure function, no model needed.
  Published on the observability record; this is what a Router may consume.
- **Pass 2 — assemble.** The actual window from
  `ModelMetadata.context_window_tokens` / `max_output_tokens` (or an explicit caller
  override) becomes the hard budget.


---

## 2. Data Model

### 2.1 Canonical context item

New module `context_items.py`. Stdlib `@dataclass` — matching `context.py`, which is already
a stdlib dataclass module (Pydantic is the `modernization` convention, not this package's).

| Field | Type | Justification (ADR-003 / mandate requirement) |
|---|---|---|
| `context_id` | `str` | stable deterministic id (§2.7); required for dedup, dependency edges, provenance, determinism |
| `category` | `ContextCategory` | §7 categories; drives ordering and budget class |
| `content` | `str` | the actual text |
| `source` | `ContextSource` | structured `kind` + `ref` — "where did it come from" |
| `relevance` | `float` 0..1 | supplied by the capability provider, **not invented locally** (ADR-003 forbids owning trust scoring) |
| `required` | `bool` | mandatory flag; the protection mechanism (§2.2) |
| `required_for` | `tuple[str, ...]` | task/stage/verification reasons — "why was this selected" |
| `depends_on` | `tuple[str, ...]` | dependency edges for bounded expansion |
| `provenance` | `ContextProvenance` | ADR-003 §6 mandatory: acquired_from, acquired_at, tool/ref chain |
| `estimated_tokens` | `int` | budget accounting (an estimate, labelled as such) |
| `cacheability` | `ContextCacheability` | §7 metadata only |
| `exclusion_reason` | `str \| None` | set when dropped — answers "why was another item excluded" |

**Deliberately NOT added** (no speculative fields): embeddings, trust scores, TTL, tenant
fields, a stored ordering index. Ordering is *derived* (§2.5) — a stored index would drift
from the sort key and break determinism. Trust scoring is excluded because ADR-003 forbids
the Context Engine from owning it.

`ContextSourceKind` maps 1:1 to ADR-003's consumed-capability table plus the §7 categories:
`system | project | task | dependency | evidence | decision | verification | execution |
tool | runtime_state | git | test_output`.

### 2.2 Mandatory vs optional — the protection mechanism

`required=True` items are **never dropped and never truncated**. They are the explicit
guarantee required by §16 of the mandate and RULE 12. An item is mandatory when it is:
system instructions, explicit user constraints, the task objective itself, a dependency
pulled in by expansion, a referenced artifact, required verification evidence, an
authoritative decision, a required tool instruction, or a security/system constraint.

This is a **whitelist of sources**, not a heuristic — determinism is preserved.

### 2.3 Selection policy (deterministic)

```
task → required context → optional context → dependency expansion
     → ranking → deduplication → budget → final ordered context
```

- **Required set**: gathered from mandatory sources (§2.2). Always admitted; ordered first.
- **Optional set**: everything else, admitted only if budget remains after required.
- **Ranking key** (total order, no ties left to chance):
  `(not required, category_rank, -relevance, dependency_depth, context_id)`
  `category_rank` is a fixed enum order — stable categories, then project, task, dependency,
  evidence, decision, verification, execution, then the rest. Deterministic and explainable.
- **Tie-breaking**: final tiebreak is always `context_id`, a content-derived hash (§2.7).
  Same inputs ⇒ byte-identical ordering, every run.

### 2.4 Dependency expansion (bounded)

Breadth-first from required roots, following `depends_on`. Three independent limits, all
constructor-configurable with safe defaults:

| Bound | Default | Purpose |
|---|---|---|
| `max_dependency_depth` | 2 | stops recursive project-history injection |
| `max_expanded_items` | 64 | hard cap on total expansion |
| cycle guard | visited set of `context_id` | prevents loops; re-visits are ignored |

An edge pointing at an unavailable item is **not** silently dropped: the missing dependency
is recorded on the observability record and, if the referrer is mandatory, raises
`UnresolvableDependencyError` (§6). This satisfies "dependency expansion must be bounded"
without ever losing a required fact.

### 2.5 Ordering

Derived, never stored: the §2.3 sort key applied to the admitted set. Equal inputs produce
equal order — the property Test 10 asserts.

### 2.6 Deduplication

Exact-match on `sha256(normalize(content))` where `normalize` = Unicode NFKC + strip
trailing whitespace per line + collapse runs of blank lines + casefold. First occurrence in
rank order wins; later duplicates are excluded with
`exclusion_reason="duplicate_of:<context_id>"`, so dedup is **auditable**, not invisible.

Deliberately **not** doing fuzzy/near-duplicate detection: it needs embedding infrastructure

---

## 3. Budgeting Policy

### 3.1 Decision: repair `ContextBudget`, or add a sibling?

**Verified constraint.** `packages/execution/pyproject.toml` depends on `autoforge-models`,
`autoforge-events`, `autoforge-runtime`, `autoforge-ai-infrastructure`,
`autoforge-connectors`, `autoforge-workflows`. It does **not** depend on
`autoforge-modernization` — where `ContextBudget` lives — and `modernization` does not depend
on `execution` either (it pulls models/events/runtime/artifacts/workforce/observability).

So the canonical context engine **cannot import `ContextBudget` without adding a new
inter-package dependency**, which would invert the layering (execution is core; modernization
is a consumer) and touch a package the mandate protects.

Additionally, `ContextBudget` is **job-scoped, not request-scoped**: it is keyed by
`project_id` / `job_id` / `unit_id` — a modernization-job accounting concept. The canonical
engine's budget is **per intelligence operation**. Merging the two would force the execution
core to speak in modernization-job vocabulary.

**Decision: do not import `ContextBudget`.** Add a small, purpose-built
`ContextWindowBudget` in `packages/execution/…/context_budget.py` (new module — no collision
with the modernization module of the same name; different package), and **leave
`ContextBudget` completely untouched** as modernization's job-level accounting.

This is a *sibling*, not a replacement and not a second authority over the same scope. The
mandate permits a second abstraction when the existing one cannot serve the need; here it
structurally cannot (wrong package, wrong granularity, wrong keying). I flag it explicitly
rather than burying it, and I am **not** modifying `modernization` to "fix" its dead code —
that is out of scope and belongs to whoever owns that package.

`ContextWindowBudget` fields — deliberately minimal:

| Field | Purpose |
|---|---|
| `model_context_window_tokens` | from `ModelMetadata.context_window_tokens` (verified to exist) |
| `reserved_for_output_tokens` | from `ModelMetadata.max_output_tokens`, else caller default |
| `reserved_for_system_tokens` | measured from assembled system instruction items |
| `reserved_for_tool_tokens` | measured from tool-schema items (0 when unused) |
| `available_for_context_tokens` | derived: window − output reserve − system − tool |
| `used_tokens`, `remaining_tokens` | maintained by `try_reserve()` |
| `declared_required_window_tokens` | Pass-1 declaration from §1.4, for shortfall reporting |

Methods: `try_reserve(n) -> bool`, `release(n)`, `is_over_budget()`, `shortfall_tokens`.
All non-negative ints; construction validates `available >= 0` and raises
`InvalidBudgetError` otherwise (never a negative or silent budget).

### 3.2 Model-awareness, without hardcoding M6

The window comes from the registry, not from constants:
`ModelMetadata.context_window_tokens` and `ModelMetadata.max_output_tokens` are **verified to
already exist** in `ai_infrastructure/metadata.py:249-250`, and
`RoutingRequest.min_context_window_tokens` (`metadata.py:303`) already expresses "I need at
least this much window". The engine therefore:

- accepts an explicit `context_window_tokens` override from the caller (the Router's choice),
- else reads it from injected model metadata,
- else falls back to a **conservative, explicitly-labelled default** that is *recorded on the
  observability record as an assumption* — never silently.

**No M6-specific numbers appear in production code.** M6 remains the authoritative node per
the frozen decision; this design neither encodes nor changes that.

### 3.3 Enforcement and overflow

1. Reserve system + tool budgets (measured, not guessed).
2. Admit all `required` items in rank order. If they exceed
   `available_for_context_tokens` → **`MandatoryContextOverflowError`**. Never truncate, never
   partially admit, never drop the tail silently.
3. Admit optional items in rank order while `try_reserve` succeeds.
4. First optional item that fails to fit ends admission for that rank tier; every remaining
   candidate is recorded as excluded with `budget_exhausted`.

Overflow is a *loud* failure by design. The recovery path is the caller's (re-plan, request a
larger window, or fail the task) — matching §16's "request a different execution strategy".

### 3.4 Token estimation (honest about being an estimate)

No tokenizer exists in the repo, and adding one would be a new dependency (forbidden this
gate). Design: a `TokenEstimator` **protocol** with one default implementation —
a documented, deterministic character-class heuristic tuned for code+prose, calibrated

---

## 4. Prompt Construction Design

### 4.1 One canonical path

`prompt_assembly.build_messages(items, budget, *, task) -> list[dict]` is the **single**
function that turns admitted `ContextItem`s into provider-neutral messages. It is the only
place prompt text is formatted. Engines may not build prompt strings.

```
Context selection → ordering → assembly → canonical message list
    → EXISTING provider adapter serialization (BaseProviderAdapter.normalize_messages)
    → model
```

`BaseProviderAdapter.normalize_messages` (`adapters/base.py:112`) is **unchanged** and remains
responsible for provider serialization. The engine emits the `{"role", "content"}` shape that
`normalize_messages` already consumes, so **no adapter change is required** and provider
neutrality is structural, not aspirational.

### 4.2 Determinism

Fixed section order — system → task → project → dependency → evidence → decision →
verification → execution. Within a section, the §2.3 rank order. Identical inputs produce a
byte-identical message list. This is what makes prompt-cache prefixes (§7) meaningful and what
Test 10 asserts.

### 4.3 Backward compatibility with the live path

`ExecutionContext.format_reasoning_prompt()` (`context.py:88`) is what the execution worker
uses today, and `normalize_messages` reads
`system/system_prompt/prompt/task/context/plan/evidence/diagnosis` from the payload dict.

**Compatibility strategy:** `format_reasoning_prompt()` keeps its existing return shape and
keys, but its *body* delegates to `prompt_assembly`. The existing regression test
`test_canonical_context_builder.py` asserts on `assemble_calls`, `project_files`, and the
`ExecutionContext` type — all preserved. `assemble_context()` keeps its exact signature
(dispatcher `dispatcher.py:141` calls it with those keywords); new behaviour arrives through
**optional keyword parameters with defaults**, so no call site changes.

The existing `else` fallback at `dispatcher.py:150` (direct
`ExecutionContext.from_task_definition`) remains; ADR-003's `context.assemble(stage=...)`
entry point is added as a thin alias, not a replacement.

---

## 5. Provenance

**No second provenance system.** ADR-003 §6 requires provenance of every included item; the
repo has two partial, incompatible shapes: `assemble_evidence()` in `execution/evidence.py`
(formatted strings like `(rank 1 | score 0.91 | python_source | src/foo.py:12-24)`) and
`CitationReference` in `power_engines/rag/grounding.py` (a customer-facing citation model).

`ContextProvenance` is the **internal** per-item audit record (`acquired_from`, `acquired_at`,
`source_ref`, `provider`). Existing mechanisms are **adapters into it**, not replacements:

- `ContextAssembler`'s knowledge citations → mapped into `ContextProvenance` on the way in
  (ADR-003: the engine composes that slice rather than replacing it).
- `GroundedContextBuilder`'s `CitationReference` → stays in power_engines; it serves
  customer-facing answer attribution, a different concern. A scoped specialization (§6.3).
- `assemble_evidence()` string formatting → left intact for existing callers; the canonical
  path uses structured fields instead.

This answers all five required questions — why selected, where from, why another excluded,
which source produced it, which item reached the model (from the record's

---

## 6. Existing-Assembler Convergence

No assembler is removed or rewritten for tidiness. Each gets an explicit classification.

### 6.1 `EngineeringContextBuilder` — **MERGE INTO CANONICAL PATH**

Already the ADR-003 implementation ("Canonical Implementation (ADR-003)", line 2) and already
live: imported at `composition_root.py:73`, constructed at `:275`, asserted by
`test_canonical_context_builder.py`. It becomes the **single engine**: it gains selection,
expansion, dedup, budget enforcement, observability, and delegation to `prompt_assembly`,
while keeping its signature and `ExecutionContext` return type. Its current additive body is
replaced by the pipeline, not wrapped in further layers.

### 6.2 `ContextAssembler` — **SCOPED SPECIALIZATION** (compose, do not replace)

ADR-003 §Consequences is explicit: *"The Knowledge Platform's existing assembler remains the
knowledge-scoped slice; the Context Engine composes it rather than replacing it."* It keeps its
`IContextAssembler` contract and its knowledge scoping.

Its two `Any`-typed dependencies (`context_window_manager`, `relevance_ranker`,
`context_assembler.py:24-25`) are a **typing gap, not a design gap** — the intent (rank by
relevance, fit to a window) is exactly what the canonical engine now implements natively.
Change: **type** them as `Protocol`s satisfied by the canonical scorer/window-fitter. Falsy /
`None` stays supported so no caller breaks. Ranking, trust filtering, dedup, and citation
assembly continue to happen in the knowledge slice; the engine treats its output as
*candidate input* and applies the global budget.

### 6.3 `GroundedContextBuilder` — **SCOPED SPECIALIZATION** (retain, with reason)

It serves customer-facing RAG grounding and answer verification (`GroundedContext`,
`GroundingVerifier`, `is_grounded`, `grounding_score`, `unsupported_claims`). That is
**answer-attribution and verification** — a different concern from general context selection.
Merging would drag customer citation semantics into the execution core and risk regressing
answer verification. Retained unchanged; it may *emit* `ContextItem`s via a small adapter so
its output flows through the canonical budget.

**Net: 1 canonical engine, 2 scoped specializations, 0 deletions.**

---

## 7. Cacheability Metadata

Provider-neutral **metadata only**. `ContextCacheability` enum:

| Value | Meaning |
|---|---|
| `STABLE_SYSTEM` | stable system instructions — same across tasks |
| `STABLE_PROJECT` | project rules, conventions, tool schemas |
| `TASK_DYNAMIC` | task objective, retrieved evidence, runtime state |
| `VOLATILE` | timestamps, iteration counters, prior-attempt records |

Rules, per RULE 11 and the mandate:

- The engine **marks** stable prefixes; it does **not** emit provider cache-control directives

---

## 8. Observability

`ContextAssemblyRecord` (new module) — **content-free by construction**. It stores ids,
categories, counts, token estimates, and reasons; it never stores context text. That satisfies
"must not leak sensitive customer content" structurally rather than by policy.

Fields: `task_id`, `stage`, `correlation_id`, `attempt_number`, `model_id`,
`declared_required_window_tokens`, `context_window_tokens`, budget snapshot
(`available/used/remaining`), `considered_count`, `selected_count`, `excluded_count`,
`selected` (id + category + tokens + cacheability + provenance ref), `excluded`
(id + category + reason), `category_breakdown`, `deduplicated_count`, `expansion`
(depth reached, items expanded, truncated-by-bound flag), `stable_prefix_tokens`,
`char_fallback_used`, `construction_duration_ms`, `budget_source`
(`caller` / `model_metadata` / `conservative_default`).

Emission: returned on the result object **and** logged once at INFO via
`logging.getLogger("autoforge.execution.context_builder")` — the logger the module already
uses (`context_builder.py:21`). No new telemetry dependency, no continuous instrumentation.

This is AutoForge application-level observability, explicitly *not* inference-lab telemetry.

---

## 9. Failure Semantics

New exceptions in `execution/errors.py`, following the existing `ExecutionError` hierarchy
(`errors.py:14`) and its `details`-dict convention:

| Condition | Behaviour |
|---|---|
| **Mandatory context exceeds budget** | `MandatoryContextOverflowError` — **hard fail, never truncate** |
| **Malformed context item** | `InvalidContextItemError` at construction; provider-supplied junk is quarantined as an excluded item, not fatal |
| **Missing provenance** | `MissingProvenanceError` for `required` items; for optional items provenance is back-filled from the gathering source and flagged `provenance_inferred=True` |
| **Dependency cannot be resolved** | `UnresolvableDependencyError` when the referrer is mandatory; optional referrers get `exclusion_reason="unresolved_dependency"` |
| **Token estimate unavailable** | Fall back to the character heuristic; if the budget is also unavailable, the 16000-char backstop applies and `char_fallback_used=True` is recorded |
| **Duplicate context** | Not an error — excluded with `duplicate_of:<id>` (auditable) |
| **Context source unavailable** | Capability-port failure is **non-fatal for optional context** (matching the builder's existing `logger.debug` tolerance at `context_builder.py:85,96,110,117`); fatal only if a mandatory source is unavailable → `ContextSourceUnavailableError` |
| **Optional retrieval failure** | Non-fatal, recorded in `excluded` with the reason; the operation proceeds |

Design rule: **fatal iff correctness is at risk.** Optional context degrades; mandatory
context fails loudly. This mirrors ADR-003's "failures are never silently dropped" while
keeping the live path's current resilience to capability hiccups.

---

## 10. Semantic-Correctness Boundary

The design keeps two classes of correctness strictly separate. **The ~40% strict correctness
observed with the HP 0.5B model is a model-capability limitation. It is not a Context
Engineering defect, and it is not a reason to lower Context Engineering requirements.**

### 10.1 Deterministic Context Engineering correctness (Gate 3 pass/fail)

Verifiable with **no model in the loop** — these are the acceptance gates: selection
correctness · ordering determinism · dedup correctness · token-budget enforcement ·
provenance completeness · dependency preservation · boundedness of expansion · mandatory-item
protection · no-silent-truncation · provider neutrality · observability completeness.

### 10.2 Model-mediated semantic correctness (reported, not gated)

answer correctness · constraint adherence · evidence grounding · dependency understanding ·
verification correctness · omission impact. These require an actual model and are **measured
and reported separately**. A PASS in §10.1 is **not** evidence for §10.2, and latency or
token-reduction gains alone can never establish a PASS.

Attribution guard: because the 0.5B ceiling confounds results, the semantic benchmark must
compare **full-context vs minimum-sufficient-context under an identical model and seed**. Any
correctness delta is then attributable to the context policy rather than to model capability.

  (`cache_control` has **zero** occurrences repo-wide, confirmed in Gate 1).
- No cache hit is ever claimed. The observability record exposes `stable_prefix_tokens` — a
  *local* measurement of how much of the prompt is cache-eligible — explicitly labelled an

---

## 11. 18-L Integration Boundary

Context Engineering participates in the canonical 18-L flow at exactly one position:

```
Intent → Strategic Planning → Workflow
   → [CONTEXT ENGINEERING]  ← assembles minimum sufficient, bounded, provenanced context
   → Knowledge / Memory      ← supplies candidates (engine consumes; never re-implements)
   → Model Allocation / Router ← provides the real context window (Pass 2)
   → AI Provider → Execution → Artifacts → Review → Verification
   → Recovery → Runtime State → Events → Completion / Approval → Delivery
```

Ordering: the engine runs **after** Workflow (it needs task + stage) and **concurrently with**
Knowledge/Memory (they are its candidate sources). It runs **before** Model Allocation in
Pass 1 (declared window) and consumes the settled window in Pass 2.

**This gate does NOT** implement the 18-L flow, orchestration, recovery, or certification. It
defines the boundary and the evidence later certification will require:

| Evidence for 18-L certification | Produced by |
|---|---|
| Context Assembly Record per operation | §8 |
| No mandatory-item loss under budget pressure | Tests 3, 7 |
| Bounded expansion proven | Test 5 |
| Deterministic prompt reproducibility | Test 10 |
| Full-vs-MSC semantic comparison at equal model/seed | §12.4 |
| Prompt-processing cost reduction without correctness loss | §12.4 |
| Provider neutrality | Test 12 |

Boundaries preserved: the engine is **stateless-ish** (ADR-003) — not a second retrieval,
trust, memory, or storage authority, and it holds no cross-task state.

---

## 12. Implementation Plan

### 12.1 File change plan (exact)

| File | Action | Justification |
|---|---|---|
| `execution/…/context_items.py` | **NEW** | canonical item, categories, provenance, cacheability |
| `execution/…/context_budget.py` | **NEW** | request-scoped model-aware budget (§3.1) |
| `execution/…/token_estimator.py` | **NEW** | `Protocol` + default heuristic; injectable |
| `execution/…/context_selection.py` | **NEW** | bounded expansion, deterministic rank, dedup |
| `execution/…/prompt_assembly.py` | **NEW** | the single canonical prompt constructor |
| `execution/…/context_observability.py` | **NEW** | content-free record |
| `execution/…/context.py` | **MODIFY** | add selected-items field; `format_reasoning_prompt` delegates to `prompt_assembly` |
| `execution/…/context_builder.py` | **MODIFY** | additive body → full pipeline; signature preserved |
| `execution/…/errors.py` | **MODIFY** | add `ContextEngineeringError` family |
| `knowledge_platform/…/context_assembler.py` | **MODIFY** | type the two `Any` deps as Protocols; behaviour unchanged |
| `execution/tests/test_context_selection.py` | **NEW** | Tests 1–5, 8, 9, 11 |
| `execution/tests/test_context_budget.py` | **NEW** | budget + overflow (Tests 6, 7) |
| `execution/tests/test_prompt_assembly.py` | **NEW** | Tests 10, 12 |
| `composition/tests/test_canonical_context_builder.py` | **EXTEND** | keep existing assertions; add determinism/observability |

**Deliberately not modified:** `adapters/base.py` (already consumes the canonical message
shape — no change needed), `router.py` (`context_window_tokens` already exposed),
`modernization/context_budget.py` (protected; different scope), `power_engines/…/grounding.py`
(retained specialization), `dispatcher.py` (call signature unchanged).

### 12.2 Migration / convergence strategy

Additive and reversible, in four ordered steps, each independently shippable:

1. **Add** new modules + error types. No behaviour change.
2. **Wire** `EngineeringContextBuilder` to run the pipeline, gated by a constructor flag
   `enable_context_engineering: bool = False` (default off ⇒ zero behaviour change on deploy).
3. **Enable** the flag in composition root; run the full existing test suite plus the 12 new
   tests. Verify the live-path regression test still passes unchanged.
4. **Converge** `ContextAssembler`'s `Any` deps to typed Protocols (no behaviour change).

The default-off flag means step 2 is a one-line revert, not a migration rollback.

### 12.3 Test strategy

Twelve required tests, all **deterministic and model-free**:

| # | Test | Assertion |
|---|---|---|
| 1 | Relevant context selected | a task-relevant evidence item is admitted |
| 2 | Irrelevant excluded | clearly irrelevant material never appears in output |
| 3 | Mandatory preserved | required items survive a budget that excludes all optional |
| 4 | Dependency expansion | a dependency of a required item is included |
| 5 | Dependency bound | depth/item caps enforced; cycle terminates |
| 6 | Budget enforcement | delivered tokens ≤ `available_for_context_tokens` |
| 7 | Oversized mandatory | `MandatoryContextOverflowError`; **nothing truncated** |
| 8 | Deduplication | duplicate excluded with `duplicate_of:<id>`; budget charged once |
| 9 | Provenance | every selected item resolves to a provenance ref |
| 10 | Prompt construction | identical inputs ⇒ byte-identical messages (10 repeats) |
| 11 | Cache metadata | stable items marked; **no provider cache directive emitted** |
| 12 | Provider neutrality | core modules contain no provider-specific identifier |

Additional invariants: cross-run determinism (§2.7), observability completeness (fields
present and content-free), backward compatibility (existing regression test unmodified), and
unchanged `ExecutionContext` return type.

  estimate, not a provider-side hit.
- Caching never justifies a larger prompt: an item is marked stable only **after** the budget
  has admitted it. Cacheability influences **ordering** (stable first, for prefix locality),
  never **admission volume**.
- If a future provider exposes real cache control, the `Protocol` seam is where it lands, with
  no change to selection, ordering, or budget logic.

`delivered_context_ids`).

against the M6/HP llama.cpp `prompt_n` values already recorded in the inference-lab
artifacts. The protocol exists so a real tokenizer can be injected later **without changing
selection logic**.

`estimated_tokens` is labelled an estimate in the field name, the observability record, and
the docs. Accounting therefore has a **safety margin** (configurable, default 10%) so
under-estimation cannot cause a real overflow. The repo's existing
`default_max_context_chars = 16000` is retained as a **last-resort character backstop** so no
existing caller can ever produce an unbounded prompt, even if no budget is supplied.

that does not exist in this repo, and near-dup is a precision risk for a correctness-critical
path. Recorded as a known limitation, not a silent gap.

### 2.7 Deterministic identity

`context_id = "ctx_" + sha256(f"{category}|{source.kind}|{source.ref}|{normalized_content}")[:16]`

Content-derived, not random. This single choice makes dedup, tie-breaking, dependency edges,
and provenance references all deterministic — and makes "same task ⇒ same prompt" a
testable property.

If Pass 2's window is smaller than Pass 1's declaration, the engine does **not** silently
degrade: mandatory overflow raises (§6) and the shortfall is reported so the Router can

### 12.4 Semantic evaluation plan (reported, never a substitute for §10.1)

Controlled A/B, **identical model + seed + temperature**, only the context policy differs:

- **Arm A (baseline):** full/unoptimized context.
- **Arm B (MSC):** minimum sufficient context.

Measure: semantic correctness rate, strict correctness rate, constraint adherence, evidence
grounding, dependency preservation, verification correctness, omission-impact failures,
input tokens, output tokens, prompt-processing time, end-to-end latency, generation throughput,
context-construction overhead.

Decision rule: if Arm B reduces prompt-processing cost **and** correctness is statistically
indistinguishable, the policy is validated. If correctness degrades materially, the policy is
**incorrect or incomplete** and the gate is **PARTIAL**, not PASS. Throughput is recorded but
never sufficient on its own. Arm A vs Arm B attribution is only valid at equal model/seed.

### 12.5 Risk matrix

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Token heuristic mis-estimates → real overflow | Medium | High | 10% safety margin; character backstop; `Protocol` allows a real tokenizer later |
| Over-truncation drops needed context | Low | **Critical** | mandatory protection + hard overflow error; Tests 3/7 |
| Under-inclusion degrades model answer quality | Medium | High | semantic A/B gate (§12.4); PARTIAL on regression |
| Breaking the live execution path | Low | High | default-off flag; signature preserved; existing regression test unmodified |
| `ContextAssembler` typing change breaks a caller | Low | Medium | `None`/falsy still supported; no behaviour change |
| Duplicate provenance systems proliferate | Low | Medium | single `ContextProvenance`; existing mechanisms adapted, not duplicated |
| Scope creep into 18-K/L or modernization | Medium | Medium | protected-file list (§13); no cross-package dependency added |
| Near-duplicate context not merged | Medium | Low | documented limitation; exact dedup only, by design |

### 12.6 Rollback strategy

- Steps 1 and 4 are pure additions → delete the new modules / revert the typing change.
- Step 2/3 → set `enable_context_engineering=False` (single constructor flag, no data
  migration, no persisted state, no schema change).
- No database, event-schema, or serialized-artifact change, so there is nothing to migrate
  backwards. The ADR-003 output contract stays valid in both states because the additive
  `ExecutionContext` fields carry defaults.

---

## 13. Protected Boundaries (no changes)

Per the mandate's protected-systems list, and verified against the live repo:

- **18-J** Durable Execution / Resumability / Idempotency — untouched, not reopened.
- **18-K** Runtime / Packaging / Delivery — untouched, not reopened.
- **Inference lab** — `gate-2.3-reconciliation/`, `gate-2.3-power-validation/`, and all
  qualified runtime/model evidence are read-only inputs. The ~61.9 tok/s qualification and the
  ~40% correctness figure are **infrastructure evidence**, not Context Engineering acceptance
  criteria and not an attribution target.
- **M6 authority model** — unchanged; no M6-specific constants in production code.
- **Qualified inference runtimes** — no runtime, model, or provider-locking change; no Ollama.
- **`ai_infrastructure/adapters/base.py`** — unchanged; provider serialization stays with the
  adapter.
- **`ai_infrastructure/router.py`** — unchanged; `context_window_tokens` already exposed.
- **`modernization/context_budget.py`** — protected; different scope, not "fixed" from here.
- **`power_engines/…/rag/grounding.py`** — retained scoped specialization, unchanged.
- **Phase 19 learning / self-improvement**, **security hardening**, **frozen 18-H work** —
  untouched.
- **Unrelated pre-existing worktree changes** — the 8 modified `packages/modernization/**` and
  `packages/security/pyproject.toml` files (mtimes Sep 22–23, pre-existing) are not mine and
  are not part of this design.

---

## 14. Gate 2 STOP CONDITION

**STOPPING HERE.** Design only: no source code, tests, dependencies, roadmap files, commits,
or pushes. Repository unchanged except for this report.

**Awaiting explicit approval before Gate 3 implementation.**

Summary of the three judgement calls that most shape this design, each flagged for review:

1. **`ContextWindowBudget` as a sibling, not a reuse of `ContextBudget`** (§3.1) — forced by
   verified package boundaries and job-vs-request granularity. `modernization` is left
   untouched.
2. **`EngineeringContextBuilder` is the engine; the other two assemblers are scoped
   specializations** (§6) — mandated by ADR-003's own Consequences clause, so no deletion
   occurs.
3. **Deterministic correctness is gated; model-mediated semantic correctness is reported**
   (§10) — the ~40% 0.5B figure is a model limitation and must not lower Context Engineering
   requirements, nor be claimed as an achievement.

fail over to a larger model. Context Engineering must not pretend a smaller window is fine.
