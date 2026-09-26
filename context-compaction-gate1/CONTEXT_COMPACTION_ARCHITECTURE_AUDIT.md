# Context Compaction — Gate 1 Architecture Audit

**Workstream:** 18-L — Context Compaction
**Gate:** 1 of N — Audit / Design (no implementation)
**Date:** 2026-09-26
**Status:** Gate 1 complete — recommendation to proceed to Gate 2 design
**Not committed. Not pushed.**

**Prerequisites verified before this audit began:**
- Context Engineering: COMPLETE + globally enabled (`enable_context_engineering = True`)
- 18-J durable-execution defect: REPAIRED and verified (`18-j-defect-repair/18J_DEFECT_REPAIR_REPORT.md`)

> **Gate 1 is audit/design only. No production compactor, no Context Engineering
> change, no new persistence system, no Model Router change, and no worker-model
> selection were produced. Evidence is in `gate1_probe_evidence.json`, produced
> by `probe_accumulation.py`.**

---

## 0. The Two Capabilities Are Not the Same Thing

| | Context Engineering (**shipped**) | Context Compaction (**this audit**) |
|---|---|---|
| Question | *What information should this operation receive?* | *How do we compress accumulated context over time while preserving what continued execution requires?* |
| Time axis | Within one operation | **Across** operations |
| Input | Sources gathered now | History accumulated by prior operations |
| Output | A selected, budgeted, attributed context set | A durable, derived representation of past context |
| Mechanism | `select_context` + `prompt_assembly` | **does not exist yet** |

They compose as:

```text
accumulated context  →  Context Engineering  →  select/structure
                      →  compaction when required
                      →  compact durable state
                      →  (next operation) →  MSC selection →  prompt →  model
```

Compaction is **downstream of** Context Engineering's output and **upstream of**
the next operation's selection. It is not a replacement architecture, and
`enable_context_engineering` must remain `True`.

---

## 1. Existing Context Accumulation Mechanisms

| Mechanism | Location | Nature | Durable? |
|---|---|---|---|
| `ExecutionContext.prior_iterations` | `execution/context.py:44` | `list[LoopIterationRecord]`, grows every iteration | No |
| `ExecutionContext.last_evaluation` / `last_diagnosis` | `execution/context.py:45-46` | Only the **most recent** | No |
| `LoopIterationRecord` | `execution/models.py:359` | Per-iteration: plan, changed files, commands, evaluation, diagnosis, `passed` | No |
| `EngineeringLoop._iterations` | `execution/loop.py` | In-process list across the loop | No |
| `format_reasoning_prompt()` prior_attempts | `execution/context.py:123` | Serialises **every** prior attempt verbatim | No |
| `retrieved_knowledge` | `execution/context.py:51` | Bounded to 3 hits at gather time | No |
| Worker agent history | `power_engines/agent/runtime.py:175` | Bounded by `max_history` | No |

**Empirical finding (`probe_prior_iterations`):** with 6 supplied iterations,
`ExecutionContext.prior_iterations` retains all 6, but the MSC candidate set
produces **0 items representing intermediate iterations** — only the last
evaluation and diagnosis become context items.

> **Gap G-1:** the system *accumulates* full iteration history, but the model
> effectively sees only the latest failure. Decisions and rejected approaches
> from iterations 1..n-1 are structurally invisible — not through deliberate
> compaction, but because they are never projected into the candidate set.

**Empirical finding (`probe_legacy_payload`):** the legacy payload enumerates
all 6 attempts in full with **no budget applied**. The two paths are
complementary failures: the canonical path drops history, the legacy path
overflows with it.

---

## 2. Existing Memory Mechanisms

`KernelMemoryEngineAdapter` (`composition/kernel_adapters.py:509`) wraps the
Kernel `MemoryEngine` interface (`kernel/interfaces.py:297`).

**Critical finding:** `store_memory` appends to `self._local_memories`, a
**plain in-process dict**. `persist_state` best-effort writes a checkpoint.
Nothing is queryable across a restart.

