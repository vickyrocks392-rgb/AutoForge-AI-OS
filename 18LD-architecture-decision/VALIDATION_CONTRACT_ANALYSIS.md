# PHASE 18-LD — VALIDATION CONTRACT ANALYSIS

**Companion to:** `PHASE_18LD_ARCHITECTURE_DECISION_REPORT.md`
**Scope:** BLOCKER B — deterministic verification-command ownership, **plus** the D-8b defect this gate discovered.
**Analysis only. No implementation.**

---

## 1. Current validation call graph

```
                    ┌──────────────────────────────────────────────────┐
                    │ WHERE VALIDATION IS DEFINED                     │
                    │  parse_test_output         evaluation.py:25     │
                    │  EvaluationEngine.evaluate_attempt  :109        │
                    │  deterministic: exit codes, parse_test_output,  │
                    │  required_files, custom checks                  │
                    └──────────────────────────────────────────────────┘
                                  ▲
        ┌─────────────────────────┴─────────────────────────┐
        │ (A) PER-ITERATION                                 │ (B) PER-PROJECT
EngineeringLoop.run                                WorkspaceValidationPort
  loop.py:265  for cmd in commands_to_run:               validation_wiring.py:92
          cmd_res = env.execute_command(cmd_spec)        validate_project():127
  loop.py:286  eval_res = evaluate_attempt(cmd_results)   WorkspaceEnvironment
  loop.py:289  record_evaluation_artifact                    .execute_command  ★ SAME
                                                            + parse_test_output
  ★ commands_to_run is EMPTY (loop.py:108)                 _project_configuration
  ★ fallback input_data["commands"]/["test_commands"]        :119  ★ BROKEN (D-8b)
    are also unset (loop.py:110)                          reads resolve_verification_command
        │                                                    from ProjectState.configuration
        │                                          ★ NEVER SEES A DECLARED COMMAND
        ▼                                                     │
KernelReviewEngineAdapter.review_project  kernel_adapters.py:436
  _test_summary_from_context              kernel_adapters.py:54
  → ReviewEvidence(test_results=…)        → ReviewEngine.review   review/engine.py:163
                                             _tests_pass(None) → True  review/engine.py:66
        │                                            │
        └──────────────────┬─────────────────────────┘
                           ▼
     DefaultCompletionModule.finalize_project          completion.py:637
       ├─ validate_completion                           completion.py:290
       ├─ _run_final_review                             completion.py:529
       │    └─ _collect_validation_evidence            completion.py:475
       ├─ review approved?                              completion.py:671
       ├─ validation_truth["required"] and not passed → BLOCK  completion.py:695
       └─ transition_state("Finished")                 completion.py:713
```

---

## 2. `verification_commands` lifecycle — 17 stages, one break

| # | Stage | Location | State |
|---|---|---|---|
| 1 | Request | `interfaces.py:64` | ❌ never read |
| 2 | Normalize | `request_intake.py:98` | ❌ keys lowercased; value untouched |
| 3 | Project init | `request_intake.py:152` | ❌ nested under `metadata["configuration"]` |
| 4 | Runtime state | `runtime_facade.py:103,131` | ❌ **durable** as `ProjectState.configuration` |
| 5 | Intent | `intent_analysis.py:39` | ❌ not read |
| 6 | Strategic | `strategic_engine.py:101` | ❌ reads `language`/`framework` only |
| 7 | Workflow | `kernel_adapters.py:115` | ❌ **`Request` is not even passed in** |
| 8 | O-2 loop ctx | `orchestration.py:163` | ❌ not added |
| 9 | **`execute_loop`** | `kernel_adapters.py:297-327` | ❌ **← THE BREAK** |
| 10 | Dispatch | `workforce/dispatch.py:141` | ❌ not read |
| 11 | Context | `context.py:98` | ✅ `input_data` carried faithfully |
| 12 | **Worker** | `workforce/workers.py:93` | ✅ **reads `input_data["verification_commands"]`** → always `None` |
| 13 | **Loop** | `loop.py:102,108-116` | ✅ parameter honoured; ❌ fallback keys also unset |
| 14 | Execute | `loop.py:265` | ❌ **zero commands** |
| 15 | Evaluate | `loop.py:286` | ⚠️ `evaluate_attempt([])` → `INCONCLUSIVE`, `passed=False` |
| 16 | Artifact | `loop.py:289` | ⚠️ `"status":"inconclusive"`, `"test_results": null`, `"deterministic_checks": []` |
| 17 | Completion port | `validation_wiring.py:119` | ❌ **D-8b** |

