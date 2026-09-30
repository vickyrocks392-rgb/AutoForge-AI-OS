# PHASE 18-LD — EVIDENCE MATRIX

**Companion to:** `PHASE_18LD_ARCHITECTURE_DECISION_REPORT.md`
**All rows are source-verified or re-executed at HEAD `c72dad9` during this gate.**
**No production code was modified. Nothing committed, nothing pushed.**

---

## 1. Primary evidence matrix

| # | Evidence | Source | Finding | Consequence |
|---|---|---|---|---|
| E-1 | **18-LR canonical routing test** (dynamic) | `18LR-defect-repair/layer_b_canonical_engines.py`; evidence `18LR-defect-repair/evidence/layer_b_canonical_engines.json` (read back by this gate) | All 5 capabilities: `reached_commercial_engine=false`, `distinct_executors=['ExecutionEngine']`, 4 loops each, `orchestration_engine=DefaultOrchestrationEngine`. `"canonical_integration_pass": false` | **BLOCKER A confirmed.** The canonical path executes the generic `ExecutionEngine` for every commercial request |
| E-2 | **AST reachability** (static) | `18LR-defect-repair/ast_engine_reachability.py`, **re-run by this gate** at HEAD `c72dad9` | `autoforge_power_engines`: 49 internal importers, `external_importing_packages: {}`. Same for `autoforge_modernization`. All 7 canonical-path files import neither. `canonical_path_reaches_any_engine: false` | Routing seam is **provably isolated** at the O-2 loop dispatch; no engine is reachable from production |
| E-3 | **Five engine source inventory** | `power_engines/{rag,agent,automation,migration}/engine.py:29/22/22/36`; `modernization/pipeline.py:161`; `power_engines/base.py:103-301` | 4 engines share `PowerEngine.execute_lifecycle(spec) -> PowerEngineResult` over the 11-stage lifecycle. `ModernizationPipeline.run(...)` is **sync**, different package, different input/output | A thin adapter can serve 4 of 5 uniformly; engine 5 needs an input adapter + a sync→async bridge + result normalisation |
| E-4 | **Existing engine certification** | `packages/power_engines/tests/` and `packages/modernization/tests/` — **re-run by this gate** | Power engines: **123 passed, 3 skipped, 1 failed**. Modernization (B-2 + G.3): **91 passed**. The single failure is the documented **environmental 8080 port collision** (MLX holds `127.0.0.1:8080`; the fixture declares `host_port=8080` and `--require-service` finds it online) — `lsof` confirms the listener | **ENGINE IMPLEMENTATION = PASS for all five.** The 1 failure is environmental, not a regression; reproducible in both directions |
| E-9 | **B-1 completion semantics** | `kernel/completion.py:458-469,577-606,664-682`; `review/engine.py:180-201`; `test_completion_gates_18lr.py` (20 pass) | Mandatory review + zero reviewable evidence ⇒ `approved=False` with an explicit reason; the Review Engine's own `no_target` branch is deliberately untouched; `evaluate_final_review_result` fails closed on `None`/malformed/non-approving verdicts | B-1 is **repaired and correct**. But it **cannot** catch BLOCKER B: the greenfield project has 16 evidence files, so B-1 passes it |
| E-10 | **Verification channel is live** | `workforce/workers.py:93`; `workforce/dispatch.py:96,134`; `execution/loop.py:102,108-116`; `execution/context.py:98`; **live probe** | Canonical dispatch resolves `BackendEngineer`, a verified `WorkforceWorker` subclass reading `input_data["verification_commands"]`; `EngineeringLoop.run` additionally honours `input_data["commands"]`/`["test_commands"]`; `input_data` is carried faithfully by `ExecutionContext.from_task_definition` | The repair needs **one new write**, not new machinery. Two existing keys would both work |
| E-11 | **The write that is missing** | `composition/kernel_adapters.py:297-327` | `input_data = loop_input["loop"]["input_data"]` → `TaskDefinition(input_data=input_data)`. `verification_commands` is **never assigned**, and the loop's fallback keys are never set either | The exact, single-line-class location of BLOCKER B's root cause |
| E-12 | **Capability identity is durable and unused** | `interfaces.py:64`; `request_intake.py:98,150-155`; `runtime_facade.py:103,131`; `strategic_engine.py:101-110`; `kernel_adapters.py:154-158,297`; **live probe** | `Request.configuration` → `Project.metadata` → `ProjectState.configuration` survives intact (the probe shows the declared key present). Arbitrary config keys provably reach `execute_loop` via the `language`/`framework` path. No component *reads* a capability key | **No new abstraction is required to name a capability.** `Request.configuration` is the natural, already-durable carrier |
| E-13 | **`verification_framework` already exists** | `kernel/strategic_engine.py:109` | `technology_choices["verification_framework"] = "pytest" if language == "python" else "standard_test_runner"` | The closest existing first-class verification declaration — but a **framework name, not a command**. A product decision is needed on whether this may become authoritative |
| E-14 | **Engines already self-verify** | `rag/engine.py:183,354`; `agent/engine.py:177,207`; `automation/engine.py:170,200`; `migration/engine.py:290,353,456`; `rag/repair.py:144-170`; `base.py:98,254` | Every engine runs `_stage_verify` (real `unittest discover` subprocess for RAG; `ast.parse` + proprietary-leak + test-file presence for Agent/Automation; behavioural equivalence for Migration) and publishes `verification_scorecard`. The delivery platform ships `scripts/test.sh` to the customer | **The verification contract already exists inside the engines and is discarded at the seam.** Supports a **layered** (L2) contract that 18-LR did not name |
| E-15 | **No engine registry exists** | `workforce/registry.py`; `modernization/capability_registry.py`; `apps/api/src/autoforge_api/service.py:2358`; AST scan of all `packages/*/src` | `WORKER_REGISTRY` maps 23 *worker specialisations* (different domain). `TechnologyCapabilityRegistry` maps *source-technology* capabilities (different domain). The only production engine instantiation is `apps/api` `execute_rag_power_engine`, which **hardcodes RAG**, bypasses the Kernel entirely, and uses `asyncio.run` — unreachable from the async O-2 path | Edges 1–2 of routing are **genuinely new work**. The `apps/api` precedent proves engine invocation is sanctioned but is **not** a routing seam and is O-3, *"parallel to the Kernel"* per ADR-019 |
| E-16 | **Architecture vs implementation** | `ARCHITECTURE.md:686,1409-1413`; `KERNEL_SPECIFICATION.md:2917-2920,2952-2956`; `MANIFEST.md:17,72` | The architecture states Power Engines produce turnkey deliverables, that the Review Engine *is* the quality gate, and that completion requires *"All tests passed"*. The **architecture never specifies where capability selection lives** | The routing gap is a **specification omission**, hence an ADR is required (DECISION D). *"All tests passed"* is already a specified requirement that is simply unenforced |
| E-17 | **Protected systems frozen** | `git diff --name-only` over the 14 modified files; `git status --porcelain` = 34 pre-existing lines at start and at finish (the 35th is this gate's own new report directory) | Zero matches for `context_builder`, `context_selection`, `prompt_assembly`, `compaction`, `router`, `durable`, `artifact_catalog`, `physical`. `power_engines/` (all 4 engines), `review/` and `strategic_engine.py` are unmodified. `modernization/pipeline.py` **is** in the diff — but that is 18-LR's **B-2 repair**, pre-existing at gate entry and **not** made by this gate; the modernization *engine* internals (`transformation.py`, `analysis.py`, `g3_transform_strategies.py`, `analyzers/`) are untouched. `context_builder.py` contains **no** `input_data` reference. No Brain module; no `phase19`; `local-m1`/`local-hp` are labels bound to `127.0.0.1` | **No protected subsystem requires modification** for Options A, B or D. **Option C alone would require changing the Strategic Engine** — reported, not taken |
| E-18 | **B-1 / D-8 are complementary** | `kernel/completion.py:596` (B-1) vs `:695` (D-8) | B-1 blocks on *empty evidence*; D-8 blocks on *deterministic failure*. A project with many artifacts and failing tests passes B-1 and must be caught by D-8 | The two repairs do not overlap and must both be in place. **D-8b must be fixed together with propagation** — fixing one alone leaves the chain broken at the other end |
| E-19 | **Review's `None` semantics are correct and must not change** | `review/engine.py:64-68` | `_tests_pass(evidence)` returns `True` when `test_results is None` — documented as *"absence is not a failure — treat as 'not asserted'"* | The defect is **not** this line. It is that no evidence is ever produced. **The deterministic verification requirement must not be weakened here.** |
| E-20 | **Test-isolation observation** | `packages/composition/tests/` in one process vs individually | 3 failures in a single-process run (`test_canonical_context_builder`, `test_canonical_durable_artifacts`, `test_execution_platform_integration`); **all three pass individually** | Cross-test state pollution in the harness — **not** a 18-L/18-LR regression. Recorded so it is not mistaken for one |

---

## 2. Two-dimension engine matrix

| Engine | Existing Certified Entry | Canonical Entry | ENGINE IMPLEMENTATION | CANONICAL INTEGRATION | Missing Edge(s) |
|---|---|---|---|---|---|
| RAG Knowledge | `RAGKnowledgePowerEngine.execute_lifecycle` `base.py:141` | none | **PASS** (123 PE suite) | **FAIL** | identify → route → invoke |
| Custom AI Agent | `CustomAIAgentPowerEngine.execute_lifecycle` `agent/engine.py:22` | none | **PASS** | **FAIL** | identify → route → invoke |
| AI Automation | `AIAutomationPowerEngine.execute_lifecycle` `automation/engine.py:22` | none | **PASS** | **FAIL** | identify → route → invoke |
| Code Migration | `CodeMigrationPowerEngine.execute_lifecycle` `migration/engine.py:36` | none | **PASS** | **FAIL** | identify → route → invoke |
| Legacy Modernization | `ModernizationPipeline.run` `pipeline.py:222` (**sync**) | none | **PASS** (B-2 + G.3, 91 tests) | **FAIL** | identify → route → invoke **+ input adaptation** |

**No engine is declared broken. All five remain independently certified.**

---

## 3. Validation-evidence matrix

| Consumer | Needs | Currently receives | Status |
|---|---|---|---|
| `EngineeringLoop` (per iteration) | `input_data["verification_commands"]` / `["commands"]` / `["test_commands"]` | nothing (never written) | ❌ D-8 edge 1 |
| `EvaluationEngine` | ≥1 `CommandResult` | `evaluate_attempt([])` ⇒ `INCONCLUSIVE`, `passed=False` | ❌ zero commands |
| `evaluation_report_iter_N.json` | real `test_results` | `"status":"inconclusive"`, `"test_results": null` | ❌ |
| `WorkspaceValidationPort` (per project) | `ProjectState.configuration` | `{}` — coroutine never awaited | ❌ **D-8b** |
| `KernelReviewEngineAdapter` → Review | real `TestResultSummary` | `None` ⇒ `_tests_pass → True` | ❌ |
| `finalize_project` deterministic gate | `validation["required"] and not passed` | `required: False` | ❌ gate never applies |
| `FinalReviewEvidenceCollector` | COMMITTED 18-K artifacts | real artifacts | ✅ **WORKS** |
| B-1 evidence-authority gate | collector + non-empty evidence | real | ✅ **WORKS** (20 tests) |

**The evidence *delivery* machinery is complete and correct (B-1 ✅, 18-K ✅). The *production* of deterministic evidence is absent, and one consumer is additionally broken (D-8b).**

---

## 4. Commands executed by this gate (all read-only)

| Command | Purpose | Result |
|---|---|---|
| `git branch --show-current; git rev-parse --short HEAD; git rev-parse --short origin/main; git status --porcelain` | baseline | `main` · `c72dad9` · `c72dad9` · 34 lines |
| `python3 18LR-defect-repair/ast_engine_reachability.py` | re-derive E-2 | `canonical_path_reaches_any_engine: false` |
| `pytest packages/power_engines/tests/` | re-verify E-4 | 123 passed, 3 skipped, 1 failed (env. 8080) |
| `pytest packages/modernization/tests/test_18lr_b2_real_source_transformation.py test_g3_llm_and_transform.py` | re-verify E-5 | 91 passed |
| `pytest packages/kernel/tests/test_completion_gates_18lr.py` | re-verify E-9 | 20 passed |
| `pytest packages/composition/tests/test_final_review_evidence_e2e.py` | re-verify E-6 | 9 passed |
| `lsof -nP -iTCP:8080 -sTCP:LISTEN` | confirm E-4 root cause | MLX server holds the port |
| `/tmp/18ld_probe_d8.py` | prove E-8 | `required: false` despite a declared command |
| `/tmp/18ld_probe_worker2.py` | prove E-10 | `BackendEngineer` (a `WorkforceWorker`) reads `verification_commands` |

**All probes wrote only to `/tmp`. No repository file other than these four reports was created or modified.**



| E-5 | **G.3 real-source modernization** | `18LR-defect-repair/layer_a_modernization.py`; `modernization/pipeline.py`; `test_18lr_b2_real_source_transformation.py` (**re-run: 8 pass**), `test_g3_llm_and_transform.py` (**re-run: 83 pass**) | Real `LEDGER.cbl` (616 B, genuine `IDENTIFICATION DIVISION`) → real Java; `LEDGER.jcl` (174 B) → real workflow config; pipeline `complete`; 2/2 real files transformed; zero placeholders | Legacy Modernization is **certified and repaired**. Any routing adapter must supply **real** reconnaissance input or B-2 regresses through a new door |
| E-6 | **D-8 validation repair** | `validation_wiring.py:92-190`; `kernel/completion.py:475-505,608-609,684-709`; `kernel_adapters.py:54-101`; `test_completion_gates_18lr.py` (**re-run: 20 pass**); `test_final_review_evidence_e2e.py` (**re-run: 9 pass**) | The Kernel defines only a port; composition reuses the existing `WorkspaceEnvironment` + `parse_test_output`; `finalize_project` blocks a mandatory failed validation even after an explicit `APPROVED`, recording `overridden_by: "deterministic_validation_gate"`; the review adapter consumes a real `TestResultSummary` | The **mechanism** is correct and proven. It is inert on the canonical path — for **two** independent reasons (E-7, E-8) |
| E-7 | **Greenfield reproduction** | `18L-autonomous-certification/evidence/greenfield_run.json`; 18-LR §5.2 | 27/27 COMMITTED artifacts (15 `source_code`); the project's own suite: **2 failed, 4 passed**; `evaluation_report_iter_{1,2,3}.json` all `"status":"inconclusive"`, `"test_results": null`; final review **APPROVED**; project **finished** | **BLOCKER B confirmed.** No command runs ⇒ no deterministic truth ⇒ nothing for D-8 to enforce |
| E-8 | **D-8b — NEW, found by this gate** | `validation_wiring.py:119` vs `runtime_facade.py:150`; `composition_root.py:457-460`. **Live probe** | `_project_configuration` calls `self._runtime.get_project_state()` **synchronously**, but the wired `KernelRuntimeFacade.get_project_state` is `async def`. It receives a coroutine, `isinstance(state, dict)` is `False`, returns `{}`. The repo's own test run emits `RuntimeWarning: coroutine ... was never awaited` at `validation_wiring.py:134` | **The port reports `required: False` for EVERY project — even one that declares a command.** A third blocker inside DECISION B, **independent** of declared-vs-discovered. Reported, NOT fixed |
