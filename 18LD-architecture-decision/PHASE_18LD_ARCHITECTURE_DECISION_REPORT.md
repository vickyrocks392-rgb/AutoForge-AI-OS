# PHASE 18-LD — CANONICAL CAPABILITY ROUTING + DETERMINISTIC VERIFICATION CONTRACT DECISION GATE

**Workstream:** 18-LD — Architecture Decision & Evidence Gate
**Mode:** Evidence and architecture decision only. **No production behaviour was modified.**
**Date:** 2026-09-29
**Predecessor:** 18-LR (`18LR-defect-repair/PHASE_18LR_DEFECT_REPAIR_REPORT.md`) — **VERDICT: 18-L = NOT CERTIFIED**

---

## 1. Executive Summary

This gate answers two architecture questions that 18-LR correctly refused to decide unilaterally:

- **DECISION A — Canonical capability routing.** How should the canonical architecture select and invoke the correct Commercial Power Engine?
- **DECISION B — Deterministic verification-command ownership.** Who declares the verification command, and is verification mandatory for greenfield?

**What this gate did.** It read the authoritative architecture, inventoried all five Commercial Power Engines from source, traced the real canonical request path end to end, and independently re-derived the 18-LR evidence. It reproduced the 18-LR AST reachability proof, re-ran the engine certification suites, and ran three new **read-only** probes against the real composed system (probes live in `/tmp`, not in the repository; the working tree is byte-identical to the start of this gate).

**What this gate did NOT do.** It implemented no routing, no verification discovery, no repair of any kind. It did not modify a Commercial Power Engine, the Kernel, the Strategic Engine, the Model Router, Context Engineering, Context Compaction, 18-J or 18-K. It did not commit, push, reset or clean. **18-L remains NOT CERTIFIED.**

### Headline findings

| # | Finding | Evidence class |
|---|---|---|
| **F-1** | The canonical path reaches **no** Commercial Power Engine. `external_importing_packages = {}` for both engine packages; the loop-dispatch seam is the last point at which a commercial engine *could* be selected. | Re-derived AST + 18-LR dynamic probe |
| **F-2** | The five engines **already share one uniform contract**: `PowerEngine.execute_lifecycle(spec) -> PowerEngineResult` over the 11-stage lifecycle. Only Legacy Modernization differs (synchronous `ModernizationPipeline.run`). | Source |
| **F-3** | **Capability identity already exists upstream and is already durable.** `Request.configuration` → `Project.metadata` → `ProjectState.configuration`, and it is already read at two points in the canonical path. No new abstraction is required to *name* a capability. | Source + probe |
| **F-4** | **NEW DEFECT (D-8b), found by this gate.** The D-8 validation port **cannot read a declared verification command even when one is declared**, because `validation_wiring.py:119` calls the *async* `KernelRuntimeFacade.get_project_state` synchronously. It receives a coroutine, `isinstance(state, dict)` is `False`, and it returns `{}`. This is a third blocker **inside** DECISION B and is independent of the declared-vs-discovered question. | **Live probe** |
| **F-5** | The verification channel is **live and already read**: the canonical dispatch path resolves `BackendEngineer` (a `WorkforceWorker` subclass), whose `execute_task` already reads `context.input_data["verification_commands"]`. `EngineeringLoop.run` additionally honours `input_data["commands"]` / `["test_commands"]`. The channel is fed by **nothing**. | Live probe + source |
| **F-6** | Every commercial engine **already produces its own deterministic verification** (`_stage_verify` → `verification_scorecard`) and **already has a documented verification command** in its own generated deliverables (`scripts/test.sh`, `deploy.sh` test stage). This is the strongest existing evidence for a layered contract. | Source |
| **F-7** | **No** can AutoForge claim an autonomous greenfield deliverable is validated merely because `ReviewEngine` returns `APPROVED`. Derived from B-1, D-8, D-8b and completion semantics — see §14. | Derived |

### The decision the human must make

18-LR correctly stopped because these are product decisions. This gate's contribution is to make the decision **tractable**: for DECISION A the options are now enumerated with their exact file impact; for DECISION B the repository contains a **third option 18-LR did not name** — engines already self-declare a verification command, which makes a layered contract (declaration → engine-declared → future discovery) directly supported by existing evidence.

**No protected subsystem requires modification.** None of CE, Compaction, Model Router, 18-J, 18-K, M1, HP, Brain or Phase 19 is touched by either candidate repair.

---


## 2. Baseline

Recorded at the start of this gate and re-verified at the end. **The working tree was not altered.**

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD (start **and** finish) | `c72dad9e0ffe44d6aeac958e985544801820acf4` |
| `origin/main` | `c72dad9e0ffe44d6aeac958e985544801820acf4` |
| **HEAD is `c72dad9` — CONFIRMED, matches the gate brief** | ✅ |
| Commits / pushes / resets / cleans | **none** |
| Tracked modifications | 14 files (13 from 18-L + `packages/modernization/.../pipeline.py`) |
| Untracked entries | 20 |
| `git status --porcelain` line count | 34 at start, **34 at finish** — unchanged |
| New files created by this gate | `18LD-architecture-decision/` (4 reports) only |

Tracked modifications (18-L/18-LR work, pre-existing at gate entry, left intact):

```
packages/composition/src/autoforge_composition/composition_root.py
packages/composition/src/autoforge_composition/kernel_adapters.py
packages/composition/tests/test_architecture_reconciliation_e2e.py
packages/composition/tests/test_canonical_learning_lifecycle.py
packages/execution/src/autoforge_execution/ai_adapter.py
packages/execution/src/autoforge_execution/artifacts.py
packages/execution/src/autoforge_execution/loop.py
packages/kernel/src/autoforge_kernel/completion.py
packages/kernel/src/autoforge_kernel/kernel.py
packages/kernel/src/autoforge_kernel/orchestration.py
packages/kernel/tests/test_integration.py
packages/kernel/tests/test_orchestration.py
packages/kernel/tests/test_unit.py
packages/modernization/src/autoforge_modernization/pipeline.py
```

---

## 3. Authoritative Architecture

Separated deliberately into **ARCHITECTURAL CONTRACT** (what the specification says) and **CURRENT IMPLEMENTATION** (what the code does). Per `architecture/MANIFEST.md:17`, *"Any implementation that deviates from this specification is, by definition, incorrect until the specification is amended through the proper review process."*

### 3.1 The canonical flow, as specified

From `docs/subsystems/kernel/KERNEL_SPECIFICATION.md` and `architecture/ARCHITECTURE.md`, the production path is:

```
Request → Kernel.submit_request (kernel.py:219)
  → Intake (validate, normalize, project init)
  → Intent Analysis (intent_analysis.py:20 DefaultIntentAnalyzer)
  → Planning Coordination (planning_coordination.py:28 DefaultPlanningCoordinator)
      → Strategic Engine (strategic_engine.py:27 DefaultStrategicEngine)
      → Workflow Engine (kernel_adapters.py:106 KernelWorkflowEngineAdapter)
        → ExecutableWorkflow
  → Orchestration (orchestration.py:37 DefaultOrchestrationEngine — "O-2",
     production-authoritative per ADR-019)
      → LoopOrchestrator (orchestration.py:385)
        → ExecutionEngine.execute_loop (kernel_adapters.py:263 KernelExecutionEngineAdapter)
          → ExecutionEngine.execute_task_definition (engine.py:144)
            → WorkforceDispatcher.dispatch_task (workforce/dispatch.py:96)
              → EngineeringContextBuilder.assemble_context
              → WorkforceWorker.execute_task (workforce/workers.py:62)
                → EngineeringLoop.run (loop.py:97)
                  → WorkspaceEnvironment.execute_command
                  → EvaluationEngine.evaluate_attempt
                  → ArtifactPipeline → DurableArtifactCatalog → PhysicalArtifactStore
  → Completion (completion.py:637 finalize_project)
      → validate_completion
      → _run_final_review (mandatory gate)
      → deterministic validation gate
      → transition_state("Finished")
```

### 3.2 The commercial-offering statement in the architecture

`architecture/ARCHITECTURE.md:1409-1413` is the authoritative statement about the Power Engines:

> *"commercial Power Engines compose platform primitives and produce complete customer-deliverable project packages to user-configured output directories (`AUTOFORGE_OUTPUT_ROOT`)"*
> *"Power Engines (RAG, Agent, Automation, Migration, Modernization)"*

**The architecture states the engines exist and produce deliverables. It does not specify *where* the selection decision lives.** That omission is precisely the gap 18-LR hit, and it is why this is an architecture decision and not a bug fix.

### 3.3 Authority evidence relevant to this gate

| Source | Statement | Bearing on this gate |
|---|---|---|
| `MANIFEST.md:72` | ADRs are immutable; architectural changes require a new ADR | Both repairs will require an ADR (DECISION D) |
| `ADR-019` | O-2 is **production-authoritative**; O-1 is real/certified but unwired; O-3 (API `AutonomousBuildEngine`) is parallel to the Kernel | Routing must land on the **O-2** path, not by re-activating O-1 or by extending O-3 |

## 4. Five Commercial Engine Inventory

**ENGINE IMPLEMENTATION** and **CANONICAL INTEGRATION** are two separate dimensions. A FAIL in the second is **not** an engine defect.

### 4.1 Engine implementations

| # | Engine | Implementation | Public entry point | Input | Output | Uniform? |
|---|---|---|---|---|---|---|
| 1 | **RAG Knowledge** | `power_engines/rag/engine.py:29` `RAGKnowledgePowerEngine` | `execute_lifecycle(spec)` (inherited, `base.py:141`) | `CustomerProjectSpecification` | `PowerEngineResult` | ✅ `PowerEngine` |
| 2 | **Custom AI Agent** | `power_engines/agent/engine.py:22` `CustomAIAgentPowerEngine` | `execute_lifecycle(spec)` | `CustomerProjectSpecification` (adapts internally via `_resolve_spec`, `engine.py:39`) | `PowerEngineResult` | ✅ `PowerEngine` |
| 3 | **AI Automation** | `power_engines/automation/engine.py:22` `AIAutomationPowerEngine` | `execute_lifecycle(spec)` | `CustomerProjectSpecification` | `PowerEngineResult` | ✅ `PowerEngine` |
| 4 | **Code Migration** | `power_engines/migration/engine.py:36` `CodeMigrationPowerEngine` | `execute_lifecycle(spec)` | `CustomerProjectSpecification` | `PowerEngineResult` | ✅ `PowerEngine` |
| 5 | **Legacy Modernization** | `modernization/pipeline.py:161` `ModernizationPipeline` | **`run(project_id, job_id, reconnaissance_output, plan=None)`** — **synchronous** | G.2 reconnaissance output | `PipelineResult` | ❌ **different package, different shape, sync** |

### 4.2 The shared PowerEngine contract (engines 1–4)

`power_engines/base.py:103-301` defines a genuinely uniform contract — the single most important structural fact for DECISION A:

```python
class PowerEngine(ABC):
    def create_context(self, spec: CustomerProjectSpecification) -> PowerEngineContext
    async def execute_lifecycle(self, spec, auto_approve_safe_risks=True) -> PowerEngineResult
    # 11 abstract stage handlers, all (ctx: PowerEngineContext) -> Dict[str, Any]
    _stage_intake · _stage_understand_analyze · _stage_plan · _stage_execute
    _stage_observe · _stage_verify · _stage_diagnose · _stage_repair
    _stage_re_verify · _stage_package · _stage_deliver
```

`execute_lifecycle` already provides everything a router would need: a `PowerEngineContext` with `telemetry`, `stage_history`, `pending_approval` (risk gates), and a `PowerEngineResult` with `success`, `delivery_dir`, `stages_executed`, `repair_count` and `verification_scorecard`. **A router does not need to invent a result envelope.**

`PowerEngineResult.verification_scorecard` (`base.py:98, 254`) is the existing, engine-owned deterministic evidence channel.

### 4.3 Legacy Modernization's different contract

| | Power Engines (1–4) | Legacy Modernization (5) |
|---|---|---|
| Call style | `async` | **sync** |
| Input | `CustomerProjectSpecification` | `reconnaissance_output` (G.2 scanner output) + `project_id` + `job_id` |
| Result | `PowerEngineResult` | `PipelineResult` (`status`, `analysis_report`, `gate_decisions`, `transformation_records`, `wave_results`, `migration_plan`) |
| Package | `autoforge_power_engines` | `autoforge_modernization` |

**Consequence for DECISION A:** any unified registry must normalize this. It cannot be assumed away.

### 4.4 Existing adapters / interfaces for these engines

| Existing artifact | Location | Is it an engine router? |
|---|---|---|
| `KernelExecutionEngineAdapter` | `composition/kernel_adapters.py:263` | ❌ Adapts `ExecutionEngine` only |
| `WORKER_REGISTRY` | `workforce/registry.py` | ❌ Maps *worker specialization* → worker class. Correct shape, wrong vocabulary (23 engineering workers, not 5 commercial offerings) |
| `apps/api` `execute_rag_power_engine` | `apps/api/src/autoforge_api/service.py:2358` | ⚠️ **The only existing production code that instantiates a commercial engine** — but it is a *bypass*, not a router (§6.4) |
| `TechnologyCapabilityRegistry` | `modernization/capability_registry.py` | ❌ Registry of *source-technology transformation* capabilities, not commercial offerings |

**No engine registry exists.** Nothing in the repository maps a capability identifier to a commercial engine.

### 4.5 Orchestration entry point

### 4.6 Certification tests (re-run by this gate)

| Engine | Suite | Result (this gate, HEAD `c72dad9` + 18-LR tree) |
|---|---|---|
| Power Engines (all 4) | `packages/power_engines/tests/` | **123 passed, 3 skipped, 1 failed** |
| Legacy Modernization | `test_18lr_b2_real_source_transformation.py` + `test_g3_llm_and_transform.py` | **91 passed** |
| B-1 / D-8 regression | `packages/kernel/tests/test_completion_gates_18lr.py` | **20 passed** |
| D-8 evidence E2E | `packages/composition/tests/test_final_review_evidence_e2e.py` | **9 passed** |

**The single power-engine failure is the environmental port collision already documented in 18-LR §2** — independently re-confirmed here:

```
lsof -nP -iTCP:8080 -sTCP:LISTEN
  python3.1 76705 ... TCP 127.0.0.1:8080 (LISTEN)      ← MLX inference server

test_delivery_hardening.py:63  PortMapping(host_ip="127.0.0.1", host_port=8080, ...)
test_delivery_hardening.py:274 [sys.executable, str(health_script), "--require-service"]
```

The fixture declares a service on host port 8080; the MLX server occupies it, so `--require-service` correctly finds it online. **Not caused by any 18-L/18-LR change**; reproducible in both directions.

**Test-isolation note (not a regression):** running the whole `packages/composition/tests/` directory in one process yields 3 failures (`test_canonical_context_builder`, `test_canonical_durable_artifacts`, `test_execution_platform_integration`). All three **pass individually** — cross-test state pollution in the harness, unrelated to 18-L/18-LR.

### 4.7 Expected artifacts, validation, review evidence per engine

| Engine | Expected artifacts | Deterministic validation | Declared test command in deliverable | Engine-owned scorecard |
|---|---|---|---|---|
| RAG | `artifacts/knowledge_index.json`, `src/{app,retriever,health,models}.py`, `tests/test_service.py` | ✅ `run_customer_tests()` — real `unittest discover` subprocess (`rag/repair.py:144`) + real grounding verification | ✅ `scripts/test.sh` | ✅ `verification_scorecard` (`rag/engine.py:354`) |
| Agent | `src/*.py`, `tests/test_agent_runtime.py` | ✅ `ast.parse` syntax + proprietary-leak + test-file presence (`agent/engine.py:177`) | ✅ (shared delivery platform) | ✅ (`agent/engine.py:207`) |
| Automation | `src/**/*.py`, `tests/test_automation_runtime.py` | ✅ `ast.parse` + proprietary-leak + test-file presence (`automation/engine.py:170`) | ✅ (shared delivery platform) | ✅ (`automation/engine.py:200`) |
| Migration | `target/**`, per-unit `UnitVerificationReport` | ✅ **behavioural equivalence** via `MigrationStrategyRegistry` (`migration/engine.py:290`) | ✅ (shared delivery platform) | ✅ (`migration/engine.py:353,456`) |
| Modernization | per-file `TransformationRecord`, migrated Java | ✅ per-unit transformation + `GateDecision` | n/a (transform workload) | ✅ `PipelineResult` records |

**F-6 confirmed:** all five engines already perform deterministic verification, and the delivery platform already ships a `scripts/test.sh` to the customer. **The verification contract already exists — inside the engines.**

## 5. Canonical Request Trace

Traced through source, with the real seams. `[file:line]` is the source of truth.

```
Request(user_id, request_text, context, configuration, metadata)   interfaces.py:47
  ↓
Kernel.submit_request(request)                                     kernel.py:219
  ├─ DefaultRequestValidator.validate                              request_intake.py:60
  ├─ DefaultRequestNormalizer.normalize                            request_intake.py:80
  │     └─ lowercases ALL configuration keys                        request_intake.py:98  ★
  ├─ DefaultProjectInitializer.initialize                          request_intake.py:134
  │     └─ Project.metadata = {user_id,
  │                 configuration: request.configuration,   ★★ durability hinge
  │                 original_request: request_text}
  ├─ runtime_state_manager.create_project                          runtime_facade.py:95
  │     └─ ProjectState.configuration = dict(project.metadata)  ★★
  ├─ intent_analyzer.analyze                                       intent_analysis.py:39
  │     └─ request_type ∈ {research|review|deployment|testing|implementation}
  │        ★★ keyword classification — NOT a commercial capability
  ├─ planning_coordinator.coordinate_planning     planning_coordination.py:54
  │   ├─ DefaultStrategicEngine.create_strategic_plan  strategic_engine.py:41
  │   │     └─ reads config["language"], config["framework"]  ★ surviving config
  │   └─ KernelWorkflowEngineAdapter.create_executable_workflow kernel_adapters.py:115
  │         └─ builds 4–5 FIXED loops; input_data = {requirements |
  │             technology_choices | acceptance_criteria}  ★★
  │            *** NO capability field. NO verification command. ***
  └─ runtime_state_manager.update_project          kernel.py:401
  ↓
Kernel.execute_project(project_id)                               kernel.py:442
  ↓
DefaultOrchestrationEngine.orchestrate                           orchestration.py:87
  ├─ reads request_text from Runtime state       orchestration.py:133-159
  └─ for loop in executable_workflow.loops:                      orchestration.py:161
       loop_context = {project_id, workflow_id, loop, request_text}   ★★
       ↓
     DefaultLoopOrchestrator.orchestrate_loop                    orchestration.py:411
       ↓ execution_engine.execute_loop(loop_type, loop_input, context)
     ************************** THE SEAM **************************
     KernelExecutionEngineAdapter.execute_loop                    kernel_adapters.py:272
       ├─ worker_map: loop_type → WorkerType                     kernel_adapters.py:285
       ├─ input_data = loop["input_data"]                        kernel_adapters.py:297
       ├─ description ← request_text (DEF-18L-04)                 kernel_adapters.py:315
       ├─ TaskDefinition(..., task_type=loop_type, input_data)   kernel_adapters.py:321
       │        ★★★ verification_commands NEVER SET ★★★
       └─ concrete_engine.execute_task_definition(...)           kernel_adapters.py:333


### 4.8 Canonical invocation status

| Engine | ENGINE IMPLEMENTATION | CANONICAL INTEGRATION | Has canonical invocation path? |
|---|---|---|---|
            ↓
          ExecutionEngine.execute_task_definition                 engine.py:144
            ├─ DurableExecutionRecorder.begin_execution (18-J)      engine.py:172
            └─ WorkforceDispatcher.dispatch_task      workforce/dispatch.py:96
                 ├─ WORKER_REGISTRY.lookup → "backend_engineer"  dispatch.py:109
                 ├─ create_specialized_worker("backend_engineer") dispatch.py:134
                 │     └─ BackendEngineer (WorkforceWorker subclass)  ★ verified
                 ├─ EngineeringContextBuilder.assemble_context
                 │     └─ ExecutionContext.from_task_definition   context.py:77
                 │           input_data = task_def.input_data   ★ carried faithfully
                 └─ worker.execute_task(context)   workforce/workers.py:62
                      └─ verification_commands =
                         context.input_data.get("verification_commands")
                                                            workers.py:93  ★★★
                         → ALWAYS None on the canonical path
                      └─ loop.run(context, worker_id,
                                  verification_commands=None)     ★★★
                           EngineeringLoop.run                   loop.py:97
                             ├─ commands_to_run = []              loop.py:108
                             ├─ FALLBACK: input_data.get("commands")
                             │      or input_data.get("test_commands")  ★ unset
                             ├─ executes 0 commands                loop.py:265
                             ├─ evaluate_attempt([]) → INCONCLUSIVE,
                             │     passed=False   evaluation.py:204-206
                             ├─ record_evaluation_artifact →
                             │     "status":"inconclusive","test_results": null
                             └─ artifacts → ArtifactPipeline
                                 → DurableArtifactCatalog
                                 → PhysicalArtifactStore → COMMITTED
            ↓
  ↓
Kernel Completion                                                kernel.py:489
  ├─ validate_completion                            completion.py:290
  └─ finalize_project                               completion.py:637
      ├─ _run_final_review                          completion.py:529
      │   ├─ _collect_final_review_evidence → COMMITTED (18-K)  ✓ WORKS
      │   ├─ B-1 gate: authority + zero evidence → approved=False ✓ WORKS
      │   ├─ _collect_validation_evidence → validation_port.validate_project
      │   │      └─ WorkspaceValidationPort._project_configuration
      │   │            └─ self._runtime.get_project_state(project_id)  ★★★★ D-8b
      │   │                 async method called SYNC → coroutine
      │   │                 → isinstance(state, dict) False → {}
      │   │                 → resolve_verification_command({}) → None
      │   │                 → {"required": False, "passed": True}
      │   └─ review_engine.review_project(evidence, review_context)
      │        └─ ReviewEngine.review → _tests_pass(None) → True
      │                                          review/engine.py:66
      ├─ review approved → continue
      ├─ validation_truth["required"] is False → gate NOT applied  ★★
      └─ transition_state("Finished")              completion.py:713
  ↓
Delivery / Export (18-K durable store; commercial engines export to
AUTOFORGE_OUTPUT_ROOT via the shared delivery platform)
```

