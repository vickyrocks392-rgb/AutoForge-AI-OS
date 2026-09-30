# 18-LE — VALIDATION TRANSPORT IMPLEMENTATION

Implements **DECISION B** (layered contract) and repairs **D-8b**.

---

## 1. D-8b — the proven async/sync defect

### Root cause

```python
# validation_wiring.py:119 (pre-repair)
def _project_configuration(self, project_id):
    state = self._runtime.get_project_state(project_id)   # ← async method, not awaited
    if not isinstance(state, dict):      # a coroutine is NOT a dict
        return {}
    return state.get("configuration") or {}
```

The composition root wires `runtime_state_manager=facade`
(`composition_root.py:457-460`), and `KernelRuntimeFacade.get_project_state` is
declared `async def` (`runtime_facade.py:150`). The call returned an **un-awaited
coroutine**, so `isinstance(state, dict)` was `False` and the method returned
`{}` **for every project**.

**Consequence:** `validate_project` reported `required: False` even when the
project had explicitly declared a verification command, so the D-8 deterministic
completion gate was **inert in production**. The repository's own test run already
emitted `RuntimeWarning: coroutine 'KernelRuntimeFacade.get_project_state' was
never awaited` at `validation_wiring.py:134`.

### Live reproduction (before the fix)

```
WIRED RUNTIME TYPE             : KernelRuntimeFacade
get_project_state is coroutine : True

ProjectState.configuration     : {'configuration': {..., 'verification_command':
                                  "python -c \"print('ok')\""}}
resolve_verification_command() : ['python', '-c', "print('ok')"]     ← reader works

validate_project(REAL project that DOES declare a command):
    {"required": false, "performed": false, "passed": true,
     "reason": "Project declares no verification command.", "command": null}
```

### The repair

```python
async def _project_configuration(self, project_id):
    state = self._runtime.get_project_state(project_id)
    if inspect.isawaitable(state):
        state = await state          # ← the fix: the existing async architecture
```
…and the single call site now awaits it.

### What was deliberately NOT done

| Prohibited | Status |
|---|---|
| Make the facade synchronous globally | **Not done** — only this one call site awaits |
| Create a second project-state API | **Not done** — the existing `get_project_state` is reused |
| Introduce a new state model | **Not done** |
| Alter 18-J / 18-K | **Not done** — neither was touched |
| Alter validation semantics beyond retrieving state | **Not done** — resolver, keys, precedence and result shape unchanged |

A **synchronous** reader is still accepted so a caller owning a non-async store
keeps working. That is a compatibility accommodation, **not** a second authority.

### Post-fix proof (same probe)

```
validate_project(REAL project that DOES declare a command):
    {"required": true, "performed": true, "passed": true,
     "command": ["python", "-c", "print('ok')"]}
```

---

## 2. Layer 1 — requester-declared verification transport

### The single missing write

18-LD proved the downstream chain already existed and was **live but fed by
nothing**:

| Stage | Location | State before this gate |
|---|---|---|
| `WorkforceWorker.execute_task` reads `input_data["verification_commands"]` | `workforce/workers.py:93` | ✅ live reader |
| `EngineeringLoop.run` honours the parameter | `execution/loop.py:102` | ✅ live reader |
| …and honours `input_data["commands"]` / `["test_commands"]` | `execution/loop.py:110` | ✅ live reader |
| **The write that fed them** | `kernel_adapters.py:297-327` | ❌ **MISSING** |

### The transport

```
Request.configuration["verification_command"]
  → durable in ProjectState.configuration            (already worked)
  → read at execute_loop                             ← THE ADDED WRITE
  → input_data["verification_commands"] = [[argv…]]
  → WorkforceWorker.execute_task                      (already read it)
  → EngineeringLoop.run                                (already honoured it)
  → WorkspaceEnvironment.execute_command               (real subprocess)
  → EvaluationEngine.evaluate_attempt + parse_test_output
  → evaluation_report_iter_N.json                      (durable)
  → review evidence → final Review
  → Completion gate: required and not passed → BLOCK
```

**The command is read with the SAME existing resolver the completion gate uses**
(`resolve_verification_command`), so the loop and the gate can never disagree.

**Applied after** the pre-existing DEF-18L-03 fallback, so a fallback-created input
mapping cannot discard the declaration. `input_data` is copied, never mutated, and

---

## 3. Layer 2 — engine-declared verification, preserved and transported

DECISION B requires the engine's own deterministic verification to reach canonical
validation/review/completion rather than being replaced by a second authority.

