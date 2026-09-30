# PHASE 18-LD — CAPABILITY ROUTING ANALYSIS

**Companion to:** `PHASE_18LD_ARCHITECTURE_DECISION_REPORT.md`
**Scope:** BLOCKER A — canonical capability routing. **Analysis only. No implementation.**

---

## 1. Current call graph (as it actually is)

Every arrow below is source-verified. `★` marks a place where capability identity is absent or unread.

```
Request(configuration={"capability": ...}?)        interfaces.py:47
  │                                              ★ NOT READ
  ├─ DefaultRequestNormalizer.normalize            request_intake.py:98
  │     └─ Project.metadata["configuration"] = request.configuration
  │                                                    ★ CARRIED (durable)
  ├─ runtime_state_manager.create_project          runtime_facade.py:103
  │     └─ ProjectState.configuration = dict(project.metadata)   ★ DURABLE
  │
  ├─ DefaultIntentAnalyzer.analyze                 intent_analysis.py:39
  │     └─ _classify_request_type → "implementation"
  │        ★ WRONG VOCABULARY: {research, review, deployment,
  │          testing, implementation} — all five commercial
  │          offerings classify as "implementation"
  │
  ├─ DefaultStrategicEngine.create_strategic_plan  strategic_engine.py:41
  │     └─ reads config["language"], config["framework"] ONLY
  │        ★ everything else in configuration DISCARDED
  │
  ├─ KernelWorkflowEngineAdapter.create_executable_workflow
  │                                              kernel_adapters.py:115
  │     ★ SIGNATURE IS (strategic_plan, context) — Request NOT PASSED IN
  │     └─ emits 4–5 fixed loops:
  │          research? / architecture / coding / qa / review
  │          input_data = {requirements | technology_choices
  │                       | acceptance_criteria}
  │          ★ NO capability key anywhere
  │
  └─ DefaultOrchestrationEngine.orchestrate        orchestration.py:87
        ├─ reads request_text from Runtime state   orchestration.py:133-159
        │   ★ proves durable project config IS readable at this boundary
        ├─ for loop in loops:  loop_context = {project_id, workflow_id,
        │                                      loop, request_text}   ★
        └─ DefaultLoopOrchestrator.orchestrate_loop      orchestration.py:411
              └─ execution_engine.execute_loop(loop_type, loop_input, context)
                    ★★ THE SEAM ★★
              KernelExecutionEngineAdapter.execute_loop   kernel_adapters.py:272
                ├─ worker_map: loop_type → WorkerType        :285
                ├─ input_data = loop["input_data"]           :297  ★ no capability
                ├─ description ← request_text                :315
                ├─ TaskDefinition(..., input_data=input_data):321
                └─ concrete_engine.execute_task_definition   :333
                      └─ ExecutionEngine.execute_task_definition  engine.py:144
                            └─ WorkforceDispatcher.dispatch_task  dispatch.py:96
                                  └─ WORKER_REGISTRY.lookup("backend_engineer")
                                        ★ WORKER vocabulary, not offering vocabulary
```

**The chain terminates at the generic `ExecutionEngine`. No commercial engine is reachable.**

### 1.1 Re-derived AST proof (independently reproduced by this gate)

`18LR-defect-repair/ast_engine_reachability.py`, re-run at HEAD `c72dad9`:

```json
{
  "autoforge_power_engines": { "internal_importing_files": 49,
                               "external_importing_packages": {} },
  "autoforge_modernization": { "internal_importing_files": 49,
                               "external_importing_packages": {} },
  "canonical_path_engine_reachability": {
    "packages/kernel/src/autoforge_kernel/kernel.py": [],
    "packages/kernel/src/autoforge_kernel/orchestration.py": [],
    "packages/kernel/src/autoforge_kernel/completion.py": [],
    "packages/kernel/src/autoforge_kernel/strategic_engine.py": [],
    "packages/composition/src/autoforge_composition/composition_root.py": [],
    "packages/composition/src/autoforge_composition/kernel_adapters.py": [],
    "packages/execution/src/autoforge_execution/engine.py": []
  },
  "canonical_path_reaches_any_engine": false
}
```

---

## 2. Five-engine entry points

