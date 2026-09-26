# Context Compaction — Gate 2 Architecture & Implementation Design

**Workstream:** 18-L — Context Compaction
**Gate:** 2 — Architecture & Implementation Design (**DESIGN ONLY**)
**Date:** 2026-09-26
**Status:** Design COMPLETE · Implementation NOT STARTED
**Not committed. Not pushed.**

**Inputs:** `context-compaction-gate1/CONTEXT_COMPACTION_ARCHITECTURE_AUDIT.md` (authoritative),
`18-j-defect-repair/18J_DEFECT_REPAIR_REPORT.md` (18-J re-frozen).

> **No production code was modified in this gate.** No compactor exists, no schema
> was created, no event or Model Router change was made, no worker model was
> selected, and no migration was created. All findings below are traced to actual
> code paths.

---

## 1. Executive Summary

Context Compaction is designed as a **deterministic-first, reference-based,
versioned, provenance-linked** capability sitting in one precisely bounded
position: **between accumulated history and Context Engineering's candidate
construction**.

```text
LoopIterationRecord history (unbounded, in-process)
        ↓  ── compaction boundary (durable, replayable) ──
CompactedContextRecord (bounded, versioned, content-free provenance)
        ↓
EngineeringContextBuilder._build_candidates   ← the ONLY integration point
        ↓
select_context (MSC: rank, dedup, budget)
        ↓
prompt_assembly.build_messages
        ↓
BaseProviderAdapter.normalize_messages → local runtime
```

**Core principle:** compaction is a *derived, rebuildable representation*. It
never owns authoritative state, never becomes a second context-selection
mechanism, and never requires a model for correctness.

| # | Decision | Rationale (evidence-based) |
|---|---|---|
| D-1 | Deterministic core; model-mediated only as optional, validated enrichment | Iteration history is already structured (E-9) and durably backed (E-18), so most compaction is lossless by reference. |
| D-2 | Reference-based over text-summarisation | `DurableArtifactCatalog` already stores content hashes and paths; referencing is lossless and auditable. |
| D-3 | Versioned + `supersedes` lineage | Matches 18-J `IdempotentOperationState` / `DurableArtifactState` (E-14, E-19). |
| D-4 | Reuse `IdempotentOperationState` for idempotency | §2 forbids redesigning 18-J; its `idempotency_key` + `request_fingerprint` is exactly what compaction needs. |
| D-5 | Content-free provenance | Extends the principle proven in `ContextProvenance` / `ContextAssemblyRecord` (E-25). |
| D-6 | Compaction runs **before** MSC selection, never after | Prevents double-budgeting and double-ranking (§21). |

---

## 2. Repository Evidence

Read from source, not inferred from filenames.

| # | Evidence | Location | Design consequence |
|---|---|---|---|
| E-1 | `ContextItem` carries `context_id` (content-derived), `depends_on`, `required`, `required_for`, `provenance`, `category` | `context_items.py:141` | Compaction keys/links/classes using the **existing** identity scheme — no parallel id system. |
| E-2 | `context_id = "ctx_" + sha256(category\|source\|ref\|normalized_content)[:16]` | `context_items.py:94` | Deterministic ids make compaction output deterministically derivable and idempotent. |
| E-3 | `ContextCategory`: 12 fixed values incl. `DECISION`, `VERIFICATION`, `DEPENDENCY`, `EVIDENCE`, `RUNTIME_STATE` | `context_items.py:46` | Preservation class derivable from `category` — no new taxonomy needed. |
| E-4 | `select_context`: price → split → expand → dedup → admit mandatory (hard fail) → admit optional by rank | `context_selection.py:145` | Compaction must run **before** this, else ranking/budgeting applies twice. |
| E-5 | Optional items over budget excluded with reason `budget_exhausted` | `context_selection.py:296` | G-3: budget pressure *drops* history. Compaction is the controlled alternative. |
| E-6 | `MandatoryContextOverflowError` is a hard failure | `context_selection.py:274` | Compaction must **never** be a back door around mandatory admission. |
| E-7 | `expand_dependencies` pulls deps and marks them `required=True` | `context_selection.py:135` | Dependency preservation already enforced; compaction preserves `depends_on`, not re-derives. |
| E-8 | `TokenEstimator` Protocol + deterministic `HeuristicTokenEstimator` (`safety_margin=1.10`) | `token_estimator.py:24` | Compaction cost accounting reuses this seam; no new tokenizer. |
| E-9 | `LoopIterationRecord` = `iteration, started_at, finished_at, action_plan, changed_files, commands_executed, evaluation, diagnosis, passed` | `models.py:359` | History is **already structured** — raw material for deterministic compaction, and the answer to G-1. |
| E-10 | Loop appends to `_iterations` and `context.prior_iterations`; only `last_evaluation`/`last_diagnosis` become items | `loop.py:87,287` | **G-1 confirmed at source.** |
| E-11 | `format_reasoning_prompt()` enumerates **all** prior iterations verbatim, unbudgeted | `context.py:123` | The legacy unbounded-growth path. |
| E-12 | `EvaluationResult`: *"Deterministic checks ALWAYS take precedence over model confidence"* | `models.py:182` | **Contradiction rule already exists in code.** Reuse, don't reinvent (§13). |
| E-13 | `EvaluationResult` separates `deterministic_checks` / `test_results` / `execution_results` / `qualitative_findings` (AI) | `models.py:188` | Deterministic-vs-model separation structurally available. |
| E-14 | `IdempotentOperationState`: `idempotency_key` + `request_fingerprint`; differing fingerprint ⇒ conflict | `runtime/models.py:735` | **Exactly the idempotency mechanism needed.** Reuse; do not redesign 18-J. |
| E-15 | `StateModel`: `frozen`, `extra="forbid"`, `version` (optimistic concurrency), `created_at`, `updated_at` | `runtime/models.py:324` | Compaction record extends `StateModel` to get concurrency free. |
| E-16 | `write_state(..., expected_version=...)` returns row revision, raises `VersionConflictError` | `persistence.py:1183` | The durable write seam. |

| E-17 | `EntityType`: `PROJECT, WORKFLOW, LOOP, TASK, WORKER, CHECKPOINT, RECOVERY, EXECUTION, EXECUTION_ATTEMPT, EXECUTION_CHECKPOINT, IDEMPOTENT_OPERATION, APPROVAL_REQUEST, DURABLE_ARTIFACT` | `runtime/models.py:127` | **No compaction entity type exists.** Adding one is a documented schema decision (§9/§20), not done here. |
| E-18 | `DurableArtifactState`: deterministic `artifact_id` from key, `content_hash`, `storage_path`, `logical_version`, `parent_artifact_id` | `runtime/models.py:883` | The reference substrate. Compaction references; never copies content. |
| E-19 | `DurableArtifactState`: *"existing key reused with a differing hash is rejected with a conflict error (unless… a legitimate new version)"* | `runtime/models.py:896` | The exact **supersession/conflict semantics** compaction mirrors. |
| E-20 | `CheckpointManager` creates `CheckpointState` with `state_snapshot`, `parent_checkpoint_id`, lineage | `checkpoint_manager.py:305` | Existing durable boundary + lineage model to reuse. |
| E-21 | `ConsequentialActionType`: `TECH_STACK_FINALIZATION, ARCHITECTURE_FINALIZATION, GIT_COMMIT, GIT_PUSH, DEPLOYMENT, PUBLISH, DESTRUCTIVE_CLEANUP` | `models.py:378` | Concrete, enumerable **Irreplaceable/governance** set (§14). |
| E-22 | `ExecutionGovernance.check_action` raises `GovernanceApprovalRequired`; a `REJECTED` gate returns `False` | `governance.py:74` | A rejected approval **must survive compaction** or a rejected action could reappear as available (§17). |
| E-23 | `KernelMemoryEngineAdapter.store_memory` appends to `self._local_memories` (in-process dict) | `kernel_adapters.py:535` | **G-2 confirmed**: Memory Engine is not a durable substrate. |
| E-24 | `assemble_evidence(hits, max_hits=5, max_content_chars=800)` truncates by **chars** | `evidence.py:14` | Char truncation is lossy and unattributed; a compaction reference is strictly better. |
| E-25 | `ContextAssemblyRecord` is content-free (no field can hold a payload) | `context_observability.py:47` | The observability precedent compaction matches (§25). |
| E-26 | Orchestrator builds `ExecutionContext(...)` **directly**, bypassing `EngineeringContextBuilder` | `orchestrator.py:1793` | A **second context-construction path** exists. Gate 3 scope item; not modified here. |
| E-27 | `RAGRetrievalEngine` is a Protocol; execution depends on it, not on knowledge_platform | `models.py:478` | Keeps compaction provider-neutral. |
| E-28 | `ContextEngineeringError` family (7) incl. `MissingProvenanceError`, `UnresolvableDependencyError`, `MandatoryContextOverflowError` | `errors.py:225` | Compaction errors extend this family, not a parallel taxonomy. |
| E-29 | `prompt_assembly.SECTION_ORDER` is a fixed 12-category order | `prompt_assembly.py:30` | Compacted records map onto existing categories; the single prompt constructor keeps working. |
| E-30 | `build_messages()` re-sorts via `sort_context_items` before rendering | `prompt_assembly.py:102` | Order-independence means compaction cannot break determinism by reordering. |