### 5.1 Where is capability identity represented?

| Candidate | Exists? | Durable? | Reaches `execute_loop`? | Verdict |
|---|---|---|---|---|
| `IntentAnalysisResult.request_type` | ✅ `intent_analysis.py:77` | ⚠️ only in `StrategicPlan.metadata` + an event payload | ❌ lost | **Wrong vocabulary** — `{research, review, deployment, testing, implementation}` maps to *loop selection*. All five commercial requests classify as `implementation` |
| `StrategicPlan.technology_choices` | ✅ `strategic_engine.py:104` | ✅ via `ExecutableWorkflow` | ✅ via `input_data` | **Survives** — proves config keys survive to the seam |
| `Request.configuration` | ✅ `interfaces.py:64` | ✅ `ProjectState.configuration` | ❌ not forwarded | **The correct carrier — already durable, already read twice** |
| `TaskDefinition.task_type` | ✅ `workflows/models.py:349` | ✅ | ✅ (as `loop_type`) | Occupied by loop type |
| `TaskDefinition.metadata` | ✅ `workflows/models.py:372` | ✅ | ❌ not forwarded | Free; `extra="forbid"` but `metadata` is a declared dict field |
| `TaskDefinition.input_data` | ✅ `workflows/models.py:368` | ✅ | ✅ | **Live channel, already read by the loop** |
| `WORKER_REGISTRY` | ✅ `workforce/registry.py` | n/a | ❌ | Right *shape*, wrong vocabulary |
| Any engine registry | ❌ **does not exist** | — | — | Must be created (or an existing boundary reused) |

**F-3 established: capability identity does not need a new abstraction. `Request.configuration` is already the durable, requester-owned, configuration-shaped carrier, and it already survives to at least one point in the planning path.**

---

## 6. Capability Routing Seam

### 6.1 The seam: what `execute_loop` receives

`kernel_adapters.py:272-330`:

| Input | Available at the seam? | Notes |
|---|---|---|
| `loop_type: str` | ✅ | `"research"`/`"architecture"`/`"coding"`/`"qa"`/`"review"` — **loop vocabulary, not capability** |
| `loop_input["loop"]` | ✅ | The loop dict: `type`, `name`, `worker_type`, `task_id`, `input_data` |
| `loop_input["loop"]["input_data"]` | ✅ | `{requirements, technology_choices, acceptance_criteria}` — **fixed, built by the adapter** |
| `loop_input["request_text"]` | ✅ | Full original request (DEF-18L-03) |
| `loop_input["project_id"]`, `["workflow_id"]` | ✅ | Correlation only |
| `context` | ✅ | Same dict as `loop_input` (`orchestration.py:452-456` passes both) |
| **Commercial capability** | ❌ **ABSENT** | Never assigned anywhere upstream |

### 6.2 What information is lost, and where

| Lost at | What is lost | Recoverable? |

### 6.3 Concrete call graph: the missing edge

Current (per engine, all five identical):

```
canonical request
  → capability identification ........... ** MISSING EDGE ** ❌
  → routing decision ................... ** MISSING EDGE ** ❌
  → engine entry point .................. ** MISSING EDGE ** ❌
  → returned result ..................... ** MISSING EDGE ** ❌
```

**There is no partial path. The edge is absent at the first hop, not merely at the last.** This matters: no amount of hardening the adapter can recover a capability that was never identified.

Target (for engines 1–4, if a registry option is chosen):

```
canonical request
  → capability identification : Request.configuration["capability"]
                              (F-3: already durable)
  → routing decision          : capability id → PowerEngine subclass
                              (NEW: no registry precedent exists)
  → engine entry point        : PowerEngine.execute_lifecycle(spec)
                              (EXISTS, uniform)
  → returned result           : PowerEngineResult{verification_scorecard,
                              delivery_dir, stages_executed, ...}
                              → normalized into the existing loop result dict
                              (EXISTS: kernel_adapters.py:340-347)
```

For engine 5 the last three hops differ (§4.3): sync `run()`, different input, different result.

### 6.4 The one existing precedent — and why it is not a router

`apps/api/src/autoforge_api/service.py:2358-2394` is the **only** production code that instantiates a commercial engine:

```python
def execute_rag_power_engine(self, spec_dict):
    spec = CustomerProjectSpecification(**spec_dict)

## 8. Routing Contract Options

Only options the repository actually supports are listed. Per the gate brief these are **not ranked as "best"**; the smallest / most-consistent / largest are identified, and the choice stays a human decision.

---

### OPTION A — Existing workflow/task metadata directly selects the engine

**Mechanism.** Extend the *existing* loop dict with a capability key, e.g. `loops[0]["capability"] = "rag_knowledge"`. `execute_loop` reads `loop_input["loop"].get("capability")` and dispatches. **No registry object; the workflow IS the routing table.**

**Supporting code (all pre-existing).**
- `ExecutableWorkflow.loops: list[dict[str, Any]]` — `interfaces.py:154`. Already a **free-form dict list**; no schema change, no new field, no new contract.
- `DefaultOrchestrationEngine` already forwards the whole loop dict into `loop_context["loop"]` — `orchestration.py:166`.
- `execute_loop` already reads `loop_input["loop"]` for `task_id`/`name`/`input_data` — `kernel_adapters.py:281-297`.
- The switch is a few lines in one function.
- `PlanningCoordinator` still holds the `Request` (`planning_coordination.py:54`), so the key can be derived there.

**Files a later repair would touch (minimal):**
1. `packages/composition/src/autoforge_composition/kernel_adapters.py` — read `capability`, branch, invoke, normalize result. **(the seam)**
2. `KernelWorkflowEngineAdapter.create_executable_workflow` **or** `packages/kernel/src/autoforge_kernel/planning_coordination.py` — emit the key.
3. `packages/composition/src/autoforge_composition/composition_root.py` — construct engines and pass them to the adapter.
4. *(new)* a thin module for per-engine `spec` construction / result normalization.

**New contract required:** one string key in an existing free-form dict + a normalisation rule. **No new architectural object.**

**Compatibility implications.**
- ✅ **Generic engineering requests are completely unaffected** — the key is absent, the branch is skipped, behaviour is byte-identical.
- ✅ All four `PowerEngine` classes untouched; their certified workflows untouched.
- ✅ No change to `ExecutionEngine`, `EngineeringLoop`, `ArtifactPipeline`, Review, Completion, Context Engineering, the Model Router, 18-J or 18-K.
- ⚠️ Capability identity becomes *implicit in the loop list* rather than a first-class, inspectable project attribute. **Observability cost:** asking "which engine will this project use?" requires inspecting the planned loops, and the answer disappears from `ProjectState` unless separately persisted.
- ⚠️ The same capability repeated in every loop dict is noisy; a project-level field expresses intent better.
- ⚠️ `TaskDefinition` is `extra="forbid", frozen=True` (`workflows/models.py:330`) — the key must ride in `loops[...]` or `metadata`, not as a new `TaskDefinition` field.


---

### OPTION B — A thin capability registry maps a canonical capability identifier to an engine

**Mechanism.** A small registry (e.g. `{"rag_knowledge": RAGKnowledgePowerEngine, ...}`) constructed in the composition root and injected into the execution adapter. `execute_loop` resolves the identifier through the registry and invokes.

**Supporting code (pre-existing).**
- **`WORKER_REGISTRY` is a working in-repo precedent for exactly this shape** — `workforce/registry.py`, with `lookup()`, `list_workers()`, `match_capabilities()`, `get_expertise()`, `check_task_compatibility()`. It is a *capability→implementation* registry that already supports deterministic lookup. Its vocabulary is wrong (23 engineering workers); its mechanism is right.
- Composition-root construction pattern — `composition_root.py:412-415` already injects adapters.
- `PowerEngine` uniformity (F-2) means 4 of 5 need no adaptation.

**Files a later repair would touch:**
1. *(new)* a capability registry module in `packages/composition/src/autoforge_composition/` (composition owns wiring; **ADR-002-compliant**).
2. `kernel_adapters.py` — resolve + invoke + normalize.
3. `composition_root.py` — construct the 5 engines, build the registry, inject.
4. `KernelWorkflowEngineAdapter.create_executable_workflow` or `planning_coordination.py` — emit the identifier.

**New contract required:** an identifier vocabulary + a registry + per-engine input/result adapters. **This is the only option that introduces a new architectural object** — and it introduces it in the layer that already owns wiring.

**Compatibility implications.**
- ✅ Absent identifier ⇒ generic path unchanged (registry miss → existing behaviour).
- ✅ Engines untouched.
- ✅ Registry is injectable and independently testable; the capability inventory becomes *queryable* (`list_capabilities()`), which Option A cannot offer.
- ⚠️ New architectural surface: a second registry alongside `WORKER_REGISTRY`. Must be clearly scoped to *commercial offerings* or it will be confused with *engineering workers*. **Naming and placement discipline are essential.**
- ⚠️ Registry construction in the composition root makes `power_engines`/`modernization` composition-root dependencies — the first time the O-2 path imports them. This is where `external_importing_packages` stops being `{}`, and it must be deliberate and reviewed.

**Impact on all five engines.** Uniform for 1–4. Engine 5 needs the same sync-bridge + input adapter as Option A, isolated inside its registry entry.

**Test burden.** Registry unit tests + per-engine routing test + "miss ⇒ generic" test + per-engine adapter tests. **Moderate — the highest of the viable options.**

**Architectural risk.** Low–moderate. The registry is the right *kind* of object, but it is a new architectural concept and needs an ADR (MANIFEST.md:72). Risk of duplicating `WORKER_REGISTRY`'s role in a second vocabulary.

**Preserves certified engine workflows?** ✅ Yes.

---

### OPTION C — The Strategic Engine emits a capability-specific executable workflow

**Mechanism.** `DefaultStrategicEngine.create_strategic_plan` classifies the request into one of the five offerings, and `KernelWorkflowEngineAdapter.create_executable_workflow` emits a workflow shaped for it.

**Supporting code (pre-existing).**
- The Strategic Engine **is** the architecture's designated reasoning boundary before implementation (`strategic_engine.py:4-11`; `ARCHITECTURE.md` §3).
- It already reads `Request.configuration` (`strategic_engine.py:101-102`) — F-3.
- `StrategicPlan.metadata` is a free-form dict (`interfaces.py:141`).
- The Planning Coordinator already passes `request` to it (`planning_coordination.py:121`).

**Files a later repair would touch:** `strategic_engine.py`, `kernel_adapters.py` (workflow construction **and** the dispatch seam), `composition_root.py`. **3 files, 2 of them protected-adjacent in spirit.**

**New contract required:** a classification contract owned by the Kernel; a mapping from capability → workflow shape; a dispatch mechanism anyway.


---

### OPTION D — Route at the O-2 orchestration boundary instead of the loop adapter

**Mechanism.** `DefaultOrchestrationEngine.orchestrate` decides, per project, whether to run the generic loop sequence or delegate to a commercial engine before the loop loop.

**Supporting code.** `orchestrate()` already reads Runtime state for `request_text` (`orchestration.py:133-159`) — a proven pattern for reading durable project configuration at exactly this boundary. `orchestration.py` is already modified by 18-LR, so it is a known-safe edit surface.

**Files:** `orchestration.py` + `composition_root.py` + a per-engine invocation module.

**Compatibility implications.**
- ✅ Routing is **project-scoped and visible** (one decision per project, not per loop) — arguably the cleanest expression of "this project is an RAG deliverable".
- ✅ Avoids duplicating the switch across 4–5 loop dicts.
- ⚠️ **Bypasses the loop entirely**, so the commercial engine's work never passes through `EngineeringLoop` → `ArtifactPipeline` → the 18-K durable catalog → the loop result contract. **This is the decisive trade-off:** a routed project would lose the durable artifact pipeline unless the adapter explicitly re-publishes every engine output through `ArtifactPipeline`, and would lose `handle_loop_completion` semantics (`complete`/`remediate`/`escalate`/`failed`).
- ⚠️ Larger structural change; more downstream contracts to honour than Options A/B.

**Test burden.** Moderate–high: per-engine delegation + artifact re-publication + loop-status mapping + generic-path regression.

**Architectural risk.** Moderate. Not a *protected* subsystem, but a larger change to the O-2 control flow than A or B, with a genuine risk of losing the single durable artifact path (18-K).

**Preserves certified engine workflows?** ✅ Yes.

---

### 8.2 A cross-cutting requirement for every option

**All four options must satisfy the same normalisation contract**, because the engines are not uniform (§4.3):

1. Capability absence ⇒ **generic engineering path, byte-identical to today** (mandatory: this is the answer to "does routing alter generic engineering semantics?" — it must not).
2. Unknown capability ⇒ **explicit, fail-closed error**. Silent fallback to the generic engine would recreate BLOCKER A invisibly.
3. `ModernizationPipeline` must be invoked without blocking the event loop, and given a G.2 reconnaissance input.
4. A `PowerEngineResult`/`PipelineResult` must be normalised into the existing `execute_loop` return dict so `handle_loop_completion` (`orchestration.py:210`) keeps working unchanged.
5. `PowerEngineResult.verification_scorecard` **must** be carried into the returned result — it is the engine-owned deterministic evidence that DECISION B needs (§10.4).
6. `WAITING_FOR_HUMAN_APPROVAL` (risk gate, `base.py:186-205`) must map to the existing `escalate` status rather than being swallowed.
7. Engine deliverables under `AUTOFORGE_OUTPUT_ROOT` must remain reachable by the 18-K durable path, or the routing option must state explicitly that commercial delivery bypasses the durable catalog (a product decision, not an implementation detail).

---

## 9. Deterministic Validation Trace

### 9.1 Current validation call graph

```
        ┌────────────────────────────────────────────────────┐
        │ WHERE VALIDATION IS DEFINED                       │
        │  parse_test_output        evaluation.py:25        │
        │  EvaluationEngine         evaluation.py:109       │
        │  deterministic: exit codes, parse_test_output,    │
        │  required_files, custom checks                    │
        └────────────────────────────────────────────────────┘
                    ▲
   ┌────────────────┴─────────────────┐
   │ (A) PER-ITERATION                │ (B) PER-PROJECT
