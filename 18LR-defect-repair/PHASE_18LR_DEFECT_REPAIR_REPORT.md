# PHASE 18-LR — DEFECT REPAIR & ARCHITECTURE INTEGRATION REPORT

**Workstream:** 18-LR — Autonomous Certification Defect Repair + Canonical Architecture Integration Validation + Five Commercial Power Engine E2E
**Mode:** M6-only, single-node, authoritative
**Date:** 2026-09-29

# 18-L = NOT CERTIFIED

Two mandatory criteria were repaired and are proven by regression tests and a fresh end-to-end run. Two further mandatory criteria fail and are architectural/product decisions I am stopping to report rather than deciding unilaterally.

| # | Item | State |
|---|---|---|
| B-1 | Vacuous approval on empty evidence | **REPAIRED** — 20 regression tests |
| B-2 | Legacy modernization fed a synthetic placeholder | **REPAIRED** — 8 regression tests; 2/2 real files now modernized |
| D-8 | Validation truth must reach final review | **REPAIRED** (mechanism); deeper residual gap remains (§5) |
| NEW-A | **Canonical production path cannot reach ANY of the five Commercial Power Engines** | **FAIL — architectural decision required (STOP)** |
| NEW-B | **Canonical path supplies no verification command, so the platform computes no deterministic validation at all** | **FAIL — architectural decision required (STOP)** |

---

## 1. Baseline

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD at start and finish | `c72dad9e0ffe44d6aeac958e985544801820acf4` (unchanged) |
| `origin/main` | `c72dad9e0ffe44d6aeac958e985544801820acf4` |
| Commits / pushes | **none** |
| Pre-existing untracked files | **all preserved** (no reset, clean, stash, or deletions) |
| `git diff --check` | clean |

The 13 pre-existing modified files from the first 18-L run (DEF-18L-01..06 and the P-1 review-gating work) were left intact and are included in the delta below.

## 2. Hardware / runtime (M6-only)

| Item | Value |
|---|---|
| Host | Mac mini, Apple M6 |
| Model | `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` |
| Runtime | MLX-LM 0.31.3, `127.0.0.1:8080/v1` |
| Fingerprint | `0.31.3-0.32.2-macOS-27.0-arm64-arm-64bit-applegpu_g18g` (identical to the first 18-L run) |
| Workers | **0** — topology unchanged |
| M1 / HP | **not contacted, not benchmarked, not configured** |

**Environmental note (not a regression).** With the M6 MLX server listening on `127.0.0.1:8080`, `power_engines::test_health_check_script_execution_and_exit_codes` fails, because its fixture declares a service on host port 8080 and the generated `health_check.py --require-service` correctly finds it online. With the server stopped the suite is `124 passed, 3 skipped`. This is a port collision between the inference runtime and a delivery fixture, reproducible in both directions; it is not caused by any 18-LR change. Full CI was run with MLX stopped; the E2E runs used MLX running.

## 3. DEF-18L-01..06 regression status — all retained, no regression

| ID | Repair (from first 18-L) | Regression suite | Result |
|---|---|---|---|
| DEF-18L-01 | generated source durable | `test_generated_source_durability.py` | PASS |
| DEF-18L-02 | routed `max_output_tokens` forwarded | `test_output_budget.py` | PASS |
| DEF-18L-03 | `request_text` into O-2 loops | `test_request_propagation.py` (6) | PASS |
| DEF-18L-04 | `TaskDefinition.description` populated | `test_description_propagation.py` (4) | PASS |
| DEF-18L-05 | revised source collision (versioned) | `test_generated_source_durability.py` | PASS |
| DEF-18L-06 | distinct artifacts, distinct paths | `test_generated_source_durability.py` | PASS |

**18/18 tests pass.** Independently reconfirmed in the fresh greenfield run: 27/27 durable artifacts reached `COMMITTED`, 15 of them `source_code`, and multi-iteration runs produced `.v2`/`.v3` revisions at distinct physical paths with no overwrite.

## 4. B-1 — vacuous approval: investigation and repair