**The break is a single missing write at stage 9. The readers at stages 12–13 are live.**


---

## 3. NEW DEFECT — D-8b: the validation port cannot read a declared command

### 3.1 The defect

`packages/composition/src/autoforge_composition/validation_wiring.py:114-125`:

```python
def _project_configuration(self, project_id: Any) -> dict[str, Any]:
    if self._runtime is None:
        return {}
    try:
        state = self._runtime.get_project_state(project_id)   # ← line 119
    except Exception as exc:
        logger.warning("Validation port could not read project state: %s", exc)
        return {}
    if not isinstance(state, dict):        # ← a coroutine is NOT a dict
        return {}
    return state.get("configuration") or {}
```

`self._runtime` is wired by the composition root to the **`KernelRuntimeFacade`** (`composition_root.py:457-460`), whose `get_project_state` is declared **`async def`** (`runtime_facade.py:150`).

`self._runtime.get_project_state(project_id)` therefore returns a **coroutine object**, never awaited. `isinstance(state, dict)` is `False`, so `_project_configuration` returns `{}` for **every project on the production path**.

### 3.2 Live reproduction (this gate, read-only probe)

```
PORT TYPE                      : WorkspaceValidationPort
WIRED RUNTIME TYPE             : KernelRuntimeFacade
get_project_state is coroutine : True
validate_project(unknown id)   : {"required": false, "performed": false, "passed": true,
                                  "reason": "Project declares no verification command."}

ProjectState.configuration keys: ['configuration', 'original_request',
                                  'user_id', 'workflow_id']
  nested 'configuration'       : {'environment': 'production', 'execute': False,
                                  'verification_command': "python -c \"print('ok')\""}
resolve_verification_command() : ['python', '-c', "print('ok')"]     ← the reader works

validate_project(REAL project that DOES declare a command):
    {"required": false, "performed": false, "passed": true,
     "reason": "Project declares no verification command.", "command": null}
```

**The configuration IS durable, the command IS declared, and `resolve_verification_command` resolves it correctly — yet the port still reports `required: false`.**

Corroborating symptom already present in the repository's own test output:

```
packages/composition/src/autoforge_composition/validation_wiring.py:134: RuntimeWarning:
  coroutine 'KernelRuntimeFacade.get_project_state' was never awaited
```

---

## 4. Existing validation contracts

| Contract | Verification field? | Evidence |
|---|---|---|
| `Request` | ⚠️ free-form `configuration: dict` | `interfaces.py:64` |
| `IntentAnalysisResult` | ❌ `constraints: dict` only | `interfaces.py:85` |
| `StrategicPlan` | ⚠️ `technology_choices["verification_framework"] = "pytest"` — a **framework name, not a command** | `strategic_engine.py:109` |
| `StrategicPlan.metadata` | ❌ free-form | `interfaces.py:141` |
| `ExecutableWorkflow` | ❌ no field; `loops[].input_data` is the only carrier | `interfaces.py:147` |
| `TaskDefinition` | ❌ no field; `input_data`/`metadata` free-form | `workflows/models.py:368-375` |
| `ExecutionContext` | ❌ no field; `input_data` carried | `context.py:31` |
| **`EngineeringLoop.run`** | ✅ **`verification_commands` parameter exists and is honoured** | `loop.py:102` |
| **`WorkforceWorker.execute_task`** | ✅ **reads `input_data["verification_commands"]`** | `workers.py:93` |
| `ProjectState.configuration` | ⚠️ free-form; **already carries `Request.configuration`** | `runtime_facade.py:103` |
| `CustomerProjectSpecification` | ❌ no field | `specification.py:225` |
| **`PowerEngineResult`** | ✅ **`verification_scorecard`** | `base.py:98` |
| **`PipelineResult`** | ✅ `transformation_records`, `gate_decisions`, wave results | `pipeline.py:92` |

**The `verification_framework` value (`"pytest"`, `strategic_engine.py:109`) is the closest thing to a first-class verification declaration that already exists — and it is a name, not a command.**

### 4.1 Ownership map

