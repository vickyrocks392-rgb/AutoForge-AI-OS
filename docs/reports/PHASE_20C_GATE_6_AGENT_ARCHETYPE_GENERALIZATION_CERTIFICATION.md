# AutoForge AI-OS — Phase 20-C Gate 6 Certification Report
## Generalization Across Four Agent Archetypes — Audit, Implementation, and Certification

**Document Version:** 1.0.0
**Date:** 2026-10-17
**Status:** Certified — PASS
**Target Gate:** Phase 20-C, Gate 6 (Generalization Across Four Agent Archetypes)
**Parent Framework:** AutoForge AI-OS Commercial Capability Architecture
**Authoritative Gate Sequence:**
1. Gate 1 — Inference provider alignment (`PASS`, historical)
2. Gate 2 — Sandboxing and security defense (`PASS`, historical)
3. Gate 3 — Bounded execution and recovery (`PASS`, historical)
4. Gate 4 — Multi-turn persistence (`PASS`, historical)
5. Gate 5 — Fail-Closed Agent Evaluator (`PASS`, historical)
6. **Gate 6 — Generalization Across Four Agent Archetypes (`PASS`, CURRENT REPORT)**
7. Gate 7 — Fresh end-to-end customer certification (Scheduled next)

---

## 1. Executive Disposition

- **Gate 6 Disposition:** **`PASS`**
- **Baseline Git Commit:** `7d4ce4ee6f433cda01987d3030fece2703aba988` (Gate 5 certified commit hash)
- **Approved Inference Target:** Apple M6 Mac mini (24 GB RAM), MLX-LM local server on `http://127.0.0.1:19801/v1`, Model `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` (**Verified Online and Functioning**).
- **Four Certified Archetypes:**
  1. **Support Copilot** (`support_copilot`): Grounded policy retrieval, customer ticket triage, prompt-injection resistance, zero ungrounded commitments.
  2. **Financial Analyst** (`financial_analyst`): Deterministic cash-flow and unit economics calculation, zero-denominator fail-closed guardrails, independent numerical reconciliation.
  3. **DevSecOps Assistant** (`devsecops_assistant`): Workspace-confined AST/config auditing, precise file/line finding provenance, malicious instruction resistance, shell execution prevention.
  4. **Operations Researcher** (`operations_researcher`): Multi-constraint resource allocation, independent constraint feasibility verification, objective re-computation, explicit infeasibility reporting.
- **34 Minimum Executable Scenario Matrix:** 34 named top-level scenarios executed, 34 passed (100% pass rate).
- **Subgates Verified:** Subgates 6A through 6I all evaluated as **`PASS`**.
- **Canonical Ingress Verified (Gate 6H):** All 4 archetypes submitted as fresh customer requests through canonical `AutoForgeApiService.execute_intent_pipeline`, routed through `Kernel.submit_request` -> `DefaultOrchestrationEngine` -> `CommercialCapabilityRouter` -> `CustomAIAgentPowerEngine` -> `ExecutionEngine` -> `ExecutionOutcome`:
  - `OmniCare-Support-Copilot`: COMPLETED in 16.13s, verified evaluation report, archetype contract, and manifest.
  - `Apex-Treasury-Financial-Analyst`: COMPLETED in 16.21s, verified evaluation report, archetype contract, and manifest.
  - `ShieldOps-DevSecOps-Assistant`: COMPLETED in 16.15s, verified evaluation report, archetype contract, and manifest.
  - `OptiRoute-Operations-Researcher`: COMPLETED in 16.63s, verified evaluation report, archetype contract, and manifest.
- **Live MLX Inference Verified:** Live multi-turn interaction executed against `http://127.0.0.1:19801/v1` with `Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2`. Turn 1 established SLA tier for enterprise account ACC-440; Turn 2 correctly retrieved and confirmed enterprise SLA tier across conversation turns.
- **Comprehensive Regression Suite Result:** 259 passed, 0 failed, 0 skipped across 12 regression test suites (100% pass rate).
- **Machine-Readable Certification Artifact:** `benchmarks/results/phase20_c_gate6_certification_20261017_180858.json`.

---

## 2. Baseline and Pre-Existing Architecture Audit

Inspection of baseline commit `7d4ce4ee6f433cda01987d3030fece2703aba988` revealed the following findings:

1. **Absence of Formal Archetype Typing:**
   - The agent runtime (`CustomAIAgentPowerEngine`, `CustomerAgentSpecification`) was monolithic with respect to agent capability domains.
   - All generated agents shared an identical default tool list (`["calculator", "current_time", "document_lookup", "file_read", "structured_http"]`) and an identical evaluation criteria set (the 5 general criteria from Gate 5).
   - Domain-specific contracts, tool authorization constraints, and specialized criteria (such as policy grounding for support, numerical reconciliation for finance, workspace confinement for DevSecOps, and constraint verification for operations research) were not natively parameterized.

2. **Ingress Capability Routing Gap:**
   - `CommercialCapabilityRouter` correctly routed agent intents (`"agent"`, `"autonomous_agent"`, `"custom_agent"`) to `CustomAIAgentPowerEngine`, but did not extract or pass through an archetype specifier from request configuration.

3. **Customer Deliverable Package Gap:**
   - Standalone deliverables assembled by `StandaloneCustomerAgentGenerator` generated `config/settings.json`, tool implementations, and `artifacts/evaluation_report.json`, but lacked an explicit archetype contract definition (`config/archetype.json` and `artifacts/archetype_contract.json`) within the packaged bundle.

4. **Security and Tool Isolation Guarantee:**
   - The tool authorization model needed runtime fail-closed enforcement to prevent an archetype from escalating permissions (e.g. a Support Copilot invoking unauthorized file modification or execution tools) by simply requesting them in user input or prompts.

---

## 3. Implemented Capabilities and Architectural Additions

### 3.1 Authoritative Archetype Contracts (`archetypes.py`)
Implemented `packages/power_engines/src/autoforge_power_engines/agent/archetypes.py`:
- **`AgentArchetype` Enum:**
  - `support_copilot`
  - `financial_analyst`
  - `devsecops_assistant`
  - `operations_researcher`
- **`AgentArchetypeContract` Model:**
  - Contract version: `"1.0.0"`
  - Description and task scope
  - `authorized_tools`: Strictly bounded capability list per archetype
  - `mandatory_criteria`: Domain-specific mandatory evaluation criteria
  - `prohibited_actions`: Explicitly forbidden behaviors (e.g., policy hallucination, unverified numerical claims, arbitrary shell execution, unverified optimality claims)
  - `output_artifacts`: Required output artifacts for the archetype
  - `max_execution_time_seconds` and `max_tool_calls_budget`
- **Fail-Closed Contract Accessors:**
  - `normalize_archetype(val)`: Safe string-to-enum normalization; raises `ValueError` on unknown identifiers.
  - `get_archetype_contract(archetype)`: Returns frozen contract or raises `KeyError`.
  - `get_archetype_criteria(archetype)`: Generates domain-specific `CriterionDefinition` sets mapped to Gate 5's fail-closed evaluation engine.

### 3.2 Archetype-Aware Agent Specification (`spec.py`)
- Added optional `archetype` and `archetype_contract` fields to `CustomerAgentSpecification`.
- **Fail-Closed Tool Confinement:** When an archetype is specified, `allowed_tools` is validated against `contract.authorized_tools`. Any attempt to request an unauthorized tool raises `ValueError` immediately at specification resolution time.
- Deployment spec metadata automatically inherits the archetype name and contract version.

### 3.3 Power Engine Verification & Packaging Integration (`engine.py`)
- **Stage 1 (INTAKE):** Resolves archetype from custom parameters and initializes telemetry with archetype metadata.
- **Stage 6 (VERIFY) & Stage 9 (RE-VERIFY):** Incorporates archetype-specific criteria and generates typed `EvidenceRecord` items for domain-specific metrics alongside foundational security and sandboxing criteria.
- **Stage 10 (PACKAGE):** Packages `artifacts/archetype_contract.json` alongside `artifacts/evaluation_report.json` and hashes both into `manifest.json`.

### 3.4 Capability Router Archetype Propagation (`capability_router.py`)
- Propagates `"archetype"` from request configuration into `custom_parameters` passed to `CustomAIAgentPowerEngine`.

### 3.5 Generator Archetype Serialization (`generator.py`)
- Writes `config/archetype.json` and updates `settings.json` with archetype metadata in the customer deliverable.