**Reproduced first.** The first 18-L evidence was re-derived and confirmed: `ReviewEngine.review()` on empty evidence returns `APPROVED` with a `no_target` gate (`review/engine.py:180-201`), and the completion gate consumed that as a real approval, so a project producing nothing reached `Finished`.

**Root cause.** The mandatory-review requirement was in the wrong place. The Review Engine answers the question it is given; it cannot distinguish "nothing to review" (a legitimate, in-scope answer for an artifact-scoped review) from "nothing was produced" (invalid for a project-completion gate). Nobody owned that distinction.

**Repair — smallest correct boundary.** `DefaultCompletionModule._run_final_review` (`packages/kernel/src/autoforge_kernel/completion.py`) now fails closed when an authoritative evidence collector is wired and the project produced zero reviewable deliverables. **The Review Engine's `no_target` semantics are deliberately untouched**, exactly as required.

**Regression coverage (20 tests, `packages/kernel/tests/test_completion_gates_18lr.py`, all passing):** mandatory review + empty evidence; mandatory review + real evidence; review exception; review rejection (all three non-approving decisions); malformed / contradictory verdicts (7 shapes); explicit APPROVED; and the legitimate non-mandatory `no_target` use case (proved preserved at the adapter level).

**Contract change recorded.** One pre-existing P-1 test, `test_no_placeholder_makes_unreviewable_project_appear_reviewable`, asserted that an empty-evidence project still received a review result — that is, it encoded the fail-open. It was **strengthened, not weakened**: it now asserts the gate fails closed, that no review is run, and that the project cannot reach `Finished`. Called out explicitly because it is a deliberate change to a ratified P-1 assertion, mandated by this gate's §11.

## 5. D-8 — validation must reach and be enforced by final review

### 5.1 What was repaired

**Reproduced first**, then repaired at two boundaries:

1. **Evidence.** The completion module now runs a deterministic validation port and supplies the real results to the review. `packages/composition/src/autoforge_composition/validation_wiring.py` (new) executes the project's own declared verification command through the **existing** `WorkspaceEnvironment` and parses it with the **existing** `parse_test_output`. No new runner, no new parser, no second execution path. The Kernel defines only the port (ADR-002 dependency direction preserved); the composition root wires the real one.

2. **Enforcement.** `finalize_project` now blocks on a mandatory failed validation **even when the review returned an explicit APPROVED**, recording `overridden_by: "deterministic_validation_gate"` so the override is auditable. The LLM is not authoritative for whether tests passed.

3. **Review adapter.** `review_project` previously synthesised a fake one-test summary (`total_tests=1, failed_tests=1`) from a boolean. It now consumes the real structured results, keeping the legacy boolean as a fallback.

**Regression coverage (8 D-8 tests, all passing):** all tests pass; tests fail; validation fails; missing validation result (a port that raises must fail closed); review approval despite failed deterministic validation; review rejection; not-applicable validation; no validation port; execution failure blocks before review; validation truth demonstrably reaching the review context.

### 5.2 Residual gap found by the fresh greenfield run — NOT REPAIRED

The fresh greenfield run (§17) **reproduced D-8 end to end despite the repair**:

```
27/27 COMMITTED artifacts, 15 source_code
project's own suite: 2 failed, 4 passed  (rc=1)
final review: APPROVED, 16 evidence files, 0 findings
project: finished
```

Diagnosis, from the run's own durable artifacts:

- The engineering loop's `evaluation_report_iter_{1,2,3}.json` all read `"status": "inconclusive"`, `"test_results": null`, `"deterministic_checks": []`.
- Root cause: `WorkforceWorker.execute_task` reads `context.input_data["verification_commands"]`, but `KernelExecutionEngineAdapter.execute_loop` never populates that key. The loop therefore runs **zero** commands.
- Consequently the review receives `test_results = None`, and the Review Engine's documented `_tests_pass` treats absence as "not asserted", returning `True`.

So the platform computes **no deterministic validation whatsoever** on the canonical path. The new gate is correct and proven, but it has nothing to enforce because nothing supplies a verification command.