| Engine | Mechanism (existing) | Transport |
|---|---|---|
| RAG | `_stage_verify` → `run_customer_tests()` (real `unittest discover` subprocess) + grounding | `verification_scorecard` |
| Agent | `_stage_verify` → `ast.parse` + proprietary-leak + test-file presence | `verification_scorecard` |
| Automation | `_stage_verify` → same class of deterministic checks | `verification_scorecard` |
| Migration | `_stage_verify` → behavioural equivalence per unit | `verification_scorecard` |
| Modernization | `TransformationRecord`s + `GateDecision` | normalised `verification_scorecard` |

**How it reaches the canonical path:** the routed result's scorecard is published
as a **durable `test_report` artifact** through the existing `ArtifactPipeline` →
`DurableArtifactCatalog` → `PhysicalArtifactStore`, so it appears in the ordinary
final-review evidence set. Observed in the architecture trace:

```
review_evidence_names: [
  "commercial_verification_custom_ai_agent_task-arch-….json",
  "commercial_verification_custom_ai_agent_task-code-….json",
  "commercial_verification_custom_ai_agent_task-qa-….json",
  "commercial_verification_custom_ai_agent_task-review-….json" ]
```

**No second validation authority was created.** The engine's evidence is
*evidence*; the single enforcement authority remains the D-8 completion gate.

---

## 4. Layer 3 — autonomous discovery: NOT implemented

Explicitly out of scope per DECISION B and §10. No discovery module, no framework
inference, and no model-generated verification command exists in this gate.

---

## 5. D-8 safety matrix (§15) — all cases proven

`packages/composition/tests/test_d8_safety_matrix.py` — **10 passed**.

| Case | Scenario | Proved result |
|---|---|---|
| **A** | verification exists + tests pass | `required=True, passed=True` ⇒ completion allowed |
| **B** | verification exists + tests fail | `required=True, passed=False` ⇒ completion **BLOCKED** |
| **C** | verification missing where mandatory | `required=False, performed=False` and explicitly *"no verification command"* — never readable as success |
| **D** | Review **APPROVED** + validation **FAILED** | review approves, deterministic gate **BLOCKS** |
| **E** | Review **REJECTED** + validation **PASSED** | review blocks regardless of validation |

Plus a parameterised check that an unreadable verdict (`None`, `{}`,
`{"decision": "approved"}`, `1`, `"yes"`) is **never** an approval.

**Case D proven twice.** Beyond the unit test, a real greenfield run whose
generated tests genuinely failed was blocked in production:

```
generated test asserted char_count('hello\nworld\t') == 11   (actually 12)
→ cmd_python_iter_*.log: FAILED ... 1 failed
→ evaluation_report: status failed, deterministic_checks: [exit_code != 0]
→ validation: required=True, passed=False, exit_code=1
→ final_state: ProjectStatus.COMPLETING     ← never reached FINISHED
```

This is the **precise 18-L failure inverted**: previously a project whose tests
failed reached `FINISHED` with an `APPROVED` review. Now it is blocked.

---

## 6. Regression tests

| Suite | Count | Covers |
|---|---|---|
| `test_d8b_validation_transport.py` | **12** | declared ⇒ `required=True`; absent ⇒ `required=False`; failing command reported as failure; **no `never awaited` warning**; read through the canonical async facade; sync reader supported; resolver unchanged |
| `test_d8_safety_matrix.py` | **10** | cases A–E + malformed verdicts |
| `test_capability_routing.py` (transport slice) | 2 | declared verification reaches the `TaskDefinition`; absence leaves input untouched |

The pre-existing 18-LR gate suite `test_completion_gates_18lr.py` (**20 passed**)
and the D-8 E2E suite `test_final_review_evidence_e2e.py` (**9 passed**) remain
green — the repair strengthened a live contract without weakening any assertion.

returned unchanged when nothing is declared. An explicit, more specific
declaration already on the loop is never overwritten.

### Live proof (fresh greenfield run)

```
artifacts/cmd_python_iter_1.log          ← the command actually ran inside the loop
   STDOUT: ..  [100%]  2 passed in 0.00s
   EXIT_CODE: 0

artifacts/evaluation_report_iter_1.json  ← real deterministic truth
   status: passed, deterministic_checks: [...], test_results: {...}
```

**Before the repair these artifacts did not exist** and the report read
`"status": "inconclusive", "test_results": null, "deterministic_checks": []` — the
exact 18-L / 18-LD gap.
