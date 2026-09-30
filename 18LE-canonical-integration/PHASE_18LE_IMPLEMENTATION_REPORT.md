# PHASE 18-LE — CANONICAL CAPABILITY ROUTING + VALIDATION TRANSPORT REPAIR

**Workstream:** 18-LE — Implementation gate following 18-L, 18-LR and 18-LD
**Date:** 2026-09-30 · **M6-only, single-node, authoritative**

# 18-L = CERTIFIED

All 25 certification criteria pass. The two 18-LR blockers are repaired, the
18-LD-discovered **D-8b** defect is repaired, and a fresh greenfield autonomous
run reaches `FINISHED` on real M6 inference with real deterministic validation.

---

## 1. Baseline

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD (start **and** finish) | `c72dad9e0ffe44d6aeac958e985544801820acf4` |
| `origin/main` | `c72dad9e0ffe44d6aeac958e985544801820acf4` |
| Tracked modifications at gate entry | 14 files (18-L/18-LR work, pre-existing) |
| Untracked at gate entry | 20 entries |
| Commits / pushes / resets / cleans | **none** |
| Pre-existing untracked files | **all preserved** |

Created by **this** gate:

```
?? packages/composition/src/autoforge_composition/capability_router.py   (NEW routing seam)
?? packages/composition/tests/test_capability_routing.py                  (NEW, 26 tests)
?? packages/composition/tests/test_d8b_validation_transport.py           (NEW, 12 tests)
?? packages/composition/tests/test_d8_safety_matrix.py                    (NEW, 10 tests)
?? 18LE-canonical-integration/                                           (harness + evidence)
```

Modified by this gate (3, all in `packages/composition`):

```
M composition_root.py   (wire router + durable-config reader)
M kernel_adapters.py    (routing seam + verification transport)
M validation_wiring.py  (D-8b async fix; 18-LR file, already untracked)
```

**No Commercial Power Engine, Strategic Engine, Model Router, Context
Engineering, Context Compaction, 18-J, 18-K or Review Engine was modified.**

---

## 2. 18-LR / 18-LD findings reproduced

| Finding | Reproduced how | Result |
|---|---|---|
| **A.** Five capabilities fail canonical routing | 18-LR AST probe re-run + 18-LR evidence | Confirmed at gate entry |
| **B.** D-8b: async `get_project_state` called synchronously | 18-LD's probe re-run **before** the fix | `required: false` despite a declared command |
| **C.** Engines independently produce deterministic verification | `_stage_verify` → `verification_scorecard` (×4); `PipelineResult` (×1) | Confirmed |
| **D.** Certified G.3 modernization with real COBOL/JCL | `test_18lr_b2_real_source_transformation.py` + `test_g3_llm_and_transform.py` | **91 passed** |

**D-8b reproduced verbatim (pre-fix):**
```
validate_project(REAL project that DOES declare a command):
    {"required": false, "performed": false, "passed": true,
     "reason": "Project declares no verification command.", "command": null}
```

---

## 3. D-8b repair

**Root cause.** `WorkspaceValidationPort._project_configuration` called
`self._runtime.get_project_state(project_id)` **synchronously**. The wired
object is `KernelRuntimeFacade`, whose `get_project_state` is `async def`
(`runtime_facade.py:150`). The call returned an un-awaited coroutine;
`isinstance(state, dict)` was `False`; the method returned `{}` **for every
project**, so the D-8 deterministic gate was inert in production.

**Repair** — the ONLY semantic change:

```python
async def _project_configuration(self, project_id):
    state = self._runtime.get_project_state(project_id)
    if inspect.isawaitable(state):
        state = await state          # ← the fix
```
…and the single call site now awaits it.

**Not done** (per §4): facade not made synchronous; no second project-state API;
no new state model; no 18-J/18-K change; no change to validation semantics
beyond retrieving the state. A synchronous reader is still accepted — an
accommodation, not a second authority.

**Post-fix (same probe):**
```
validate_project(REAL project that DOES declare a command):
    {"required": true, "performed": true, "passed": true,
     "command": ["python", "-c", "print('ok')"]}
```

**Regression tests:** `test_d8b_validation_transport.py` — **12 passed**:
declared → `required=True`; absent → `required=False` (unchanged contract);
failing command reported as failure; **no `never awaited` RuntimeWarning**; read
through the canonical async facade; sync reader supported; resolver unchanged.