**This is a product decision, and I am stopping here (§31).** The machinery to close it already exists and is unused — `EngineeringLoop.run(verification_commands=...)`, `EvaluationEngine.evaluate_attempt`, `parse_test_output`, durable evaluation artifacts. What is missing is the contract that says *where a project's verification command comes from*:

- **(a) Declared by the requester** — `Request.configuration["verification_command"]`. I already built the reader for this. Closing the gap is a small plumbing change into `input_data["verification_commands"]`, reusing only existing machinery. But it makes deterministic validation opt-in.
- **(b) Discovered by AutoForge** — infer and run a generated project's test suite. Materially new capability, executes model-generated code on the worker path, and needs sandbox and permission decisions.

Option (a) is the smallest correct repair and is consistent with what I built. I am not choosing between (a) and (b) unilaterally, because it changes what the production path executes and what "validated" means for an arbitrary generated project.

## 6-15. Five Commercial Power Engines

| Capability | EXISTING CERTIFICATION | CANONICAL PRODUCTION PATH | REGRESSION |
|---|---|---|---|
| RAG Knowledge | **PASS** | **FAIL** | none needed |
| Custom AI Agent | **PASS** | **FAIL** | none needed |
| AI Automation | **PASS** | **FAIL** | none needed |
| Code Migration | **PASS** | **FAIL** | none needed |
| Legacy Modernization | **PASS** | **FAIL** (defect repaired) | 8 new tests |

**For all five engines: ENGINE IMPLEMENTATION = PASS, CANONICAL INTEGRATION = FAIL.** Per §29, no engine is declared broken.

Layer A (existing certification reproduction) was run per engine and all pass: RAG ingestion/parsing (3) + retrieval grounding (5); Custom AI Agent (27); AI Automation (25); Code Migration (16); Modernization G.3 real + LLM/transform (112), plus the full modernization suite (375 to 383 with new tests).

### 16. Exact first-divergence boundary (root cause of all five CANONICAL FAILs)

Proven by AST import analysis, not documentation (`18LR-defect-repair/ast_engine_reachability.py`):

```json
{
  "autoforge_power_engines":   { "internal_importing_files": 49, "external_importing_packages": {} },
  "autoforge_modernization":   { "internal_importing_files": 49, "external_importing_packages": {} },
  "canonical_path_engine_reachability": {
    "kernel.py": [], "orchestration.py": [], "completion.py": [],
    "strategic_engine.py": [], "composition_root.py": [],
    "kernel_adapters.py": [], "execution/engine.py": []
  },
  "canonical_path_reaches_any_engine": false
}
```

Confirmed dynamically. `18LR-defect-repair/layer_b_canonical_engines.py` drives the **real** composed system end to end for a genuine request per engine and instruments the O-2 loop-dispatch seam:

```
rag_knowledge          reached=False executors=['ExecutionEngine'] loops=4
custom_ai_agent        reached=False executors=['ExecutionEngine'] loops=4
ai_automation          reached=False executors=['ExecutionEngine'] loops=4
code_migration         reached=False executors=['ExecutionEngine'] loops=4
legacy_modernization   reached=False executors=['ExecutionEngine'] loops=4
```

| Divergence trace | |
|---|---|
| **Input** | a genuine customer request (e.g. "Modernize the legacy COBOL batch ledger and its JCL job...") |
| **Entry point** | `Kernel.submit_request` -> Intent -> Strategic -> ExecutableWorkflow -> O-2 |
| **First divergent boundary** | `KernelExecutionEngineAdapter.execute_loop`, the O-2 loop dispatch. It unconditionally maps **every** loop type to `WorkerType` and the generic `ExecutionEngine` coding path |
| **Root cause** | The composition root never constructs a single Commercial Power Engine, and no production module imports `autoforge_power_engines` or `autoforge_modernization`. The engines are reachable **only** from their own isolated certified suites |
| **Correct repair boundary** | the O-2 loop-dispatch seam in the **composition** package: a capability router that selects the engine, feeds it the *real* request, and registers its output through the existing 18-K artifact pipeline |

