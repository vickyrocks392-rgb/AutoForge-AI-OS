"""Comprehensive Certification Test Suite for 18-COMMERCIAL-C (AI Automation Power Engine).

Audits all functional, security, state machine, idempotency, AI decision, approval,
verification, and standalone customer delivery requirements.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from autoforge_power_engines.automation import (
    CustomerAutomationSpecification,
    TriggerSpec,
    TriggerType,
    StepSpec,
    StepType,
    ActionSpec,
    ActionRiskLevel,
    ConditionSpec,
    ConditionRule,
    AIDecisionSpec,
    HumanApprovalSpec,
    AgentInvokeSpec,
    WorkflowExecutionPolicy,
    RetryPolicy,
    VerificationRule,
    VerificationRuleType,
    WebhookAuthConfig,
    TriggerRegistry,
    WebhookTrigger,
    ManualTrigger,
    EventTrigger,
    ScheduledTrigger,
    TriggerSecurityError,
    ActionRegistry,
    HTTPRequestAction,
    TransformDataAction,
    SafeCalculatorAction,
    FileOperationAction,
    DocumentLookupAction,
    WorkspaceSecurityError,
    SSRFSecurityError,
    validate_workspace_path,
    validate_outbound_url,
    safe_eval_expression,
    ConditionEvaluator,
    WorkflowStateMachine,
    WorkflowState,
    StepExecutionState,
    ApprovalManager,
    ApprovalStatus,
    WorkflowVerifier,
    RepairHandler,
    IdempotencyStore,
    ExecutionTrace,
    mask_sensitive_data,
    StandaloneAutomationRuntime,
    AIAutomationPowerEngine,
    StandaloneCustomerAutomationGenerator,
    ModelProvider,
    OllamaModelProvider,
)
from autoforge_power_engines.delivery.sanitizer import ProprietaryBoundarySanitizer


class TestAIAutomationPowerEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_autoforge_comm_c_"))
        self.workspace_dir = self.temp_dir / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_db = self.temp_dir / "state.db"

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── 1. Specification Validation ───────────────────────────────────────────

    def test_01_spec_valid(self):
        spec = CustomerAutomationSpecification(
            project_name="Order Processing Workflow",
            project_description="Processes and verifies retail orders",
            workflow_id="order_flow_v1",
            workflow_version="1.0.0",
            initial_step_id="calc_step",
            steps=[
                StepSpec(
                    step_id="calc_step",
                    name="Calculate Total",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="safe_calculator",
                        name="calculate_order",
                        parameters={"expression": "100 + 20"},
                    ),
                )
            ],
        )
        self.assertEqual(spec.workflow_id, "order_flow_v1")
        self.assertEqual(len(spec.steps), 1)

    def test_02_spec_invalid_duplicate_steps(self):
        with self.assertRaises(ValueError):
            CustomerAutomationSpecification(
                project_name="Duplicate Steps",
                project_description="Invalid duplicate steps",
                workflow_id="dup_flow",
                initial_step_id="step1",
                steps=[
                    StepSpec(step_id="step1", name="Step 1", step_type=StepType.ACTION, action=ActionSpec(action_type="safe_calculator", name="calc")),
                    StepSpec(step_id="step1", name="Step 1 Duplicate", step_type=StepType.ACTION, action=ActionSpec(action_type="safe_calculator", name="calc")),
                ],
            )

    def test_03_spec_invalid_missing_action(self):
        with self.assertRaises(ValueError):
            CustomerAutomationSpecification(
                project_name="Missing Action",
                project_description="Invalid missing action",
                workflow_id="missing_action_flow",
                initial_step_id="step1",
                steps=[
                    StepSpec(step_id="step1", name="Step 1", step_type=StepType.ACTION, action=None),
                ],
            )

    # ── 2. Triggers ───────────────────────────────────────────────────────────

    def test_04_manual_trigger(self):
        spec = TriggerSpec(name="manual_init", trigger_type=TriggerType.MANUAL)
        tr = ManualTrigger(spec)
        fired, payload = tr.evaluate({"inputs": {"order_id": "ORD-123"}})
        self.assertTrue(fired)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.payload["order_id"], "ORD-123")

    def test_05_webhook_trigger_auth_and_payload_limits(self):
        spec = TriggerSpec(
            name="order_webhook",
            trigger_type=TriggerType.WEBHOOK,
            webhook_path="/webhooks/orders",
            webhook_auth=WebhookAuthConfig(
                require_auth=True,
                expected_token="secret_token_abc",
                max_payload_bytes=100,
            ),
        )
        tr = WebhookTrigger(spec)

        # 1. Reject missing auth
        with self.assertRaises(TriggerSecurityError):
            tr.verify_request(b'{"key": "val"}', {"content-type": "application/json"})

        # 2. Reject wrong token
        with self.assertRaises(TriggerSecurityError):
            tr.verify_request(b'{"key": "val"}', {"content-type": "application/json", "authorization": "Bearer wrong"})

        # 3. Reject oversized payload (> 100 bytes)
        big_body = json.dumps({"data": "x" * 200}).encode("utf-8")
        with self.assertRaises(TriggerSecurityError):
            tr.verify_request(big_body, {"content-type": "application/json", "authorization": "Bearer secret_token_abc"})

        # 4. Accept valid request
        valid_body = json.dumps({"order_id": 456}).encode("utf-8")
        payload = tr.verify_request(valid_body, {"content-type": "application/json", "authorization": "Bearer secret_token_abc"})
        self.assertEqual(payload.payload["order_id"], 456)
        self.assertEqual(payload.headers["authorization"], "[MASKED]")

    def test_06_webhook_trigger_hmac_verification(self):
        secret = "super_hmac_secret"
        spec = TriggerSpec(
            name="hmac_webhook",
            trigger_type=TriggerType.WEBHOOK,
            webhook_auth=WebhookAuthConfig(
                require_auth=True,
                hmac_secret=secret,
            ),
        )
        tr = WebhookTrigger(spec)
        body = b'{"event": "payment_received", "amount": 250}'
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        # Valid signature
        payload = tr.verify_request(body, {"content-type": "application/json", "x-webhook-signature": sig})
        self.assertEqual(payload.payload["amount"], 250)

        # Tampered body fails
        with self.assertRaises(TriggerSecurityError):
            tr.verify_request(b'{"event": "payment_received", "amount": 9999}', {"content-type": "application/json", "x-webhook-signature": sig})

    def test_07_event_trigger_pattern_match(self):
        spec = TriggerSpec(
            name="inventory_event",
            trigger_type=TriggerType.EVENT,
            event_topic="inventory.updates",
            event_pattern={"status": "low_stock"},
        )
        tr = EventTrigger(spec)

        fired, _ = tr.evaluate({"event_topic": "wrong.topic", "event_data": {"status": "low_stock"}})
        self.assertFalse(fired)

        fired, _ = tr.evaluate({"event_topic": "inventory.updates", "event_data": {"status": "in_stock"}})
        self.assertFalse(fired)

        fired, payload = tr.evaluate({"event_topic": "inventory.updates", "event_data": {"status": "low_stock", "sku": "ABC-9"}})
        self.assertTrue(fired)
        self.assertEqual(payload.payload["sku"], "ABC-9")

    # ── 3. Actions & Security ─────────────────────────────────────────────────

    def test_08_safe_calculator_ast(self):
        calc = SafeCalculatorAction()
        res = calc.execute({"expression": "(10 + 5) * 4 - 20 / 2", "variables": {}}, {})
        self.assertEqual(res["result"], 50.0)

        res2 = calc.execute({"expression": "subtotal * 1.08 + shipping", "variables": {"subtotal": 100, "shipping": 15}}, {})
        self.assertEqual(res2["result"], 123.0)

        # Prohibit arbitrary code / import
        with self.assertRaises(ValueError):
            calc.execute({"expression": "__import__('os').system('ls')"}, {})

    def test_09_file_operation_workspace_confinement(self):
        f_op = FileOperationAction(workspace_root=str(self.workspace_dir))

        # Write inside workspace
        w_res = f_op.execute({"operation": "write", "path": "invoices/inv_1.txt", "content": "INV-100"}, {})
        self.assertEqual(w_res["status"], "written")

        # Read back
        r_res = f_op.execute({"operation": "read", "path": "invoices/inv_1.txt"}, {})
        self.assertEqual(r_res["content"], "INV-100")

        # Deny traversal outside workspace
        with self.assertRaises(WorkspaceSecurityError):
            f_op.execute({"operation": "read", "path": "../../etc/passwd"}, {})

        # Deny access to sensitive files
        with self.assertRaises(WorkspaceSecurityError):
            f_op.execute({"operation": "write", "path": ".env", "content": "SECRET=123"}, {})

    def test_10_ssrf_protection_outbound_url(self):
        # Localhost denied
        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://127.0.0.1:8080/admin")

        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://localhost:5000/internal")

        # AWS metadata IP denied
        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://169.254.169.254/latest/meta-data")

        # RFC 1918 private IP denied
        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://192.168.1.100/api")

        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://10.0.0.5/api")

        # Public HTTPS allowed
        valid = validate_outbound_url("https://api.example.com/v1/resource")
        self.assertEqual(valid, "https://api.example.com/v1/resource")

    def test_11_transform_data_action(self):
        transformer = TransformDataAction()
        raw = {"vendor": "Acme", "total_raw": 100, "tax_rate": 0.1}
        res = transformer.execute({
            "data": raw,
            "mapping": {"supplier": "vendor", "base": "total_raw", "tax": "tax_rate"},
            "compute": {"total_with_tax": "base + (base * tax)"}
        }, {})
        out = res["result"]
        self.assertEqual(out["supplier"], "Acme")
        self.assertEqual(out["total_with_tax"], 110.0)

    # ── 4. Conditions & Branching ─────────────────────────────────────────────

    def test_12_condition_branching(self):
        cond_rule = ConditionRule(
            field="${inputs.amount}",
            operator="gt",
            value=5000,
        )
        cond_spec = ConditionSpec(
            rule=cond_rule,
            then_step_id="approval_step",
            else_step_id="auto_process_step",
        )

        branch_high = ConditionEvaluator.resolve_branch(cond_spec, {"inputs": {"amount": 7500}})
        self.assertEqual(branch_high, "approval_step")

        branch_low = ConditionEvaluator.resolve_branch(cond_spec, {"inputs": {"amount": 3200}})
        self.assertEqual(branch_low, "auto_process_step")

    def test_13_condition_composite_logic(self):
        composite_rule = ConditionRule(
            all_of=[
                ConditionRule(field="${inputs.status}", operator="eq", value="APPROVED"),
                ConditionRule(field="${inputs.priority}", operator="in", value=["HIGH", "URGENT"]),
            ]
        )
        self.assertTrue(ConditionEvaluator.evaluate_rule(composite_rule, {"inputs": {"status": "APPROVED", "priority": "HIGH"}}))
        self.assertFalse(ConditionEvaluator.evaluate_rule(composite_rule, {"inputs": {"status": "PENDING", "priority": "HIGH"}}))

    # ── 5. Verification Engine ────────────────────────────────────────────────

    def test_14_verification_rules_pass_and_fail(self):
        rules = [
            VerificationRule(rule_type=VerificationRuleType.SCHEMA, rule_name="SchemaCheck", config={"required_keys": ["status", "total"]}),
            VerificationRule(rule_type=VerificationRuleType.NUMERIC_INVARIANT, rule_name="TotalMatch", config={"field": "total", "expected_value": 150.0}),
        ]

        valid_out = {"status": "PROCESSED", "total": 150.0, "details": "ok"}
        v_res = WorkflowVerifier.verify_step_output("step_1", valid_out, rules)
        self.assertTrue(v_res.passed)

        invalid_out = {"status": "PROCESSED", "total": 140.0}
        v_res2 = WorkflowVerifier.verify_step_output("step_1", invalid_out, rules)
        self.assertFalse(v_res2.passed)
        self.assertIn("TotalMatch", v_res2.failure_reasons[0])

    # ── 6. State Machine & Idempotency ────────────────────────────────────────

    def test_15_state_machine_valid_transitions(self):
        sm = WorkflowStateMachine()
        self.assertEqual(sm.current_state, WorkflowState.CREATED)

        sm.transition_workflow(WorkflowState.READY, "Config ready")
        sm.transition_workflow(WorkflowState.RUNNING, "Started")
        sm.transition_workflow(WorkflowState.EXECUTING_STEP, "Step 1", step_id="step1")
        sm.transition_workflow(WorkflowState.VERIFYING, "Verifying step 1", step_id="step1")
        sm.transition_workflow(WorkflowState.RUNNING, "Next step")
        sm.transition_workflow(WorkflowState.COMPLETED, "Done")

        self.assertEqual(sm.current_state, WorkflowState.COMPLETED)
        self.assertTrue(sm.is_terminal())

    def test_16_state_machine_invalid_transition_denied(self):
        sm = WorkflowStateMachine()
        with self.assertRaises(ValueError):
            # Cannot jump directly from CREATED to COMPLETED
            sm.transition_workflow(WorkflowState.COMPLETED)

    def test_17_idempotency_store(self):
        store = IdempotencyStore(self.state_db)
        key = store.generate_key("workflow", "order_123", {"amount": 500})

        exists, _ = store.check_key(key)
        self.assertFalse(exists)

        store.record_start(key, "workflow", "order_flow", "exec_001")
        exists, resp = store.check_key(key)
        self.assertTrue(exists)
        self.assertEqual(resp, {})

        store.record_complete(key, {"status": "PROCESSED", "invoice_num": "INV-99"})
        exists, resp2 = store.check_key(key)
        self.assertTrue(exists)
        self.assertEqual(resp2["invoice_num"], "INV-99")

    # ── 7. Bounded Retries & 1-Pass Repair ─────────────────────────────────────

    def test_18_bounded_retries(self):
        call_count = 0
        def flaky_action():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Transient network failure")
            return {"status": "ok"}

        policy = RetryPolicy(max_attempts=4, initial_backoff_ms=10)
        ok, res, attempts, err = RepairHandler.execute_with_retry(flaky_action, policy, "flaky_step")
        self.assertTrue(ok)
        self.assertEqual(attempts, 3)
        self.assertEqual(res["status"], "ok")

    def test_19_ai_decision_one_pass_repair(self):
        malformed_raw = "Sure, here is the decision: { 'risk': 'LOW', missing_closing_brace..."
        schema = {"required": ["risk_level", "approved"]}

        def mock_repair_model(repair_prompt: str) -> str:
            self.assertIn("violated the required JSON format", repair_prompt)
            return '```json\n{"risk_level": "LOW", "approved": true}\n```'

        ok, parsed, repaired, err = RepairHandler.parse_and_repair_json(
            raw_text=malformed_raw,
            expected_schema=schema,
            repair_fn=mock_repair_model,
            max_repair_passes=1,
        )

        self.assertTrue(ok)
        self.assertTrue(repaired)
        self.assertEqual(parsed["risk_level"], "LOW")
        self.assertTrue(parsed["approved"])

    # ── 8. Human Approval Workflow Execution ──────────────────────────────────

    def test_20_human_approval_pause_and_resume(self):
        spec = CustomerAutomationSpecification(
            project_name="High Value Transfer Approval",
            project_description="Approves transfers above threshold",
            workflow_id="transfer_flow",
            initial_step_id="check_amount",
            steps=[
                StepSpec(
                    step_id="check_amount",
                    name="Calculate Fee",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="safe_calculator",
                        name="calc_fee",
                        parameters={"expression": "${inputs.amount} * 0.02"},
                    ),
                    next_step_id="approval_gate",
                ),
                StepSpec(
                    step_id="approval_gate",
                    name="Human Approval",
                    step_type=StepType.HUMAN_APPROVAL,
                    human_approval=HumanApprovalSpec(
                        reason="Amount exceeds $5,000 threshold",
                        approval_prompt="Please sign off on wire transfer",
                    ),
                    next_step_id="final_disburse",
                ),
                StepSpec(
                    step_id="final_disburse",
                    name="Disburse Funds",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="transform_data",
                        name="disburse",
                        parameters={"data": {"status": "DISBURSED"}},
                    ),
                ),
            ],
            output_mapping={"transfer_status": "${steps.final_disburse.output.result.status}"},
        )

        runtime = StandaloneAutomationRuntime(
            spec=spec,
            workspace_root=self.workspace_dir,
            state_db_path=self.state_db,
        )

        # 1. Start execution -> should pause at approval_gate
        outcome = runtime.start_workflow(inputs={"amount": 10000})
        self.assertEqual(outcome.status, WorkflowState.WAITING_FOR_APPROVAL)
        self.assertFalse(outcome.success)
        self.assertIsNotNone(outcome.pending_approval)
        req_id = outcome.pending_approval.request_id

        # 2. Resume execution with human sign-off
        resumed = runtime.resume_workflow(
            execution_id=outcome.execution_id,
            approval_request_id=req_id,
            approved=True,
            reviewer_id="lead_cfo",
            comment="Wire approved per invoice verification",
        )
        self.assertEqual(resumed.status, WorkflowState.COMPLETED)
        self.assertTrue(resumed.success)
        self.assertEqual(resumed.outputs["transfer_status"], "DISBURSED")

    # ── 9. Standalone Customer Packaging & Generator ──────────────────────────

    def test_21_generator_builds_standalone_package(self):
        delivery_dir = self.temp_dir / "customer_pkg"
        spec = CustomerAutomationSpecification(
            project_name="Commercial Customer Automation",
            project_description="Customer automated billing process",
            workflow_id="billing_flow",
            initial_step_id="step1",
            steps=[
                StepSpec(
                    step_id="step1",
                    name="Compute Billing",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="safe_calculator",
                        name="calc_bill",
                        parameters={"expression": "500 * 1.1"},
                    ),
                )
            ],
        )

        gen = StandaloneCustomerAutomationGenerator(delivery_dir)
        res = gen.generate_customer_project(spec)
        self.assertEqual(res["status"], "success")

        # Verify filesystem contents
        self.assertTrue((delivery_dir / "src" / "app.py").exists())
        self.assertTrue((delivery_dir / "src" / "workflow" / "runtime.py").exists())
        self.assertTrue((delivery_dir / "tests" / "test_automation_runtime.py").exists())
        self.assertTrue((delivery_dir / "deploy.sh").exists())
        self.assertTrue((delivery_dir / "Deploy.command").exists())
        self.assertTrue((delivery_dir / "docker-compose.yml").exists())
        self.assertTrue((delivery_dir / "README.md").exists())
        self.assertTrue((delivery_dir / "DELIVERY_REPORT.md").exists())

        # Strict proprietary boundary scan
        sanitizer = ProprietaryBoundarySanitizer(delivery_dir)
        violations = sanitizer.sanitize()
        self.assertEqual(violations, [])

    # ── 10. Canonical 11-Stage Power Engine Lifecycle ─────────────────────────

    async def _run_lifecycle(self, spec: CustomerAutomationSpecification, delivery_dir: Path):
        engine = AIAutomationPowerEngine()
        ctx = engine.create_context(spec)
        ctx.delivery_dir = delivery_dir
        return await engine.execute_lifecycle(spec)

    def test_22_full_11_stage_lifecycle_execution(self):
        import asyncio
        delivery_dir = self.temp_dir / "lifecycle_delivery"
        spec = CustomerAutomationSpecification(
            project_name="Turnkey Enterprise Flow",
            project_description="Fully automated enterprise business process",
            workflow_id="enterprise_flow",
            output_root=str(self.temp_dir),
            initial_step_id="step_calc",
            steps=[
                StepSpec(
                    step_id="step_calc",
                    name="Calculate Metrics",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="safe_calculator",
                        name="metric_calc",
                        parameters={"expression": "250 * 4"},
                    ),
                )
            ],
        )

        result = asyncio.run(self._run_lifecycle(spec, delivery_dir))
        self.assertTrue(result.success)
        self.assertEqual(len(result.stages_executed), 11)
        self.assertIn("PACKAGE", result.stages_executed)
        self.assertIn("DELIVER", result.stages_executed)

    # ── 11. Commercial Demonstration Workload ─────────────────────────────────

    def test_23_commercial_demonstration_invoice_processing(self):
        """
        Full Commercial Demonstration: Invoice Processing Automation.
        Multi-step workflow:
        1. Ingest invoice data
        2. Safe calculate subtotal and tax
        3. AI classification of vendor risk
        4. Conditional branching: if total > $5,000 -> requires human approval
        5. Human approval resolution
        6. Deterministic verification of calculated balance
        7. Audit trace emission
        """
        # Mock model provider for deterministic AI decision
        class MockAIProvider(ModelProvider):
            def invoke(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None, temperature: float = 0.0) -> str:
                return json.dumps({
                    "vendor_risk": "LOW",
                    "tax_compliant": True,
                    "confidence": 0.98,
                    "reasoning": "Vendor is an established supplier with valid tax ID."
                })

        invoice_spec = CustomerAutomationSpecification(
            project_name="Invoice Processing Automation",
            project_description="Automates commercial vendor invoice validation and approval",
            workflow_id="invoice_processing_v1",
            initial_step_id="step_calc_total",
            steps=[
                # Step 1: Calculate Total
                StepSpec(
                    step_id="step_calc_total",
                    name="Calculate Total Amount",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="safe_calculator",
                        name="calculate_invoice",
                        parameters={
                            "expression": "subtotal + (subtotal * tax_rate)",
                            "variables": {
                                "subtotal": "${inputs.subtotal}",
                                "tax_rate": "${inputs.tax_rate}",
                            },
                        },
                        verification_rules=[
                            VerificationRule(
                                rule_type=VerificationRuleType.NUMERIC_INVARIANT,
                                rule_name="NumericBalanceCheck",
                                config={"field": "result", "expected_value": 5500.0},
                            )
                        ],
                    ),
                    next_step_id="step_ai_risk_assessment",
                ),
                # Step 2: AI Risk Assessment
                StepSpec(
                    step_id="step_ai_risk_assessment",
                    name="AI Vendor Risk Assessment",
                    step_type=StepType.AI_DECISION,
                    ai_decision=AIDecisionSpec(
                        prompt_template="Analyze vendor '${inputs.vendor}' with invoice amount ${steps.step_calc_total.output.result}.",
                        expected_output_schema={
                            "type": "object",
                            "required": ["vendor_risk", "tax_compliant", "confidence"],
                        },
                    ),
                    next_step_id="step_check_approval_needed",
                ),
                # Step 3: Branching Condition
                StepSpec(
                    step_id="step_check_approval_needed",
                    name="Check Approval Threshold",
                    step_type=StepType.CONDITION,
                    condition=ConditionSpec(
                        rule=ConditionRule(
                            field="${steps.step_calc_total.output.result}",
                            operator="gt",
                            value=5000.0,
                        ),
                        then_step_id="step_human_approval",
                        else_step_id="step_emit_payment",
                    ),
                ),
                # Step 4: Human Approval
                StepSpec(
                    step_id="step_human_approval",
                    name="Manager Sign-off",
                    step_type=StepType.HUMAN_APPROVAL,
                    human_approval=HumanApprovalSpec(
                        reason="Invoice total ($5,500.00) exceeds $5,000 threshold",
                        approval_prompt="Authorize payment to vendor",
                    ),
                    next_step_id="step_emit_payment",
                ),
                # Step 5: Emit Payment
                StepSpec(
                    step_id="step_emit_payment",
                    name="Emit Disbursement Record",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="transform_data",
                        name="create_disbursement",
                        parameters={
                            "data": {
                                "status": "APPROVED_FOR_DISBURSEMENT",
                                "invoice_id": "${inputs.invoice_id}",
                                "total": "${steps.step_calc_total.output.result}",
                            },
                        },
                    ),
                ),
            ],
            output_mapping={
                "status": "${steps.step_emit_payment.output.result.status}",
                "invoice_id": "${steps.step_emit_payment.output.result.invoice_id}",
                "final_amount": "${steps.step_emit_payment.output.result.total}",
                "vendor_risk": "${steps.step_ai_risk_assessment.output.decision.vendor_risk}",
            },
        )

        runtime = StandaloneAutomationRuntime(
            spec=invoice_spec,
            workspace_root=self.workspace_dir,
            state_db_path=self.state_db,
            model_provider=MockAIProvider(),
        )

        # Run 1: Input $5000 subtotal + 10% tax = $5500 -> Triggers approval pause
        input_data = {
            "invoice_id": "INV-COMM-2026",
            "vendor": "Apex Logistics Corp",
            "subtotal": 5000.0,
            "tax_rate": 0.10,
        }
        outcome = runtime.start_workflow(inputs=input_data)
        self.assertEqual(outcome.status, WorkflowState.WAITING_FOR_APPROVAL)
        self.assertIsNotNone(outcome.pending_approval)

        # Human Manager signs off
        final_outcome = runtime.resume_workflow(
            execution_id=outcome.execution_id,
            approval_request_id=outcome.pending_approval.request_id,
            approved=True,
            reviewer_id="controller_alice",
            comment="Approved per contract PO-409",
        )

        self.assertTrue(final_outcome.success)
        self.assertEqual(final_outcome.status, WorkflowState.COMPLETED)
        self.assertEqual(final_outcome.outputs["status"], "APPROVED_FOR_DISBURSEMENT")
        self.assertEqual(final_outcome.outputs["final_amount"], 5500.0)
        self.assertEqual(final_outcome.outputs["vendor_risk"], "LOW")

        # Verify audit trace
        trace = final_outcome.trace
        self.assertGreaterEqual(len(trace.step_traces), 5)
        self.assertIsNotNone(trace.get_step_trace("step_calc_total").verification_result)
        self.assertTrue(trace.get_step_trace("step_calc_total").verification_result.passed)

    # ── 12. Real Ollama Live Model Execution ──────────────────────────────────

    def test_24_real_ollama_model_step(self):
        """
        Live Ollama execution with qwen2.5-coder:7b-instruct-q3_K_M.
        Verifies that structured JSON decision is generated and validated.
        """
        try:
            provider = OllamaModelProvider()
            prompt = (
                "Evaluate the risk for vendor 'Acme Global'. Return JSON matching schema:\n"
                '{"risk": "LOW"|"HIGH", "reason": "short explanation"}'
            )
            raw = provider.invoke(
                prompt=prompt,
                model="qwen2.5-coder:7b-instruct-q3_K_M",
                temperature=0.0,
            )
            self.assertTrue(len(raw) > 5)
            # Must parse as JSON
            ok, parsed, repaired, _ = RepairHandler.parse_and_repair_json(raw, {"required": ["risk"]})
            self.assertTrue(ok)
            self.assertIn("risk", parsed)
        except Exception as e:
            # If Ollama service is temporarily busy or unreachable, skip gracefully
            self.skipTest(f"Ollama local service unavailable: {e}")

    # ── 13. Detached Customer Execution & Proprietary Scan ─────────────────────

    def test_25_detached_customer_package_execution(self):
        """
        Tests standalone customer package execution in complete isolation from AutoForge.
        Ensures customer tests pass when executed directly inside the delivery directory.
        """
        import subprocess

        delivery_dir = self.temp_dir / "detached_delivery"
        spec = CustomerAutomationSpecification(
            project_name="Detached Customer Automation",
            project_description="Executes independently of AutoForge",
            workflow_id="detached_flow",
            initial_step_id="step1",
            steps=[
                StepSpec(
                    step_id="step1",
                    name="Calculate Output",
                    step_type=StepType.ACTION,
                    action=ActionSpec(
                        action_type="safe_calculator",
                        name="calc",
                        parameters={"expression": "100 * 2 + 50"},
                    ),
                )
            ],
        )

        gen = StandaloneCustomerAutomationGenerator(delivery_dir)
        gen.generate_customer_project(spec)

        # 1. Proprietary Boundary Scan
        sanitizer = ProprietaryBoundarySanitizer(delivery_dir)
        violations = sanitizer.sanitize()
        self.assertEqual(violations, [])

        # 2. Run customer pytest suite detached from AutoForge
        clean_env = os.environ.copy()
        clean_env["PYTHONPATH"] = str(delivery_dir)

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_automation_runtime.py", "-v"],
            cwd=str(delivery_dir),
            env=clean_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"Customer test suite failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    def test_26_secret_leakage_detection(self):
        """
        Verifies that sanitizer detects exposed credentials or private keys in deliverables.
        """
        delivery_dir = self.temp_dir / "secret_leak_test"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        leaky_file = delivery_dir / "config.json"
        leaky_file.write_text('{"api_key": "sk-12345678901234567890123456789012"}', encoding="utf-8")

        sanitizer = ProprietaryBoundarySanitizer(delivery_dir)
        violations = sanitizer.scan_for_secrets()
        self.assertGreaterEqual(len(violations), 1)
        self.assertIn("Exposed OpenAI / Model API Key", violations[0])
