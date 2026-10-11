# PHASE 20-A — GATE 1 FORENSIC REPORT
## Canonical Customer Ingress Convergence
**Status:** Pre-Implementation Investigation Completed  
**Repository:** AutoForge AI-OS  
**Architecture:** Certified AutoForge Production Architecture  

---

## 1. Executive Summary

This forensic report investigates the end-to-end customer ingress integration seam identified in the Phase 20 audit.
Specifically, `apps/api/src/autoforge_api/service.py:execute_intent_pipeline` calls `self.system.kernel.submit_request(kernel_req)` but subsequently discards the Kernel result and unconditionally executes `generate_default_app(req.prompt)`. This synthesizes a greenfield calculator/todo Python application, runs a local pytest subprocess on that synthesized application, tarballs it into `dist/`, constructs a local synthetic `ExecutionOutcome(loop_type="coding")`, and returns it as `IntentExecutionResponse`.

Consequently, any customer request—specifically legacy modernization requests targeting `legacy_modernization`—has its canonical execution ignored and overwritten at the customer-facing boundary.

This gate (`Phase 20-A Gate 1`) repairs this seam without altering the certified production architecture, without introducing a second orchestrator or API-local loop, and in a strictly technology- and language-agnostic manner.

---

## 2. Current Call Graph

### Current Flow (Observed Defect):
```
Customer / HTTP Client
  ↓
POST /api/intent/execute (apps/api/src/autoforge_api/server.py:358)
  ↓
AutoForgeApiService.execute_intent_pipeline (apps/api/src/autoforge_api/service.py:2030)
  ↓
Request Construction:
  kernel_req = Request(
      user_id=...,
      request_text=req.prompt,
      configuration={
          "environment": "production",
          "execute": True,
          "stages": [...],
          "context": req.context,        <-- Nested, not elevated
          "project_id": proj_id
      }
  )
  ↓
self.system.kernel.submit_request(kernel_req) (service.py:2146)
  ↓ [try/except swallowing with fallback kernel_res = {"project_id": proj_id, "status": "created"}]
  ↓
[DISCONNECT & OVERWRITE SEAM (service.py:2153)]
  ↓
app_code, test_code, readme = generate_default_app(req.prompt)
  ↓
Write local app.py, test_app.py to workspace
  ↓
subprocess.run([sys.executable, "-m", "pytest", "test_app.py", ...])
  ↓
tarfile.open("dist/...tar.gz")
  ↓
outcome = ExecutionOutcome(status=COMPLETE if test_exit_code == 0 else FAILED, loop_type="coding", ...)
  ↓
IntentExecutionResponse(...) returned to Customer
```

---

## 3. Kernel Return Type & Execution Behavior

### A. What object/result does `Kernel.submit_request` return?
`packages/kernel/src/autoforge_kernel/kernel.py:submit_request(self, request: Request) -> dict[str, Any]` (lines 300–521):
- Return dictionary contract per Kernel Specification §6:
  ```python
  {
      "project_id": project_id,          # uuid.UUID
      "status": "created",               # Literal "created"
      "estimated_duration": float,
      "estimated_cost": float,
  }
  ```
- When `configuration["execute"] == True` (or `auto_execute`), `submit_request` awaits `self.execute_project(project_id)` at line 504.
- `execute_project` executes the full canonical orchestration lifecycle:
  1. `runtime_state_manager.transition_state(project_id, "running")`
  2. `orchestration_engine.orchestrate(project_id, executable_workflow)`
  3. `completion_module.validate_completion(project_id)`
  4. `completion_module.finalize_project(project_id)` (mandatory final review and deterministic validation quality gates)
- However, `submit_request` does not currently include the execution outcome or `finalize_result` in its return payload, and `service.py` did not inspect durable runtime state or the artifact catalog.

### B. Where does the result become an `ExecutionOutcome`?
In the canonical architecture, `ExecutionOutcome` is defined in `packages/composition/src/autoforge_composition/execution_outcome.py`:
- `KernelExecutionEngineAdapter.execute_loop` (`packages/composition/src/autoforge_composition/kernel_adapters.py:424-442`) produces a canonical loop result dict containing:
  ```python
  {
      "status": routed.status,              # "complete" | "remediate" | "escalate" | "failed"
      "loop_type": loop_type,
      "passed": routed.success,
      "artifacts": artifacts,               # Durable artifacts registered in catalog
      "findings": [...],
      "routed": True,
      "capability": capability,             # e.g., "legacy_modernization"
      "engine_class": routed.engine_class,  # e.g., "ModernizationPipeline"
      "verification_scorecard": routed.verification_scorecard,
      "summary_report": routed.summary_report,
      "error": routed.error_message,
  }
  ```
- `ExecutionOutcome.from_loop_result(loop_result)` normalizes this into the canonical `ExecutionOutcome` model with `OutcomeStatus` (`COMPLETE`, `REMEDIATE`, `ESCALATE`, `FAILED`).
- For routed capabilities, `KernelExecutionEngineAdapter._publish_routed_evidence` also registers the commercial verification scorecard as a durable artifact in the `DurableArtifactCatalog`.