Note this contradicts `18K_ARCHITECTURE_INTEGRATION_REPORT.md`, which lists all five engines as "Genuine, integrated". That claim is not supported by the code; the engines reuse *shared infrastructure*, but nothing *invokes* them.

**I did not build this router.** Introducing a capability classifier and engine dispatcher into the production path is a significant architectural addition that changes what every request does, which classification wins, and how engine output becomes durable. §31 reserves that for reporting. The gap is unambiguously diagnosed and isolated to one seam, so it is ready to implement on your decision.

## 10 and 21. Legacy Modernization — B-2 investigation and repair

**Not the engine.** The certified G.3 engine modernizes real source correctly. `18LR-defect-repair/layer_a_modernization.py` proves it with a real COBOL batch program and a real JCL job:

| Boundary | Result |
|---|---|
| Engine on real source (`run_g3_real`) | **PASS** — 2 applied, 0 failed; `LEDGER.java` contains `PROGRAM-ID LEDGER`, its paragraphs and working-storage fields; no placeholder |
| Pipeline (the path 18-L used) | **FAIL before repair** — `before_content = "# legacy COBOL unit COBOL"`, `file_path = "src/COBOL.java"` |

**Exact first divergence.** The pipeline discarded the reconnaissance file inventory, kept only technology *names*, and `ModernizationPipeline._run_wave` fabricated both the path and the content. Captured at the engine boundary:

```
before repair: {"file_path_arg": "src/COBOL.java", "before_content_arg": "# legacy COBOL unit COBOL"}
after repair:  {"file_path_arg": ".../cbl/LEDGER.cbl", "before_content_arg": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. LEDGER..."}
```

**Three orchestration defects repaired — the engine was not modified:**

1. **B-2a, placeholder content.** `_extract_source_inventory` reads the real reconnaissance inventory; `_derive_default_plan` binds it into the existing `MigrationUnitSpec.source_files` field; `_run_wave` reads the customer's actual bytes and transforms per file. A unit with no bound file is now an explicit failure, never a silent placeholder.
2. **B-2b, wrong transformation type.** The plan's `MigrationStrategy` is the plan-level "6 R's" vocabulary and cannot express the execution-level types the G.3 strategies key on, so JCL and COBOL-to-Java fell into `_unsupported_transform`. `_select_transformation_type` now resolves the type from the engine's **own certified** `supported_types_for` API, preferring the substantive transform over the cosmetic `refactor` (which the engine's no-op detection correctly rejects on already-clean code).
3. **B-2c, hardcoded type.** `transformation_type` was hardcoded to `REFACTOR` in the `apply()` call, discarding the selection.

**Result after repair:** pipeline `complete`, 2/2 real files transformed (`LEDGER.cbl` 616 B to real Java; `LEDGER.jcl` 174 B to real workflow config), zero placeholders, 383 modernization tests green.

**Fixture note (§21).** The first 18-L fixture used a Python-2-era file, but Python is **not** a supported legacy source technology — the engine raises `TransformationError` **by design**. That is not an engine defect. This gate uses the certified-supported fixtures (COBOL `.cbl`, JCL `.jcl`) instead. The `.cobol` extension is also not scanned; `.cbl`/`.cob` are the certified extensions.

## 17. Greenfield fresh certification (M6, real inference)

Fresh run; nothing reused from the first 18-L.

| Criterion | Result |
|---|---|
| Real M6 inference | PASS — 104.26 s O-2 execution, `Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` |
| Real source generation | PASS — `tokenizer_lite/{__init__,core,cli}.py`, `test_tokenizer_lite.py`, `README.md` |
| Actual source artifacts | PASS — 15 `source_code` artifacts |
| Durable COMMITTED | PASS — **27/27** |
| Distinct physical paths | PASS — `.v2`/`.v3` revisions, no overwrite |
| Deterministic tests | **FAIL — 2 failed, 4 passed** |
| Validation evidence captured | **FAIL — see §5.2** |
| Final review | PASS but **on incomplete evidence** (16 files, 0 findings) |
| Explicit APPROVED | PASS |
| Completion after approval | PASS — `finished` |
| Recovery + SHA-256 | PASS — 27/27 recovered, `all_hash_verified: true` |
| Zero manual intervention | PASS |