> **Gap G-2:** the Memory Engine is **not durable**. It cannot be the substrate
> for compaction, because compaction output must survive restart to be useful for
> resume. Making Memory durable is a *separate* work item; Compaction must not
> silently depend on it or become a back-door persistence system.

`EngineeringLearningEngine` (`kernel/learning_engine.py:35`) reflects over
execution evidence and promotes validated learnings to Knowledge. Promotion is
gated on confidence — a precedent for how model-mediated output should be
validated before becoming authoritative.

---

## 3. Existing Durable Execution State

| Store | Module | Holds | Authority |
|---|---|---|---|
| `DurableExecutionStore` (18-J) | `runtime/execution_store.py:233` | executions, attempts, checkpoints, transition history, recovery metadata | **Authoritative** |
| `DurableArtifactCatalog` (18-K) | `runtime/artifact_catalog.py:212` | artifact identity, lifecycle, content hash, storage path | **Authoritative** |
| `PhysicalArtifactStore` (18-K) | `runtime/physical_artifact_store.py` | physical bytes, staging/quarantine | **Authoritative** |
| `CheckpointManager` | `runtime/checkpoint_manager.py:305` | named state snapshots | **Authoritative** |
| `ApprovalStore` | `runtime/approval_store.py` | human approvals, fingerprints, expiry | **Authoritative** |
| `PersistenceLayer` | `runtime/persistence.py` | SQLite, optimistic versioning, JSON indexes | **Authoritative** |

Compaction **must not** delete, rewrite, or contradict any of these (§16).

## 4. Existing Event History

`EventPlatform` + `CanonicalEventBus` (composition root) carry canonical domain
events; `runtime/event_publisher.py` formats state-change, lifecycle and
checkpoint events. `_lift_runtime_event` converts raw runtime callbacks into
canonical events.

Events are an **append-only derivation source**: they can reconstruct *what
happened*, but they are not a context store, and replaying them is not context
assembly. Compaction may **reference** events by id; it must not summarise them
into a competing history.

## 5. Existing Artifact Persistence

Committed artifacts carry a deterministic `artifact_id`, a SHA-256
`content_hash`, a `storage_path` and `committed_at` (`runtime/models.py:883`).

> Compaction should **reference artifacts by id + hash**, never inline their
> content. This is reference-based compaction the architecture already supports
> at near-zero extra storage cost.

## 6. Existing Context-Window / Budget Mechanisms

`ContextWindowBudget` (`execution/context_budget.py`) enforces a two-pass window.
`select_context` (`execution/context_selection.py`) enforces mandatory admission
(**hard failure**, `MandatoryContextOverflowError`) and optional admission by
rank until budget is exhausted, marking the rest `excluded` with reason
`budget_exhausted`.

**Empirical finding:** when the budget is exhausted, items are **dropped**, not
compacted.

> **Gap G-3:** budget pressure currently causes **silent information loss**
> (recorded as an exclusion reason, but the model never sees the content). This
> is precisely what Compaction addresses — but compaction must be *recorded and
> inspectable*, never a silent drop.

## 7. Existing Summarization / Compaction-Like Functionality

| Component | Location | Verdict |
|---|---|---|
| `ResearchBriefGenerator` | `knowledge_platform/research/research_brief_generator.py` | Different concern (research briefs) |
| `assemble_evidence()` | `execution/evidence.py` | String formatting of RAG hits, not compaction |
| `ContextWindowBudget` | `execution/context_budget.py` | Budget enforcement, not compaction |
| `GroundingVerifier` | `power_engines/rag/grounding.py` | Answer attribution, not compaction |
| `LearningEngine` reflection | `kernel/learning_engine.py` | Cross-project learning, not per-execution compaction |

> **Gap G-4:** there is **no compaction capability on the canonical engineering
> path at all**. Everything above is adjacent but not equivalent. Compaction is
> genuinely new capability, not a duplicate.

## 8. Existing Model-Mediated Summarization

`EngineeringLearningEngine` is the only model-mediated reflection on the
canonical path. It produces lessons, and **promotion to Knowledge is
confidence-gated** — a model output does not become authoritative merely by
being produced.