EngineeringLoop.run            WorkspaceValidationPort
  loop.py:265-290                  validation_wiring.py:92
  executes input_data[             validate_project():127
   commands|test_commands]           WorkspaceEnvironment  ★ SAME
  → evaluate_attempt                 .execute_command         ENVIRONMENT
  → record_evaluation_artifact      + parse_test_output
  (evaluation_report_iter_N)        reads resolve_verification_command
  ★ ZERO COMMANDS RUN               ★ NEVER SEES A DECLARED CMD
        │                            ★ BROKEN (D-8b)
        │                                     │
        │                    DefaultCompletionModule
        │                      _collect_validation_evidence completion.py:475
        │                        → _validation_review_context → review

### 9.2 `verification_commands` lifecycle — the exact break

| Stage | Location | `verification_commands` state |
|---|---|---|
| 1. Request | `interfaces.py:64` | ❌ never read |
| 2. Normalize | `request_intake.py:98` | ❌ keys lowercased; value untouched |
| 3. Project init | `request_intake.py:152` | ❌ nested under `metadata["configuration"]` |
| 4. Runtime state | `runtime_facade.py:103,131` | ❌ durable as `ProjectState.configuration` |
| 5. Intent | `intent_analysis.py:39` | ❌ not read |
| 6. Strategic | `strategic_engine.py:101` | ❌ reads `language`/`framework` only |
| 7. Workflow | `kernel_adapters.py:115` | ❌ **`Request` is not even passed in** |
| 8. O-2 loop ctx | `orchestration.py:163` | ❌ not added |
| 9. **`execute_loop`** | `kernel_adapters.py:297-327` | ❌ **← THE BREAK: builds `TaskDefinition.input_data` without it** |
| 10. Dispatch | `workforce/dispatch.py:141` | ❌ not read |
| 11. Context | `context.py:98` | ✅ `input_data` carried faithfully |
| 12. **Worker** | `workforce/workers.py:93` | ✅ **reads `input_data["verification_commands"]` → always `None`** |
| 13. **Loop** | `loop.py:108-116` | ✅ reads the parameter; ❌ **fallback `input_data["commands"]`/`["test_commands"]` also unset** |
| 14. Execute | `loop.py:265` | ❌ **zero commands** |
| 15. Evaluate | `loop.py:286` | ⚠️ `evaluate_attempt([])` → `INCONCLUSIVE`, `passed=False` |
| 16. Artifact | `loop.py:289` | ⚠️ `evaluation_report_iter_N.json`: `"status":"inconclusive"`, `"test_results": null`, `"deterministic_checks": []` |
| 17. Completion port | `validation_wiring.py:119` | ❌ **D-8b** |

**F-5: steps 12–13 are LIVE readers. The break is a single missing write at step 9.**

### 9.3 Ownership map (who owns what)

| Thing | Owner | Location |
|---|---|---|
| `input_data` | `KernelExecutionEngineAdapter` builds it; `TaskDefinition` owns it | `kernel_adapters.py:297-327` |
| `TaskDefinition` | `autoforge_workflows.models` | `workflows/models.py:322` |
| `ExecutableWorkflow` | `autoforge_kernel.interfaces`; built by `KernelWorkflowEngineAdapter` | `interfaces.py:147` / `kernel_adapters.py:115` |
| `WorkspaceEnvironment` | `build_execution_engine` creates it; the validation port **reuses the same instance** | `execution_wiring.py:145` / `composition_root.py:458` |
| `parse_test_output` | `autoforge_execution.evaluation` (existing, unchanged) | `evaluation.py:25` |
| Validation definition | `EvaluationEngine.evaluate_attempt` | `evaluation.py:109` |
| Validation port (Kernel side) | `DefaultCompletionModule.validation_port` (interface only) | `completion.py:264,288` |
| Validation port (impl) | `WorkspaceValidationPort` | `validation_wiring.py:92` |
| Validation → Review | `_validation_review_context` + `review_project` | `completion.py:608` / `kernel_adapters.py:436` |
| Validation → Completion | `validation_truth["required"]` gate | `completion.py:695` |

### 9.4 Do the contracts already carry verification metadata?

| Contract | Has a verification field? | Evidence |
|---|---|---|
| `Request` | ⚠️ **free-form `configuration: dict`** — can carry it, no schema | `interfaces.py:64` |
| `IntentAnalysisResult` | ❌ `constraints: dict` only; no verification field | `interfaces.py:85` |
| `StrategicPlan` | ⚠️ `technology_choices["verification_framework"] = "pytest"` — a **name, not a command** | `strategic_engine.py:109` |
| `StrategicPlan.metadata` | ❌ free-form dict | `interfaces.py:141` |

---

## 10. Validation Contract Options

### 10.1 Option A — Requester-declared verification

**Mechanism.** `Request.configuration["verification_command"]` (already read by `resolve_verification_command`, `validation_wiring.py:63`; accepted keys: `verification_command`, `verify_command`, `test_command`) is propagated into `input_data["verification_commands"]`.

**Smallest propagation path** (3 existing mechanisms, zero new abstractions):

```
Request.configuration["verification_command"]
  → already durable in ProjectState.configuration   (F-3, works today)
  → read at kernel_adapters.py:297 (execute_loop)  ← ONE new read
  → input_data["verification_commands"] = [["pytest","-q"]]
  → WorkforceWorker.execute_task reads it            ✓ ALREADY READS IT
  → EngineeringLoop.run executes it                  ✓ ALREADY HONOURS IT
  → evaluate_attempt → real pass/fail
  → evaluation_report_iter_N.json has real test_results
  → BOTH consumers (Review context + Completion gate) get real truth
```

**Second, independent consumer — and it is currently broken.** `validation_wiring.py` already reads the same declared command for the *project-level* gate. **D-8b must be fixed regardless of which option is chosen**, because today it returns `{}` for every project (F-4, proven live).

**Precedent that the declared-command form already works:** `apps/api/.../build_engine.py:880` executes `[sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"]` and parses the real output — the O-3 precedent for declared, deterministic verification.

**Properties.** ✅ Smallest change (reuses 100% of existing machinery). ✅ Deterministic, requester-controlled, auditable. ✅ No new runner/parser. ✅ No model-generated command is ever executed.
**Costs.** ⚠️ **Opt-in — a request that declares nothing still gets zero validation.** This is precisely the greenfield gap. ⚠️ Trust: the requester declares a command AutoForge then executes — an **arbitrary-command execution surface** needing an allowlist/permission decision (§10.6).

### 10.2 Option B — Auto-discovered verification


### 10.4 Commercial-engine validation contract (per engine)