---

## 4. Capability identity

18-LD proved no new abstraction is needed. The identifier uses the **already
proven durable configuration channel**.

| Capability | Canonical value | Aliases | Engine |
|---|---|---|---|
| RAG | `rag_knowledge` | `rag`, `rag_pipeline`, `knowledge` | `RAGKnowledgePowerEngine` |
| Custom AI Agent | `custom_ai_agent` | `agent`, `ai_agent`, `custom_agent` | `CustomAIAgentPowerEngine` |
| AI Automation | `ai_automation` | `automation`, `ai_automation_pipeline` | `AIAutomationPowerEngine` |
| Code Migration | `code_migration` | `migration`, `code_migration_refactoring` | `CodeMigrationPowerEngine` |
| Legacy Modernization | `legacy_modernization` | `modernization`, `legacy_modernization_pipeline` | `ModernizationPipeline` |


---

## 5. Routing implementation

**Seam — verified against source before editing (as required):**
`KernelExecutionEngineAdapter.execute_loop`, the last boundary before the
generic `ExecutionEngine` commits.

**What was added**

1. `capability_router.py` — **new**, in the composition package (ADR-002
   compliant: composition owns all wiring). The only new architectural object.
2. `KernelExecutionEngineAdapter` gains two **optional** injected collaborators
   (`capability_router`, `project_configuration_reader`), both defaulting to
   `None`, so any caller that does not supply them gets the original adapter.
3. A routing branch at the top of `execute_loop`. **No capability ⇒ the generic
   code below runs unchanged.**

**Result shape** — the same dict `handle_loop_completion` already consumes, plus
routing evidence: `routed`, `capability`, `capability_source`, `engine_class`,
`delivery_dir`, `stages_executed`, `verification_scorecard`.

**Engine boundary adaptation — engines NOT modified:**

- Engines 1–4: `execute_lifecycle(spec)`, the uniform existing contract.
- Automation and Migration **reject a base spec by design** (`_resolve_spec`
  raises `TypeError`), so their typed specs are built at the routing boundary.
- Legacy Modernization is synchronous and reconnaissance-driven: it runs through
  `asyncio.to_thread` and **refuses to run without a real `legacy_source_root`**,
  which prevents B-2 from regressing through a new door.

**Nothing is bypassed.** The routed result flows through the existing
`ArtifactPipeline` → `DurableArtifactCatalog` → `PhysicalArtifactStore`, and the
engine's own verification scorecard is published as a **durable `test_report`
artifact**, so it reaches Review by the ordinary evidence path.

**Five-engine routing result** (real composed system, no mocks):

| Capability | Engine actually invoked | Routed | Status | Delivery |
|---|---|---|---|---|
| `rag_knowledge` | `RAGKnowledgePowerEngine` | 4/4 | complete | ✅ |
| `custom_ai_agent` | `CustomAIAgentPowerEngine` | 4/4 | complete | ✅ |
| `ai_automation` | `AIAutomationPowerEngine` | 4/4 | complete | ✅ |
| `code_migration` | `CodeMigrationPowerEngine` | 4/4 | complete | ✅ |
| `legacy_modernization` | `ModernizationPipeline` | 4/4 | complete | n/a |

`"canonical_routing_pass": true` — `evidence/canonical_routing.json`.

---

## 6. Validation transport

**The single missing write 18-LD identified, now written:**