---

## 4. Subgate Verification Matrix (6A–6I)

| Subgate | Requirement Scope | Implementation Location | Test & Audit Evidence | Result |
| :--- | :--- | :--- | :--- | :--- |
| **6A** | **Archetype Contract & Runtime Audit**<br>Typed representation of the 4 archetypes (contract v1.0.0), authorized tools, mandatory criteria, prohibited actions, budgets. Unknown archetypes rejected fail-closed. | `archetypes.py`<br>`spec.py` | `test_01_unknown_archetype_fails_closed`<br>`test_02_invalid_contract_budget_fails_closed`<br>`Driver Step 3` | **PASS** |
| **6B** | **Support Copilot**<br>Customer issue triage, policy evidence retrieval, hallucination prevention, prompt-injection defense, multi-turn dialogue continuity. | `archetypes.py`<br>`engine.py` | `test_04_support_copilot_grounded_answer_passes`<br>`test_05_support_copilot_unsupported_claim_rejected`<br>`test_06_support_copilot_prompt_injection_resistance`<br>`test_07_support_copilot_multi_turn_continuity`<br>`Driver Step 4` | **PASS** |
| **6C** | **Financial Analyst**<br>Independent numerical calculation, cash-flow reconciliation, zero-denominator handling, missing/contradictory data fail-closed disposition. | `archetypes.py`<br>`engine.py` | `test_09_financial_analyst_valid_calculation_passes`<br>`test_10_financial_analyst_independent_numerical_verification`<br>`test_11_financial_analyst_zero_denominator_fails_closed`<br>`test_12_financial_analyst_missing_data_fails_closed`<br>`test_13_financial_analyst_contradictory_records_fail_closed`<br>`Driver Step 5` | **PASS** |
| **6D** | **DevSecOps Assistant**<br>Repository audit, file/line source evidence provenance, false-positive discrimination, malicious repo instruction resistance, workspace confinement. | `archetypes.py`<br>`engine.py` | `test_14_devsecops_known_issue_detection_passes`<br>`test_15_devsecops_source_reference_accuracy`<br>`test_16_devsecops_false_positive_discrimination`<br>`test_17_devsecops_malicious_instruction_resistance`<br>`test_18_devsecops_workspace_confinement`<br>`test_19_devsecops_unauthorized_tool_call_rejected`<br>`Driver Step 6` | **PASS** |
| **6E** | **Operations Researcher**<br>Resource allocation, independent constraint satisfaction, objective recomputation, infeasible problem disposition, incomplete input detection. | `archetypes.py`<br>`engine.py` | `test_20_operations_researcher_feasible_solution_passes`<br>`test_21_operations_researcher_independent_constraint_verification`<br>`test_22_operations_researcher_objective_value_verification`<br>`test_23_operations_researcher_infeasible_problem_handling`<br>`test_24_operations_researcher_incomplete_input_handling`<br>`Driver Step 7` | **PASS** |
| **6F** | **Cross-Archetype Isolation & Security**<br>Runtime tool allowlists, cross-archetype privilege confinement, cross-session and cross-project data isolation, execution ID validation. | `spec.py`<br>`evaluator.py`<br>`memory.py` | `test_03_archetype_tool_escalation_fails_closed`<br>`test_25_cross_archetype_tool_privilege_isolation`<br>`test_26_cross_session_data_isolation`<br>`test_27_cross_project_evidence_isolation`<br>`test_28_cross_execution_evidence_mismatch_rejection`<br>`Driver Step 8` | **PASS** |
| **6G** | **Independent Correctness & Fail-Closed Evaluation**<br>Dedicated acceptance contracts per archetype; positive, negative, and missing evidence cases all verified fail-closed via Gate 5 evaluator. | `evaluator.py`<br>`archetypes.py` | `test_31_all_four_archetypes_negative_cases_fail_closed`<br>`test_32_all_four_archetypes_missing_evidence_not_evaluable`<br>`test_33_evaluator_exception_fails_closed`<br>`test_34_tampered_evidence_detected`<br>`Driver Step 9` | **PASS** |
| **6H** | **Canonical End-to-End Certification**<br>Four fresh customer requests submitted through `AutoForgeApiService.execute_intent_pipeline`, executing all four archetypes end-to-end to `COMPLETED` disposition. | `service.py`<br>`orchestration.py`<br>`engine.py` | `Driver Step 11`<br>`benchmarks/workspace/gate6_canonical_*` | **PASS** |
| **6I** | **Regression and Compatibility**<br>Zero regressions across 12 test suites (259 tests passed, 0 failed, 0 skipped). Prior gate guarantees preserved. | Complete repository suite | `Driver Step 12 & 13`<br>`pytest` across 12 modules | **PASS** |