> **Gap G-5:** there is no model-mediated *history compaction*, and no schema /
> validation / rollback contract for one. The Learning Engine's promotion gate is
> the closest existing precedent to follow.

## 9. Existing Provenance Mechanisms

`ContextProvenance` (`execution/context_items.py:125`) provides
`acquired_from`, `source_ref`, `provider`, `acquired_at`, `inferred` — and is
**content-free by construction**. `ContextAssemblyRecord`
(`execution/context_observability.py`) is likewise content-free.

> This is a strong asset: compaction provenance can reuse the *same* discipline,
> so a compacted representation is fully auditable without ever storing or
> logging the source payload.

## 10. Existing Resume/Recovery Mechanisms

- `CheckpointManager` / `CheckpointCreator` / `CheckpointRestorer` — named snapshots.
- `DurableExecutionStore.get_latest_checkpoint`, `list_interrupted_executions`,
  `recovery_metadata` — 18-J resume and recovery.
- `reconcile_on_startup` — artifact crash-window reconciliation.
- `RecoveryCoordinator` (kernel) — recovery orchestration.

Compaction must be **idempotent and replay-safe** against all of these, exactly
as the 18-J repair established for artifacts: replay must not corrupt state or
duplicate work.

---

## 11. Exact Duplication / Overlap

| Overlap | Assessment |
|---|---|
| Compaction vs `ContextWindowBudget` | **Complementary, not duplicate.** Budget *drops*; compaction *preserves meaning*. |
| Compaction vs Memory Engine | **Must not duplicate.** Memory is cross-project recall; compaction is intra-execution history. Memory is also non-durable (G-2). |
| Compaction vs Knowledge Engine | **Must not duplicate.** Knowledge is curated, promoted, cross-task. |
| Compaction vs artifact persistence | **Must reference, not copy.** |
| Compaction vs RAG | **Must not duplicate.** RAG retrieves external knowledge; compaction condenses this task's own history. |

## 12. Missing Capabilities

| ID | Gap | Evidence |
|---|---|---|
| **G-1** | Intermediate iteration history never reaches the model | `distinct_iterations_represented: 0` |
| **G-2** | Memory Engine is not durable | `_local_memories` in-process dict |
| **G-3** | Budget pressure silently drops history | `budget_exhausted` exclusion |
| **G-4** | No compaction capability exists | §7 |
| **G-5** | No schema/validation/rollback contract for model-mediated compaction | §8 |
| **G-6** | No compaction provenance model linking a compact record to its sources | §9 |

---

## 13. Proposed Compaction Boundary

**What is compactable:** intra-execution accumulated history — superseded
`LoopIterationRecord`s (older than the active window), superseded
evaluation/diagnosis detail once a newer one supersedes it, and accumulated
non-mandatory observations/tool output already durably captured as artifacts.

**What must remain durable and canonical (never compacted destructively):**
`DurableExecutionStore` state, `DurableArtifactCatalog` records,
`PhysicalArtifactStore` bytes, `CheckpointManager` snapshots, `ApprovalStore`
approvals, canonical event history, verification evidence.

**What must never be compacted:** human approvals and security decisions;
durable artifact content (reference it instead); mandatory context items — the
MSC engine already hard-fails rather than dropping them, and compaction must not
become a back door around that.

**What should be referenced by ID/provenance:** everything already durable —
artifacts (id + content hash), checkpoints, events, executions, approvals.

> **Boundary rule:** *compaction operates on the derived context representation
> only. The moment information is durably recorded elsewhere, the context copy
> becomes a reference, not a payload.*

This keeps compaction strictly downstream of Context Engineering and upstream of
the next selection pass, and prevents it from becoming a second persistence
system.

## 14. Information-Preservation Model

Mapped to actual AutoForge state, not invented categories.

| Class | AutoForge instances | Compaction rule |
|---|---|---|
| **Irreplaceable** | task objective & intent; architectural/security constraints; human approvals; unrecovered failure mechanisms; unresolved contradictory diagnoses | **Never dropped.** Always injected verbatim, or stored durably and referenced. |
| **Reconstructable** | iteration plan text; command stdout/stderr; evaluation output; diagnosis prose | Compactable — regenerable from artifacts/records by id. |
| **Ephemeral** | duplicate/repeated tool output; stale intermediate candidate items; superseded payloads already selected away | May be discarded once recorded. |
| **Historical** | completed-attempt artifacts; full event history; prior project learnings | Retained for audit; **not** injected into every future operation. Referenced by id. |