| Thing | Owner | Location |
|---|---|---|
| `input_data` | built by `KernelExecutionEngineAdapter`; owned by `TaskDefinition` | `kernel_adapters.py:297-327` |
| `TaskDefinition` | `autoforge_workflows.models` | `workflows/models.py:322` |
| `ExecutableWorkflow` | `autoforge_kernel.interfaces`; built by `KernelWorkflowEngineAdapter` | `interfaces.py:147` / `kernel_adapters.py:115` |
| `WorkspaceEnvironment` | `build_execution_engine`; **reused by the validation port** | `execution_wiring.py:145` / `composition_root.py:458` |
| `parse_test_output` | `autoforge_execution.evaluation` (unchanged) | `evaluation.py:25` |
| Validation definition | `EvaluationEngine.evaluate_attempt` | `evaluation.py:109` |
| Validation port (Kernel side) | `DefaultCompletionModule.validation_port` (interface only) | `completion.py:264,288` |
| Validation port (impl) | `WorkspaceValidationPort` | `validation_wiring.py:92` |
| Validation → Review | `_validation_review_context` + `review_project` | `completion.py:608` / `kernel_adapters.py:436` |
| Validation → Completion | `validation_truth["required"]` gate | `completion.py:695` |

---

## 7. The three options

### 7.1 Option A — Requester-declared verification

**Mechanism.** `Request.configuration["verification_command"]` (already read by `resolve_verification_command`, `validation_wiring.py:63`; accepted keys `verification_command` / `verify_command` / `test_command`) is propagated into `input_data["verification_commands"]`.

**Smallest propagation path** (three existing mechanisms, zero new abstractions):

```
Request.configuration["verification_command"]
  → already durable in ProjectState.configuration            ✓ works today
  → one new read at kernel_adapters.py:297                  ← the only new line
  → input_data["verification_commands"] = [["pytest","-q"]]
  → WorkforceWorker.execute_task reads it                   ✓ ALREADY READS IT
  → EngineeringLoop.run executes it                         ✓ ALREADY HONOURS IT
  → evaluate_attempt → real pass/fail
  → evaluation_report_iter_N.json carries real test_results
  → BOTH consumers (Review context + Completion gate) get real truth
```

**A second, independent consumer already exists and is broken:** the project-level port at `validation_wiring.py` reads the same declared command. **D-8b must be fixed regardless of the option chosen.**

**Precedent:** `apps/api/.../build_engine.py:880` runs `[sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"]` and parses the real output — the O-3 precedent for declared deterministic verification.

| | |
|---|---|
| ✅ | Smallest change; reuses 100% of existing machinery |
| ✅ | Deterministic, requester-controlled, auditable; no model-generated command ever executed |
| ⚠️ | **Opt-in** — a request that declares nothing still gets zero validation. This is exactly the greenfield gap |
| ⚠️ | The requester names an argv that AutoForge then executes — an arbitrary-command surface (§8) |

### 7.2 Option B — Auto-discovered verification

**Mechanism.** AutoForge infers the test command from the generated project (e.g. detect `pytest.ini` / `pyproject.toml` / `package.json` → emit a command).

**Repository evidence: NONE.** There is no discovery module, no project-metadata scanner for test frameworks, and no inference step anywhere on the canonical path.

> ### Classification: **NEW CAPABILITY**
> AutoForge currently **cannot** discover a verification command. Building it requires:
> - a project-metadata detector;
> - a framework → command mapping;
> - a decision about *which* project is authoritative (one greenfield run produced **15** `source_code` artifacts);
> - a policy for projects with **no** tests;
> - execution of **model-generated code** on the worker path.
>
> **Classified as a NEW CAPABILITY and NOT implemented, per §1 of the gate brief.**

| | |
|---|---|
| ✅ | Would close the greenfield gap without asking the requester for anything |

### 7.4 What happens when nothing applies (the undecided question)

| End-state | Rule | Consequence for 18-L |
|---|---|---|
| **G-1** | Validation is **mandatory**; if no command can be determined, completion **blocks** with an explicit "no verification contract" reason | Honest, but **the first greenfield run will fail until a contract exists** |
| **G-2** | Mandatory only when declared; absence produces a visible `unverified` state that still blocks `Finished` | Weaker, preserves throughput |
| **G-3** | Optional on the generic path | **18-L greenfield cannot be certified** — not a valid resolution |

**A silent pass is the current defect and is not an option under any of the three.**

---

## 8. Security / correctness implications