| Engine | Class | Entry point | Signature | Sync? | Package |
|---|---|---|---|---|---|
| RAG Knowledge | `RAGKnowledgePowerEngine` `rag/engine.py:29` | `execute_lifecycle` `base.py:141` | `(spec, auto_approve_safe_risks=True) -> PowerEngineResult` | async | `autoforge_power_engines` |
| Custom AI Agent | `CustomAIAgentPowerEngine` `agent/engine.py:22` | `execute_lifecycle` | same | async | `autoforge_power_engines` |
| AI Automation | `AIAutomationPowerEngine` `automation/engine.py:22` | `execute_lifecycle` | same | async | `autoforge_power_engines` |
| Code Migration | `CodeMigrationPowerEngine` `migration/engine.py:36` | `execute_lifecycle` | same | async | `autoforge_power_engines` |
| Legacy Modernization | `ModernizationPipeline` `pipeline.py:161` | **`run`** `pipeline.py:222` | `(project_id, job_id, reconnaissance_output, plan=None) -> PipelineResult` | **SYNC** | `autoforge_modernization` |

### 2.1 The uniform contract (engines 1–4)

```python
class PowerEngine(ABC):                              # base.py:103
    def create_context(spec) -> PowerEngineContext   # base.py:125
    async def execute_lifecycle(spec, auto_approve_safe_risks=True)
        -> PowerEngineResult                        # base.py:141
    # 11 abstract stage handlers                    # base.py:259-301
```

`PowerEngineResult` (`base.py:90-100`) already carries:
`success`, `execution_id`, `project_name`, `delivery_dir`, `stages_executed`,
`repair_count`, **`verification_scorecard`**, `summary_report`, `error_message`.

`PowerEngineContext` (`base.py:74-87`) already carries:
`execution_id`, `project_id`, `delivery_id`, `specification`, `output_root`,
`delivery_dir`, `current_stage`, `stage_history`, `pending_approval`, `telemetry`.

**Implication: a router needs no new result envelope and no new context object.** Both already exist and are populated.

### 2.2 The odd one out (engine 5)

`ModernizationPipeline` is in a **different package**, is **synchronous**, takes **G.2 reconnaissance output** instead of a specification, and returns a structurally different `PipelineResult` (`pipeline.py:92`) carrying `analysis_report`, `gate_decisions`, `transformation_records`, `wave_results`, `migration_plan`.

---

## 4. Capability identity analysis

### 4.1 Does capability identity exist upstream? — YES (unused)

| Location | Carrier | Durable? | Reaches the seam? |
|---|---|---|---|
| `interfaces.py:64` | `Request.configuration: dict` | via `request_intake.py:152` → `runtime_facade.py:103` | ❌ not forwarded |
| `interfaces.py:147-189` | `ExecutableWorkflow.metadata` | ✅ | ❌ **never populated** by `kernel_adapters.py:223-233` |
| `interfaces.py:154` | `ExecutableWorkflow.loops[i]` free-form dict | ✅ | ✅ **already forwarded** (`orchestration.py:166`) |
| `workflows/models.py:368` | `TaskDefinition.input_data` | ✅ | ✅ already read at `kernel_adapters.py:297` |
| `workflows/models.py:372` | `TaskDefinition.metadata` | ✅ | ❌ not forwarded |

### 4.2 The decisive proof that config keys survive

`DefaultStrategicEngine` reads `config.get("language")` and `config.get("framework")` (`strategic_engine.py:102-103`) and places them in `StrategicPlan.technology_choices` (`strategic_engine.py:104-110`). `KernelWorkflowEngineAdapter` then reads `strategic_plan.technology_choices` and writes it into `loops[2]["input_data"]` (`kernel_adapters.py:154-158`). `execute_loop` then reads `loop["input_data"]` (`kernel_adapters.py:297`).

**Therefore an arbitrary `Request.configuration` key provably reaches `execute_loop` today.** The channel is proven; only the read is missing.

### 4.3 Live probe (this gate, read-only)

```
ProjectState.configuration keys: ['configuration', 'original_request',
                                  'user_id', 'workflow_id']
  nested 'configuration'       : {'environment': 'production', 'execute': False,
                                  'verification_command': "python -c \"print('ok')\""}
```

**Confirmed: `Request.configuration` survives intact into authoritative Runtime state, and the composition root already reads it (for the validation port).**

### 4.4 What does NOT carry capability

