# 18-LE — CAPABILITY ROUTING IMPLEMENTATION

Implements **DECISION A** at the seam 18-LD isolated.

---

## 1. The seam, verified before editing

18-LD proved (AST + dynamic) that `KernelExecutionEngineAdapter.execute_loop`
is the last boundary before the generic `ExecutionEngine` commits. Verified
against source before editing:

```python
# kernel_adapters.py:272 (pre-repair)
async def execute_loop(self, loop_type, loop_input, context) -> dict:
    input_data = loop_input.get("loop", {}).get("input_data", {})
    task_def = TaskDefinition(..., input_data=input_data)   # ← no capability read
    passed, artifacts, eval_res = await self.concrete_engine.execute_task_definition(...)
```

The generic `ExecutionEngine` was unconditionally the executor. Confirmed.

---

## 2. Capability identity

Uses the **already proven** durable configuration channel. No new abstraction.

```
Request.configuration["capability"]          (existing, proven durable)
  → Project.metadata["configuration"]        (existing intake)
  → ProjectState.configuration                (existing runtime projection)
  → read at execute_loop                      (NEW read)
```

| Capability | Canonical value | Engine |
|---|---|---|
| RAG | `rag_knowledge` | `RAGKnowledgePowerEngine` |
| Custom AI Agent | `custom_ai_agent` | `CustomAIAgentPowerEngine` |
| AI Automation | `ai_automation` | `AIAutomationPowerEngine` |
| Code Migration | `code_migration` | `CodeMigrationPowerEngine` |
| Legacy Modernization | `legacy_modernization` | `ModernizationPipeline` |

Aliases (`rag`, `agent`, `automation`, `migration`, `modernization`, …) map the
gate brief's prose vocabulary onto the canonical values. Matching is
case-insensitive and normalises `-`/space to `_`.

**Resolution order** (first match wins, fully deterministic, no model consulted):
1. `loop["input_data"]["capability"]` → source `loop_input`
2. `ProjectState.configuration["capability"]` → source `project_configuration`

**Fail-closed:** an unrecognised value resolves to `None` and the router raises
`UnknownCapabilityError`. A silent fallback to the generic engine would recreate
BLOCKER A invisibly, so it is explicitly forbidden.

---

## 3. What was added

### `capability_router.py` (new — the only new architectural object)

Lives in the composition package, which already owns all wiring (ADR-002).
Engine imports are **deferred inside factories**, so importing the composition
package does not eagerly pull in the engine packages.

| Component | Responsibility |
|---|---|
| `normalize_capability` | deterministic identifier normalisation |
| `read_capability` | resolution + inspectable source |
| `RoutedExecution` | one result envelope for both engine shapes |
| `CommercialCapabilityRouter` | registry, invoke, boundary adaptation |
| `UnknownCapabilityError` | fail-closed error |
| `build_default_router` | binds the five real engines |

### `kernel_adapters.py` (modified)

- `KernelExecutionEngineAdapter.__init__` gains two **optional** injected
  collaborators: `capability_router` and `project_configuration_reader`. Both
  default to `None`, so any existing caller gets the original adapter.
- `execute_loop` gains a routing branch at the top. **If no capability resolves,
  the generic code below runs completely unchanged.**
- `_execute_commercial_loop` invokes the engine and returns the dict shape
  `handle_loop_completion` already consumes.
- `_publish_routed_evidence` records the engine's own verification scorecard as a
  **durable `test_report` artifact** through the existing `ArtifactPipeline`.

### `composition_root.py` (modified)

Constructs the router and injects it plus `facade.get_project_state` as the
durable-config reader. This is the **only** place the canonical O-2 path becomes a
consumer of the engine packages — the edge 18-LD proved absent.


---

## 4. Engine boundary adaptation (engines NOT modified)

18-LD found edges 3–4 (invoke, return) already existed. Two real differences had
to be absorbed **at the boundary**:

| Engine | Difference | Adaptation at the routing boundary |
|---|---|---|
| RAG, Agent | accept base `CustomerProjectSpecification` | none needed (Agent adapts internally via `_resolve_spec`) |
| **Automation** | **rejects** a base spec — `TypeError` by design | build `CustomerAutomationSpecification` (requires ≥1 step + `workflow_id`) |
| **Migration** | **rejects** a base spec — `TypeError` by design | build `CustomerMigrationSpecification` (needs real `source_path` + `target_language`) |
| **Modernization** | **synchronous**, reconnaissance-driven, different package | `asyncio.to_thread`; **refuses to run without a real `legacy_source_root`** |