> This is **not** "summarize the text". The unit of compaction is a
> *classification decision per information class*, backed by durable references.

## 15. Trigger Model

Deterministic triggers only, evaluated on already-durable boundaries:

| Trigger | Rationale | Deterministic? |
|---|---|---|
| **Execution phase boundary** (iteration complete) | Matches the existing `LoopIterationRecord` boundary; naturally recoverable | Yes |
| **Explicit durable checkpoint** (18-J `CheckpointManager`) | A recovery boundary already exists and is replay-safe | Yes |
| **Budget pressure** (available tokens below a floor) | Addresses G-3 directly — compacts *before* `budget_exhausted` drops items | Yes |
| **Iteration-count threshold** | Bounds growth deterministically | Yes |
| Recovery/resume boundary | Deterministic, and required for correctness | Yes |

**Rejected as triggers:** raw token threshold alone (non-deterministic across
routing), model-judged "the context feels large", wall-clock time.

> Every trigger must map to a point where a durable record already exists, so
> compaction can be **rolled back** by rebuilding from that record.

## 16. Failure / Recovery Model

| Failure | Required behaviour |
|---|---|
| Compaction raises | Original context retained unchanged; operation proceeds; error surfaced, never swallowed |
| Malformed / invalid compacted output | Schema validation rejects it; the previous valid compact version stays current |
| Incomplete compaction | Rejected by validation; never promoted as current |
| Model/provider failure (if model-mediated) | Deterministic fallback only, or defer; never partial promotion |
| Context overflow **before** compaction | Mandatory-overflow error unchanged — compaction must not weaken the existing hard failure |
| Context overflow **after** compaction | Hard failure surfaces as today; compaction recorded as attempted-but-insufficient |
| Corrupted compact state | Detected by hash/version; fall back to the previous version, then to source records |
| Stale compact state | Version/fingerprint check against source records; regenerate |
| Resume after compaction | Rebuild from durable sources; compact state is a cache, never the only copy |
| Rollback | Discard compact state; rebuild from durable records |
| Repeated compaction (idempotency) | Deterministic key ⇒ same inputs produce the same compact record; no duplicate work (mirrors the 18-J lesson) |

> **Invariant: no destructive compaction occurs without a recoverable boundary.**
> Because every trigger sits on a durable boundary, rollback is always possible.

## 17. Provenance Model

A compacted representation must be auditable **without** inlining source content,
reusing the discipline already proven in `ContextProvenance` and
`ContextAssemblyRecord`.

| Field | Purpose |
|---|---|
| `compact_id` | deterministic identity of the compact record |
| `source_context_ids` | the `ContextItem.context_id`s it derives from |
| `source_artifact_refs` | artifact ids + content hashes referenced, not copied |
| `source_execution_id` / `task_id` / `correlation_id` | canonical correlation |
| `source_event_refs` | referenced event ids |
| `compaction_version` | schema/method version |
| `compaction_method` | deterministic / model-mediated (and which) |
| `model_id` / `provider_id` | **only if** model-mediated; allocated via the Model Router, never hard-coded |
| `validation_status` | passed / rejected, with reason |
| `confidence` | only if model-mediated |
| `created_at`, `trigger`, `supersedes` | lineage |

> Provenance is **reference-only**. Raw source content is never copied into
> observability to "preserve provenance" — the same content-free principle the
> Context Engineering record already enforces.

## 18. Memory / Knowledge Interaction