### C. What is the actual canonical response/result contract?
- The internal canonical execution result is `ExecutionOutcome`.
- The customer-facing API response contract is `IntentExecutionResponse` (`apps/api/src/autoforge_api/models.py:668-682`):
  ```python
  class IntentExecutionResponse(BaseModel):
      execution_id: str
      project_id: str
      project_name: str
      status: str                           # "COMPLETED" | "FAILED" | "REMEDIATING" | "ESCALATED"
      stages: List[IntentStageInfo]
      activities: List[AgentActivityItem]
      summary: str
      artifacts: List[Dict[str, Any]]
      output_preview: Dict[str, Any]
      tech_stack: Optional[TechStackProposal] = None
      build_metrics: Optional[BuildMetricsInfo] = None
      toolchains: List[PackagingToolchainInfo] = Field(default_factory=list)
      sandbox: Optional[SandboxInfo] = None
  ```
- The translation boundary from `ExecutionOutcome` to `IntentExecutionResponse` must be a pure adapter at the API layer that preserves the canonical status and evidence without rewriting outcomes.

---

## 4. Fallback Behavior Analysis

### D. Where is `generate_default_app()` currently invoked?
`apps/api/src/autoforge_api/service.py:2153` inside `execute_intent_pipeline`.

### E. Why does that fallback exist?
`generate_default_app()` was implemented early in API/UI development (`apps/api/src/autoforge_api/generator.py`) to provide instantaneous, deterministic greenfield Python applications (such as a calculator or todo app) for interactive web UI testing before full platform convergence.

### F. Is it still required for any legitimate non-modernization API behavior?
Yes. For generic greenfield application build requests where no commercial power engine or capability is targeted and where the generic loop is unconfigured, retaining it as an unrouted greenfield fallback prevents regressions in early UI demo workflows.

### G. Can it be retained behind a legitimate existing capability path without interfering with canonical execution?
Yes. It can remain strictly scoped as a fallback for unrouted default greenfield application synthesis when no capability has been executed and no canonical execution outcome exists. It must NEVER execute when a capability request is present, nor when canonical execution has produced an `ExecutionOutcome`.

### H. How should the API distinguish execution states?
The API boundary must map canonical outcomes faithfully:
- **`OutcomeStatus.COMPLETE` / Passed**: Status `COMPLETED`, summary from canonical execution / review.
- **`OutcomeStatus.REMEDIATE`**: Status `REMEDIATING`, report failure findings without converting to success.
- **`OutcomeStatus.ESCALATE`**: Status `ESCALATED`, report escalation reason.
- **`OutcomeStatus.FAILED`**: Status `FAILED`, report failure details / scorecard error.
- **Unsupported Capability**: Fails closed with `FAILED` (HTTP 400 or explicit failure response) indicating unknown capability.
- **Security Rejection**: Fails closed (HTTP 401/403 or unauthorized error).
- **Validation / Final Review Rejection**: Status `FAILED`, reason from `finalize_result["error"]` / review findings.

---

## 5. Affected Files & Smallest Safe Implementation Seam

1. **`apps/api/src/autoforge_api/service.py` (`execute_intent_pipeline`)**:
   - Elevate configuration parameters (`req.context` keys including `capability`, `legacy_source_root`, etc.) into `kernel_req.configuration` so `read_capability` resolves them natively from durable state.
   - Detect capability routing from `req.context.get("capability")` or `normalize_capability(req.intent_type)` in a language-agnostic manner.
   - Execute `self.system.kernel.submit_request(kernel_req)` canonically.
   - Extract the canonical `ExecutionOutcome` (from the Kernel execution result, active project info, or durable state/artifacts).
   - If canonical execution executed (or a capability request was specified):
     - Translate the canonical `ExecutionOutcome` and durable artifacts directly into `IntentExecutionResponse`.
     - DO NOT call `generate_default_app()`.
     - DO NOT run synthetic pytest.
     - Return the canonical result directly.
   - If and only if it is an unrouted default application build with no capability and no canonical execution: retain `generate_default_app()` as the greenfield fallback.

2. **`packages/kernel/src/autoforge_kernel/kernel.py` (`submit_request` & `execute_project`)**:
   - Ensure `execute_project` records and returns the canonical `finalize_result` and execution outcome.
   - Ensure `submit_request` returns `execution_result` in its return dictionary while strictly preserving `status: "created"` for Kernel Specification §6 compatibility.
   - Ensure `active_projects[project_id]` captures the execution result and canonical outcome.

3. **`apps/api/tests/test_phase20_a_gate1_ingress.py`**:
   - Implement TESTS 1 through 9 verifying:
     - Canonical API → Kernel delegation.
     - AST guards against API-local orchestrator instantiation.
     - Canonical result propagation (outcome -> API response).
     - No synthetic overwrite when capability / canonical execution is present.
     - Failure propagation (canonical failed -> API failed).
     - Remediation / escalation state preservation.
     - Capability neutrality (AST checks: zero language-specific keywords like `COBOL`, `Java`, `JCL`).
     - Orchestration Engine authority.
     - Preservation of existing greenfield fallback behavior for unrouted default prompts.

---

## 6. Architecture Invariants That Must Remain True

1. **Frozen Architecture**: No new orchestrator, no second lifecycle controller, no workflow replacement.
2. **Naming**: The canonical orchestrator is the `Orchestration Engine`.
3. **Language/Technology Agnostic**: API ingress and capability routing MUST NOT branch on `COBOL`, `Java`, `JCL`, `CardDemo`, etc. Routing is strictly capability-based (`legacy_modernization`).
4. **ExecutionOutcome Canonical**: `ExecutionOutcome` remains the platform's canonical execution result model.
5. **No AI Infrastructure Modifications**: Model Router, Context Engineering, and Compaction remain untouched. M1 and HP remain strictly inactive.
6. **No Premature Modernization Rewiring**: The modernization engine internals are NOT touched in Gate 1.