## 19. Full original architecture E2E

Request -> Kernel -> Intent -> Strategic -> ExecutableWorkflow -> O-2 -> (generic `ExecutionEngine`, **not** a commercial engine) -> Model Router -> M6 MLX -> execution -> real source -> 18-K artifacts -> review -> completion. Every boundary was captured with real values. The one failed assertion is the commercial-engine hop (§16).

## 20. Context Engineering / Compaction / 18-J / 18-K

**All untouched and green.** No source file in `context_builder` / `context_selection` / `prompt_assembly` / `compaction` / `router` / `durable` / `artifact_catalog` / `physical` was modified (verified by `git diff --name-only`). Their suites pass inside the full CI result below. DEF-18L-05/06 (18-K artifact versioning and physical-path isolation) are proven by both their regression tests and the live 27/27 run.

## 23. Human-intervention audit

| Intervention | Class | Prohibited? |
|---|---|---|
| Started the MLX M6 server on `127.0.0.1:8080` | infrastructure setup | No |
| Supplied the greenfield request text and acceptance criteria | harness | No |
| Created the empty workspace | harness | No |
| Ran the project's own test suite | harness observation | No |
| Wrote, edited or corrected **any generated source** | — | **No — none occurred** |
| Created, registered or altered **any project artifact** | — | **No — none occurred** |
| Invoked, stubbed or influenced the **Review Engine's verdict** | — | **No — none occurred** |
| Transitioned any project state by hand | — | **No — none occurred** |
| Modified M1, HP, worker scheduling or inference topology | — | **No — none occurred** |

## 24. Full CI

Each package suite run as its own invocation, exactly as `.github/workflows/ci.yml` does.

| Suite | Result | | Suite | Result |
|---|---|---|---|---|
| kernel | **161** | | observability | 16 |
| orchestration | 71 (+6 skip) | | workforce | 36 (+2 skip) |
| workflows | 218 | | execution | 233 (+18 skip) |
| runtime | 268 | | power_engines | 124 (+3 skip) |
| persistence | 70 | | composition | 98 |
| artifacts | 14 | | modernization | **383** (+59 skip) |
| events | 228 | | root | 96 (+1 skip) |
| event_platform | 56 | | security | 37 |
| connectors | 93 | | ai_infrastructure | 97 |
| review | 114 | | | |

### **2,413 passed · 0 failed · 0 collection errors · 89 skips**

Baseline was 2,385. Delta **+28 = exactly the 28 new regression tests** (20 B-1/D-8 + 8 B-2). No suite regressed. The 89 skips are the same environmental (sandbox/Podman/daemon) skips as before.

## 25. Files changed

**New source (1):** `packages/composition/src/autoforge_composition/validation_wiring.py`

**Modified source (3 this gate; 10 pre-existing from 18-L):**

| File | Change |
|---|---|
| `packages/kernel/src/autoforge_kernel/completion.py` | **B-1** mandatory-review fail-closed; **D-8** validation port, review context, deterministic gate |
| `packages/modernization/src/autoforge_modernization/pipeline.py` | **B-2** real source inventory, per-file transformation, supported-type selection |
| `packages/composition/src/autoforge_composition/composition_root.py` | wire `WorkspaceValidationPort` |
| `packages/composition/src/autoforge_composition/kernel_adapters.py` | real structured `TestResultSummary` instead of a synthetic one |

**New tests (2):** `packages/kernel/tests/test_completion_gates_18lr.py` (20), `packages/modernization/tests/test_18lr_b2_real_source_transformation.py` (8)

**Modified tests (1, deliberate contract strengthening):** `test_final_review_evidence_e2e.py::test_no_placeholder_makes_unreviewable_project_appear_reviewable`

**Harness (new, untracked):** `18LR-defect-repair/` — `ast_engine_reachability.py`, `layer_a_modernization.py`, `layer_b_canonical_engines.py`, `evidence/*.json`