| System | Relationship |
|---|---|
| **Memory Engine** | **Not a substrate.** In-process and non-durable (G-2). Compaction writes to the durable runtime layer instead. Making Memory durable is separate work. |
| **Knowledge Engine** | **Not a substrate.** Cross-task curated knowledge; compaction is intra-execution. A compaction *may* propose a lesson, but only via the existing confidence-gated `EngineeringLearningEngine` path. |
| **Context Engineering** | **Host.** Compaction operates on its output; CE remains globally ON and unchanged. |
| **RAG** | **Unrelated axis.** RAG retrieves external knowledge; compaction condenses this task's own history. |
| **Artifact storage** | **Referenced, not duplicated.** |
| **Event history** | **Referenced, not duplicated.** |
| **Runtime state** | **Authoritative; never rewritten** (§29). |

> Compaction must not become a second persistence system. Its durable output is a
> *derived cache* of context, stored through the existing runtime persistence
> layer, and is always rebuildable from authoritative state.

## 19. Model Router Interaction

Compaction sits **below/adjacent to** the existing allocation architecture and
must not invent independent model selection.

If a model is required (Gate 2 decides — §27):

- allocate through the **existing Model Router / `ModelAllocationPort`**;
- respect `ModelMetadata.context_window_tokens` and `max_output_tokens`;
- remain **provider-neutral** — no Ollama, no runtime-specific assumption;
- remain **local-first**, matching `LocalRuntimeProviderAdapter`;
- **never hard-code M6** or any specific worker model.

Deterministic compaction (§21) needs **no** model at all, which is a strong
argument for making deterministic the default.

## 20. Worker-Fleet Interaction Boundary

**No worker-model experiments or selections were performed in this gate.** The
boundary is recorded so the later worker workstream knows what is in scope.

Future lightweight workers are *candidates* for four bounded, structured tasks:

| Task | Suitability | Note |
|---|---|---|
| Structured extraction (into the compaction schema) | Good fit | Output is schema-constrained, verifiable |
| Structured summarization of a bounded window | Possible | Must be schema-validated |
| Stale-context / duplicate detection | Good fit | Largely deterministic today |
| Contradiction detection across diagnoses | Good fit | Needs verification, not trust |
| Compaction **validation** | Good fit | Independent checking is low-risk, high-value delegation |

Deliberately **out of scope here**: selecting 0.5B / 1B / 2B models, modifying
inference-lab configuration, or designing the fleet.

## 21. Lossless / Loss-Aware Design — Determination

The audit considered: lossless compaction, loss-aware compaction, hierarchical
summaries, structured state extraction, reference-based compaction,
evidence-preserving compaction, reversible compaction, versioned compacted state,
provenance-linked summaries.

**Determination: hybrid, with a deterministic core and an optional
model-mediated extraction stage.**

| Layer | Mechanism | Why |
|---|---|---|
| **Reference substitution** (deterministic) | Replace a payload with `artifact_id` + `content_hash` | Zero information loss — the content still exists durably. Primary mechanism, and it covers most of AutoForge's accumulated history. |
| **Structured state extraction** (deterministic) | Fold supersession chains, pass/fail outcomes, repeated identical failures into a bounded record | The information is already structured in `LoopIterationRecord`; extraction is a projection, not a summary. |
| **Versioned, provenance-linked compact state** | Immutable versions + `supersedes` lineage | Enables rollback (§16) and audit (§17). |
| **Model-mediated extraction** (optional, off by default) | Fill declared schema fields from bounded windows | Only where structure is genuinely absent; always schema-validated, never authoritative by default |

**Rejected:** lossy free-text summarisation of source content (violates
irreplaceable constraints and the content-free provenance discipline);
irreversible compaction (blocks rollback).

> "Hybrid" is driven by AutoForge's actual state: because iteration history is
> *already structured* and *already durably backed*, most compaction can be
> lossless by reference. A model is only needed for unstructured residue.

## 22. Deterministic vs Model-Mediated

**Deterministic by default; model-mediated only as an explicitly validated
enrichment stage.** A model must never be *required* for correctness.

If model-mediated (Gate 2 may enable it):

| Requirement | Rule |
|---|---|
| Schema | Fixed, versioned; every field typed, required/optional by contract |
| Validation | Structural validation before any promotion; rejection keeps the previous version |
| Required fields | `compact_id`, sources, method, version, `validation_status` |
| Provenance | Full reference set (§17) |
| Confidence | Recorded; below-threshold output is **not** promoted |
| Verification | Optional independent check pass; a model does not verify itself |
| Failure behaviour | Defer compaction; never partial promotion |
| Rollback | Discard to previous version; rebuild from sources |
| Versioning | Immutable versions, `supersedes` lineage |