---

## 3. Gate 1 Finding Reconciliation

Gate 1's findings are **authoritative input**, neither reinterpreted nor silently
replaced.

| Finding | Gate 1 evidence | Gate 2 response | Status |
|---|---|---|---|
| **G-1** Iteration history structurally invisible | `distinct_iterations_represented: 0` | Confirmed at source (E-10). Compaction emits a **bounded, per-iteration structured record** so each iteration is distinguishable (§10). | **Addressed** |
| **G-2** Memory Engine not durable | `_local_memories` in-process | Confirmed (E-23). Memory explicitly **excluded** as a substrate; durable artifacts/checkpoints/idempotency records are the substrate (§22). | **Addressed** |
| **G-3** Budget pressure drops history | `budget_exhausted` | Confirmed (E-5). Compaction runs **before** selection and yields a bounded representation, so optional history is compacted rather than dropped (§7, §21). | **Addressed** |

### Additional source findings that change the design

| New | Evidence | Impact |
|---|---|---|
| **N-1** Iteration history is already *structured* | `LoopIterationRecord` (E-9) | D-1: deterministic extraction is viable; a model is largely unnecessary. |
| **N-2** A deterministic-vs-model precedence rule already exists in code | `EvaluationResult` (E-12) | Contradiction handling **reuses** this, not invented policy (§13). |
| **N-3** An exact idempotency mechanism already exists | `IdempotentOperationState` (E-14) | D-4: no 18-J redesign; compaction reuses it (§19). |
| **N-4** A second context path bypasses the builder | orchestrator (E-26) | Explicit Gate 3 scope decision, not silently ignored (R-9). |
| **N-5** Artifact supersession semantics already defined | `DurableArtifactState` (E-19) | Compaction mirrors this for its own records (§20). |

## 4. Current Context Accumulation Architecture (traced)

```text
EngineeringLoop.run()  [loop.py:142]
   while current_iteration < max_iterations:
       provenance = ArtifactProvenance(..., iteration=N)   [loop.py:151]
       plan / implementation / repair / diagnosis         [loop.py:161-228]
       record_diff_artifact / record_artifact(cmd log)    [loop.py:239,254]
       evaluate_attempt -> EvaluationResult               [loop.py:263]
       record_evaluation_artifact / record_diagnosis_artifact [loop.py:266,273]
       iter_record = LoopIterationRecord(...)             [loop.py:277]
       self._iterations.append(iter_record)              [loop.py:287]
       context.prior_iterations.append(iter_record)       [loop.py:288]
```

Two parallel accumulations, both in-process: `EngineeringLoop._iterations`
(loop-owned) and `ExecutionContext.prior_iterations` (threaded into the next
`assemble_context` via `dispatcher.py:141`).

Exactly **one** `EvaluationResult` / `DiagnosisReport` pair is carried forward
(`last_evaluation` / `last_diagnosis`); previous pairs are overwritten. This is
the structural cause of G-1: intermediate results exist in `prior_iterations` but
`_build_candidates` reads only `last_diagnosis` / `last_evaluation` (E-10), so
they never become context items.

The durable side-channel already captures the raw material: each iteration writes
`evaluation_report_iter_N.json`, `diagnosis_report_iter_N.json`,
`changes_iter_N.diff`, `cmd_<name>_iter_N.log` as **durable artifacts** with id +
content hash (E-18). Lossless reference-based compaction is therefore possible
today.

## 5. Durable State vs Working Context

`context != state` and `memory != durable state` are both **false equivalences**
the design rejects.

| Question | Answer (evidence-based) |
|---|---|
| **What is authoritative?** | `DurableExecutionStore`, `DurableArtifactCatalog` + `PhysicalArtifactStore`, `CheckpointManager`, `ApprovalStore`, canonical event history — all `StateModel`s in `PersistenceLayer` (E-15, E-16). |
| **What is a projection?** | `ExecutionContext` (incl. `prior_iterations`), `ContextItem`s, `CompactedContextRecord`, `ContextAssemblyRecord`. All rebuildable. |
| **What can be a reference?** | Anything already durable: artifact id + hash, checkpoint id, execution id, approval id, event id. |
| **What must stay inline?** | Current-iteration task objective, latest diagnosis/evaluation, and anything **Irreplaceable** (§6). |
| **What can be regenerated?** | Superseded iteration detail, command output, older evaluation/diagnosis prose — all present as durable artifacts. |
| **What needs historical retention?** | Committed artifacts, superseded compact versions, event history, promoted learnings. |
| **Referenced source unavailable** | Reported as explicitly unresolvable with a reason; **not** silently dropped and **not** fabricated. New error in the `ContextEngineeringError` family (E-28). |
| **Referenced source changed** | Detected via `content_hash` mismatch; re-derive or mark stale. Reuses 18-J conflict semantics (E-19). |
| **Provenance** | Content-free reference set (§12), mirroring `ContextProvenance` / `ContextAssemblyRecord` (E-1, E-25). |

> **Invariant:** compacted context is a *cache*. Delete it and nothing is lost.

## 6. Information Preservation Model

Derived from actual AutoForge structures, not invented categories.

### Irreplaceable — never lost, dropped, or model-transformed

| Instance | Where it lives (evidence) |
|---|---|
| Task objective, name, description, input_data | `TaskDefinition` → `ContextItem(category=TASK, required=True)` (E-3) |
| Architectural / tech constraints | `ContextItem(category=PROJECT, SYSTEM)`; strategic engine output |
| Governance-gated actions | `ConsequentialActionType` (7 values, E-21) |
| Human approvals / rejections | `ApprovalStore`, `ExecutionGovernance` gates (E-22) |
| Latest unresolved failure mechanism | `DiagnosisReport` → `ContextItem(category=VERIFICATION, required=True)` |
| Acceptance criteria | `TaskDefinition` / review `QualityGate` |
| Current execution status | `LoopStatus`, `ExecutionState` (E-9) |

**Rule:** verbatim and inline; never summarised; never model-produced.

### Reconstructable — safely replaced by reference

| Instance | Reconstructed from |
|---|---|
| Prior iteration plans | `LoopIterationRecord.action_plan` (E-9) |
| Command output | `cmd_*_iter_*.log` artifact (E-24) |
| Evaluation detail | `evaluation_report_iter_*.json` + content hash (E-18) |
| Diagnosis prose | `diagnosis_report_iter_*.json` artifact |
| Diffs | `changes_iter_*.diff` artifact |
| Workspace file list | re-gathered each assembly |
| Retrieved knowledge | `RAGRetrievalEngine` re-retrieval (E-27) |

**Rule:** replaced by `artifact_id` + `content_hash` + `logical_version` —
**lossless**, because the content still exists durably.

### Ephemeral — may disappear after the operation

Redundant/duplicate items (already deduplicated by `content_digest`, E-2),
superseded rank-excluded items (`exclusion_reason` recorded), transient prompt
scaffolding (E-29), token-estimation scratch (E-8).

**Rule:** discardable **only after** being recorded in the compact record's
`superseded` lineage, so an audit can see what was dropped.