| Question | RAG | Agent | Automation | Migration | Modernization |
|---|---|---|---|---|---|
| Deterministic validation in its certified workflow? | ✅ | ✅ | ✅ | ✅ | ✅ |
| **How supplied?** | `_stage_verify` (engine.py:183) | `_stage_verify` (engine.py:177) | `_stage_verify` (engine.py:170) | `_stage_verify` (engine.py:290) | `TransformationEngine.apply` + `GateDecision` |
| Declared **before** execution? | ✅ spec + delivery profile | ✅ spec | ✅ spec | ✅ spec | ✅ `MigrationPlan` |
| Generated **by** the engine? | ✅ generates + runs `scripts/test.sh` | ✅ syntax + leak + test presence | ✅ | ✅ behavioural equivalence | ✅ |
| Generated by orchestration? | ❌ | ❌ | ❌ | ❌ | ❌ |
| Produced **after** artifact creation? | ✅ stage 6 follows stage 4 | ✅ | ✅ | ✅ | ✅ |
| **What happens on failure?** | `defects` → `_stage_diagnose` → `_stage_repair` → `_stage_re_verify`; `repair_count` on result | same | same | same | `PipelineStatus.FAILED` / `BLOCKED` |
| **How does final Review get the evidence?** | ❌ **IT DOESN'T** — `verification_scorecard` is returned in `PowerEngineResult` and dropped at the seam | ❌ | ❌ | ❌ | ❌ |

**This table is the single most important input to DECISION B.** The engines already do the right thing end-to-end *internally*, and the platform currently discards the result of that work. **BLOCKER B is, for the commercial path, largely a transport gap — not a missing capability.**

### 10.5 The greenfield gap

| Question | Answer (traced) |
|---|---|
| Where does source generation succeed? | `EngineeringLoop.run` → AI adapter writes files into `WorkspaceEnvironment.root` (`loop.py:257-262`) |
| Where do source artifacts become durable? | `ArtifactPipeline` → `DurableArtifactCatalog.register_artifact` → `PhysicalArtifactStore` (staged write → SHA-256 → atomic publish → commit). **18-LR: 27/27 COMMITTED, 15 `source_code`** |
| Where is validation *supposed* to occur? | `loop.py:265-290` (per iteration) **and** `completion.py:475` (per project) |
| **Why is `verification_commands` empty?** | `kernel_adapters.py:297-327` never sets it; the fallback keys at `loop.py:110` are never set either. **One missing write.** |
| **Why can Review approve despite failing tests?** | (1) no command ran ⇒ `evaluate_attempt([])` ⇒ `INCONCLUSIVE`, `test_results: null`; (2) `review_project` builds `ReviewEvidence(test_results=None)`; (3) `_tests_pass(None) → True` — documented as *"absence is not a failure"* (`review/engine.py:66-67`); (4) the completion gate's `required` is `False` because the port found no command (**and would not have found it anyway — D-8b**) |
| **What contract must exist before greenfield can be certified?** | A rule that determines, for every project, **which verification command applies** — and a rule for the case where **none** applies. That is DECISION B. |

### 10.6 Security / correctness implications

| Concern | Declared (L1) | Engine-declared (L2) | Discovered (L3) |
|---|---|---|---|
| Executes model-generated code | ❌ No | ❌ No | ⚠️ **Yes** |
| Arbitrary-command surface | ⚠️ Yes — requester names the argv | ✅ No — the engine owns it | ⚠️ Yes — inference decides |
| Mitigations available today | `WorkspaceEnvironment.execute_command` already enforces: workspace-confined `cwd` (`environment.py:71-95`), path-traversal rejection, null-byte rejection, argv type validation, process-group isolation + SIGTERM/SIGKILL on timeout (`environment.py:159-184`) | Same environment; the command is a first-party constant | Same environment, **but the command is derived from generated content** |
| Recommended hardening for L1 | An argv allowlist / policy gate before execution | none needed | n/a |
| Determinism | ✅ explicit | ✅ explicit | ✅ deterministic *algorithm*, but the input is model output |
| Bounded | ✅ `DEFAULT_TIMEOUT_SECONDS = 600` | ✅ | ✅ |

**Note:** the port's existing mitigations are real and already certified. L1 and L2 are both well inside them. **L3 is a categorically different security conversation and should not be bundled with an 18-L repair.**

---

## 11. Existing Certified Workflow Compatibility

**The binding constraint: neither repair may alter a certified commercial engine workflow.**

| Certified behaviour | Touched by routing (A/B/D)? | Touched by layered validation? |
|---|---|---|
| 11-stage lifecycle, stage order | ❌ No — called, not modified | ❌ No |

---

## 12. Greenfield Implications

**The greenfield path is the hard case, and it is where DECISION B must actually decide something.**

Facts:
- Generic greenfield has **no commercial capability**, so routing options are irrelevant to it (correctly — it must stay on the generic path).
- The generated project *does* contain a test file (`test_tokenizer_lite.py`), but **nothing records how to run it**.
- The 18-LR greenfield run: `2 failed, 4 passed` → review `APPROVED` → project `finished`.
- Even with perfect L1 propagation, **a requester who declares no command still gets zero validation** — and the generic path is exactly where the requester is least likely to think to declare one.

**Therefore, a "requester-declared only" contract does not by itself make greenfield certifiable.** Three honest end-states, all product decisions:

| End-state | Meaning | Consequence for 18-L |
|---|---|---|
| **G-1 (recommended to consider)** | Validation is **mandatory** for certification; if no verification command can be determined, completion **blocks** with an explicit "no verification contract" reason | Greenfield certification becomes honest, but **the first greenfield run will fail until a verification contract exists**. A real behaviour change; must be a deliberate product decision |
| **G-2** | Validation is mandatory **only when declared**; absence is recorded as an explicit, visible `unverified` status that **blocks `Finished`** but is distinguishable from "tests passed" | Weaker guarantee, but preserves greenfield throughput |
| **G-3** | Validation remains **optional** on the generic path | 18-L greenfield **cannot** be certified. The blocker stands, unresolved |

**Not weakening the requirement.** This gate does **not** propose relaxing the deterministic verification requirement. G-3 is listed only to make explicit that it is *not a valid resolution* — the question is **where the command comes from and what happens when none exists**, never *whether a passing Review is enough*.

---

## 13. Legacy Modernization Implications

Documented from the now-proven G.3 path (`18LR-defect-repair/layer_a_modernization.py`).

### 13.1 The real-source reference flow