```
Request.configuration["verification_command"]
  → durable in ProjectState.configuration          (already worked)
  → read at execute_loop                          ← THE ADDED WRITE
  → input_data["verification_commands"] = [[argv…]]
  → WorkforceWorker.execute_task                  (already read it)
  → EngineeringLoop.run                            (already honoured it)
  → WorkspaceEnvironment.execute_command           (real subprocess)

---

## 7. Five-engine results

Full matrix in `FIVE_ENGINE_CERTIFICATION_MATRIX.md`.

| Engine | Existing cert | Canonical routing | Real output | Deterministic validation | Durable artifacts | Review | Completion |
|---|---|---|---|---|---|---|---|
| RAG | PASS (123) | PASS | PASS | PASS | PASS | PASS | PASS |
| Agent | PASS (123) | PASS | PASS | PASS | PASS | PASS | PASS |
| Automation | PASS (123) | PASS | PASS | PASS | PASS | PASS | PASS |
| Migration | PASS (123) | PASS | PASS | PASS | PASS | PASS | PASS |
| Modernization | PASS (91) | PASS | PASS | PASS | PASS | PASS | PASS |

**No engine is marked broken.** Existing certification unchanged: 123 power-engine
tests + 383 modernization tests (+ 59 skip) pass.

**Engine-owned verification transported (DECISION B layer 2):**

| Engine | Scorecard keys reaching the canonical result |
|---|---|
| RAG | `grounding_score`, `real_inference`, `syntax_valid`, `tests_passed`, `tests_run` |
| Agent | `defects_count`, `passed`, `proprietary_violations` |
| Automation | `defects_count`, `passed`, `proprietary_violations` |
| Migration | `failed`, `inconclusive`, `passed`, `total` |
| Modernization | `analysis_present`, `gate_decisions`, `pipeline_status`, `real_source`, `transformation_records`, `units_failed`, `units_transformed`, `wave_count` |

---

## 8. G.3 modernization regression

**Certified workflow re-run, unchanged: 91 passed** (8 B-2 real-source +
83 G.3 LLM/transform).

**Canonical routing with real COBOL/JCL** (`evidence/canonical_routing.json`):
```
capability : legacy_modernization
engine     : ModernizationPipeline
status     : complete
scorecard  : pipeline_status, real_source=true, transformation_records,
             units_transformed, units_failed, wave_count, gate_decisions,
             analysis_present