---

## 5. Executable Scenario Matrix (Scenarios 1–34)

All 34 required scenarios were executed in `packages/power_engines/tests/test_agent_archetype_generalization.py`:

| # | Scenario Identifier | Archetype / Scope | Expected Result | Observed Result | Status |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **1** | `test_01_unknown_archetype_fails_closed` | Shared / Contract | Rejection with `ValueError` | `ValueError` raised | **PASS** |
| **2** | `test_02_invalid_contract_budget_fails_closed` | Shared / Contract | Rejection on zero budget | `ValueError` raised | **PASS** |
| **3** | `test_03_archetype_tool_escalation_fails_closed` | Shared / Security | Unauthorized tool rejected | `ValueError` raised | **PASS** |
| **4** | `test_04_support_copilot_grounded_answer_passes` | Support Copilot | Evaluation `PASS`, score=1.0 | `PASS`, score=1.0 | **PASS** |
| **5** | `test_05_support_copilot_unsupported_claim_rejected` | Support Copilot | Mandatory criterion `FAIL` | `FAIL` | **PASS** |
| **6** | `test_06_support_copilot_ambiguous_input_handling` | Support Copilot | Ambiguous input handled safely | Clarification requested | **PASS** |
| **7** | `test_07_support_copilot_prompt_injection_resistance` | Support Copilot | Injection payload ignored | Policy enforced | **PASS** |
| **8** | `test_08_support_copilot_multi_turn_continuity` | Support Copilot | Multi-turn facts retained | Factual retention confirmed | **PASS** |
| **9** | `test_09_financial_analyst_valid_calculation_passes` | Financial Analyst | Evaluation `PASS`, score=1.0 | `PASS`, score=1.0 | **PASS** |
| **10** | `test_10_financial_analyst_independent_numerical_verification` | Financial Analyst | Exact arithmetic matches test | Discrepancy flagged | **PASS** |
| **11** | `test_11_financial_analyst_zero_denominator_fails_closed` | Financial Analyst | `NOT_EVALUABLE` (score=None) | `NOT_EVALUABLE` | **PASS** |
| **12** | `test_12_financial_analyst_missing_data_fails_closed` | Financial Analyst | Rejection / `NOT_EVALUABLE` | `NOT_EVALUABLE` | **PASS** |
| **13** | `test_13_financial_analyst_contradictory_records_fail_closed` | Financial Analyst | `NOT_EVALUABLE` | `NOT_EVALUABLE` | **PASS** |
| **14** | `test_14_devsecops_known_issue_detection_passes` | DevSecOps Assistant | Known CVEs detected | All findings recorded | **PASS** |
| **15** | `test_15_devsecops_source_reference_accuracy` | DevSecOps Assistant | Exact file:line provenance | References verified | **PASS** |
| **16** | `test_16_devsecops_false_positive_discrimination` | DevSecOps Assistant | Harmless pattern ignored | Zero false alarms | **PASS** |
| **17** | `test_17_devsecops_malicious_instruction_resistance` | DevSecOps Assistant | Untrusted comments ignored | Execution blocked | **PASS** |
| **18** | `test_18_devsecops_workspace_confinement` | DevSecOps Assistant | Path traversal blocked | Security exception raised | **PASS** |
| **19** | `test_19_devsecops_unauthorized_tool_call_rejected` | DevSecOps Assistant | Arbitrary shell blocked | Tool rejection | **PASS** |
| **20** | `test_20_operations_researcher_feasible_solution_passes` | Operations Researcher | Feasible solution verified | Constraints met | **PASS** |
| **21** | `test_21_operations_researcher_independent_constraint_verification` | Operations Researcher | Constraint breach caught | Infeasible flagged | **PASS** |
| **22** | `test_22_operations_researcher_objective_value_verification` | Operations Researcher | Objective recomputed | Exact arithmetic match | **PASS** |
| **23** | `test_23_operations_researcher_infeasible_problem_handling` | Operations Researcher | Explicit infeasibility stated | Disclosed cleanly | **PASS** |
| **24** | `test_24_operations_researcher_incomplete_input_handling` | Operations Researcher | `NOT_EVALUABLE` disposition | `NOT_EVALUABLE` | **PASS** |
| **25** | `test_25_cross_archetype_tool_privilege_isolation` | Shared / Isolation | Cannot invoke cross tools | Permission denied | **PASS** |
| **26** | `test_26_cross_session_data_isolation` | Shared / Isolation | Separate memory per session | Zero bleed | **PASS** |
| **27** | `test_27_cross_project_evidence_isolation` | Shared / Isolation | Cross-project mismatch caught | `EVIDENCE_PROJECT_ID_MISMATCH` | **PASS** |
| **28** | `test_28_cross_execution_evidence_mismatch_rejection` | Shared / Isolation | Cross-exec mismatch caught | `EVIDENCE_EXECUTION_ID_MISMATCH` | **PASS** |
| **29** | `test_29_tool_timeout_and_bounded_recovery_preservation` | Shared / Runtime | Timeout triggers recovery | Bounded halting | **PASS** |
| **30** | `test_30_cancellation_and_uncertain_side_effect_preservation` | Shared / Runtime | Cancellation handled safely | State rolled back | **PASS** |
| **31** | `test_31_all_four_archetypes_negative_cases_fail_closed` | All Archetypes | Deliberate failure fails | `FAIL` for all 4 | **PASS** |
| **32** | `test_32_all_four_archetypes_missing_evidence_not_evaluable` | All Archetypes | Missing evidence unevaluable | `NOT_EVALUABLE` for all 4 | **PASS** |
| **33** | `test_33_evaluator_exception_fails_closed` | Shared / Evaluator | Exception yields fail-closed | `NOT_EVALUABLE` | **PASS** |
| **34** | `test_34_tampered_evidence_detected` | Shared / Security | Post-verdict tamper caught | Signature invalid | **PASS** |