- `IntentAnalysisResult.request_type` — loop vocabulary, not offering vocabulary.
- `TaskDefinition.task_type` — occupied by the loop type (`"coding"`, `"qa"`, …).
- `WORKER_REGISTRY` — 23 engineering worker specialisations, a different domain.
- `TechnologyCapabilityRegistry` — source-technology *transformation* capabilities (COBOL/JCL analysis support), a different domain.
- `ModelRouter` / `InMemoryCapabilityRegistry` — **model** capabilities (text generation, reasoning, context size). A different domain entirely. Must not be reused for commercial offerings.

---

## 5. Existing registries and adapters

| Artifact | Location | Shape | Reusable as a router? |
|---|---|---|---|
| `WORKER_REGISTRY` | `workforce/registry.py` | specialization → class; `lookup`, `list_workers`, `match_capabilities`, `get_expertise`, `check_task_compatibility`, `validate_permission` | ⚠️ **Mechanism yes, vocabulary no.** The strongest in-repo precedent for Option B's shape. |
| `KernelExecutionEngineAdapter` | `composition/kernel_adapters.py:263` | adapts `ExecutionEngine` | ❌ Not a router; it is the *place* a router would live. |

---

## 7. Why the existing API precedent is not the seam

```python
# apps/api/src/autoforge_api/service.py:2358
def execute_rag_power_engine(self, spec_dict):
    spec = CustomerProjectSpecification(**spec_dict)
    engine = RAGKnowledgePowerEngine()          # hardcoded — no selection
    result = asyncio.run(engine.execute_lifecycle(spec))
    return result.model_dump()
```

| Property | Assessment |
|---|---|
| Selects a capability? | ❌ No — RAG is hardcoded |
| Passes through the Kernel? | ❌ No |
| Passes through Intent/Strategic/Workflow/O-2? | ❌ No |
| Passes through `execute_loop`? | ❌ No |
| Reaches Context Engineering / the Model Router? | ❌ No |
| Reaches `EngineeringLoop` / `ArtifactPipeline` / 18-K? | ❌ No |
| Reaches Review / Completion? | ❌ No |
| Covers all five engines? | ❌ 1 of 5 |
| Callable from the async O-2 path? | ❌ `asyncio.run` inside a running loop raises |
| Authority | O-3, *"parallel to the Kernel"* (ADR-019) — **not production-authoritative** |

**It is a bypass, not a routing seam. It must not be promoted into the canonical path, and it must not be treated as proof that routing already exists.**

---

## 8. Routing proof per engine (what a future repair must demonstrate)

| Engine | Engine actually executed on the O-2 path? | Engine class that must be observed | Extra obligations |
|---|---|---|---|
| RAG Knowledge | ❌ (`ExecutionEngine` only) | `RAGKnowledgePowerEngine` | build `CustomerProjectSpecification` from the request |
| Custom AI Agent | ❌ | `CustomAIAgentPowerEngine` | supply `agent_purpose` / `allowed_tools` (or let `_resolve_spec` adapt, `agent/engine.py:39`) |
| AI Automation | ❌ | `AIAutomationPowerEngine` | build a specification |
| Code Migration | ❌ | `CodeMigrationPowerEngine` | build a specification |
| Legacy Modernization | ❌ | `ModernizationPipeline` | **G.2 reconnaissance from real source**; **sync→async bridge**; `PipelineResult` normalisation; **B-2 must not regress** |

---

## 9. No implementation

**This document implements nothing.** No routing, no registry, no adapter, no dispatch branch was created. The probes used to derive §1.2 and §4.3 were **read-only** and were written to `/tmp`, never to the repository. The working tree is byte-identical to the start of the gate (34 `git status --porcelain` lines at start and at finish; HEAD `c72dad9` unchanged).

**The routing seam is proven; the routing design is DECISION A and belongs to the human.**

| `KernelWorkflowEngineAdapter` | `composition/kernel_adapters.py:106` | builds `ExecutableWorkflow` | ❌ Not a router; where a capability key would be *emitted*. |
| `DefaultOrchestrationEngine` | `kernel/orchestration.py:37` | O-2 control flow | ❌ Not a router; the Option D seam. |
| `apps/api` `execute_rag_power_engine` | `apps/api/src/autoforge_api/service.py:2358` | hardcoded `RAGKnowledgePowerEngine()` + `asyncio.run` | ❌ A **bypass** (see §7). |
| `TechnologyCapabilityRegistry` | `modernization/capability_registry.py` | source-technology support registry | ❌ Different domain. |
| `InMemoryCapabilityRegistry` | `ai_infrastructure` | model/provider capability registry | ❌ Different domain (models, not offerings). |