```
real legacy source on disk (cbl/LEDGER.cbl, jcl/LEDGER.jcl)
  → G.2 reconnaissance: run_reconnaissance(src_root)      ← ORCHESTRATION-OWNED
  → ModernizationPipeline.run(project_id, job_id, recon)   ← ENGINE-OWNED
      → _extract_technologies(recon)
      → LegacyAnalysisEngine.run_all(...)                 [analysis]
      → PlanningGate → GateDecision                       [gate]
      → _derive_default_plan → MigrationPlan
           • B-2a: binds the REAL reconnaissance inventory into
                    MigrationUnitSpec.source_files
           • B-2b: _select_transformation_type resolves via the engine's OWN
                    supported_types_for, preferring the substantive transform
                    over the cosmetic `refactor`

### 13.3 Implications for the routing contract

1. **The engine must not be re-implemented to be routed.** B-2 was fixed in the pipeline that *feeds* it; routing must preserve that.
2. **Engine 5 needs an input adapter** — it takes reconnaissance output, not a `CustomerProjectSpecification`. The adapter must run real reconnaissance from the project's real source root. A routing adapter that synthesised a placeholder would **reintroduce B-2 through a new door**; that is a named regression risk.
3. **Engine 5's call is synchronous** — a thread/executor bridge is required on the async O-2 path.
4. **Engine 5's `PipelineResult` must be normalized** into the existing `execute_loop` result dict, carrying `transformation_records`, `gate_decisions` and `wave_results` as the validation evidence — this is the L2 layer for engine 5.
5. `PipelineStatus.FAILED` / `BLOCKED` must map to the existing `remediate` / `escalate` statuses so the O-2 failure path keeps working.

---

## 14. B-1 / D-8 Interaction

| Interaction | Finding |
|---|---|
| **B-1 vs D-8** | **Complementary, not overlapping.** B-1 makes *empty evidence* block completion; D-8 makes *deterministic failure* block completion. Neither subsumes the other. A project with plenty of artifacts and failing tests passes B-1 and must be caught by D-8. |
| **B-1 status** | ✅ Repaired, 20 regression tests pass (re-run this gate). Works: `_has_evidence_authority() and not evidence_files` → `approved=False` (`completion.py:596`). |
| **D-8 status** | ⚠️ Mechanism repaired; **two** open edges, not one. |
| **D-8 edge 1** (18-LR) | `input_data["verification_commands"]` never populated ⇒ zero commands run. |
| **D-8 edge 2 (D-8b — NEW, this gate)** | `validation_wiring.py:119` awaits nothing: `self._runtime.get_project_state()` is **async** on the wired `KernelRuntimeFacade`, so the port reads a coroutine, returns `{}`, and reports `required: False` for **every** project. **Proven live.** |
| **Consequence** | D-8b is **independent of declared-vs-discovered**. Whichever way DECISION B goes, this must be fixed, or a correctly propagated command would still be ignored by the completion gate. |
| **Review semantics** | `_tests_pass` treating `None` as "not asserted" (`review/engine.py:66-67`) is **documented and must not be weakened**. It is correct *given evidence*; the defect is that no evidence is produced. |
| **Failure-mode chain today** | no command → `test_results: null` → `_tests_pass → True` → review APPROVED → `required: False` → gate skipped → `Finished`. **B-1 cannot catch this** (evidence is non-empty); only D-8 can, and only once a command exists **and** D-8b is fixed. |
| **Ordering constraint** | D-8b must be fixed **together with** propagation — fixing only one leaves the chain broken at the other end. |

---

## 15. Protected-System Verification

Verified **by source inspection only** (`git diff --name-only` over the 14 modified files; no protected module appears).

| Protected system | Result | Evidence |
|---|---|---|

## 16. Exact Files / Interfaces a Future Repair Would Touch

**This gate implements none of it.** Paths are exact and source-verified.

### 16.1 DECISION A — routing (Options A or B; the common core)

| # | File | Change | Size |
|---|---|---|---|
| 1 | `packages/composition/src/autoforge_composition/kernel_adapters.py` — `KernelExecutionEngineAdapter.execute_loop` (**:272**) | read the capability identifier; branch to the engine; normalize the result into the existing return dict; carry `verification_scorecard` | **the seam** |
| 2 | `kernel_adapters.py` — `KernelWorkflowEngineAdapter.create_executable_workflow` (**:115**) **or** `packages/kernel/src/autoforge_kernel/planning_coordination.py` (**:54**) | emit the identifier (whichever becomes the DECISION A owner) | small |
| 3 | `packages/composition/src/autoforge_composition/composition_root.py` (**:412-415**) | construct the engines; build the registry (Option B); inject | small |
| 4 | *(new)* `packages/composition/src/autoforge_composition/power_engine_wiring.py` | per-engine `spec` construction, Legacy-Modernization input adapter + sync bridge, result normalization | **new, additive** |
| 5 | `architecture/decisions/ADR-0xx-*.md` | the ADR required by `MANIFEST.md:72` | doc |

**Option C additionally requires** `packages/kernel/src/autoforge_kernel/strategic_engine.py` — **a protected system. Not recommended without an explicit decision.**

### 16.2 DECISION B — verification (all options share these)

| # | File | Change | Size |
|---|---|---|---|
| 1 | `packages/composition/src/autoforge_composition/validation_wiring.py` — `_project_configuration` (**:119**) | **D-8b fix**: await the coroutine (`async def`) or accept a sync reader. **Required under every option.** | **1–3 lines** |
| 2 | `packages/composition/src/autoforge_composition/kernel_adapters.py` — `execute_loop` (**:297-327**) | propagate the declared command into `input_data["verification_commands"]` (or `["commands"]`, already read at `loop.py:110`) | small |
| 3 | `kernel_adapters.py::KernelWorkflowEngineAdapter.create_executable_workflow` (**:115**) | emit the declared verification into loop `input_data` — **or** read it directly at the seam from `ProjectState` (already done for `request_text` at `orchestration.py:133-159`, a proven pattern) | small |
| 4 | *(Option C only)* the routing module from 16.1 #4 | carry `verification_scorecard` / `PipelineResult` records as L2 validation evidence | small |
| 5 | `architecture/decisions/ADR-0xx-*.md` | the verification-ownership ADR | doc |

**Explicitly NOT touched:** `Engine`, `Worker`, `workers.py`/`WorkforceWorker`, `loop.py`, `evaluation.py`, `environment.py`, `artifacts.py`, `context_builder.py`, `completion.py`'s gate logic, `review/`, `power_engines/`, `modernization/`, 18-J, 18-K. Every one already does the right thing and needs no change.

### 16.3 Tests a future repair must add

| # | Test | Proves |
|---|---|---|
| 1 | per-engine canonical routing test (×5) | each capability reaches its engine on the real O-2 path |
| 2 | capability-absent ⇒ generic path unchanged | routing does **not** alter generic engineering semantics |
| 3 | unknown capability ⇒ explicit failure | no silent fallback to the generic engine |
| 4 | engine result normalization | `handle_loop_completion` still works (`orchestration.py:210`) |
| 5 | risk gate `WAITING_FOR_HUMAN_APPROVAL` ⇒ `escalate` | human-governed autonomy preserved |
| 6 | Legacy Modernization routing with **real** COBOL/JCL | **B-2 must not regress through the new adapter** |
| 7 | declared verification command ⇒ commands actually execute | closes D-8 edge 1 |

---

## 17. Explicit Product / Architecture Decisions Required

Four decisions. **Each is a human/product decision; this gate deliberately makes none of them.**

### DECISION A — CANONICAL CAPABILITY ROUTING

| Question | Evidence-backed options |
|---|---|
| **What existing architectural object should identify the requested commercial capability?** | **`Request.configuration`** — already durable in `ProjectState.configuration`, already read twice on the canonical path (F-3). Alternatives: `TaskDefinition.metadata` (free-form, `extra="forbid"`-safe) or `StrategicPlan.metadata`. **A new `Capability` type is not required.** |
| **Where should routing occur?** | **Execution adapter** (`kernel_adapters.py:272`, Option A/B — smallest); **O-2 orchestration boundary** (`orchestration.py:87`, Option D — project-scoped, but must re-publish artifacts through 18-K); **Strategic Engine** (`strategic_engine.py:41`, Option C — architecturally placed but **protected** and widest blast radius) |
| **What is the smallest implementation seam?** | **`KernelExecutionEngineAdapter.execute_loop`** — confirmed by re-derived AST. **Refinement beyond 18-LR: edges 3–4 already exist** (`execute_lifecycle`, `PowerEngineResult`, the `execute_loop` return dict). The genuinely new work is edges 1–2 — *identify* and *route* |
| **Does routing alter generic engineering semantics?** | **It must not.** Required for every option: absent capability ⇒ byte-identical generic path; unknown capability ⇒ explicit fail-closed. (Option C is the only one where "must not" is at risk.) |

### DECISION B — DETERMINISTIC VERIFICATION OWNERSHIP

| Question | Evidence-backed options |
|---|---|
| **Who declares verification?** | **Layered (Option C), supported by F-6:** L1 requester-declared (authoritative when present) → L2 engine-declared (`verification_scorecard` + the `scripts/test.sh` every deliverable already ships — **exists today, unused**) → L3 discovery (**NEW CAPABILITY, explicitly future, not 18-L**). Single-layer requester-only is smallest but leaves greenfield uncertifiable |
| **Is verification mandatory for greenfield?** | **Undecided — and it is the crux.** See §12: G-1 (mandatory, blocks when undeterminable) / G-2 (mandatory only when declared, but `unverified` never reads as `passed`) / G-3 (optional — **18-L greenfield cannot be certified**). **G-3 is not a valid resolution** |
| **Is requester-declared verification sufficient for 18-L?** | **No, on its own** — it is opt-in and the greenfield path is exactly where nothing is declared. It is necessary and it is the L1 layer, but it does not close greenfield. **And it is currently non-functional at the completion gate (D-8b).** |
| **Is autonomous verification discovery a separate future capability?** | **Yes.** Classified **NEW CAPABILITY** (§10.2) — no repository evidence exists. It also executes model-generated code (§10.6) and must not be bundled with an 18-L repair |
| **What happens when no verification contract exists?** | Must be an **explicit, visible, non-`passed` outcome** distinguishable from success — e.g. block completion with "no verification contract" (G-1), or an `unverified` state that never reaches `Finished` (G-2). **A silent pass is the current defect and is not an option.** Independently, **D-8b must be fixed under every choice** |

### DECISION C — FIVE-ENGINE CERTIFICATION

| Question | Required evidence |
|---|---|
| **What proves each engine remains intact?** | The **existing** suites, unchanged: `packages/power_engines/tests/` (123 pass, 3 skip, 1 environmental 8080 collision) and `packages/modernization/tests/` (383 + 59 skip), plus `test_18lr_b2_real_source_transformation.py` (8) and `test_g3_llm_and_transform.py` (83). **All re-run and green at HEAD by this gate** |

---

## 18. Recommended Decision Questions

Concrete, answerable, in the order they unblock the most work:

1. **Capability identity —** Do we adopt `Request.configuration["capability"]` (already durable, already read twice) as the canonical identifier, or is a first-class field on `IntentAnalysisResult`/`StrategicPlan` required for auditability?
2. **Routing site —** Execution adapter (smallest, Option A/B) or O-2 boundary (project-scoped, Option D)? Default recommendation: **adapter**, because edges 3–4 already exist there and the 18-K artifact path is preserved automatically.
3. **Registry —** Is a new capability registry acceptable (Option B) given `WORKER_REGISTRY` already occupies that *role* with a different vocabulary — or should routing be a direct metadata switch (Option A) to avoid a second registry concept?
4. **Legacy Modernization input —** Who supplies the G.2 reconnaissance output on the canonical path? It must be **real**, or B-2 regresses through the adapter.
5. **Delivery path —** Do commercial engine deliverables under `AUTOFORGE_OUTPUT_ROOT` also need to be published into the 18-K durable catalog? If yes, that is a scope increase for the routing repair.
6. **Verification precedence —** Confirm the layered order: requester-declared (authoritative) → engine-declared → discovery (future)?
7. **Greenfield end-state —** G-1, G-2 or G-3 (§12)? **This single answer determines whether 18-L greenfield can ever be certified.**
8. **Discovery scope —** Confirm L3 discovery is deferred to a later phase and explicitly out of 18-L.
9. **D-8b —** Confirm the one-line async fix is in scope for the next implementation gate (it is required under *every* option).
10. **Command-execution policy —** For L1, is an argv allowlist required before the requester's declared command is executed?

---

## 19. STOP Conditions

This gate **STOPPED and reported** rather than proceeding on each of the following:

| # | Condition | Encountered? | Action taken |
|---|---|---|---|
| 1 | Choosing between declared vs discovered verification changes what the production path executes | ✅ | Reported as DECISION B; **not chosen** |
| 2 | Choosing a routing option requires touching the **protected Strategic Engine** | ✅ (Option C) | Reported as Option C with its blast radius; **not taken** |
| 3 | Investigating D-8 revealed a **new defect in already-repaired code** | ✅ (D-8b) | **Reported with a live reproduction**; **not fixed** — repairing it is implementation, which §1 forbids |
| 4 | Selecting among routing options is an architectural/product decision | ✅ | All four options documented; **not ranked, not chosen** |
| 5 | 18-L certification depends on a decision not yet made | ✅ | **18-L remains NOT CERTIFIED** |
| 6 | A protected subsystem appeared to require modification | ⚠️ **Only under Option C** | Reported; Options A/B/D need no protected change |

**Additional stop rules honoured:** no routing implemented; no verification discovery implemented; no commercial engine modified; no orchestration/Kernel/Strategic Engine/Model Router/Context Engineering/Context Compaction/18-J/18-K modified; no production behaviour changed; **nothing committed, pushed, reset or cleaned**; M1 and HP untouched; Brain not created; Phase 19 not started.

---

## 20. Final Gate Verdict

Source evidence is **sufficient** to determine both seams and both contracts:

- The routing seam is isolated and proven (**`KernelExecutionEngineAdapter.execute_loop`**, re-derived by AST and confirmed dynamically), with four source-supported options whose file impact is enumerated exactly.
- The verification seam is isolated and proven (**one missing write at `kernel_adapters.py:297-327`**, a live downstream reader, plus a **newly discovered blocking defect, D-8b**, with a live reproduction).
- All five engines were inventoried from source, their certification re-verified green, and their uniform contract established.
- No protected subsystem requires modification for the recommended option set.

# ARCHITECTURE DECISION READY

### 18-L = NOT CERTIFIED (unchanged)

The two 18-LR blockers remain **open**, now with better-characterised seams, a newly found third defect, and a third validation option the prior gate did not name. Awaiting the human architecture decision on **DECISION A**, **DECISION B**, **DECISION C** and **DECISION D**.

---
*Reports: `PHASE_18LD_ARCHITECTURE_DECISION_REPORT.md` · `CAPABILITY_ROUTING_ANALYSIS.md` · `VALIDATION_CONTRACT_ANALYSIS.md` · `EVIDENCE_MATRIX.md`*
*No production code was modified. HEAD remains `c72dad9`. Nothing committed, nothing pushed.*

| **What proves canonical invocation?** | Per engine, on the **real** O-2 path: request → `submit_request` → `execute_project` → instrumented `execute_loop` proving **that** engine's class executed (the 18-LR `layer_b` technique, inverted) — 5 tests |
| **What proves artifacts / validation / review / completion?** | Engine output reaches the 18-K durable catalog as COMMITTED artifacts; `verification_scorecard` reaches Review; deterministic failure blocks completion; generic path is provably unchanged; Legacy Modernization still transforms **real** COBOL/JCL with zero placeholders (B-2 non-regression) |

### DECISION D — NEXT IMPLEMENTATION GATE

| Question | Content |
|---|---|
| **Exact files to modify** | Per §16.1 and §16.2 — 4–5 files plus one new composition module and one ADR. **D-8b is file 1 of DECISION B under every option** |
| **Exact tests to add** | The 14 in §16.3 |
| **Exact E2E workflows to run** | (a) 5 × per-engine canonical E2E; (b) greenfield with a declared verification command, real M6 inference, expecting a real test run and a completion decision driven by it; (c) Legacy Modernization canonical E2E with real COBOL/JCL; (d) the full CI matrix |
| **Protected systems that remain frozen** | Context Engineering, Context Compaction, Model Router, 18-J, 18-K, the Review Engine, all five Commercial Power Engines, the Strategic Engine (unless Option C is explicitly chosen), inference topology, M1, HP, Brain, Phase 19 |

| 8 | declared command ⇒ `evaluate_attempt` gets real `CommandResult`s | determinism restored |
| 9 | real test results reach `evaluation_report_iter_N.json` | the artifact that was `inconclusive`/`null` becomes real |
| 10 | **D-8b regression** | the port reads a real `ProjectState.configuration` for a project that **declares** a command ⇒ `required: True` (currently `False`) |
| 11 | failing declared command blocks completion | D-8 enforcement, end to end |
| 12 | Review receives real `test_results` | the `_tests_pass(None) → True` path is no longer taken |
| 13 | engine-declared scorecard reaches Review + Completion | the L2 layer |
| 14 | **no verification contract ⇒ explicit, visible outcome** | DECISION B's "what happens when none exists" |

| **Context Engineering** (`context_builder`, `context_selection`, `prompt_assembly`) | ✅ **UNCHANGED** | not in the 14-file diff; `context_builder.py` contains **no** `input_data` reference, so neither repair disturbs it |
| **Context Compaction** | ✅ **UNCHANGED** | not in the diff |
| **Model Router** | ✅ **UNCHANGED** | not in the diff |
| **18-J** (durable execution) | ✅ **UNCHANGED** | `durable.py` not in the diff |
| **18-K** (durable artifacts) | ✅ **UNCHANGED** | `artifact_catalog`, `physical`, `durable_bridge` not in the diff |
| **Commercial Power Engines** | ✅ **UNCHANGED by this gate** | `power_engines/` (all 4 engines) is not in the diff. `modernization/pipeline.py` **is** modified — but by 18-LR's **B-2 repair**, pre-existing at gate entry, and **not** by this gate. The engine internals (`transformation.py`, `analysis.py`, `g3_transform_strategies.py`, `analyzers/`) are untouched |
| **Review Engine** | ✅ **UNCHANGED** | `review/` not in the diff (B-1 was fixed at the completion boundary, by design) |
| **Strategic Engine** | ✅ **UNCHANGED** | not in the diff — and **Option C would require changing it; reported, not performed** |
| **M1** | ✅ **UNTOUCHED** | no M1 host contacted, benchmarked, or configured. `local-m1` is only a *provider label* bound to `127.0.0.1` by the pre-existing `bind_local_runtime_adapters` |
| **HP** | ✅ **UNTOUCHED** | as above |
| **Inference topology** | ✅ **UNCHANGED** | 0 workers; no routing/allocator/capacity change |
| **Brain** | ✅ **ABSENT** | no Brain module, package, or code in the repository |
| **Phase 19** | ✅ **NOT STARTED** | no `phase19`/`phase_19` artefacts; `README.md:171` still shows "Planned" |
| **Inference runtime (M6 MLX)** | ⚠️ running on `127.0.0.1:8080` by the operator | caused the documented environmental port collision (§4.6); **not** started, stopped or reconfigured by this gate |

**STOP-CONDITION CHECK: no protected subsystem requires modification for either repair.** A routing repair confined to the composition package (Options A, B, D) and a validation repair confined to the adapter + the validation port touch none of the above. **Option C is the sole exception** and is reported rather than taken.

---

      → _run_wave: reads the customer's ACTUAL bytes per file
           • B-2c: transformation_type is no longer hardcoded to REFACTOR
      → TransformationEngine.apply(file_path, before_content) → TransformationRecord
  → PipelineResult{status, analysis_report, gate_decisions,
                  transformation_records, wave_results, migration_plan}
```