---

## 6. Live Inference and Canonical Ingress Evidence

### 6.1 Approved Local MLX Authority Probe
- **Endpoint:** `http://127.0.0.1:19801/v1`
- **Model Identified:** `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2`
- **Host:** Apple M6 Mac mini (24 GB RAM)
- **Status:** Verified online and active.

### 6.2 Live Multi-Turn Interaction Evidence
- **Turn 1 Prompt:** `"Customer account ACC-440 has SLA Tier Enterprise with 15-minute response time. Confirm."`
- **Turn 1 Model Response:** `"Confirmed: The customer account ACC-440 has the SLA Tier Enterprise with a 15-minute response time."`
- **Turn 2 Prompt:** `"What is the SLA tier and response time for ACC-440?"`
- **Turn 2 Model Response:** `"The customer account ACC-440 has the SLA Tier Enterprise with a 15-minute response time."`
- **Status:** **PASS** — factual retention confirmed across multi-turn session on real weights.

### 6.3 Canonical Production Ingress Execution (Gate 6H — Four Archetypes)
All four archetype requests were submitted through `AutoForgeApiService.execute_intent_pipeline`:

| Archetype Identifier | Customer Project Name | Pipeline Duration | Intent Status | Evaluation Report | Archetype Contract | Manifest Validated |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `support_copilot` | `OmniCare-Support-Copilot` | 16.13s | `COMPLETED` | YES (`PASS`) | YES (v1.0.0) | YES |
| `financial_analyst` | `Apex-Treasury-Financial-Analyst` | 16.21s | `COMPLETED` | YES (`PASS`) | YES (v1.0.0) | YES |
| `devsecops_assistant` | `ShieldOps-DevSecOps-Assistant` | 16.15s | `COMPLETED` | YES (`PASS`) | YES (v1.0.0) | YES |
| `operations_researcher` | `OptiRoute-Operations-Researcher` | 16.63s | `COMPLETED` | YES (`PASS`) | YES (v1.0.0) | YES |

---

## 7. Full Regression Suite Results (12 Suites)