```

Real source in, real modernized output out. The engine implementation is
**untouched** — `git diff --name-only` contains no `modernization/` file other
than `pipeline.py`, which is 18-LR's pre-existing B-2 repair. B-2 has **not**
regressed: the router refuses to synthesise a placeholder and requires a real
`legacy_source_root`.


---

## 10. Greenfield certification

**FRESH run, M6-only, real inference, nothing reused.** Full evidence in
`GREENFIELD_CERTIFICATION_REPORT.md` and `evidence/greenfield.json`.

| Requirement | Result |
|---|---|
| Actual model generation | ✅ Qwen3-Coder-30B via MLX on `127.0.0.1:8080` |
| Real source produced | ✅ `textmetrics/core.py`, `__init__.py`, `tests/test_textmetrics.py`, `README.md` |
| **G-1** verification contract exists | ✅ `verification_command: "python -m pytest -q tests"` — **declared**, never invented |
| **G-2** verification executes | ✅ `cmd_python_iter_1.log` → `2 passed`, `EXIT_CODE: 0` |
| **G-3** validation governs completion | ✅ `required=True, performed=True, passed=True, exit_code=0` |
| Passing deterministic validation | ✅ |
| Validation evidence reaches Review | ✅ 9 evidence files incl. the command log + evaluation report |
| Review APPROVED → Completion succeeds | ✅ `final_state = ProjectStatus.FINISHED` |
| Source artifacts durable | ✅ 10/10 **committed** |
| Artifacts recoverable, hashes match | ✅ `all_exist=True, all_hashes_match=True` |
| Zero manual engineering intervention | ✅ no generated file edited/created/stubbed by hand |

**Model binding note (configuration only, no source change).** The production
Model Router catalog registers `qwen2.5-coder-7b` / `ornith-9b`; the M6 runtime
serves `Qwen3-Coder-30B`. The existing provider-neutral deployment seam
`BaseProviderAdapter.register_model_alias` binds them — exactly as 18-L did. This
adds no provider, registers no model, changes no router, changes **no inference
topology**, starts no worker, and references no M1/HP hardware.

---

## 11. CE regression

Context Engineering is **unchanged and still enabled by default**
(`composition_root.py:376`, `enable_context_engineering` defaults `True`).

`context_builder.py`, `context_selection.py`, `prompt_assembly.py` — **zero
source changes**. Critically, `context_builder.py` contains **no** `input_data`
reference, so the new transport cannot disturb context assembly; `input_data`
reaches the worker through `ExecutionContext.from_task_definition`
(`context.py:98`), which is untouched.

Proven live: the greenfield run produced bounded, attributable context
(`architecture_proposal.md`, `qa_test_strategy.md`, per-iteration diffs), with
evidence correctly attributed to the right workflow/project (verified by
`find_by_workflow` correlation — 10/10 artifacts, no cross-task collision).

Suites: `execution` 233 passed / 18 skipped, `runtime` 268 passed.

---

## 12. Compaction regression

Context Compaction is **unchanged and still enabled by default**
(`composition_root.py:364`, `enable_context_compaction` defaults `True`).
`compaction` source: **zero changes**. The compaction record store is still owned
by the composition root over the same `DurableArtifactCatalog` /
`PhysicalArtifactStore`.


---

## 14. Full CI

Each package suite run as its own invocation, exactly as
`.github/workflows/ci.yml` does, with `AUTOFORGE_ALLOW_DETERMINISTIC_FALLBACK=1`
(the harness variable 18-LR used for offline model binding).

| Suite | Result | Suite | Result |
|---|---|---|---|
| kernel | **161 passed** | modernization | **383 passed**, 59 skip |
| orchestration | **71 passed**, 6 skip | power_engines | **123 passed**, 3 skip, **1 env** |
| workflows | **218 passed** | connectors | **93 passed** |
| execution | **233 passed**, 18 skip | ai_infrastructure | **97 passed** |
| runtime | **268 passed** | workforce | **36 passed**, 2 skip |
| review | **114 passed** | observability | **16 passed** |
| persistence | **70 passed** | events | **228 passed** |
| security | **37 passed** | event_platform | **56 passed** |
| artifacts | **14 passed** | composition | **146 passed** |
| root (`tests/`) | **96 passed**, 1 skip | | |

### Product failures: **0**. Collection errors: **0**.

**Environmental failure (explicitly separated, not a product failure):**
`power_engines/tests/test_delivery_hardening.py::test_health_check_script_execution_and_exit_codes`
— the fixture declares a service on host port **8080**, which the operator's MLX
inference server is listening on, so `--require-service` correctly finds it online
and asserts "offline". Independently confirmed with `lsof`; the same collision is
documented in 18-LR §2. It is **not** caused by this gate and disappears when the
inference server is stopped. Every other power-engine test passes (123).

New this gate: **48 tests** (26 routing + 12 D-8b + 10 safety matrix), all passing.

---

## 15. Remaining defects

**None blocking certification.** Two environmental observations:

| Item | Class | Status |
|---|---|---|
| Power-engine health-check test vs. MLX on port 8080 | **Environmental** | Pre-existing, documented in 18-LR §2, re-confirmed. Not a product defect |
| The Model Router catalog names `qwen2.5-coder-7b` / `ornith-9b` while M6 serves `Qwen3-Coder-30B` | **Deployment configuration** | Handled by the existing `register_model_alias` seam, exactly as 18-L did. Not a defect, and not repaired (Model Router is protected) |

**Not implemented, by instruction:** autonomous verification discovery
(DECISION B layer 3) — explicitly out of scope.

---

## 16. Final verdict

# 18-L = CERTIFIED

| # | Criterion | Result |
|---|---|---|
| 1 | D-8b repaired and regression-tested | ✅ 12 tests |
| 2 | Canonical capability identity works | ✅ 26 tests |
| 3 | All five commercial engines reachable canonically | ✅ 5/5 |
| 4 | Existing engine certifications remain green | ✅ 123 + 383 |
| 5 | Canonical engine invocation proven with real execution | ✅ 11-stage lifecycle observed |
| 6 | Real engine outputs produced | ✅ real delivery dirs |
| 7 | Deterministic validation executes | ✅ real pytest, exit 0 |
| 8 | Validation evidence reaches Review | ✅ 9 evidence files |
| 9 | Failed deterministic validation blocks completion | ✅ CASE B/D + live run |
| 10 | Missing mandatory validation blocks completion | ✅ CASE C |
| 11 | Review rejection blocks completion | ✅ CASE E |
| 12 | Durable artifacts committed | ✅ 10/10 |
| 13 | Artifacts recoverable with matching hashes | ✅ SHA-256 verified |
| 14 | Fresh greenfield autonomous run passes | ✅ FINISHED |
| 15 | Fresh certified legacy modernization passes | ✅ 91 tests + canonical run |
| 16 | Full architecture path proven | ✅ canonical trace evidence |
| 17 | CE intact | ✅ unchanged, enabled |
| 18 | Compaction intact | ✅ unchanged, enabled |
| 19 | 18-J intact | ✅ unchanged |
| 20 | 18-K intact | ✅ unchanged |
| 21 | M1 untouched | ✅ |
| 22 | HP untouched | ✅ |
| 23 | Inference topology unchanged | ✅ 0 workers, no change |
| 24 | Brain absent / Phase 19 not started | ✅ |
| 25 | Full CI green | ✅ 0 product failures, 0 collection errors |

**Nothing was committed. Nothing was pushed. HEAD remains `c72dad9`.**

*Reports: `PHASE_18LE_IMPLEMENTATION_REPORT.md` · `CAPABILITY_ROUTING_IMPLEMENTATION.md` ·
`VALIDATION_TRANSPORT_IMPLEMENTATION.md` · `FIVE_ENGINE_CERTIFICATION_MATRIX.md` ·
`GREENFIELD_CERTIFICATION_REPORT.md`*

Proven live: the multi-iteration greenfield run produced versioned artifacts
(`evaluation_report_iter_2.json.v2`, `changes_iter_3.diff.v3`), the existing 18-K
versioning behaviour; no compaction record was misattributed.

---

## 13. 18-J / 18-K regression

`durable.py` (18-J); `artifact_catalog`, `physical_artifact_store`,
`durable_bridge` (18-K): **zero source changes**.

| Behaviour | Evidence |
|---|---|
| Durable artifact registration | 10/10 **committed** in the fresh greenfield run |
| Idempotency | pre-existing `register_artifact` replay semantics untouched; re-publish iterations produced `.v2`/`.v3` keys, not duplicates |
| Interruption / resume | 18-J suite green within `runtime` 268 passed |
| Recovery | `artifacts` 14 passed |
| Hash integrity | **`all_exist=True, all_hashes_match=True`** across every committed artifact |
| Versioned physical paths | `.v2` / `.v3` revisions, no overwrite |

---

---

## 9. D-8 safety matrix

`test_d8_safety_matrix.py` — **10 passed**. All five mandatory cases:

| Case | Scenario | Result |
|---|---|---|
| **A** | verification exists + tests pass | completion allowed ✅ |
| **B** | verification exists + tests fail | completion **BLOCKED** ✅ |
| **C** | verification missing where mandatory | distinguishable from "passed", not silently passing ✅ |
| **D** | Review **APPROVED** + validation **FAILED** | completion **BLOCKED** ✅ |
| **E** | Review **REJECTED** + validation **PASSED** | completion **BLOCKED** ✅ |

Plus: an unreadable/malformed verdict (`None`, `{}`, `{"decision":"approved"}`,
`1`, `"yes"`) is **never** an approval.

**Case D is proven twice** — as a unit test, and for real: a greenfield run whose
generated tests genuinely failed (`assert 12 == 11`) was **blocked** at
`COMPLETING`, never reaching `FINISHED`.

---

  → EvaluationEngine.evaluate_attempt + parse_test_output
  → evaluation_report_iter_N.json  (real deterministic_checks + test_results)
  → review evidence → final Review
  → Completion gate: required and not passed → BLOCK
```

The command is read with the **same** existing resolver the completion gate uses
(`resolve_verification_command`), so the loop and the gate can never disagree.
It is applied **after** the pre-existing DEF-18L-03 fallback so a
fallback-created input mapping cannot discard the declaration.

**Proven in the live greenfield run:**
```
artifacts/cmd_python_iter_1.log            ← the command actually ran
   STDOUT: ..  [100%]  2 passed in 0.00s
   EXIT_CODE: 0
artifacts/evaluation_report_iter_1.json    ← real deterministic truth
   status: passed, deterministic_checks: [...], test_results: {...}
```

Before the repair these files did not exist and the report read
`"status": "inconclusive", "test_results": null` — the exact 18-L gap.

**No second validation authority.** Layer 1 (requester-declared) feeds the loop;
Layer 2 (engine-declared scorecard) is transported as durable evidence; Layer 3
(autonomous discovery) is **out of scope and NOT implemented**.

Proven by test: survives **Request → ProjectState → execution**; **deterministic**
(pure string normalisation, no model consulted); **inspectable**
(`capability_source` is returned); **does not change generic requests**;
**requires no engine modification**; **fail-closed** (unknown → `None` →
`UnknownCapabilityError`, never silently coerced).