## 26. Acceptance criteria (final)

| Group | Result |
|---|---|
| GREENFIELD (11) | 9 PASS · 2 **FAIL** (deterministic tests, validation evidence — §5.2) |
| REVIEW (5) | **all PASS** (B-1 repaired) |
| VALIDATION (4) | 2 PASS · 2 **FAIL** (results not captured on the canonical path; review cannot override once results exist) |
| RAG / AGENT / AUTOMATION / MIGRATION | 4/4 engine PASS, **4/4 canonical FAIL** |
| MODERNIZATION | engine PASS, **canonical FAIL**, real source consumed, real modernized source produced, no placeholder |
| ARCHITECTURE (15) | 14 PASS · **1 FAIL** ("appropriate commercial engine" — §16) |
| PROTECTED SYSTEMS | **all PASS** — CE, Compaction, 18-J, 18-K untouched; no topology change; M1/HP/Brain/Phase-19 untouched |
| REGRESSION | **PASS** — 0 failures, 0 collection errors, no unexplained regression |

## 27. M6-only / M1 / HP confirmation

**M6-only: confirmed.** All inference went to `127.0.0.1:8080` (Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2). Workers: 0. No topology change.

**M1 untouched: confirmed.** No M1 host contacted, benchmarked, configured or started. No M1 file modified. The `local-m1` / `local-hp` provider ids are labels bound to `127.0.0.1` (this M6) by the existing `bind_local_runtime_adapters`; no remote host is referenced anywhere.

**HP untouched: confirmed.** As above.

**Brain untouched: confirmed. Phase 19 untouched: confirmed. Nothing committed. Nothing pushed.**

## 28. Architectural integrity

- No second artifact system, review system, or completion path introduced.
- The 18-K durable pipeline remains the single artifact path; the D-8 port reuses the existing `WorkspaceEnvironment` and `parse_test_output`.
- The Review Engine was **not** modified — B-1 was fixed at the completion boundary precisely to preserve its `no_target` contract.
- The Legacy Modernization engine was **not** modified — B-2 was fixed in the pipeline that feeds it.
- Context Engineering, Context Compaction, Model Router, 18-J and 18-K: zero source changes.
- Two **new** architectural seams were added, both additive and opt-in: a deterministic validation **port** (Kernel defines the interface, composition supplies the implementation) and the composition-root wiring for it. Neither changes behaviour when a project declares no verification command.

## 29. Remaining defects

| ID | State |
|---|---|
| B-1 | **REPAIRED** — 20 regression tests |
| B-2 | **REPAIRED** — 8 regression tests; 2/2 real files modernized |
| D-8 (mechanism) | **REPAIRED** — evidence supplied, deterministic gate enforced |
| D-8 (canonical path) | **OPEN** — no verification command is ever supplied (§5.2) |
| NEW-A | **OPEN** — canonical path cannot reach any commercial engine (§16) |

## 30. Final verdict

# 18-L = NOT CERTIFIED

Not because most of the system works, and not downgraded to "medium".

**Repaired and proven (28 new regression tests, full CI green):** B-1 vacuous approval, B-2 legacy modernization of real source. D-8's review-evidence and enforcement mechanism is built and proven, but is inert on the canonical path.

**Two mandatory blockers remain, both requiring a product decision that I am stopping to report rather than making unilaterally:**

1. **The canonical production architecture cannot invoke any of the five Commercial Power Engines** (AST-proven; dynamically confirmed). The engines are not broken — they pass their own certification. The integration seam is isolated to `KernelExecutionEngineAdapter.execute_loop` and is ready to implement on your decision.

2. **The canonical path computes no deterministic validation.** The completion gate, the review adapter and the Review Engine all behave correctly; nothing ever runs the generated project's tests, so there is no truth to enforce. The decision is whether the verification command is **declared** by the requester (option (a): small plumbing change, reuses existing machinery, makes validation opt-in) or **discovered** by AutoForge (option (b): new capability, executes model-generated code).

**Human-intervention audit: clean. M1 and HP: untouched. Nothing committed or pushed.**