> **Anti-misclassification guard:** an item is Ephemeral only if it is derivable
> by the deterministic reconstruction path above. Anything not reconstructable
> and not Irreplaceable defaults to **Historical**, never Ephemeral. The default
> is safety, not brevity.

### Historical — retained, not injected

All committed artifacts (E-18), superseded compact versions (§20), event history,
promoted project learnings.

**Rule:** retrievable by id for audit/debug/replay/dispute/learning; **not**
injected into every operation.

## 7. Compaction Boundary

### Position in the canonical flow

```text
Intent → Strategic Planning → Workflow
   → Context Engineering
        → [ COMPACTION BOUNDARY ]        ← compaction runs HERE
        → _build_candidates
        → select_context (MSC)
        → prompt_assembly
   → Model Allocation / Router → Provider → Execution
   → Artifacts → Review → Verification → Recovery → Runtime State
   → Events → Completion/Approval → Delivery
```

**Before or after selection: BEFORE.** Compaction transforms *accumulated
history* into a bounded candidate representation; Context Engineering then selects
from it. Compacting after selection would mean the model already saw the
uncompacted context, and would apply budgeting twice (E-4).

### When compaction MAY occur

| Boundary | Rationale (evidence) |
|---|---|
| **End of an engineering-loop iteration** | `LoopIterationRecord` already appended (E-9, `loop.py:287`) and its artifacts already committed (E-18) — the durable source exists *before* compaction. |
| **On a durable checkpoint** | `CheckpointManager` already defines this boundary with lineage (E-20). |
| **On budget pressure** | `ContextWindowBudget` exposes remaining tokens *before* selection (E-4/E-5), so compaction can preempt `budget_exhausted`. |
| **On resume/recovery start** | Deterministic and required for correctness. |
| **Between workflow tasks** | `prior_iterations` is re-threaded at dispatch (`dispatcher.py:141`). |

### When compaction MUST NOT occur

| Prohibited | Reason |
|---|---|
| Inside/after `select_context` admission | Double-budgeting and double-ranking (E-4). |
| Between mandatory and optional admission | `MandatoryContextOverflowError` must remain the hard failure (E-6). |
| Inside `prompt_assembly` | That is the single prompt constructor; compaction must not become a second prompt builder. |
| On an **Irreplaceable** item | §6 rule. |
| While referenced durable sources are uncommitted | A reference must point at committed content (E-18). |
| On a partially written compact record | §18 partial-completion rule. |

### What enters / exits

**In:** `ExecutionContext.prior_iterations` (E-9), superseded
`last_evaluation`/`last_diagnosis` detail, accumulated optional items excluded for
budget (E-5).

**Out:** a bounded set of `ContextItem`s in existing categories (E-3) — so
`select_context` and `prompt_assembly` are completely unchanged — plus a durable
`CompactedContextRecord` for audit.

### Between model calls / workflow steps / durable boundaries

All three are permissible under the boundary table. Between-model-call and
between-workflow-step compaction are the *same mechanism* triggered at different
points, not different code paths. Across durable execution boundaries compaction
is permitted but must be **reconstructible from 18-J state**, so an interrupted
compaction is re-derived rather than resumed from partial state.

## 8. Canonical Compaction Lifecycle

```text
 1. TRIGGER     deterministic predicate fires (§16)
 2. GATHER      read prior_iterations + current items (read-only)
 3. CLASSIFY    assign preservation class per item (§6)
 4. RESOLVE     for Reconstructable: resolve durable artifact ref + hash (E-18)
 5. EXTRACT     deterministic structured projection (§15)
 6. [OPTIONAL]  model-mediated enrichment (§16) — off by default
 7. VALIDATE    schema, provenance, budget bound, unsupported-claim check (§17)
 8. CLAIM       idempotency key + fingerprint (§19) via IdempotentOperationState
 9. PERSIST     durable write with optimistic versioning (E-16)
10. PROMOTE     mark current only after validation + persistence succeed
11. EMIT        content-free observability record (§25)
12. HANDOFF     candidates flow into _build_candidates → select_context
```

Steps 1–5 and 7–12 are **fully deterministic**. Step 6 is optional. Step 10 is
the only promotion point: a record that is not validated and persisted is never
authoritative.

## 9. Compaction Data Contract

**Proposed — NOT implemented.** Extends `StateModel` (E-15) to inherit
`version`/`created_at`/`updated_at`/frozen/`extra="forbid"`, following the
`DurableArtifactState` (E-18/E-19) and `IdempotentOperationState` (E-14) shapes.

```python
class CompactionMethod(str, Enum):
    DETERMINISTIC   = "deterministic"     # default, always available
    HYBRID          = "hybrid"            # deterministic + validated model stage
    MODEL_MEDIATED  = "model_mediated"    # only if explicitly enabled later

class PreservationClass(str, Enum):
    IRREPLACEABLE   = "irreplaceable"
    RECONSTRUCTABLE = "reconstructable"
    EPHEMERAL       = "ephemeral"
    HISTORICAL      = "historical"

class ValidationStatus(str, Enum):
    PENDING = "pending"; VALID = "valid"; REJECTED = "rejected"

class CompactedContextRecord(StateModel):
    # identity: deterministic, like context_id (E-2) / artifact_id (E-18)
    compaction_id: str          # "cmp_" + sha256(scope+fingerprint)[:16]
    idempotency_key: str
    request_fingerprint: str    # sha256 over canonicalized source (E-14 pattern)

    # scope
    task_id: str
    execution_id: uuid.UUID | None
    workflow_id: uuid.UUID | None
    correlation_id: uuid.UUID | None
    source_scope: str           # "prior_iterations" | "budget_excluded_items" | ...

    # versioning
    compaction_version: int = 1
    policy_version: int = 1
    supersedes: str | None      # previous compaction_id (E-19 lineage)
    logical_version: int = 1

    # content (bounded)
    items: tuple[ContextItem, ...]          # existing categories (E-3)
    item_count: int
    durable_refs: tuple[DurableRef, ...]    # artifact_id + content_hash + version

    # classification
    preservation_breakdown: dict[str, int]
    loss_classification: str      # "lossless_by_reference" | "loss_aware"
    completeness: str             # "complete" | "partial_unresolvable"

    # method / provenance (content-free)
    compaction_method: CompactionMethod
    provenance: CompactionProvenance
    model_id: str | None = None        # only if model-mediated
    provider_id: str | None = None    # only if model-mediated

    # validation
    validation_status: ValidationStatus
    validation_reasons: tuple[str, ...] = ()
    estimated_tokens: int = 0         # via TokenEstimator (E-8)
```

**Contract properties:** provider-neutral (no runtime import), deterministic where
possible, auditable (content-free provenance), versionable, provenance-linked,
recoverable, bounded (`estimated_tokens` enforced), and **compatible with Context
Engineering** — `items` are ordinary `ContextItem`s, so `select_context` and
`prompt_assembly` need no change (E-4, E-29, E-30).

**Rejected from the brief's candidate field list:** `summary` (free text is lossy
and unauditable — references replace it), `source_hash` (subsumed by
`request_fingerprint`), `source_version` (subsumed by `policy_version` +
`logical_version`), `source_context_id` (compaction is 1-to-many over items, so it
is `items[].context_id`, E-1).

**Schema decision required (not made here):** no `EntityType` exists for
compaction (E-17). Gate 3 must choose (a) a new `EntityType` + `StateModel` row,
or (b) storing the record as a durable **artifact** via `DurableArtifactCatalog`,
which yields content-hash integrity and 18-J idempotent replay for free
(E-18/E-19). **Recommendation: (b)**, avoiding any change to the durable state
model (§32).

## 10. Iteration History Representation (answers G-1)

Each iteration becomes **its own explicit, addressable item** rather than being
concatenated or discarded. Existing `ContextCategory` values are reused (E-3), so
no new category is needed.

