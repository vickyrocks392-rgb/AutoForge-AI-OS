# AutoForge AI — Execution Platform (Phase 10)

The **Execution Platform** is the autonomous engineering execution substrate of AutoForge AI OS. It executes actual engineering work dispatched by the Workflow Platform (Phase 9), running workers in sandboxed workspace environments through bounded autonomous engineering loops.

---

## 1. Architectural Role

The Execution Platform transforms abstract tasks into verified code and artifacts:

```
Workflow Engine (Phase 9)
    │
    │ (Dispatches eligible tasks)
    ▼
Worker Dispatcher (Phase 10)
    │
    ▼
Engineering Worker (CREATED → READY → RUNNING → COMPLETED / FAILED / WAITING_APPROVAL)
    │
    ▼
Engineering Loop
    │
    ├── 1. UNDERSTAND & PLAN (AI Infrastructure)
    ├── 2. IMPLEMENT (WorkspaceFilesystem & Git connectors)
    ├── 3. EXECUTE & TEST (Controlled subprocess runner)
    ├── 4. EVALUATE (Deterministic-First verification)
    └── 5. DIAGNOSE & REPAIR (Informed recovery if failed)
            │
            └── (Retest until PASS or bounded limit)
    │
    ▼
Artifact Pipeline (Provenance, Diffs, Test Reports, Execution Logs)
    │
    ▼
Outcome Report -> Workflow Platform & Runtime State Manager
```

---

## 2. Key Modules & Subsystems

| Module | Responsibility |
|---|---|
| `engine.py` | `ExecutionEngine` — Central facade coordinating dispatcher, workers, loops, workflow engine, runtime, and events. |
| `worker.py` | `EngineeringWorker` — Manages worker lifecycle (`CREATED`, `READY`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `WAITING_APPROVAL`). |
| `dispatcher.py` | `WorkerDispatcher` — Enforces concurrency limits and dispatches workflow `QueueEntry` tasks. |
| `environment.py` | `WorkspaceEnvironment` — Confined workspace path resolution, explicit `argv` execution, timeout enforcement, process group cleanup (`SIGTERM`/`SIGKILL`). |
| `context.py` | `ExecutionContext` — Context assembly integrating task inputs, project files, and attempt history (ADR-003). |
| `ai_adapter.py` | `AIEngineeringProvider` & `AIInfrastructureAdapter` — Provider-neutral AI reasoning using ModelRouter / ExecutionContinuityService. |
| `evaluation.py` | `EvaluationEngine` — Deterministic-first verification of exit codes, test outputs (pytest/unittest), and check rules. |
| `diagnosis.py` | `FailureDiagnoser` — Assembly of failure evidence and AI-assisted root-cause diagnosis. |
| `loop.py` | `EngineeringLoop` — Bounded autonomous engineering loop with repair and reimplementation cycles. |
| `artifacts.py` | `ArtifactPipeline` — Captures diffs, execution logs, reports, and rich provenance metadata. |
| `governance.py` | `ExecutionGovernance` — HITL gating for consequential actions (tech stack finalization, git push, deployment). |
| `events.py` | `ExecutionEvents` — Canonical event emission (`execution.*`, `loop.*`, `artifact.*`). |
| `recovery.py` | `ExecutionRecovery` — Checkpoint snapshot and restore for worker states. |
| `errors.py` | Machine-readable error taxonomy rooted at `ExecutionError`. |
| `models.py` | Pydantic and dataclass value objects and execution state models. |

---

## 3. Core Principles

1. **Real Execution** — Subprocess commands run inside a real workspace environment with full output capture and timeout protection.
2. **Deterministic-First** — Exit codes and test runner results strictly determine evaluation outcomes; AI confidence never overrides deterministic failures.
3. **Informed Autonomous Repair** — When a test fails, `FailureDiagnoser` analyzes exact stdout/stderr/stack traces so attempt $N$ is informed by attempt $N-1$, rather than blindly retrying.
4. **HITL Governance at Consequential Boundaries** — Routine loop iterations proceed autonomously, while consequential actions (e.g. tech stack finalization, git push, deployment) pause at approval gates.
5. **No Distributed Infrastructure** — In-process, lightweight, and dependency-inverted.

---

## 4. Verification

* **37 Phase 10 tests** covering models, environment, worker lifecycle, dispatcher, evaluation, diagnosis, artifacts, governance, recovery, and engine coordination.
* **Real E2E Engineering Loop Acceptance Test** (`test_real_autonomous_engineering_loop_e2e`) verifying real file creation, initial failing test execution, root-cause diagnosis, repair generation, and passing retest.
* **100% Green Test Suite** across all repository packages with zero regressions.