**No commercial-engine registry exists anywhere in the repository.**

---

## 6. The exact candidate seam

```python
# packages/composition/src/autoforge_composition/kernel_adapters.py:272
async def execute_loop(
    self,
    loop_type: str,          # ← loop vocabulary, NOT capability
    loop_input: dict,        # ← {"project_id","workflow_id","loop","request_text"}
    context: dict,           # ← same dict (orchestration.py:452-456)
) -> dict:
```

**What is available here (source-verified):**

| Available | Source |
|---|---|
| `loop_type` (`research`/`architecture`/`coding`/`qa`/`review`) | `orchestration.py:162` |
| the full `loop` dict | `orchestration.py:166` |
| `loop["input_data"]` (`requirements`, `technology_choices`, `acceptance_criteria`) | `kernel_adapters.py:154-179` |
| `request_text` (full original request) | `orchestration.py:133-168` |
| `project_id`, `workflow_id` | `orchestration.py:164-165` |
| read access to `ProjectState.configuration` (durable) | proven in §4.3; precedent at `orchestration.py:133-159` |
| an existing return contract consumed downstream | `orchestration.py:210-270` |

**What is NOT available:** any commercial capability identifier.

**Conclusion:** `execute_loop` is the correct and smallest seam — it is the last boundary before the generic `ExecutionEngine` commits, it already builds the `TaskDefinition`, and it already returns the dict the O-2 completion handler consumes. The identifier must be **carried in** from one of three existing upstream points (§4.1).

### 6.1 Three viable injection points, all pre-existing

| # | Injection point | Precedent |
|---|---|---|
| **I-1** | `KernelWorkflowEngineAdapter.create_executable_workflow` emits `loops[0]["capability"]` | the loop dict is already free-form (`interfaces.py:154`) |
| **I-2** | `DefaultStrategicEngine` puts the capability in `StrategicPlan.metadata`/`technology_choices` | it already reads `Request.configuration` (`strategic_engine.py:101-110`) — **but this is a protected file** |
| **I-3** | `execute_loop` reads `ProjectState.configuration` directly | exactly what `orchestration.py:133-159` already does for `request_text` |


Any registry or switch must normalise it. It cannot be assumed into uniformity.

---

## 3. Missing edges

| Edge | Status | Evidence |
|---|---|---|
| **1. capability identification** | ❌ **MISSING** | No component assigns a capability identifier. `IntentAnalysisResult.request_type` uses loop vocabulary (`intent_analysis.py:83-117`) and is never forwarded to the seam. |
| **2. routing decision** | ❌ **MISSING** | No registry maps an identifier to an engine. `WORKER_REGISTRY` maps *worker specialization* → worker class only. |
| **3. engine invocation** | ⚠️ **EXISTS for 1–4, MISSING for 5** | `execute_lifecycle` is uniform and callable (`base.py:141`). Engine 5's `run` is sync and takes a different input. |
| **4. result return** | ✅ **EXISTS** | `execute_loop` already returns `{"status","loop_type","passed","artifacts","evaluation","findings"}` (`kernel_adapters.py:340-347`), consumed by `handle_loop_completion` (`orchestration.py:210-270`). |

**Refinement of 18-LR's finding.** 18-LR reported the seam as `execute_loop`; that is correct as the *last point of no return*. Source shows the sharper truth: **edges 3 and 4 already exist**; only **edges 1 and 2 are genuinely new work**, plus a normalisation duty for engine 5. This materially reduces the size of DECISION A.


### 1.2 Re-derived dynamic proof

`18LR-defect-repair/evidence/layer_b_canonical_engines.json` (read back by this gate):

| Capability | `reached_commercial_engine` | `distinct_executors` | Loops |
|---|---|---|---|
| `rag_knowledge` | **false** | `['ExecutionEngine']` | 4 |
| `custom_ai_agent` | **false** | `['ExecutionEngine']` | 4 |
| `ai_automation` | **false** | `['ExecutionEngine']` | 4 |
| `code_migration` | **false** | `['ExecutionEngine']` | 4 |
| `legacy_modernization` | **false** | `['ExecutionEngine']` | 4 |

`"canonical_integration_pass": false`, `"engines_reached_by_canonical_path": []`.