| Field on `ContextItem` | Value (E-1) | Purpose |
|---|---|---|
| `source.kind` | `"iteration"` | Distinguishes history from live candidates |
| `source.ref` | `f"iter-{n}"` | Stable per-iteration address |
| `category` | `VERIFICATION` if the iteration failed; `EXECUTION` if it passed | Lets MSC rank them naturally (E-3) |
| `content` | Bounded projection: objective → action → evidence refs → result → correction → decision → status | Answers "attempted / happened / learned / changed / unresolved" |
| `required` | `True` only for the **latest** iteration | Active failure stays inline; older ones optional (E-6 safety) |
| `depends_on` | `ctx_…` of the immediately preceding iteration | Preserves the causal chain (E-7) |
| `provenance` | `ContextProvenance(acquired_from="engineering_loop", source_ref=f"iter-{n}", inferred=False)` | Attributable, not inferred |
| `relevance` | Decays with iteration age | Lets MSC deprioritise old history naturally |

**What is preserved, and how:**

- **Objective** — inherited from the task item; never duplicated.
- **Action** — `action_plan` projection (Reconstructable → referenced).
- **Evidence** — artifact refs for evaluation/command output (Reconstructable).
- **Result** — `passed` / `EvaluationStatus`, kept **inline** (token-cheap fact).
- **Failure + correction** — `DiagnosisReport` mechanism, inline for the latest
  iteration, referenced for older ones.
- **Decision** — an explicit `DECISION`-category item when a repair strategy was
  chosen; otherwise the strategy projection.
- **Status** — "current" / "superseded by iter-N+1", derivable from `source.ref`
  and `depends_on`.

