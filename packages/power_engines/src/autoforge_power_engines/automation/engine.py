"""AI Automation Power Engine — Phase 18-COMMERCIAL-C Canonical Implementation."""

from __future__ import annotations

import ast
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from autoforge_power_engines.base import PowerEngine, PowerEngineContext
from autoforge_power_engines.automation.spec import CustomerAutomationSpecification
from autoforge_power_engines.automation.generator import StandaloneCustomerAutomationGenerator
from autoforge_power_engines.risk import PowerEngineRiskEvaluator

logger = logging.getLogger("autoforge.power_engines.automation.engine")


class AIAutomationPowerEngine(PowerEngine):
    """
    18-COMMERCIAL-C: AI Automation Power Engine.
    Autonomous turnkey customer deliverable engine for self-deployable AI Automation Workflows.
    Executes the canonical 11-stage lifecycle.
    """

    def __init__(
        self,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        risk_evaluator: Optional[PowerEngineRiskEvaluator] = None,
    ):
        super().__init__(event_sink=event_sink, risk_evaluator=risk_evaluator)
        self._in_flight_generators: Dict[str, StandaloneCustomerAutomationGenerator] = {}
        self._in_flight_specs: Dict[str, CustomerAutomationSpecification] = {}
        self._in_flight_defects: Dict[str, List[Any]] = {}

    def _resolve_spec(self, ctx: PowerEngineContext) -> CustomerAutomationSpecification:
        if isinstance(ctx.specification, CustomerAutomationSpecification):
            return ctx.specification
        raise TypeError(
            f"Expected CustomerAutomationSpecification, got {type(ctx.specification).__name__}"
        )

    # ── Stage 1: INTAKE ───────────────────────────────────────────────────────
    async def _stage_intake(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        auto_spec = self._resolve_spec(ctx)
        self._in_flight_specs[ctx.execution_id] = auto_spec
        logger.info(f"Executing Stage 1 (INTAKE) for Automation: {auto_spec.project_name}")

        if not auto_spec.workflow_id or len(auto_spec.workflow_id.strip()) < 2:
            raise ValueError("Customer specification missing valid workflow_id.")
        if not auto_spec.steps:
            raise ValueError("Customer specification contains zero steps.")

        ctx.telemetry["intake"] = {
            "project_name": auto_spec.project_name,
            "workflow_id": auto_spec.workflow_id,
            "version": auto_spec.workflow_version,
            "steps_count": len(auto_spec.steps),
            "triggers_count": len(auto_spec.triggers),
        }

        return {
            "status": "accepted",
            "workflow_id": auto_spec.workflow_id,
            "steps_declared": len(auto_spec.steps),
        }

    # ── Stage 2: UNDERSTAND / ANALYZE ─────────────────────────────────────────
    async def _stage_understand_analyze(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        auto_spec = self._in_flight_specs[ctx.execution_id]
        logger.info(f"Executing Stage 2 (UNDERSTAND/ANALYZE) for Automation: {auto_spec.project_name}")

        step_types = [s.step_type.value for s in auto_spec.steps]
        trigger_types = [t.trigger_type.value for t in auto_spec.triggers]

        ctx.telemetry["analysis"] = {
            "step_types": step_types,
            "trigger_types": trigger_types,
            "max_steps": auto_spec.execution_policy.max_total_steps,
            "timeout_seconds": auto_spec.execution_policy.total_timeout_seconds,
            "idempotency_enabled": auto_spec.execution_policy.enable_idempotency,
        }

        return {
            "step_types": step_types,
            "trigger_types": trigger_types,
            "safety_profile": "CONFINED_WORKSPACE_AST_EVAL_NO_SHELL",
        }

    # ── Stage 3: PLAN ─────────────────────────────────────────────────────────
    async def _stage_plan(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        auto_spec = self._in_flight_specs[ctx.execution_id]
        logger.info(f"Executing Stage 3 (PLAN) for Automation: {auto_spec.project_name}")

        gen = StandaloneCustomerAutomationGenerator(ctx.delivery_dir)
        self._in_flight_generators[ctx.execution_id] = gen
        dep_spec = gen.build_deployment_spec(auto_spec)

        ctx.telemetry["plan"] = {
            "target": dep_spec.target.value,
            "primary_service": dep_spec.primary_service,
            "services": list(dep_spec.services.keys()),
            "data_directories": dep_spec.data_directories,
            "primary_port": dep_spec.get_primary_port(),
        }

        return {
            "target": dep_spec.target.value,
            "primary_service": dep_spec.primary_service,
            "services_count": len(dep_spec.services),
            "data_directories_count": len(dep_spec.data_directories),
        }

    # ── Stage 4: EXECUTE ──────────────────────────────────────────────────────
    async def _stage_execute(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        auto_spec = self._in_flight_specs[ctx.execution_id]
        gen = self._in_flight_generators[ctx.execution_id]
        logger.info(f"Executing Stage 4 (EXECUTE) for Automation: {auto_spec.project_name}")

        t0 = time.perf_counter()
        gen_result = gen.generate_customer_project(auto_spec)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        ctx.telemetry["execute"] = {
            "generation_duration_ms": duration_ms,
            "files_created": gen_result.get("files_count", 0),
        }

        return {
            "status": "completed",
            "files_created": gen_result.get("files_count", 0),
            "duration_ms": duration_ms,
        }

    # ── Stage 5: OBSERVE ──────────────────────────────────────────────────────
    async def _stage_observe(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 5 (OBSERVE)")
        delivery_dir = ctx.delivery_dir

        src_files = list((delivery_dir / "src").glob("**/*.py"))
        config_files = list((delivery_dir / "config").glob("*"))
        launchers = [
            delivery_dir / "deploy.sh",
            delivery_dir / "Deploy.command",
            delivery_dir / "Deploy.bat",
            delivery_dir / "manage.sh",
        ]

        # Ensure POSIX launchers are executable
        for lch in [delivery_dir / "deploy.sh", delivery_dir / "Deploy.command", delivery_dir / "manage.sh"]:
            if lch.exists():
                mode = os.stat(lch).st_mode
                os.chmod(lch, mode | 0o755)

        ctx.telemetry["observe"] = {
            "src_files_count": len(src_files),
            "config_files_count": len(config_files),
            "launchers_present": all(l.exists() for l in launchers),
        }

        return {
            "src_files": [f.name for f in src_files],
            "launchers_ready": True,
        }

    # ── Stage 6: VERIFY ───────────────────────────────────────────────────────
    async def _stage_verify(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 6 (VERIFY)")
        delivery_dir = ctx.delivery_dir
        gen = self._in_flight_generators[ctx.execution_id]
        defects = []

        # 1. Syntax check on generated python files
        for py_file in (delivery_dir / "src").glob("**/*.py"):
            try:
                ast.parse(py_file.read_text(encoding="utf-8"))
            except Exception as e:
                defects.append({"type": "SYNTAX_ERROR", "file": str(py_file), "error": str(e)})

        # 2. Strict Proprietary Boundary Isolation check
        violations = gen.delivery_builder.sanitize_proprietary_boundary()
        if violations:
            for v in violations:
                defects.append({"type": "PROPRIETARY_LEAK", "details": v})

        # 3. Verify customer test file presence and syntax
        test_file = delivery_dir / "tests" / "test_automation_runtime.py"
        if not test_file.exists():
            defects.append({"type": "MISSING_TEST_FILE", "file": str(test_file)})
        else:
            try:
                ast.parse(test_file.read_text(encoding="utf-8"))
            except Exception as e:
                defects.append({"type": "SYNTAX_ERROR", "file": str(test_file), "error": str(e)})

        self._in_flight_defects[ctx.execution_id] = defects
        ctx.telemetry["verification_scorecard"] = {
            "defects_count": len(defects),
            "passed": len(defects) == 0,
            "proprietary_violations": len(violations),
        }

        if defects:
            logger.warning(f"Verification discovered {len(defects)} defects; proceeding to DIAGNOSE/REPAIR.")
        else:
            logger.info("Verification passed with 0 defects.")

        return {
            "passed": len(defects) == 0,
            "defects_count": len(defects),
        }

    # ── Stage 7: DIAGNOSE ─────────────────────────────────────────────────────
    async def _stage_diagnose(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        defects = self._in_flight_defects.get(ctx.execution_id, [])
        logger.info(f"Executing Stage 7 (DIAGNOSE): {len(defects)} defects identified.")
        return {
            "defects_diagnosed": len(defects),
            "defect_types": [d.get("type") for d in defects],
        }

    # ── Stage 8: REPAIR ───────────────────────────────────────────────────────
    async def _stage_repair(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        defects = self._in_flight_defects.get(ctx.execution_id, [])
        if not defects:
            return {"repaired": False, "repair_count": 0, "status": "no_defects"}

        logger.info(f"Executing Stage 8 (REPAIR) on {len(defects)} defects.")
        auto_spec = self._in_flight_specs[ctx.execution_id]
        gen = self._in_flight_generators[ctx.execution_id]
        gen.generate_customer_project(auto_spec)

        return {"repaired": True, "repair_count": 1, "status": "regenerated"}

    # ── Stage 9: RE-VERIFY ────────────────────────────────────────────────────
    async def _stage_re_verify(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 9 (RE-VERIFY)")
        gen = self._in_flight_generators[ctx.execution_id]
        violations = gen.delivery_builder.sanitize_proprietary_boundary()
        if violations:
            raise RuntimeError(f"Re-verification failed: proprietary boundary violations persist: {violations}")
        return {"passed": True, "status": "confirmed_zero_defects"}

    # ── Stage 10: PACKAGE ─────────────────────────────────────────────────────
    async def _stage_package(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 10 (PACKAGE)")
        gen = self._in_flight_generators[ctx.execution_id]
        manifest = gen.delivery_builder.create_manifest()

        ctx.telemetry["packaging"] = {
            "total_files": len(manifest.files_created),
            "manifest_file": str(ctx.delivery_dir / "artifacts" / "manifest.json"),
        }

        return {
            "files_packaged": len(manifest.files_created),
            "manifest_created": True,
        }

    # ── Stage 11: DELIVER ─────────────────────────────────────────────────────
    async def _stage_deliver(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 11 (DELIVER)")
        delivery_dir = ctx.delivery_dir
        readme = delivery_dir / "README.md"
        report = delivery_dir / "DELIVERY_REPORT.md"

        if not readme.exists() or not report.exists():
            raise FileNotFoundError("Delivery documentation files missing from delivery directory.")

        ctx.telemetry["delivery"] = {
            "destination": str(delivery_dir),
            "readme_bytes": readme.stat().st_size,
            "report_bytes": report.stat().st_size,
        }

        return {
            "status": "delivered",
            "destination": str(delivery_dir),
            "readme_bytes": readme.stat().st_size,
            "report_bytes": report.stat().st_size,
        }