> **AI-generated compacted state must not become authoritative merely because a
> model produced it.** Authority comes from validation plus durable references —
> the same principle already applied in `EngineeringLearningEngine`'s
> confidence-gated promotion.

## 23. Security / Trust Considerations

- **Approvals and security decisions are Irreplaceable** — never compacted,
  summarised, or model-transformed.
- A compact record carries the trust boundary of its sources; derivation from
  lower-trust input cannot raise trust.
- Compacted content is injected into prompts, so it must pass the same
  prompt-injection and boundary-sanitisation controls as any other context.
- Provenance is reference-only, so compaction adds **no new secret-exposure
  surface**; error `details=` must stay content-free.
- A malformed or corrupted compact record must fail validation, never be
  silently injected.

## 24. Minimal Architecture (proposed — NOT implemented)

Four small components inside the **existing** `autoforge_execution` package — no
new service, no new persistence system, no Context Engineering change:

| Component | Responsibility | Depends on |
|---|---|---|
| `compaction/compaction_schema.py` | Versioned `CompactedContext` + content-free `CompactionProvenance` | `context_items` / `context_observability` patterns only |
| `compaction/compaction_policy.py` | Information classes, trigger predicates, retention window | existing models |
| `compaction/compactor.py` | Deterministic core: reference substitution + structured extraction | runtime `PersistenceLayer`, artifact catalog (read-only) |
| `compaction/compaction_validation.py` | Schema validation, version/fingerprint check, supersession | schema |

Integration point: **one call site** inside
`EngineeringContextBuilder._build_candidates` (or immediately upstream), so
compaction happens *before* MSC selection and the result flows through the
existing `select_context` → `prompt_assembly` path.

Explicitly **not** introduced: a new service, a new database, a new Memory
Engine, Model Router changes, `ContextWindowBudget` semantic changes, or a
second prompt-assembly path.

## 25. Expected Files / Components (Gate 2+ scope)

```
packages/execution/src/autoforge_execution/compaction/
    __init__.py
    compaction_schema.py        # CompactedContext, CompactionProvenance
    compaction_policy.py        # info classes + triggers + retention
    compactor.py                # deterministic core
    compaction_validation.py    # schema/version/fingerprint validation
packages/execution/tests/
    test_compaction_schema.py
    test_compaction_policy.py
    test_compaction_determinism.py
    test_compaction_idempotency.py
    test_compaction_failures.py
    test_compaction_provenance.py
```

Plus **one** integration point in `context_builder.py` and **one** wiring change
in the composition root — mirroring exactly how Context Engineering was wired.

## 26. Tests Required (Gate 2+)

| Area | Test |
|---|---|
| Determinism | identical inputs → byte-identical compact record |
| Idempotency | repeated compaction produces no duplicate work and no state corruption (the 18-J lesson) |
| Information classes | Irreplaceable never dropped; Reconstructable referenced; Ephemeral discardable; Historical referenced not injected |
| Preservation | decisions, constraints, intent, dependencies, unresolved work, approvals, contradictions, failure/recovery info all survive |
| Provenance | full reference set; content-free; no source payload copied |
| Failure | malformed, incomplete, model-timeout, corrupt, stale → all rejected, previous version retained |
| Rollback | discard compact state → rebuild from durable sources |
| Budget interaction | compacts before `budget_exhausted` drops; never weakens `MandatoryContextOverflowError` |
| Durability | compact state survives restart; is a cache, never the only copy |
| Neutrality | no runtime/provider imports; works under CE rollback |
| E2E | multi-iteration run with compaction active, CE ON, artifacts intact |