**Explicitly rejected:** concatenating all iterations into one large item
(reproduces G-1's invisibility in another form), and simply discarding older ones
(destroys the causal chain, contradicts §6).

## 11. Dependency Preservation

A compact representation that keeps text but loses relationships is **not
acceptable**, so edges are preserved structurally, not narratively.

| Relationship | Existing carrier | Compaction rule |
|---|---|---|
| context item → dependency | `ContextItem.depends_on` (E-1) | **Copied verbatim**; never re-derived. Compaction must not invent or resolve edges. |
| mandatory → dependency | `expand_dependencies` sets `required=True` (E-7) | Unchanged: compaction runs *before* selection, so MSC still owns this. |
| iteration → previous iteration | `depends_on` chain (§10) | Preserved so the causal chain is traversable. |
| item → artifact | `ContextItem.source` + `ContextSource.ref` (E-1) | Preserved, plus the durable ref resolved in §9. |
| item → provenance | `ContextProvenance` (E-1) | Preserved verbatim. |
| artifact → version/parent | `logical_version`, `parent_artifact_id` (E-18) | Referenced, never flattened. |
| compaction → prior compaction | `supersedes` (E-19 pattern) | Explicit lineage. |
| task → workflow/execution | `ExecutionContext.workflow_id` / `correlation_id` | Preserved on the record (§9). |

**Identity reuse (no parallel system):** `context_id` for items (E-2),
`artifact_id` + `content_hash` for durable refs (E-18), `compaction_id` derived
the same way (E-2 pattern). Because `build_messages()` re-sorts by `rank_key`
(E-30), compaction **cannot** break determinism by reordering, and the canonical
prompt constructor stays the only renderer.

> **Invariant:** compaction is edge-preserving. If a dependency cannot be
> represented, the item is rejected (not emitted with a dangling edge) —
> consistent with `UnresolvableDependencyError` (E-28).

## 12. Provenance

A future operation must be able to answer *"where did this come from?"* without
the compact record ever holding a payload — the discipline already proven by
`ContextProvenance` (E-1) and `ContextAssemblyRecord` (E-25).

```python
class DurableRef:            # reference only — no content
    artifact_id: str
    content_hash: str        # detects change (E-18)
    logical_version: int
    artifact_type: str

class CompactionProvenance:  # content-free by construction
    acquired_from: str       # "engineering_loop" | "budget_excluded_items" | ...
    source_ref: str          # scope identifier
    provider: str = ""       # allocator/provider id ONLY if model-mediated
    acquired_at: str = ""
    inferred: bool = False
    source_context_ids: tuple[str, ...]      # ctx_ ids (E-2)
    source_artifact_refs: tuple[str, ...]   # artifact ids
    source_execution_id / task_id / correlation_id
    compaction_method: str
    policy_version: int
```

**Available provenance sources (verified):** user input (`TaskDefinition`),
repository artifact (`PhysicalArtifactStore`), test result
(`EvaluationResult.test_results`), runtime state (`StateModel`s), review result
(`ReviewEngine`/`QualityGate`), durable record (`DurableArtifactState`,
`IdempotentOperationState`); model output is **not** a verification source.

> **Compaction never converts model inference into verified fact.** A
> model-produced field is marked `compaction_method=model_mediated` with its
> `provider` and (if applicable) a confidence value, and is treated as
> *unverified* until independently confirmed. This mirrors the existing
> confidence-gated promotion in `EngineeringLearningEngine`.

## 13. Contradiction Handling

Compaction must **never silently collapse a contradiction into a single
statement**. Resolution is delegated to the precedence rule that already exists
in the codebase (E-12), not to a new compaction policy.

**Reused rule (E-12):** `EvaluationResult` — *"Deterministic checks ALWAYS take
precedence over model confidence."*

| Contradiction type | Handling | Authority |
|---|---|---|
| **Model conclusion vs test evidence** | Deterministic wins. The model's claim is retained but **marked superseded** and linked to the deterministic evidence ref. | E-12/E-13 — `deterministic_checks`, `test_results`, `execution_results` |
| **Earlier assumption vs new verified fact** | Newer verified fact **supersedes**; the earlier item is retained with supersession metadata, never deleted. | §20 lineage |
| **Requirement vs later user correction** | The correction supersedes. Both are Irreplaceable-class; the superseded one is retained as Historical with `superseded_by`. | `TaskDefinition` + §6 |
| **Two diagnoses disagreeing** | **Marked UNRESOLVED** and retained. Never auto-resolved — silently picking one would be a correctness bug. | §6 Irreplaceable |
| **Model-vs-model disagreement** | Both retained, each attributed to its own `provider`/`model_id`; no adjudication. | §24 |
| **Stale referenced artifact** | `content_hash` mismatch marks the *reference* stale, not the fact. Re-resolve or mark `partial_unresolvable`. | E-18/E-19 |

**Mechanism:** a supersession edge carried alongside `depends_on`. Compaction never
resolves a contradiction; it only *records* it with evidence links. A
contradiction is "resolved" only when a deterministic source determines the
outcome (E-12/E-13) or a human approval decides it (§14).

> **Invariant:** a contradiction is either explicitly superseded with a recorded
> authority, or explicitly marked unresolved. Never silently dropped.

## 14. Approval / Governance Preservation

Approvals are the highest-risk information to lose: a compacted-away rejection
could make a **rejected action reappear as available**.

1. `ConsequentialActionType` (7 values, E-21) and any `ApprovalGate` outcome
   (E-22) are **Irreplaceable** — verbatim, inline, never compacted, never
   model-transformed.
2. A `REJECTED` gate **must be represented explicitly**. Compaction must not
   convert "rejected" into "absent" — E-22 returns `False` for a rejected gate,
   whereas absence would read as "never asked".
3. Compaction **cannot** grant, revoke, or infer approval. It only carries
   approval state as a projection of the authoritative `ApprovalStore`.
4. A `PENDING` approval is Irreplaceable and must be surfaced, not compacted
   away — otherwise an operation could proceed past a gate it should have
   stopped at.
5. The approval store's `sanitize_payload` semantics are preserved: compaction
   does not widen what is stored about an approval.

> **Invariant:** `GovernanceApprovalRequired` behaviour (E-22) is completely
> unaffected. Compaction runs on *context*; governance is evaluated on *actions*
> at the point of use. The two never share a path.

## 15. Deterministic Compaction

**The default and the correctness baseline.** No model is required for any part.

| Step | What it does | Evidence basis |
|---|---|---|
| **Classification** | Map each item to a preservation class from `category`, `required`, and source kind. | E-1, E-3, E-6 |
| **Reference substitution** | Replace a Reconstructable payload with `artifact_id` + `content_hash` + `logical_version`. | E-18 |
| **Structured projection** | Fixed field order per `source.kind` (iteration: objective → action → evidence → result → correction → decision → status). | E-9, §10 |
| **Supersession marking** | Compute supersession edges from `logical_version` / iteration order. | E-19, §13 |
| **Relevance decay** | Deterministic function of iteration age, so MSC can rank. | E-1, E-3 |
| **Boundedness** | Hard cap via `TokenEstimator`; over-cap items are **referenced**, never truncated mid-text. | E-8, E-24 |
| **Idempotency key** | `sha256` over the canonicalized source set + `policy_version`. | E-2, E-14 |

**Why deterministic is the default:** iteration history is already structured
(E-9), durable artifacts already hold raw content with hashes (E-18), and
`context_id` is already content-derived (E-2). A model would add cost, latency
and non-determinism to a job that is provably doable deterministically.

> **Never done by a model:** classification, supersession, reference resolution,
> idempotency, validation, promotion.

## 16. Optional Model-Mediated Compaction

**Off by default. Not implemented in Gate 3.** Specified so the boundary is
designed now rather than improvised later.

| Aspect | Design |
|---|---|
| **Role** | Enrich unstructured residue only (e.g. prose in a diagnosis) into declared schema fields. Never classification, references, or promotion. |
| **Input** | A **bounded, pre-selected** window — never the full history. |
| **Output** | Structured fields matching a fixed, versioned schema; free text rejected. |
| **Context budget** | Its own bounded budget via the existing `ContextWindowBudget`; independent of the operation's budget. |
| **Model allocation** | Via the **existing** `ModelAllocationPort` / Model Router (§23). No hard-coded model. |
| **Provider neutrality** | No Ollama, no runtime assumption; follows `LocalRuntimeProviderAdapter` conventions. |
| **Fallback** | Deterministic only. Model failure **degrades to deterministic**, never fails the operation. |
| **Timeout** | Bounded; on timeout the deterministic result stands. |
| **Failure handling** | Reject the model output; keep the deterministic record as current. |
| **Validation** | §17, plus every model-produced field must be schema-valid, attributable, and **flagged unverified**. |
| **Provenance** | `compaction_method=hybrid`, `provider`, `model_id`, `inferred=True` on model-derived items. |
| **Replay** | Same inputs + policy + model id ⇒ same record. Different model ⇒ different fingerprint ⇒ new version (§20). |
| **Cost / latency** | One extra routed call per compaction, amortized across the iterations it saves. Budget-bounded and optional. |

> **Critical rule (honoured):** a model-generated summary **MUST NOT** silently
> become authoritative system state. It becomes authoritative only when (a)
> schema-valid, (b) deterministically validated, and (c) explicitly promoted —
> never merely because a model produced it.

**Unsupported-claim prevention:** any model-produced claim that cannot be traced
to a source ref is **rejected at validation**, not downgraded. A model may not
introduce facts absent from its input.

## 17. Validation Contract

Validation is **deterministic** and runs before promotion (§8 steps 7/10). A
record failing any check is never authoritative.

| # | Check | Rule | Failure |
|---|---|---|---|
| V-1 | **Schema** | Conforms to `CompactedContextRecord`; `StateModel` guarantees `extra="forbid"`, frozen (E-15). | Reject |
| V-2 | **Required provenance** | Every mandatory item has non-empty `provenance.acquired_from` — mirrors `MissingProvenanceError` (E-28). | Reject |
| V-3 | **Reference integrity** | Every `DurableRef` resolves to a **COMMITTED** artifact whose `content_hash` matches. | Reject / re-resolve |
| V-4 | **Dependency integrity** | Every `depends_on` target exists in the record or candidate set. | Reject — mirrors `UnresolvableDependencyError` (E-28) |
| V-5 | **Irreplaceable present** | All Irreplaceable items present and inline. | Reject |
| V-6 | **Approval integrity** | No approval dropped, inverted, or converted to absence. | Reject |
| V-7 | **Bounded output** | `estimated_tokens` ≤ configured cap (E-8). | Reject |
| V-8 | **Determinism** | Re-deriving from the same sources yields a byte-identical result. | Reject |
| V-9 | **Version integrity** | Versions supported; `supersedes` chain resolvable. | Reject |
| V-10 | **No untraceable claims** | Every model-produced field traces to a source ref (§16). | Reject |
| V-11 | **Contradiction integrity** | No contradiction silently dropped (§13). | Reject |
| V-12 | **No cross-scope leakage** | Every item's `task_id`/`execution_id` matches the record scope. | Reject |
| V-13 | **Content-free provenance** | Provenance carries no payload (E-25). | Reject |

**New error types** (extending the existing family, E-28):
`CompactionValidationError`, `CompactionReferenceUnresolvableError`,
`CompactionPolicyVersionError` — all subclasses of `ContextEngineeringError`, so
existing error handling keeps working.

**Failure behaviour:** reject → keep the previous valid record current → the
operation proceeds with the previous (or uncompacted) context. **Compaction
failure never fails an engineering operation.**

## 18. Failure / Recovery Semantics

| Scenario | Behaviour |
|---|---|
| **Compaction raises** | Original context unchanged; operation proceeds; error surfaced (never swallowed). Previous compact record stays current. |
| **Validation fails** | Record rejected with reasons; not promoted; previous version retained. |
| **Model failure (optional stage)** | Degrade to deterministic; record `compaction_method=deterministic`. Operation unaffected. |
| **Source unavailable** | V-3 fails → `compaction_reference_unresolvable`; re-resolve or mark `partial_unresolvable`. **Never fabricate content.** |
| **Corrupted compact record** | Detected by re-derivation (V-8) or hash mismatch; fall back to the previous version, then to raw source records. |
| **Stale compact record** | `content_hash` mismatch on refs ⇒ regenerate; the *fact* is not considered changed by the record. |
| **Process crash** | Nothing partial survives: a record is durable only after step 9 and authoritative only after step 10. A crash mid-compaction leaves the previous record or none — both safe, because everything is re-derivable. |
| **Retry** | Idempotent via `idempotency_key` + `request_fingerprint` (§19). |
| **Partial completion** | **Cannot become authoritative.** Promotion is a single explicit step after full validation and persistence. |

> **Invariant:** because every trigger sits on a durable boundary (§7) and every
> record is re-derivable, **rollback is always possible** and no destructive
> compaction can occur without a recoverable boundary.

## 19. Idempotency

```text
same sources + same policy_version  →  same compaction_id → reuse existing record
same sources + different policy     →  different fingerprint → new logical_version
```

**Mechanism (reuses 18-J, §2-compliant):**
- `idempotency_key` = `f"compact:{source_scope}:{task_id}:{execution_id}"`.
- `request_fingerprint` = `sha256` over the canonicalized source set (context ids
  + content hashes + policy version) — the same shape as
  `IdempotentOperationState.request_fingerprint` (E-14).
- Claim/complete via the existing `DurableExecutionStore` idempotent operations
  (E-14), **not** by adding new durable-execution machinery.
- Same fingerprint on retry ⇒ return the existing record; **no duplicate work, no
  state mutation** — the same property proven by the 18-J repair
  (`test_repeated_replay_does_not_mutate_state`).
- Differing fingerprint on the same key ⇒ **conflict**, mirroring
  `DurableArtifactState`'s documented rule (E-19), not silent overwrite.

> **18-J is not modified.** Compaction *uses* 18-J's existing idempotent
> operation mechanism; it does not change 18-J semantics or code.

## 20. Versioning

| Version | Meaning | Change effect |
|---|---|---|
| `compaction_version` | Record schema version | Bump on any field change; older records stay readable. |
| `policy_version` | Compaction policy/classification rules | Change ⇒ different `request_fingerprint` ⇒ new `logical_version` (never mutate a released record). |
| `logical_version` | Monotonic per `idempotency_key` | Lineage via `supersedes` (E-19 pattern). |

**Rules:**
- Compacted records are **immutable** once persisted. A policy change produces a
  new record that `supersedes` the old; the old is retained (§6 Historical) for
  audit and rollback.
- `model_mediated` records additionally record `model_id`; a different model ⇒
  different fingerprint ⇒ a new version, so a model swap can never silently
  rewrite history.
- **No migration system is designed.** The existing architecture has no
  record-migration framework, and compaction records are a *cache* (§5), so the
  correct behaviour on an unsupported `compaction_version` is to **ignore and
  re-derive**, not migrate — simpler and strictly safer.

## 21. Context Engineering Integration

**Ownership boundary (single, unambiguous):**

| Concern | Owner | Compaction's relationship |
|---|---|---|
| Gather sources into candidates | Context Engineering (`_build_candidates`) | Compaction **feeds** this |
| Rank / score | MSC `select_context` (E-4) | Compaction **never** ranks |
| Budget enforcement | `ContextWindowBudget` (E-4) | Compaction **never** budgets the operation |
| Mandatory admission / overflow | MSC (E-6) | Compaction **never** overrides |
| Dependency expansion | `expand_dependencies` (E-7) | Compaction preserves edges; MSC still resolves them |
| Token estimation | `TokenEstimator` (E-8) | Compaction **uses** it for its own bound |
| Prompt rendering | `prompt_assembly` (E-29/E-30) | Compaction **never** renders prompts |

**Explicitly prevented (as required):**

| Risk | Prevention |
|---|---|
| **Double budgeting** | Compaction bounds only *its own* record; the operation budget is computed once, inside `_resolve_budget` (E-4). |
| **Double ranking** | Compaction sets `relevance` as an *input*; MSC alone produces final order via `rank_key` (E-1, E-4). |
| **Duplicated provenance** | Compaction reuses `ContextProvenance`; one provenance per item, not a parallel chain. |
| **Competing context selection** | Compaction emits candidates only; it cannot exclude, admit, or select. Exclusions remain MSC's (E-5). |
| **Compact-then-immediately-expand** | A reference is emitted only when the source is already durable and not already inline; V-3 enforces resolvability. |
| **References bypassing MSC** | Compacted items are ordinary `ContextItem`s through the same admission — no privilege gained. A referenced Reconstructable item stays **optional**, so it can still be excluded for budget (E-5). |
| **Compaction as alternative prompt builder** | Compaction never calls `build_messages`; it emits items only. `prompt_assembly` remains the single renderer (E-29). |

**Integration point (the only one):** inside
`EngineeringContextBuilder._build_candidates`, *after* live task/workspace/evidence
items are built and *before* `select_context` runs. Consequence:
`select_context`, `context_budget`, `context_selection`, `prompt_assembly`,
`context_observability` and `context.py` require **zero changes**.

**Compatibility with global CE = ON:** compaction is a *pre-selection* stage, so
it is reached only when `enable_context_engineering` is True — the current
production default. With CE OFF (rollback) it is never reached, so the rollback
path is untouched by construction.

## 22. Memory / Knowledge Integration

Gate 1's G-2 asked this explicitly. **Answered from code (E-23):**

| System | Role for compaction | Reason |
|---|---|---|
| **Memory Engine** | **Neither source nor substrate.** In-process dict (E-23), lost on restart. | Compaction must survive restart. Making Memory durable is **separate work**, not a prerequisite. |
| **Knowledge Engine** | **Neither source nor substrate.** Cross-task curated knowledge, confidence-gated promotion. | Compaction is intra-execution; injecting cross-project knowledge would change context correctness. |
| **RAG** | **Optional re-fetch source** for Reconstructable knowledge items (E-27). | Already a Protocol boundary; keeps compaction provider-neutral. |
| **Durable artifacts** | **THE authoritative reconstruction substrate** (E-18). | Content + hash + path, durable, versioned. |
| **Checkpoints** | **Rebuild anchors** for recovery/resume (E-20). | Define recoverable boundaries. |
| **Idempotency records** | **Idempotency substrate** (E-14). | Reuse 18-J; do not duplicate. |
| **Event history** | **Provenance references** only. | Referenced, never summarised into a competing history. |
| **Runtime state** | **Authoritative; never rewritten.** | §5. |

> **Design consequence:** compaction reads from **durable artifacts /
> checkpoints / idempotency records**, never from Memory. If a future gate makes
> Memory durable, compaction may *additionally* consult it — but must not require it.

## 23. Model Router Integration

**Compaction does not create a second allocation system.**

| Question | Answer |
|---|---|
| Uses the existing Model Router? | **Only** for the optional model-mediated stage (§16), via the existing `ModelAllocationPort` seam. |
| Requests a capability? | Yes — through the normal `RoutingRequest` path, not a bespoke selector. |
| Deterministic-only viable? | **Yes, and it is the default** — no model needed at all (§15). |
| Hard-coded models? | **None.** No M6, no worker model, no Ollama. |

**Protected in this gate and unmodified:** `ModelRouterService`, `RouterService`,
`CapacityAwareRouter`, `RouterModelAllocationPort`, provider adapters, reference
catalog. Compaction *consumes* these; it does not alter them.

**Budget isolation:** the optional compaction call has its own bounded budget so a
large compaction can never consume the operation's allowance or trigger
`MandatoryContextOverflowError` (E-6).

## 24. Future Worker Compatibility

The design must not assume one model, one provider, one worker, or one
conversation.

| Concern | Design property |
|---|---|
| **Worker handoff** | Records are keyed by `task_id`/`execution_id`, not worker, so any worker can consume them. |
| **Parallel reasoning** | Two workers may produce different items for one scope; compaction merges deterministically (dedup by `content_digest`, E-2) and never arbitrates meaning (§13). |
| **Worker-specific context** | Worker identity lives in `provenance.provider`/`model_id`, so per-worker context is a *view*, not a separate store. |
| **Shared compacted context** | One canonical record per `idempotency_key`; workers read the same one, avoiding divergence. |
| **Conflicting worker outputs** | Retained and attributed; contradictions marked **unresolved** (§13). Never silently merged. |
| **Provenance** | Per-item `model_id`/`provider`, so a later worker can tell whose claim is whose. |
| **Isolation** | Cross-scope leakage rejected at validation (V-12). |
| **Context budgets** | Per-operation budgets remain MSC's; a worker cannot expand the shared budget. |
| **Replay** | `compaction_id` is content/policy-derived, not worker-derived, so replay is stable across worker changes (§19). |

> No worker models were selected and no multi-node inference was tested in this
> gate, per §33.

## 25. Observability

Answers the required questions, using the **content-free** discipline already
proven in `ContextAssemblyRecord` (E-25). No full prompt or context payload is
logged.

| Question | Field |
|---|---|
| Why was this information compacted? | `trigger` (`iteration_boundary`, `checkpoint`, `budget_pressure`, `resume`, `task_boundary`), `policy_version` |
| What was preserved? | `preservation_breakdown` (class → count), `item_count` |
| What was replaced by references? | `durable_refs` count, `reference_bytes_avoided` |
| What was omitted? | `loss_classification`, `superseded_count`, `omitted_reasons` (enumerated, never free text) |
| What source produced it? | `provenance.acquired_from`, `source_ref`, `source_context_ids` |
| Was validation successful? | `validation_status`, `validation_reasons` |
| How much was reduced? | `estimated_tokens` (E-8) before/after, `reduction_ratio` |
| Was loss intentional? | `loss_classification` (`lossless_by_reference` vs `loss_aware`) |
| Can the original be reconstructed? | `reconstructability` (count of refs with verified hashes / total) |

**Content-free enforcement:** the compaction record has **no field that can hold
a context payload** beyond its own bounded `items` tuple, and the *observability*
emission contains only counts, ids, categories, and enums — the same structural
guarantee `ContextAssemblyRecord` relies on.

**Log-emitted example (shape only):**
```json
{"compaction_id":"cmp_…","trigger":"budget_pressure","policy_version":1,
 "item_count":4,"preservation_breakdown":{"irreplaceable":1,"reconstructable":2,
 "historical":1},"durable_refs":3,"loss_classification":"lossless_by_reference",
 "reduction_ratio":0.62,"validation_status":"valid","reconstructability":1.0,
 "compaction_method":"deterministic"}
```

## 26. Security / Trust

| Threat | Mitigation |
|---|---|
| **Prompt injection surviving compaction** | Compacted items are re-validated (V-1…V-13) and enter the *same* prompt path; the boundary sanitizer applies unchanged. Compaction adds no new injection surface. |
| **Malicious instructions becoming durable-looking facts** | Model-produced fields require a traceable source ref (V-10) and are flagged `inferred=True` / `unverified`. A model cannot mint a fact. |
| **Provenance spoofing** | Provenance is content-free and structurally derived from the gathering source; it cannot be set by a model. |
| **Reference substitution attack** | V-3 verifies `content_hash` against the authoritative catalog (E-18). A swapped reference fails validation. |
| **Unauthorized durable references** | V-12 scope check: every ref must belong to the record's `task_id`/`execution_id`. |
| **Cross-task / cross-tenant leakage** | V-12 rejects out-of-scope items; references are scope-bound. |
| **Stale authorization** | Approvals are Irreplaceable and never compacted (§14); `REJECTED` is represented explicitly, never as absence. |
| **Hallucinated summaries** | V-10 rejects untraceable claims (§16). Deterministic-only mode has no such surface. |
| **Privilege escalation via compacted instructions** | Compaction cannot grant capability; governance runs at the point of action (E-22) and is untouched. |

> **Invariant:** compaction never strengthens trust. A derived record inherits the
> **minimum** trust of its sources; reference-based substitution cannot raise it.

## 27. Performance Objectives

**Primary objective: `semantic sufficiency + bounded context`.** Not maximum
compression. No performance experiments were run in this gate.

| Metric | What Gate 3/4 should measure | Target direction |
|---|---|---|
| **Context reduction** | `estimated_tokens` before vs after (E-8) | Bounded and stable; materially smaller than raw history |
| **Prompt token reduction** | Tokens reaching `build_messages` for a multi-iteration task | Measurable improvement vs the current G-1 behaviour |
| **Compaction overhead** | Wall-clock cost of the stage | Small relative to the model call it protects; deterministic path is CPU-only |
| **Latency** | Added latency per operation | No added *serial* model dependency on the deterministic path |
| **Storage overhead** | Bytes of the record + referenced metadata | Small — bounded and reference-heavy |
| **Reconstruction cost** | Time to re-expand a reference | Bounded; must justify the storage saved |
| **Model cost** (optional) | One routed call per compaction | Off by default; only paid when it buys correctness |

> **Explicitly not an acceptance signal:** raw token reduction alone. A compaction
> that shrinks context by dropping Irreplaceable information is a **failure**,
> however good the ratio (§28).

**Proposed method for Gate 3/4:** replay a recorded multi-iteration execution;
compare selected context and assembled prompt with and without compaction, using
the existing deterministic `TokenEstimator` (E-8) for reproducibility.

## 28. Acceptance Contract

### Deterministic acceptance (must pass)

| # | Criterion | Testable how |
|---|---|---|
| D-1 | Required facts preserved | Irreplaceable set ⊆ compacted items (V-5) |
| D-2 | Requirements/constraints preserved | Task/Project/System items present and inline |
| D-3 | Approvals preserved, never inverted | Outcomes identical pre/post; `REJECTED` present (V-6) |
| D-4 | Provenance preserved, content-free | Every mandatory item has provenance (V-2, V-13) |
| D-5 | Dependencies preserved | Every `depends_on` resolves (V-4) |
| D-6 | References resolvable | Every `DurableRef` → COMMITTED artifact, hash matches (V-3) |
| D-7 | Contradictions preserved/represented | None dropped (V-11) |
| D-8 | Version integrity | Versions supported, `supersedes` resolvable (V-9) |
| D-9 | Idempotency | Same sources ⇒ same `compaction_id`; repeat mutates nothing (§19) |
| D-10 | Bounded output | `estimated_tokens` ≤ cap (V-7) |
| D-11 | No unauthorized leakage | Scope check passes (V-12) |
| D-12 | Determinism | Byte-identical re-derivation (V-8) |
| D-13 | Reconstruction | Every ref re-expands to original content (hash-verified) |
| D-14 | MSC integrity unchanged | `MandatoryContextOverflowError` behaviour identical with compaction on |

### Semantic acceptance (evaluate in Gate 4 with real execution)

S-1 future-task correctness · S-2 reconstructability of necessary history ·
S-3 iteration understanding (§10) · S-4 decision continuity · S-5 recovery
continuity · S-6 absence of unsupported claims.

> **Gate 3 note:** semantic acceptance cannot be established without a running
> local runtime. The execution-dependent items are therefore
> **UNKNOWN — requires Gate 4 implementation evidence**; Gate 3 can prove only
> the deterministic set.

## 29. Rollback

| Question | Answer |
|---|---|
| **Can compaction be disabled?** | Yes — one constructor/config flag at the single integration point, mirroring `enable_context_engineering`. |
| **Already-compacted contexts?** | Retained but **ignored**; the uncompacted path is used. Nothing is destroyed. |
| **Can the source be reconstructed?** | **Yes** — compaction is derived and re-derivable (§5, §18). Sources are untouched. |
| **Fall back to the pre-compaction path?** | Yes, immediately and completely — failure already degrades to uncompacted context (§18). |
| **Configuration-only rollback?** | Yes for runtime behaviour. **No durable schema change required**, provided Gate 3 adopts §9 recommendation (b) (store as an artifact, no new `EntityType`). |
| **Durable schema changes?** | **No migration** (§20). Records are a cache; an unsupported version is ignored and re-derived. |

Rollback is **total, not degraded** — the same posture proven for Context
Engineering and the 18-J repair.

## 30. Gate 3 Implementation Plan

**Scope:** deterministic-only compaction. No model-mediated stage. No global
enablement.

```text
packages/execution/src/autoforge_execution/compaction/
    __init__.py
    compaction_schema.py       # §9 contract + §12 provenance (extends StateModel)
    compaction_policy.py       # §6 classification, §7 triggers, retention window
    compactor.py               # §15 deterministic core (reference substitution)
    compaction_validation.py   # §17 V-1..V-13
packages/execution/tests/
    test_compaction_schema.py
    test_compaction_policy.py
    test_compaction_determinism.py
    test_compaction_idempotency.py
    test_compaction_failures.py
    test_compaction_provenance.py
    test_compaction_iteration_history.py   # answers G-1
    test_compaction_msc_integration.py     # no double budget/rank; D-14
```

**Integration points (exactly two):**
1. `context_builder.py` — one call in `_build_candidates` before `select_context`
   (§21), plus an optional `compactor` constructor arg.
2. `composition_root.py` — wire the compactor, defaulting to **disabled**.

**Data contract:** §9, stored as a durable artifact (recommendation (b)).
**Tests:** §28 deterministic set D-1…D-14; semantic set deferred to Gate 4.
**Migration:** **none** (§9, §20, §29).

**Out of Gate 3 scope:** model-mediated stage, global enablement, worker
integration, Memory durability, changes to 18-J / 18-K / Model Router /
inference lab.

## 31. Gate 4 Verification Plan

**Deterministic:** the full D-1…D-14 suite plus the full existing regression
(execution, ai_infrastructure, composition, orchestration, review, workflows,
kernel, runtime, artifacts) with compaction enabled in test config, compared
against the Gate 4B baseline. **Zero new failures required.**

**Semantic (S-1…S-6):** replay a multi-iteration engineering task against a real
local runtime; evaluate iteration understanding, decision continuity, and absence
of unsupported claims.

**Failure/recovery:** inject each §18 scenario (validation failure, unresolvable
ref, corrupt record, model-stage failure when enabled, crash between persist and
promote) and assert the previous record stays current and the operation completes.

**Performance (§27):** measure using the deterministic `TokenEstimator` (E-8) for
reproducibility.

**Regression requirements:** 18-J, 18-K, Context Engineering, Model Router and
inference-lab suites unchanged and passing. A **negative-control test** must prove
that disabling compaction restores byte-identical pre-compaction behaviour.

## 32. Global Enablement Criteria

Compaction may be enabled globally only when **all** hold:

1. Gate 3 implemented; deterministic set D-1…D-14 passes.
2. Gate 4 verification passed, including semantic S-1…S-6.
3. Full regression shows **zero new failures** vs the Gate 4B baseline.
4. Rollback verified: disabling returns byte-identical pre-compaction behaviour,
   with no data loss.
5. Reconstructability ≥ 1.0 — every reference re-expands to hash-verified content.
6. Provenance/approval/contradiction invariants proven by test, not assertion.
7. A negative-control test proves a wrong implementation (dropping Irreplaceable
   items, or bypassing MSC) fails the suite.
8. `enable_context_engineering = True` remains the production default and is
   **not** weakened.
9. Semantic acceptance S-1…S-6 verified against a **real** local runtime.
10. Explicit sign-off that no protected system was modified.

**Not enabled in this gate.** Compaction ships default-off; global enablement is a
separate, later decision.

## 33. Alternatives Considered

| Alternative | Why rejected |
|---|---|
| **Free-text summarisation of history** | Lossy, unauditable, cannot express dependencies, violates §6 Irreplaceable. |
| **Compaction inside `prompt_assembly`** | Creates a second prompt path; `prompt_assembly` must stay the single renderer (E-29). |
| **Compaction after MSC selection** | Double budgeting/ranking; the model already saw the uncompacted context (E-4). |
| **Memory Engine as substrate** | Not durable (E-23); would depend on separate unfinished work. |
| **New `EntityType` for compaction** | Touches the protected durable state model (§35). Artifact storage gives hash integrity and 18-J idempotency free. |
| **A record migration system** | No existing framework; records are a cache, so ignore-and-re-derive is simpler and safer (§20). |
| **Model-mediated compaction by default** | Adds cost, latency, non-determinism and a hallucination surface for a provably deterministic task (E-9, E-18, §15). |
| **Compaction as a new service/package** | Would duplicate architecture; it belongs beside Context Engineering, which it feeds. |
| **Drop old iterations instead of compacting** | Destroys the causal chain, contradicts §6, loses "what was tried and why". |
| **Retire `format_reasoning_prompt()`** | Out of scope; it remains the CE-OFF rollback body (Gate 1 Q-5). |

## 34. Risks / Open Questions

| # | Risk / question | Severity | Status / mitigation |
|---|---|---|---|
| R-1 | Irreplaceable info silently lost | **High** | §6 rule + D-1/D-3 + V-5/V-6 |
| R-2 | Compaction becomes a second persistence system | **High** | §5 derived-only invariant + D-13 |
| R-3 | Model output treated as authoritative | **High** | §16 critical rule + V-10; model stage off by default |
| R-4 | Weakening MSC mandatory-overflow | **High** | §7 prohibition + D-14 |
| R-5 | Non-determinism breaks replay | Medium | §19 fingerprint + D-9/D-12 |
| R-6 | Compaction latency harms throughput | Medium | §27; deterministic path is CPU-only |
| R-7 | Scope creep into worker/Memory work | Medium | §30 out-of-scope list |
| R-8 | Duplicate of Memory/Knowledge | Medium | §22 relationship table |
| R-9 | **N-4: a second context path exists** (orchestrator builds `ExecutionContext` directly, E-26) | Medium | **Open.** Compaction reaches only the builder path. Gate 3 must route the orchestrator through the builder or document the exception. Not changed here. |
| R-10 | Retention thresholds are guesses | Medium | §27 — must be **measured** in Gate 3/4 |
| **Q-1** | Exact retention window (how many iterations stay inline)? | — | **UNKNOWN — requires Gate 3 implementation evidence** |
| **Q-2** | Budget-pressure floor value? | — | **UNKNOWN — requires Gate 3 measurement** |
| **Q-3** | Should `format_reasoning_prompt()` consume compact state? | — | **Open** (Gate 1 question, unchanged) |
| **Q-4** | Per-execution only, or project-level rollup? | — | **Open** — design assumes per-execution, the conservative default |
| **Q-5** | Is Memory durability a prerequisite? | — | **No** by design (§22); separate work item if pursued |

## 35. Protected Systems Verification

| System | Status in Gate 2 |
|---|---|
| 18-J repaired implementation | **Unmodified**; compaction reuses its idempotency mechanism without changing it (§19) |
| 18-J tests | **Unmodified** |
| Durable execution state machine (`validation.py`) | **Unmodified** |
| Artifact replay / idempotency semantics | **Unmodified** |
| 18-K runtime / packaging / delivery | **Unmodified** |
| Context Engineering implementation | **Unmodified** — compaction integrates *into* `_build_candidates` as an additive pre-selection stage |
| Global `enable_context_engineering = True` | **Verified still ON**; never weakened |
| M6 authority model / M1 / HP | **Unmodified**; no model hard-coded (§23) |
| Inference lab / Gate 2.3 throughput / 61.923 tok/s | **Unmodified**; no experiments run |
| llama.cpp / MLX infrastructure | **Unmodified**; provider-neutral design |
| Model Router | **Unmodified**; consumed, not changed |
| Event model / durable state model | **Unmodified**; §9 recommends artifact storage precisely to avoid touching them |

**Scope compliance:** no production source modified, no compactor implemented, no
schema created, no event/Model Router change, no worker model selected, no
benchmark run, no compaction enabled, no migration created, **no commit, no
push.**

## 36. Final Recommendation

> **PROCEED to Gate 3 — Implementation, deterministic-only, default-off.**

The design is complete and evidence-backed:

- **Single integration point** (§21) — `select_context`, `context_budget`,
  `context_selection`, `prompt_assembly` and `context_observability` need
  **zero changes**.
- **Deterministic by default** (§15) — no model required for correctness, because
  history is already structured (E-9) and durably backed (E-18).
- **Reuses, never redesigns** — 18-J idempotency (E-14), conflict semantics
  (E-19), `EvaluationResult` precedence (E-12), `ContextProvenance` (E-1),
  `TokenEstimator` (E-8), `StateModel` (E-15).
- **Derived-only** (§5) — deletion is lossless; rollback is total, not degraded.
- **G-1 addressed by design** (§10) — each iteration becomes an explicit,
  addressable, dependency-linked item rather than being concatenated or dropped.

**Three items Gate 3 must resolve, deliberately undecided here:**

1. **Storage decision** (§9) — artifact-backed recommended; a new `EntityType`
   would touch a protected model.
2. **Retention window and trigger thresholds** (§34 Q-1/Q-2) — must be
   *measured*, not guessed.
3. **R-9: the second context path** (E-26) — route it through the builder or
   document the exception.

**Explicitly deferred:** model-mediated compaction (§16), global enablement (§32),
worker-fleet integration (§24), Memory durability (§22).

> **No answer in this report is invented.** Where the repository does not yet
> provide evidence — retention thresholds, semantic acceptance, orchestrator-path
> coverage — the item is marked **UNKNOWN — requires Gate 3/Gate 4 evidence**.

---

## Appendix — Design-Quality Self-Check

| Question | Answer |
|---|---|
| What exactly is being compacted? | Superseded intra-execution history (§7, §13) |
| What must never be lost? | Irreplaceable set (§6), incl. approvals and constraints |
| What can safely become a reference? | Reconstructable set (§6) → durable artifacts |
| What can be reconstructed? | Everything Reconstructable; hash-verified (D-13) |
| Where does authoritative information live? | Durable stores (§5); never Memory (E-23) |
| How are iterations represented? | Explicit per-iteration items (§10) |
| How are dependencies preserved? | `depends_on` copied verbatim (§11) |
| How is provenance preserved? | Content-free reference set (§12) |
| How are contradictions handled? | Superseded-with-authority or marked unresolved (§13) |
| How do approvals survive? | Irreplaceable; `REJECTED` explicit, never absence (§14) |
| Can the system recover after restart? | Yes — records are re-derivable (§18) |
| Is compaction idempotent? | Yes, via 18-J fingerprint semantics (§19) |
| Can it be validated deterministically? | Yes — V-1…V-13 (§17) |
| What if model compaction fails? | Degrade to deterministic; never fail the operation (§16) |
| Can a model summary become authoritative? | **NO** unless independently validated and promoted (§16) |
| How does it interact with MSC? | Pre-selection only; MSC keeps ranking, budgeting, mandatory admission (§21) |
| Memory / Knowledge relationship? | Neither source nor substrate; durable artifacts are (§22) |
| Model Router relationship? | Consumes the existing allocator; creates no second one (§23) |
| Multiple workers? | Provider-agnostic records, per-item provenance, no worker coupling (§24) |
| How is information loss measured? | `loss_classification`, `reduction_ratio`, `reconstructability` (§25) |
| How is semantic sufficiency verified? | S-1…S-6, deferred to Gate 4 with a real runtime (§28) |
| How can the system roll back? | Configuration-only; total, not degraded (§29) |
| Can the original be reconstructed? | Yes — hash-verified re-expansion (D-13) |