All specification types derive from `CustomerProjectSpecification`
(`specification.py`), so one shared kwargs builder serves all of them.

**B-2 protection:** the modernization adapter raises explicitly when no real
source root is declared. It never synthesises a placeholder — that would
reintroduce B-2 through a new door.

---

## 5. Result normalisation

`RoutedExecution` maps both engine shapes onto one contract, then into the O-2
status vocabulary (`complete` / `remediate` / `escalate` / `failed`) that
`handle_loop_completion` (`orchestration.py:210`) already consumes:

| Engine shape | Source | Status mapping |
|---|---|---|
| `PowerEngineResult` (1–4) | `success` + `stages_executed` | `WAITING_FOR_HUMAN_APPROVAL` → `escalate`; success → `complete`; else `remediate` |
| `PipelineResult` (5) | `status` + wave results | `blocked` → `escalate`; `complete` → `complete`; else `remediate` |

`verification_scorecard` is carried **verbatim** from the engine — DECISION B
layer 2 requires the engine's own deterministic evidence to reach canonical
validation/review/completion, not to be replaced by a second authority.

---

## 6. Proof: five engines routed canonically

Real composed system, real engines, no mocks. Evidence:
`18LE-canonical-integration/evidence/canonical_routing.json`.

| Capability | Engine actually invoked | Routed | Status | Delivery | Engine scorecard |
|---|---|---|---|---|---|
| `rag_knowledge` | `RAGKnowledgePowerEngine` | 4/4 | complete | ✅ | `grounding_score`, `real_inference`, `syntax_valid`, `tests_passed`, `tests_run` |
| `custom_ai_agent` | `CustomAIAgentPowerEngine` | 4/4 | complete | ✅ | `defects_count`, `passed`, `proprietary_violations` |
| `ai_automation` | `AIAutomationPowerEngine` | 4/4 | complete | ✅ | `defects_count`, `passed`, `proprietary_violations` |
| `code_migration` | `CodeMigrationPowerEngine` | 4/4 | complete | ✅ | `failed`, `inconclusive`, `passed`, `total` |
| `legacy_modernization` | `ModernizationPipeline` | 4/4 | complete | n/a | `pipeline_status`, `real_source`, `transformation_records`, `units_transformed`, `units_failed`, `wave_count` |

`"canonical_routing_pass": true`

---

## 7. Full canonical architecture trace

Evidence: `evidence/canonical_architecture_trace.json`. No simulated routing, no
mocks — every boundary observed on the real composed system.

| Boundary | Observed |
|---|---|
| `Kernel` | `Kernel` |
| Intent Analysis | executed (→ `StrategicPlan`, 2 requirements, 4 acceptance criteria) |
| `DefaultStrategicEngine` | `DefaultStrategicEngine` |
| Executable Workflow | 4 loops planned |
| O-2 Orchestration | `DefaultOrchestrationEngine` |
| **Capability routing** | `capability=custom_ai_agent`, `source=project_configuration` |
| **Engine actually invoked** | **`CustomAIAgentPowerEngine`** |
| Engine lifecycle | all 11 stages: INTAKE → DELIVER |
| Engine verification | `{defects_count: 0, passed: true, proprietary_violations: 0}` |
| Real delivery | directory created on disk ✅ |
| `ArtifactPipeline` → `DurableArtifactCatalog` → `PhysicalArtifactStore` | 4 artifacts, **all committed** |
| Review evidence | 4 files, incl. the engine scorecard artifacts |

---

## 8. Regression tests

`packages/composition/tests/test_capability_routing.py` — **26 passed**: the five
capabilities are exactly the five offerings; identifiers deterministic across 12
raw forms; unknown capability never guessed; resolution from `loop_input` and
from durable configuration; precedence; `(None, None)` when absent; the default
router binds all five; unknown registration and invocation both raise; **no
capability ⇒ the generic engine still executes, result unchanged**; **capability
⇒ routes, reports the real engine, generic engine NOT called**; engine scorecard
transported verbatim; declared verification reaches the `TaskDefinition`; absent
declaration leaves input untouched.

---

## 9. Scope discipline

| Not modified | Evidence |
|---|---|
| All five Commercial Power Engines | no `power_engines/` or `modernization/` file in `git diff --name-only` (except 18-LR's pre-existing `pipeline.py`) |
| Strategic Engine | unchanged |
| Model Router | unchanged (protected; model binding used the existing deployment seam) |
| Context Engineering / Compaction | unchanged |
| 18-J / 18-K | unchanged |
| Review Engine | unchanged |
| O-2 orchestration | unchanged |