## 27. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Compaction silently loses Irreplaceable info | **High** | Class-based rules; explicit test that approvals/constraints/intent never drop |
| Compaction becomes a second persistence system | **High** | Derived-only boundary rule (§13); rebuildable from durable state |
| Model-mediated output treated as authoritative | **High** | Deterministic default; validation gate; confidence threshold (§22) |
| Weakening the MSC mandatory-overflow guarantee | **High** | Compaction strictly upstream; hard failure preserved and tested |
| Non-deterministic compaction breaks replay | Medium | Deterministic key + byte-identical output test |
| Memory Engine assumed durable | Medium | Explicitly excluded as a substrate (G-2) |
| Scope creep into worker selection | Medium | §20 boundary; no experiments in this gate |
| Duplicate of Memory/Knowledge | Medium | §18 relationship table |

## 28. Rollback Strategy

Because compaction is a **derived cache**:

1. Disable the compaction call site (single integration point) — the system
   returns to today's behaviour immediately.
2. Delete compact records — authoritative state is untouched, so nothing is lost.
3. No data migration, no state rewrite, no schema rollback required.
4. Compatible with the existing Context Engineering rollback posture
   (`enable_context_engineering = False`).

This mirrors the 18-J / Context-Engineering precedent: **feature-off must be a
complete rollback, not a degraded mode.**

## 29. Durable State vs Context (mandatory distinction)

Compaction is a **derived representation** and must never be a mechanism for
deleting or rewriting canonical durable execution state.

| State | Rule |
|---|---|
| Durable workflow/execution state | authoritative; never rewritten by compaction |
| Artifact state (catalog + physical) | authoritative; referenced, never mutated |
| Event history | authoritative where required; referenced, never summarised away |
| Verification evidence | authoritative; never compacted away |
| Human approvals | authoritative; Irreplaceable |
| **Compacted context** | **derived cache; always rebuildable** |

> **If compaction conflicts with canonical durable state: durable state wins.**
> Compaction is never allowed to become the source of truth.

## 30. Open Questions (for Gate 2)

1. **Retention window:** how many recent iterations stay verbatim before
   compaction folds them? (Default candidate: last 2–3, configurable.)
2. **Trigger thresholds:** what budget-pressure floor and iteration count? Must
   be measured, not guessed.
3. **Model-mediated stage:** enable at all in the first cut, or ship
   deterministic-only and defer? (Recommendation: deterministic-only first.)
4. **Storage location:** `PersistenceLayer` entity vs artifact store. Artifact
   store gives content-hash integrity for free — likely preferable.
5. **Interaction with `format_reasoning_prompt()`:** the legacy path enumerates
   all prior attempts unbounded; should it consume compact state too, or be
   retired now that the canonical path is live?
6. **Cross-execution scope:** per-execution only, or project-level rollup?
7. **Memory durability (G-2):** separate work item — confirm it is not a
   prerequisite for compaction.

## 31. Gate 1 Recommendation

> **PROCEED to Context Compaction Gate 2 — Design.**

Gate 1 confirms Context Compaction is genuinely needed, genuinely absent (G-4),
and genuinely distinct from Context Engineering. The audit found a concrete,
evidence-backed problem worth solving: **G-1** — accumulated iteration history is
collected but structurally invisible to the model
(`distinct_iterations_represented: 0`), while **G-3** shows budget pressure drops
history rather than compacting it.

The recommended design is a **deterministic-first, reference-based, versioned,
provenance-linked compaction** operating strictly on derived context, wired
behind **one** integration point, with complete rollback. No model is required
for correctness.

Gate 2 should resolve the §30 open questions, produce the schema and policy
contracts, and specify the exact integration point — but **must not** implement
the production compactor, alter Context Engineering, touch the Model Router or
inference lab, or select worker models.

---

## Appendix — Artifacts

| File | Purpose |
|---|---|
| `CONTEXT_COMPACTION_ARCHITECTURE_AUDIT.md` | This audit |
| `probe_accumulation.py` | Read-only evidence probe (accumulation, durability, gaps) |
| `gate1_probe_evidence.json` | Captured probe evidence |

**Protected during this gate (verified unmodified):** M6 authority model, M1,
HP, inference lab, llama.cpp runtime qualification, 61.923 tok/s qualification,
Context Engineering architecture, global CE default ON, 18-K, worker
experiments, AutoForge Brain. 18-J was repaired under Part A and is
**re-frozen**.