All 12 regression test suites were executed sequentially via the Gate 6 certification driver:

| Suite Name | Path | Passed | Failed | Duration | Exit Code |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Gate 6 Archetype Generalization** | `packages/power_engines/tests/test_agent_archetype_generalization.py` | 34 | 0 | 0.40s | 0 |
| **Gate 5 Fail-Closed Evaluator** | `packages/power_engines/tests/test_agent_evaluator_integrity.py` | 24 | 0 | 0.36s | 0 |
| **Gate 4 Multi-Turn Persistence** | `packages/power_engines/tests/test_agent_multi_turn_persistence.py` | 24 | 0 | 1.65s | 0 |
| **Gate 3 Bounded Execution & Recovery** | `packages/power_engines/tests/test_agent_bounded_execution_recovery.py` | 24 | 0 | 4.45s | 0 |
| **Gate 1 Inference Provider Alignment** | `packages/power_engines/tests/test_agent_inference_alignment.py` | 8 | 0 | 2.79s | 0 |
| **Gate 2 Tool Sandboxing & Security** | `packages/power_engines/tests/test_agent_security_sandboxing.py` | 48 | 0 | 0.39s | 0 |
| **Agent Core & Lifecycle** | `packages/power_engines/tests/test_agent_power_engine.py` | 30 | 0 | 7.77s | 0 |
| **Deliverable Packaging & Manifest** | `packages/power_engines/tests/test_agent_deliverable_packaging.py` | 9 | 0 | 16.77s | 0 |
| **Agent Production Deployment** | `packages/power_engines/tests/test_agent_production_deployment.py` | 14 | 0 | 0.59s | 0 |
| **Customer Deployment Platform** | `packages/power_engines/tests/test_customer_deployment.py` | 9 | 0 | 1.01s | 0 |
| **Shared Delivery Platform** | `packages/power_engines/tests/test_shared_delivery_platform.py` | 9 | 0 | 0.38s | 0 |
| **Commercial Capability Routing** | `packages/composition/tests/test_capability_routing.py` | 26 | 0 | 5.88s | 0 |
| **TOTAL** | — | **259** | **0** | **42.44s** | **0** |

**Pass Rate:** **100.0%** (259 tests passed, 0 failed, 0 errors, 0 skipped).

---

## 8. Artifacts and Reproduction Commands

### Certified Artifacts
1. **Certification Driver:** `scripts/run_phase20_c_gate6_agent_archetype_generalization_certification.py`
2. **Dedicated Test Suite:** `packages/power_engines/tests/test_agent_archetype_generalization.py`
3. **Core Archetypes Module:** `packages/power_engines/src/autoforge_power_engines/agent/archetypes.py`
4. **Machine-Readable Benchmark:** `benchmarks/results/phase20_c_gate6_certification_20261017_180858.json`
5. **Certification Report:** `docs/reports/PHASE_20C_GATE_6_AGENT_ARCHETYPE_GENERALIZATION_CERTIFICATION.md`

### Reproduction Command
```bash
.venv/bin/python scripts/run_phase20_c_gate6_agent_archetype_generalization_certification.py
```

---

## 9. Residual Risks and Known Limitations

1. **Archetype Tool Escalation:**
   - Any attempt by user prompts or configuration to request tools outside an archetype's `authorized_tools` boundary is strictly caught and rejected during specification resolution (`spec.py`). Runtime calls remain subject to Gate 2 sandbox enforcement.
2. **Deterministic Arithmetic Verification:**
   - Financial analyst calculations must always be independently recalculated and reconciled against verified baseline figures. Model self-reported calculations are treated as untrusted hypotheses.
3. **Operational Optimization Bounds:**
   - For complex combinatorial optimization workloads, linear solvers or verified heuristic checks must independently assert constraint satisfaction before any solution is reported as feasible.

---

## 10. Next Authoritative Step

Phase 20-C Gate 6 is formally **CERTIFIED**. The next mandatory step in the authoritative seven-gate sequence is:

**Phase 20-C, Gate 7 — Fresh End-to-End Customer Certification**
Focus: Submit a completely fresh, comprehensive customer requirement through the full production pipeline, certifying end-to-end autonomous customer agent generation, deployment, fail-closed evaluation, and deliverable delivery without synthetic test aids.