| Concern | Declared (L1) | Engine-declared (L2) | Discovered (L3) |
|---|---|---|---|
| Executes model-generated code | ❌ No | ❌ No | ⚠️ **Yes** |
| Arbitrary-command surface | ⚠️ Yes — requester names the argv | ✅ No — the engine owns it | ⚠️ Yes — inference decides |
| Mitigations already in place | `WorkspaceEnvironment.execute_command` enforces: workspace-confined `cwd` (`environment.py:71-95`), path-traversal rejection, null-byte rejection, argv type validation, process-group isolation + SIGTERM/SIGKILL on timeout (`environment.py:159-184`) | Same environment; the command is a first-party constant | Same environment, **but derived from generated content** |
| Recommended hardening | an argv allowlist / policy gate before execution | none needed | n/a |
| Determinism | ✅ explicit | ✅ explicit | ✅ deterministic algorithm, **model-generated input** |
| Bounded | ✅ `DEFAULT_TIMEOUT_SECONDS = 600` | ✅ | ✅ |

**L1 and L2 sit comfortably inside the existing, already-certified mitigations. L3 is a categorically different security conversation and must not be bundled with an 18-L repair.**

---

## 9. No implementation

**This document implements nothing.** No verification-command propagation, no discovery, and **no D-8b fix** was written. The D-8b defect is reported with a live reproduction because repairing it is implementation work that §1 of this gate forbids.

All probes were read-only and were written to `/tmp`, never to the repository. The working tree is byte-identical to the start of the gate: 34 `git status --porcelain` lines at start and at finish, HEAD `c72dad9` unchanged, nothing committed, nothing pushed.

**The validation seams are proven; the ownership contract is DECISION B and belongs to the human.**

| ✅ | Genuinely autonomous |
| ❌ | Materially new architecture |
| ❌ | **Executes model-generated code** — a categorically larger security surface (§8) |
| ❌ | Ambiguous when multiple projects exist |
| ❌ | **Must not be in scope for 18-L** |

### 7.3 Option C — Layered contract *(supported by repository evidence)*

**Mechanism.** Precedence: **declared → engine-declared → (future) discovered.**

**18-LR did not name this option. The repository supports it** (§5 is the evidence):

| Layer | Source of truth | Precedence | Status |
|---|---|---|---|
| **L1 — Requester-declared** | `Request.configuration["verification_command"]` | **authoritative when present** | exists; needs propagation + the D-8b fix |
| **L2 — Engine-declared** | `PowerEngineResult.verification_scorecard`; the deployment profile in `CustomerProjectSpecification`; the `scripts/test.sh` every commercial deliverable ships | authoritative **for that capability** | **exists today, unused by the platform** |
| **L3 — Discovered** | project-metadata inference | fallback only | **NEW CAPABILITY — future, not 18-L** |

**Why L2 is architecturally strong.** Each commercial engine already declares and performs its own deterministic verification inside its 11-stage lifecycle, and the shared delivery platform already ships a runnable test command to the customer. The platform does not need to *discover* anything for commercial deliverables — it needs to **carry the engine's existing scorecard into the canonical validation/review/completion chain**. That is a **transport obligation, not a new capability**.

| | |
|---|---|
| ✅ | Closes the *commercial* gap today with **zero** new capability |
| ✅ | Preserves every certified engine workflow exactly (engines are read, not modified) |
| ✅ | Keeps L1 authoritative when the requester speaks |
| ✅ | L3 explicitly deferred as a separate future capability |
| ✅ | Deterministic-First preserved — every layer is an explicit command, never a model judgement |
| ⚠️ | Three layers = three code paths to test |
| ⚠️ | Needs a precise precedence rule and a "who was authoritative" record in the evidence |
| ⚠️ | Needs a clear rule for when **no** layer applies (DECISION B) |


---

## 5. Existing commercial-engine validation contracts

**Every engine already validates deterministically. None of it reaches the platform.**