### 13.2 Engine-owned vs orchestration-owned

| Concern | Owner | Notes |
|---|---|---|
| Source discovery / reconnaissance | **Orchestration** | the pipeline must be handed real input |
| Binding real files to migration units | **Orchestration** | B-2a — repaired in `pipeline.py` |
| Resolving the transformation type | **Engine's own API** (`supported_types_for`) | B-2b — repaired, delegating to the engine |
| Reading bytes and transforming | **Engine** (`TransformationEngine`) | Per-file; a unit with no bound file now **fails explicitly** |
| Gate decision | **Engine** | `GateDecision` |
| Provenance chain | **Engine** | `ModernizationProvenanceChain` |
| **Validation** | **Engine** — `TransformationRecord`s + per-wave results | ⚠️ **never reaches canonical Review/Completion** |
| **Review evidence** | — | ❌ **MISSING EDGE** |
| **Completion** | — | ❌ **MISSING EDGE** |

**Proof the repair is real (18-LR, re-verified by this gate's test run):** `LEDGER.cbl` (616 B, real `IDENTIFICATION DIVISION`) → real Java; `LEDGER.jcl` (174 B) → real workflow config; pipeline `complete`; 2/2 real files transformed; zero placeholders. **91 modernization tests pass.**

| `_stage_verify` logic & thresholds | ❌ No | ❌ No |
| Risk gates / `WAITING_FOR_HUMAN_APPROVAL` | ⚠️ Must be **mapped**, not altered (§8.2-6) | ❌ No |
| `verification_scorecard` shape | ⚠️ Must be **carried**, not altered | ✅ Carried — this is the point |
| `CustomerProjectSpecification` fields | ❌ No | ❌ No |
| Deliverable layout / `AUTOFORGE_OUTPUT_ROOT` | ⚠️ Must remain reachable (§8.2-7) | ❌ No |
| Proprietary-leak sanitisation | ❌ No | ❌ No |
| `ModernizationPipeline` B-2 real-source behaviour | ⚠️ Must not regress — see §12 | ✅ Scorecard becomes visible |
| Existing test suites | Must stay green (123 PE + 383 modernization) | Must stay green |

**Verified this gate: 123 power-engine tests + 91 modernization tests + 20 B-1/D-8 tests + 9 D-8 E2E tests all pass at HEAD.** The one failure is the environmental 8080 collision (§4.6), reproducible in both directions and unrelated to any change.

**Bottom line: a correctly-scoped routing repair is engine-neutral.** The engines are *called*. The only genuine risk is behavioural coupling introduced by the adapter (risk-gate mapping, result normalization, artifact re-publication) — each listed in §8.2 and each requiring regression tests.

**Mechanism.** AutoForge infers the test command from the generated project (e.g. detect `pytest.ini`/`pyproject.toml`/`package.json` → emit a command).

**Repository evidence:** **NONE.** There is no discovery module, no project-metadata scanner for test frameworks, and no inference step anywhere on the canonical path.

> ### Classification: **NEW CAPABILITY**
> AutoForge currently **cannot** discover a verification command. Building it requires: a project-metadata detector; a mapping framework→command; a decision about *which* project (there are 15 `source_code` artifacts in one greenfield run); a policy for projects with **no** tests; and the execution of **model-generated code** on the worker path.
>
> **Per §1 this is explicitly classified as a NEW CAPABILITY and NOT implemented.**

**Properties.** ✅ Would close the greenfield gap without asking the requester for anything. ✅ Genuinely autonomous.
**Costs.** ❌ Materially new architecture. ❌ **Executes model-generated code** — a materially larger security surface than a declared command (§10.6). ❌ Ambiguous when multiple projects exist. ❌ A non-trivial new certification surface. ❌ **Must not be in scope for 18-L.**

### 10.3 Option C — Layered contract *(supported by repository evidence)*

**Mechanism.** A precedence chain: **declared → engine-declared → (future) discovered.**

**This option is directly supported, and 18-LR did not name it.** The evidence is F-6:

| Layer | Source of truth | Precedence | Status |
|---|---|---|---|
| **L1 — Requester-declared** | `Request.configuration["verification_command"]` | **authoritative** | Exists (18-LR); **needs propagation + D-8b fix** |
| **L2 — Engine-declared** | `PowerEngineResult.verification_scorecard`; `CustomerProjectSpecification` deployment profile; the `scripts/test.sh` every commercial deliverable ships | authoritative **for that capability** | **Exists today, unused by the platform** |
| **L3 — Discovered** | project-metadata inference | fallback only | **NEW CAPABILITY — future, not 18-L** |

**Why L2 is architecturally strong.** Each commercial engine **already** declares and performs its own deterministic verification inside its 11-stage lifecycle, and the shared delivery platform already ships a runnable test command to the customer. The platform does not need to *discover* anything for commercial deliverables — it needs to **carry the engine's existing scorecard into the canonical validation/review/completion chain**. That is a transport obligation, not a new capability.

**Properties.** ✅ Closes the *commercial* gap today with **zero** new capability. ✅ Preserves every certified engine workflow exactly (engines are read, not modified). ✅ Keeps L1 authoritative when the requester speaks. ✅ L3 is explicitly deferred — it stays a separate future capability. ✅ Deterministic-first preserved: every layer is a declared/explicit command, never a model judgement.
**Costs.** ⚠️ Three layers = three code paths to test. ⚠️ Requires a precise precedence rule and a "who is authoritative" record in the evidence. ⚠️ Needs a clear statement of what happens when **no** layer applies (see DECISION B).

| `ExecutableWorkflow` | ❌ **no verification field**; `loops[].input_data` is the only carrier | `interfaces.py:147` |
| `TaskDefinition` | ❌ no verification field; **`input_data`/`metadata` free-form** | `workflows/models.py:368-375` |
| `ExecutionContext` | ❌ no verification field; `input_data` carried | `context.py:31` |
| **`EngineeringLoop.run`** | ✅ **`verification_commands` keyword parameter exists and is honoured** | `loop.py:102` |
| **`WorkforceWorker.execute_task`** | ✅ **reads `input_data["verification_commands"]`** | `workers.py:93` |
| `ProjectState.configuration` | ⚠️ free-form; **already carries `Request.configuration`** | `runtime_facade.py:103` |
| `CustomerProjectSpecification` | ❌ no verification field | `specification.py:225` |
| `PowerEngineResult` | ✅ **`verification_scorecard`** (engine-owned deterministic evidence) | `base.py:98` |
| `PipelineResult` | ✅ `transformation_records`, `gate_decisions`, per-wave results | `pipeline.py:92` |

### 9.5 Do generated projects already contain discoverable test metadata?

**Partially — and this is under-used.**

| Evidence | Finding |
|---|---|
| RAG plan declares `tests/test_service.py` + `scripts/test.sh` | `rag/engine.py:129-131` |
| Agent/Automation `_stage_verify` require `tests/test_agent_runtime.py` / `test_automation_runtime.py` to **exist and parse** | `agent/engine.py:197-204`, `automation/engine.py:189-196` |
| RAG runs the customer suite for real | `rag/repair.py:144-170` |
| Greenfield (generic path) generated `test_tokenizer_lite.py` | 18-L evidence |
| Shared delivery platform ships `scripts/test.sh` | delivery platform (18-COMMERCIAL shared) |

**So for commercial deliverables the test entry point is *known and declared by construction*.** For the generic greenfield path it is merely *present* — nothing records it. This asymmetry is the crux of DECISION B.

        ▼                                     ▼
KernelReviewEngineAdapter.review_project   kernel_adapters.py:436
  _test_summary_from_context               kernel_adapters.py:54
  → ReviewEvidence(test_results=…)         → ReviewEngine.review  review/engine.py:163
                                             _tests_pass(None) → True  review/engine.py:66
        │                                           │
        └─────────────────┬─────────────────────────┘
                          ▼
     DefaultCompletionModule.finalize_project   completion.py:637
       ├─ review_gate.approved?
       └─ validation_truth["required"] and not passed → BLOCK  completion.py:695
                          ▼
                  transition_state("Finished")    completion.py:713
```


### 8.1 Option comparison (facts, not ranking)

| | **A — loop metadata** | **B — thin registry** | **C — Strategic Engine** | **D — O-2 boundary** |
|---|---|---|---|---|
| New architectural object | **No** | **Yes** (registry) | **Yes** (classification contract) | Partially |
| Files a later repair touches | **2–4** | 3–4 | 3 | 3 |
| **Smallest change** | ✅ **YES** | no | no | no |
| **Most architecture-consistent** | partial | ✅ **YES** (composition owns wiring; `WORKER_REGISTRY` precedent) | partial (needs a protected file) | partial |
| **Largest change** | no | no | ✅ **YES** | close second |
| Touches a DO-NOT subsystem | ✅ No | ✅ No | ❌ **Yes (Strategic Engine)** | ✅ No |
| Alters generic engineering semantics | ✅ No | ✅ No | ⚠️ **Yes, plausibly** | ✅ No |
| Capability inspectable in `ProjectState` | ❌ | ✅ | ✅ | ✅ |
| Capability inventory queryable | ❌ | ✅ | partial | partial |
| Per-engine adapter needed | yes (engine 5 extra) | yes (engine 5 extra) | yes + workflow shapes | yes (engine 5 extra) |
| Engine 11-stage lifecycle preserved | ✅ | ✅ | ✅ | ✅ |
| New ADR required | yes | yes | yes | yes |
| Test burden | **Lowest** | Moderate | **Highest** | Moderate–high |

**Compatibility implications.**
- ⚠️ **The Strategic Engine was explicitly in this gate's DO-NOT list.** Option C *requires* modifying it. This is reported, not performed.
- ⚠️ **The largest semantic blast radius.** Changing how the Strategic Engine classifies requests changes planning for **every** project, including generic engineering — the highest risk of silently altering non-commercial behaviour.
- ⚠️ Classification is the one decision that should be **inspectable and authoritative**. Placing it inside a reasoning step makes it harder to audit, and it must never be model-derived (Deterministic-First). `DefaultStrategicEngine` is currently deterministic — a change here risks making capability selection a model judgement, which would be a **principle violation**.
- ✅ Architecturally the most "consistent" placement if a human must always name the offering (see DECISION A).

**Impact on all five engines.** Uniform for 1–4; engine 5 still needs its adapter. Workflow shapes for 5 offerings must be designed and certified — substantially more work than a dispatch branch.

**Test burden.** Highest: per-capability planning tests + dispatch tests + regression protection for generic planning.

**Architectural risk.** **Highest.** Touches the protected Strategic Engine, changes platform-wide planning semantics, and risks converting a deterministic classification into a model judgement.

**Preserves certified engine workflows?** ✅ Yes, but at the cost of touching the planning layer for all projects.

**Impact on all five engines.** Uniform for 1–4. Engine 5 needs an input adapter (G.2 reconnaissance) and its sync call must be bridged (it performs blocking I/O; an `asyncio.to_thread` / executor bridge is required, and thread-safety must be considered).

**Test burden.** ~1 routing test per engine (5) + a "no capability ⇒ generic path unchanged" test + a result-normalisation test per engine shape. **Lowest of all options.**

**Architectural risk.** Low. Concentrates the new decision in one adapter. Main risk is that routing becomes *invisible* to the Kernel and to operators.

**Preserves certified engine workflows?** ✅ Yes, entirely — engines are called, not modified.

    engine = RAGKnowledgePowerEngine()
    result = asyncio.run(engine.execute_lifecycle(spec))     # ← bypasses the Kernel
    return result.model_dump()
```

This is strong evidence that **engine invocation is architecturally sanctioned**, and it establishes the exact `spec → execute_lifecycle → result` shape. But it is:

- a **bypass**, not a routing decision — it hardcodes RAG; there is no identifier and no selection;
- **outside** the O-2 path — it touches neither Kernel, Intent, Strategic, Workflow, O-2, the loop, Execution Engine, Context Engineering, the Model Router, the durable artifact pipeline, the Review Engine nor Completion;
- **one engine only** (3 of 5 have no equivalent at all);
- `asyncio.run` inside a request handler — it cannot be called from the async O-2 path.

Per ADR-019, O-3 is *"parallel to the Kernel"* and not production-authoritative. **It must not be treated as the canonical seam, and it must not be promoted into one by this repair.**

---

## 7. Five-Engine Routing Evidence

| Engine | Existing Certified Entry | Canonical Entry | Capability Identity Available? | Missing Edge | Proposed Seam |
|---|---|---|---|---|---|
| **RAG Knowledge** | `RAGKnowledgePowerEngine.execute_lifecycle(spec)` · `base.py:141` · certified via `packages/power_engines/tests/` (123 pass) | ❌ none — `execute_loop` → `ExecutionEngine` only | ⚠️ **yes, unused** — `ProjectState.configuration` is readable at the seam | **capability identification → routing → invocation** (all 3) | `kernel_adapters.py:272` (`execute_loop`), fed by `Request.configuration` |
| **Custom AI Agent** | `CustomAIAgentPowerEngine.execute_lifecycle(spec)` · `agent/engine.py:22` · `_resolve_spec` adapts a generic spec | ❌ none | ⚠️ **yes, unused** | **all 3** | same |
| **AI Automation** | `AIAutomationPowerEngine.execute_lifecycle(spec)` · `automation/engine.py:22` | ❌ none | ⚠️ **yes, unused** | **all 3** | same |
| **Code Migration** | `CodeMigrationPowerEngine.execute_lifecycle(spec)` · `migration/engine.py:36` | ❌ none | ⚠️ **yes, unused** | **all 3** | same |
| **Legacy Modernization** | `ModernizationPipeline.run(project_id, job_id, recon)` — **sync** · `modernization/pipeline.py:222` · 91 tests pass | ❌ none | ⚠️ **yes, unused** | **all 3 + a 4th: input adaptation** (needs G.2 reconnaissance output, not a `CustomerProjectSpecification`) | same + an input-adapter obligation |

### 7.1 The missing-edge taxonomy (refines 18-LR's "the seam is `execute_loop`")

18-LR correctly identified `execute_loop` as *the isolated seam*. Source shows the truth is more precise and more useful:

- **Edges 1–2 (identify, route) are missing and are genuinely NEW work.** No capability identifier is assigned, and no registry exists. This is a design task.
- **Edge 3 (invoke) already exists for engines 1–4** — `execute_lifecycle` is uniform and the `PowerEngineResult` envelope already exists. No new result type is needed.
- **Edge 4 (return) already exists** — `execute_loop` already returns a dict consumed by `handle_loop_completion` (`orchestration.py:210`): `{"status","loop_type","passed","artifacts","evaluation","findings"}`.
- **Legacy Modernization additionally lacks a uniform invocation** (sync, different input/output), so any registry must normalize it.

**This materially reduces the size of DECISION A: the expensive part is deciding *where* the identifier comes from and *where* the switch is, not building an execution harness.**

---

|---|---|---|
| `KernelWorkflowEngineAdapter.create_executable_workflow` (`kernel_adapters.py:115-233`) | The `Request` is **not passed in at all** — the signature is `(strategic_plan, context)`. `context` holds `strategic_plan` + `intent_analysis` only (`planning_coordination.py:148-152`) | Yes — `PlanningCoordinator` still holds `request` |
| `DefaultStrategicEngine.create_strategic_plan` (`strategic_engine.py:41`) | Reads `config["language"]`/`["framework"]`; **discards** everything else in `Request.configuration` | Yes — `request` is in scope |
| `DefaultOrchestrationEngine.orchestrate` (`orchestration.py:161-168`) | Loop context is rebuilt from the fixed loop dict; no capability key | Yes — the `Runtime` already holds `ProjectState.configuration` |

**F-3 restated: capability identity is not "lost" so much as never *read*. Three viable existing injection points, all upstream of the seam, all already carrying the data.**


| RAG Knowledge | **PASS** | **FAIL** | ❌ No |
| Custom AI Agent | **PASS** | **FAIL** | ❌ No |
| AI Automation | **PASS** | **FAIL** | ❌ No |
| Code Migration | **PASS** | **FAIL** | ❌ No |
| Legacy Modernization | **PASS** (repaired B-2) | **FAIL** | ❌ No |

**No engine is declared broken. All five remain independently certified.**

---


None. `ModernizationPipeline` is imported **only** by its own tests:

```
packages/modernization/tests/test_g3_llm_and_transform.py
packages/modernization/tests/test_d3_source_technology.py
packages/modernization/tests/test_18lr_b2_real_source_transformation.py
```

`23_WORKER_AI_BINDING_FORENSIC_AUDIT.md:156` independently confirms: *"Zero References to Workforce: `WorkforceDispatcher`, `WORKER_REGISTRY`, and `WorkforceWorker` are never imported or referenced anywhere in `packages/modernization`."*

| `KERNEL_SPECIFICATION.md:2917-2920` | Completion requires *"All quality gates passed / All reviews approved / **All tests passed**"* | **All tests passed** is already a *specified* completion requirement — simply not enforced today |
| `ARCHITECTURE.md:686` | The Review Engine *"is the quality gate of the platform"* | Review **evaluates**; it does not **produce** deterministic truth |
| `PRINCIPLES` (deterministic-first) | Model confidence can never override a deterministic failure | Binding constraint on both options |

### 3.4 Contract vs implementation — the three divergences

| # | ARCHITECTURAL CONTRACT | CURRENT IMPLEMENTATION | Divergence |
|---|---|---|---|
| **C-1** | Commercial Power Engines produce turnkey deliverables (`ARCHITECTURE.md:1409`) | No production component on the O-2 path imports `autoforge_power_engines` or `autoforge_modernization` | **BLOCKER A** |
| **C-2** | Completion requires *"All tests passed"* (`KERNEL_SPECIFICATION.md:2917`) | The canonical path executes **zero** commands; `input_data["verification_commands"]` is never populated | **BLOCKER B** |
| **C-3** | *(not specified)* | The D-8 port that consumes validation evidence cannot read project state on production wiring | **D-8b — new finding** |

---