| Question | RAG | Agent | Automation | Migration | Modernization |
|---|---|---|---|---|---|
| Deterministic validation in its certified workflow? | ✅ | ✅ | ✅ | ✅ | ✅ |
| **How supplied?** | `_stage_verify` `engine.py:183` | `_stage_verify` `:177` | `_stage_verify` `:170` | `_stage_verify` `:290` | `TransformationEngine.apply` + `GateDecision` |
| Declared **before** execution? | ✅ spec + delivery profile | ✅ spec | ✅ spec | ✅ spec | ✅ `MigrationPlan` |
| Generated **by** the engine? | ✅ generates + runs `scripts/test.sh` | ✅ syntax + leak + test presence | ✅ | ✅ behavioural equivalence | ✅ |
| Generated by orchestration? | ❌ | ❌ | ❌ | ❌ | ❌ |
| Produced **after** artifact creation? | ✅ stage 6 follows stage 4 | ✅ | ✅ | ✅ | ✅ |
| **On failure?** | `defects` → `_stage_diagnose` → `_stage_repair` → `_stage_reverify`; `repair_count` | same | same | same | `PipelineStatus.FAILED` / `BLOCKED` |
| **How does final Review get the evidence?** | ❌ **IT DOESN'T** | ❌ | ❌ | ❌ | ❌ |

**This is the single most important input to DECISION B.** The engines do the right thing end-to-end *internally*; the platform discards the result. **For the commercial path, BLOCKER B is largely a transport gap, not a missing capability.**

---

## 6. The greenfield gap

| Question | Answer (traced) |
|---|---|
| Where does source generation succeed? | `EngineeringLoop.run` → AI adapter writes files into `WorkspaceEnvironment.root` (`loop.py:257-262`) |
| Where do source artifacts become durable? | `ArtifactPipeline` → `DurableArtifactCatalog.register_artifact` → `PhysicalArtifactStore` (staged write → SHA-256 → atomic publish → commit). **18-LR: 27/27 COMMITTED, 15 `source_code`** |
| Where is validation *supposed* to occur? | `loop.py:265-290` (per iteration) **and** `completion.py:475` (per project) |
| **Why is `verification_commands` empty?** | `kernel_adapters.py:297-327` never sets it; the fallback keys at `loop.py:110` are never set either. **One missing write.** |
| **Why can Review approve despite failing tests?** | (1) no command ran ⇒ `evaluate_attempt([])` ⇒ `INCONCLUSIVE`, `test_results: null`; (2) `review_project` builds `ReviewEvidence(test_results=None)`; (3) `_tests_pass(None) → True` — documented as *"absence is not a failure"* (`review/engine.py:66-67`); (4) the gate's `required` is `False` because the port found no command (**and would not have found it anyway — D-8b**) |
| **What contract must exist before greenfield can be certified?** | A rule determining, for every project, **which verification command applies** — and a rule for when **none** applies. That is DECISION B. |


### 3.3 Consequence

D-8 has **two** open edges, not one:

| Edge | Description | Status |
|---|---|---|
| **D-8 edge 1** (18-LR) | `input_data["verification_commands"]` is never populated ⇒ the loop runs zero commands | ❌ open |
| **D-8 edge 2 (D-8b, new)** | the port cannot read a declared command from production wiring ⇒ `required` is always `False` ⇒ the completion gate never applies | ❌ open |

**D-8b is independent of declared-vs-discovered.** Whichever option DECISION B selects, the port must be able to read project state or the deterministic gate stays inert. The probe shows the fix is bounded: make `_project_configuration` `async` and `await` the call (one call site, `validation_wiring.py:134`), or inject a synchronous reader.

**Per §1 of the gate brief this defect is REPORTED, NOT FIXED.** Repairing it is implementation.

### 3.4 An earlier mis-reading, corrected

An initial probe of this gate used `WorkerDispatcher.create_worker()` and reported that the canonical path builds a plain `EngineeringWorker`. That was **incorrect**: the canonical route is `WorkforceDispatcher.dispatch_task` (`dispatch.py:96`), which calls `create_specialized_worker` (`dispatch.py:134`) and yields `BackendEngineer`, a verified `WorkforceWorker` subclass that reads `input_data["verification_commands"]`. **The channel is live; it is simply never written to.** Recorded here for traceability.

### 2.1 Live proof that the reader is live (this gate, read-only probe)

```
DISPATCHER CLASS : WorkforceDispatcher
specialized_type selected : backend_engineer
WORKER CLASS dispatched   : BackendEngineer
BackendEngineer is WorkforceWorker subclass : True
BackendEngineer.execute_task defined in    : WorkforceWorker.execute_task
WorkforceWorker reads input_data['verification_commands'] : True

loop.run reads input_data['commands']      : True
loop.run reads input_data['test_commands'] : True
ExecutionContext.input_data : {'commands': [['pytest', '-q']]}
```

**Both channels carry `input_data` faithfully end to end. Nothing writes to them.**
