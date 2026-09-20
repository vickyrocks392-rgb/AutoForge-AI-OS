"""Code Migration / Refactoring Power Engine — Phase 18-COMMERCIAL-D Canonical Implementation."""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from autoforge_power_engines.base import PowerEngine, PowerEngineContext
from autoforge_power_engines.migration.spec import CustomerMigrationSpecification, ApprovalPolicy
from autoforge_power_engines.migration.safety import (
    safe_extract_archive,
    validate_path_confinement,
    SafeExecutionRunner,
)
from autoforge_power_engines.migration.inventory import CodebaseInventoryEngine, CodebaseInventory
from autoforge_power_engines.migration.analysis import SourceAnalyzer, SourceAnalysisReport
from autoforge_power_engines.migration.plan import MigrationPlanner, MigrationPlan, TransformationUnit
from autoforge_power_engines.migration.risk import MigrationRiskClassifier, MigrationRiskLevel, MigrationRiskAssessment
from autoforge_power_engines.migration.approval import ApprovalManager, ApprovalStatus
from autoforge_power_engines.migration.strategy import MigrationStrategyRegistry
from autoforge_power_engines.migration.transformation import TransformationPipeline, TransformationRecord
from autoforge_power_engines.migration.verifier import VerificationEngine, UnitVerificationReport, VerificationStatus
from autoforge_power_engines.migration.repair import BoundedRepairEngine, BoundedRepairReport
from autoforge_power_engines.migration.completeness import CompletenessAuditor, MigrationCompletenessManifest
from autoforge_power_engines.migration.telemetry import MigrationTelemetryCollector, PerformanceMetrics
from autoforge_power_engines.migration.generator import StandaloneCustomerMigrationGenerator
from autoforge_power_engines.risk import PowerEngineRiskEvaluator

logger = logging.getLogger("autoforge.power_engines.migration.engine")


class CodeMigrationPowerEngine(PowerEngine):
    """
    18-COMMERCIAL-D: Code Migration / Refactoring Power Engine.
    Autonomous turnkey engine for migrating, modernizing, and refactoring customer codebases.
    Executes the canonical 11-stage lifecycle.
    """

    def __init__(
        self,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        risk_evaluator: Optional[PowerEngineRiskEvaluator] = None,
        ai_inference_fn: Optional[Callable[[str], str]] = None,
    ):
        super().__init__(event_sink=event_sink, risk_evaluator=risk_evaluator)
        self.ai_inference_fn = ai_inference_fn
        # In-flight execution states keyed by execution_id
        self._in_flight_specs: Dict[str, CustomerMigrationSpecification] = {}
        self._in_flight_inventories: Dict[str, CodebaseInventory] = {}
        self._in_flight_analyses: Dict[str, SourceAnalysisReport] = {}
        self._in_flight_plans: Dict[str, MigrationPlan] = {}
        self._in_flight_verifications: Dict[str, Dict[str, UnitVerificationReport]] = {}
        self._in_flight_telemetry: Dict[str, MigrationTelemetryCollector] = {}
        self._in_flight_approvals: Dict[str, ApprovalManager] = {}
        self._in_flight_working_dirs: Dict[str, Path] = {}
        self._in_flight_target_dirs: Dict[str, Path] = {}

    def _resolve_spec(self, ctx: PowerEngineContext) -> CustomerMigrationSpecification:
        if isinstance(ctx.specification, CustomerMigrationSpecification):
            return ctx.specification
        raise TypeError(
            f"Expected CustomerMigrationSpecification, got {type(ctx.specification).__name__}"
        )

    # ── Stage 1: INTAKE & INVENTORY ───────────────────────────────────────────
    async def _stage_intake(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._resolve_spec(ctx)
        self._in_flight_specs[ctx.execution_id] = spec
        telemetry = MigrationTelemetryCollector(spec.migration_id)
        self._in_flight_telemetry[ctx.execution_id] = telemetry
        approval_mgr = ApprovalManager(spec.migration_id)
        self._in_flight_approvals[ctx.execution_id] = approval_mgr

        logger.info(f"Stage 1 (INTAKE): Starting migration intake for '{spec.project_name}'")

        # Setup isolated working directories inside ctx.output_root / ctx.project_id / "workspace"
        workspace_root = ctx.output_root / ctx.project_id / "workspace"
        working_dir = workspace_root / "working"
        source_input_dir = workspace_root / "customer_input"
        target_dir = workspace_root / "target"

        working_dir.mkdir(parents=True, exist_ok=True)
        source_input_dir.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        self._in_flight_working_dirs[ctx.execution_id] = working_dir
        self._in_flight_target_dirs[ctx.execution_id] = target_dir

        # Handle source input: extract archive or copy local directory
        source_root = source_input_dir
        if spec.source_archive:
            archive_path = Path(spec.source_archive).resolve()
            logger.info(f"Extracting source archive safely: {archive_path}")
            safe_extract_archive(archive_path, source_input_dir)
        elif spec.source_path:
            src_p = Path(spec.source_path).resolve()
            if src_p.is_dir():
                # Copy into isolated source_input_dir to protect customer original
                for item in src_p.iterdir():
                    dst = source_input_dir / item.name
                    if item.is_dir():
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.copytree(item, dst)
                    else:
                        shutil.copy2(item, dst)
            else:
                raise ValueError(f"Source path '{spec.source_path}' is not a directory.")
        else:
            raise ValueError("CustomerMigrationSpecification must provide source_path or source_archive.")

        # Execute deterministic Codebase Inventory
        inventory_engine = CodebaseInventoryEngine(
            root_dir=source_input_dir,
            excluded_patterns=spec.excluded_paths,
        )
        inventory = inventory_engine.analyze()
        self._in_flight_inventories[ctx.execution_id] = inventory

        telemetry.metrics.files_processed = inventory.total_files
        telemetry.metrics.source_loc = inventory.total_loc
        telemetry.metrics.source_nloc = inventory.total_nloc

        ctx.telemetry["inventory"] = {
            "total_files": inventory.total_files,
            "total_loc": inventory.total_loc,
            "total_nloc": inventory.total_nloc,
            "languages": list(inventory.language_breakdown.keys()),
            "entrypoints": inventory.entrypoints,
            "schemas": inventory.schema_artifacts,
        }

        return {
            "status": "accepted",
            "migration_id": spec.migration_id,
            "total_files": inventory.total_files,
            "total_loc": inventory.total_loc,
            "total_nloc": inventory.total_nloc,
        }

    # ── Stage 2: UNDERSTAND / ANALYZE ─────────────────────────────────────────
    async def _stage_understand_analyze(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        inventory = self._in_flight_inventories[ctx.execution_id]
        logger.info(f"Stage 2 (UNDERSTAND/ANALYZE): Analyzing codebase entities for '{spec.project_name}'")

        analyzer = SourceAnalyzer(inventory)
        analysis_report = analyzer.analyze()
        self._in_flight_analyses[ctx.execution_id] = analysis_report

        # Evaluate overall risk
        overall_risk = MigrationRiskClassifier.evaluate_overall(
            analysis_report=analysis_report,
            total_files=inventory.total_files,
            has_tests=bool(inventory.test_files),
        )

        ctx.telemetry["analysis"] = {
            "entities_count": len(analysis_report.entities),
            "dependencies_count": len(analysis_report.dependencies),
            "db_interactions_count": len(analysis_report.database_interactions),
            "overall_risk": overall_risk.risk_level.value,
            "risk_score": overall_risk.score,
        }

        return {
            "entities_count": len(analysis_report.entities),
            "dependencies_count": len(analysis_report.dependencies),
            "overall_risk": overall_risk.risk_level.value,
            "risk_score": overall_risk.score,
        }

    # ── Stage 3: PLAN ─────────────────────────────────────────────────────────
    async def _stage_plan(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        inventory = self._in_flight_inventories[ctx.execution_id]
        analysis = self._in_flight_analyses[ctx.execution_id]
        approval_mgr = self._in_flight_approvals[ctx.execution_id]
        logger.info(f"Stage 3 (PLAN): Formulating migration plan for '{spec.project_name}'")

        planner = MigrationPlanner(spec)
        plan = planner.build_plan(inventory, analysis)
        self._in_flight_plans[ctx.execution_id] = plan

        # Check for units requiring human approval
        for unit in plan.units:
            if unit.approval_required:
                approval_mgr.create_request(
                    target_path=unit.target_path,
                    risk_assessment=MigrationRiskAssessment(
                        risk_level=unit.risk_level,
                        score=7.5 if unit.risk_level == MigrationRiskLevel.CRITICAL else 5.0,
                        risk_factors=["High complexity or legacy financial/system construct"],
                        requires_human_approval=True,
                    ),
                    reason=f"Unit '{unit.source_path}' marked high risk ({unit.risk_level.value})",
                    unit_id=unit.unit_id,
                )

        ctx.telemetry["plan"] = {
            "total_units": plan.total_units,
            "high_risk_units": plan.high_risk_units_count,
            "requires_approval": plan.requires_approval_count,
            "execution_order": plan.execution_order,
        }

        return {
            "plan_id": plan.plan_id,
            "total_units": plan.total_units,
            "high_risk_units": plan.high_risk_units_count,
            "approval_required_units": plan.requires_approval_count,
        }

    # ── Stage 4: EXECUTE / TRANSFORM ──────────────────────────────────────────
    async def _stage_execute(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        inventory = self._in_flight_inventories[ctx.execution_id]
        plan = self._in_flight_plans[ctx.execution_id]
        telemetry = self._in_flight_telemetry[ctx.execution_id]
        working_dir = self._in_flight_working_dirs[ctx.execution_id]
        target_dir = self._in_flight_target_dirs[ctx.execution_id]
        source_input_dir = ctx.output_root / ctx.project_id / "workspace" / "customer_input"

        logger.info(f"Stage 4 (EXECUTE/TRANSFORM): Transforming {len(plan.units)} units for '{spec.project_name}'")

        pipeline = TransformationPipeline(
            source_root=source_input_dir,
            working_dir=working_dir,
            target_dir=target_dir,
        )

        records: List[TransformationRecord] = []
        trans_start = time.perf_counter()

        for unit in plan.units:
            rec = pipeline.transform_unit(unit, context={"spec": spec})
            records.append(rec)
            telemetry.record_trace(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_file=unit.target_path,
                stage="TRANSFORM",
                status="SUCCESS" if rec.success else "FAILED",
                duration_ms=rec.duration_ms,
                error_message=rec.error_message,
            )

        telemetry.metrics.transformation_time_s = time.perf_counter() - trans_start

        success_count = sum(1 for r in records if r.success)
        return {
            "units_transformed": len(records),
            "successful_units": success_count,
            "failed_units": len(records) - success_count,
        }

    # ── Stage 5: OBSERVE / BUILD ──────────────────────────────────────────────
    async def _stage_observe(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        plan = self._in_flight_plans[ctx.execution_id]
        target_dir = self._in_flight_target_dirs[ctx.execution_id]
        working_dir = self._in_flight_working_dirs[ctx.execution_id]
        telemetry = self._in_flight_telemetry[ctx.execution_id]

        logger.info(f"Stage 5 (OBSERVE/BUILD): Checking compilation and builds for '{spec.project_name}'")
        b_start = time.perf_counter()

        build_results = {}
        for unit in plan.units:
            target_p = target_dir / unit.target_path
            if target_p.exists() and not unit.transformation_type.value == "excluded":
                comp_check = VerificationEngine.check_compilation(
                    working_dir=target_dir,
                    target_path=target_p,
                    target_lang=unit.target_language,
                )
                build_results[unit.unit_id] = comp_check.status.value

        telemetry.metrics.build_time_s = time.perf_counter() - b_start
        return {
            "builds_evaluated": len(build_results),
            "status_summary": build_results,
        }

    # ── Stage 6: VERIFY ───────────────────────────────────────────────────────
    async def _stage_verify(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        plan = self._in_flight_plans[ctx.execution_id]
        target_dir = self._in_flight_target_dirs[ctx.execution_id]
        source_input_dir = ctx.output_root / ctx.project_id / "workspace" / "customer_input"
        telemetry = self._in_flight_telemetry[ctx.execution_id]

        logger.info(f"Stage 6 (VERIFY): Running deterministic verification and behavior tests")
        v_start = time.perf_counter()
        verifications: Dict[str, UnitVerificationReport] = {}

        for unit in plan.units:
            target_p = target_dir / unit.target_path
            source_p = source_input_dir / unit.source_path

            if unit.transformation_type.value == "excluded":
                verifications[unit.unit_id] = UnitVerificationReport(
                    unit_id=unit.unit_id,
                    source_file=unit.source_path,
                    target_file=unit.target_path,
                    overall_status=VerificationStatus.PASS,
                    diagnostics=[],
                )
                continue

            # Run behavioral equivalence via strategy
            strategy = MigrationStrategyRegistry.find_strategy(
                source_language=unit.source_language or "",
                target_language=unit.target_language,
            )
            beh_report = None
            if strategy and target_p.exists():
                src_text = source_p.read_text(encoding="utf-8", errors="replace") if source_p.exists() else ""
                tgt_text = target_p.read_text(encoding="utf-8", errors="replace")
                beh_report = strategy.verify_behavior(unit, src_text, tgt_text, context={})

            unit_report = VerificationEngine.verify_unit(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_path=target_p,
                target_lang=unit.target_language,
                working_dir=target_dir,
                behavior_report=beh_report,
            )
            verifications[unit.unit_id] = unit_report

            telemetry.record_trace(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_file=unit.target_path,
                stage="VERIFY",
                status=unit_report.overall_status.value,
                verification_verdict=unit_report.overall_status.value,
                error_message="; ".join(unit_report.diagnostics) if unit_report.diagnostics else None,
            )

        self._in_flight_verifications[ctx.execution_id] = verifications
        telemetry.metrics.verification_time_s = time.perf_counter() - v_start

        passed = sum(1 for r in verifications.values() if r.overall_status == VerificationStatus.PASS)
        failed = sum(1 for r in verifications.values() if r.overall_status == VerificationStatus.FAIL)
        inconclusive = sum(1 for r in verifications.values() if r.overall_status == VerificationStatus.INCONCLUSIVE)

        ctx.telemetry["verification_scorecard"] = {
            "passed": passed,
            "failed": failed,
            "inconclusive": inconclusive,
            "total": len(verifications),
        }

        return {
            "passed": passed,
            "failed": failed,
            "inconclusive": inconclusive,
            "total": len(verifications),
        }

    # ── Stage 7: DIAGNOSE ─────────────────────────────────────────────────────
    async def _stage_diagnose(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        verifications = self._in_flight_verifications.get(ctx.execution_id, {})
        failing_reports = [r for r in verifications.values() if r.overall_status == VerificationStatus.FAIL]

        diagnostics_map = {}
        for r in failing_reports:
            diagnostics_map[r.unit_id] = r.diagnostics

        logger.info(f"Stage 7 (DIAGNOSE): Diagnosed {len(failing_reports)} failing units")
        return {
            "failing_units_count": len(failing_reports),
            "diagnostics": diagnostics_map,
        }

    # ── Stage 8: REPAIR ───────────────────────────────────────────────────────
    async def _stage_repair(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        verifications = self._in_flight_verifications.get(ctx.execution_id, {})
        target_dir = self._in_flight_target_dirs[ctx.execution_id]
        plan = self._in_flight_plans[ctx.execution_id]
        telemetry = self._in_flight_telemetry[ctx.execution_id]

        failing_reports = [r for r in verifications.values() if r.overall_status == VerificationStatus.FAIL]
        if not failing_reports:
            return {"status": "skipped", "repaired": False, "repair_count": 0}

        logger.info(f"Stage 8 (REPAIR): Initiating bounded closed-loop repair on {len(failing_reports)} units")
        r_start = time.perf_counter()

        repair_engine = BoundedRepairEngine(max_iterations=spec.max_repair_iterations)
        repaired_count = 0

        for report in failing_reports:
            unit = next((u for u in plan.units if u.unit_id == report.unit_id), None)
            if not unit:
                continue
            target_p = target_dir / unit.target_path

            def verify_fn(p: Path) -> UnitVerificationReport:
                return VerificationEngine.verify_unit(
                    unit_id=unit.unit_id,
                    source_file=unit.source_path,
                    target_path=p,
                    target_lang=unit.target_language,
                    working_dir=target_dir,
                )

            res = repair_engine.execute_repair_loop(
                unit_id=unit.unit_id,
                target_path=target_p,
                target_lang=unit.target_language,
                initial_verification=report,
                verify_fn=verify_fn,
            )

            if res.repaired:
                repaired_count += 1
                verifications[unit.unit_id] = verify_fn(target_p)

            telemetry.record_trace(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_file=unit.target_path,
                stage="REPAIR",
                status="REPAIRED" if res.repaired else "EXHAUSTED",
                attempts=res.iterations_used,
                repair_attempts=res.iterations_used,
                verification_verdict=res.final_status.value,
                error_message=res.error_message,
            )

        telemetry.metrics.repair_time_s = time.perf_counter() - r_start
        return {
            "repaired": repaired_count > 0,
            "repair_count": repaired_count,
            "units_attempted": len(failing_reports),
        }

    # ── Stage 9: RE_VERIFY ────────────────────────────────────────────────────
    async def _stage_re_verify(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        verifications = self._in_flight_verifications.get(ctx.execution_id, {})
        logger.info(f"Stage 9 (RE_VERIFY): Final scorecard reconciliation")

        passed = sum(1 for r in verifications.values() if r.overall_status == VerificationStatus.PASS)
        failed = sum(1 for r in verifications.values() if r.overall_status == VerificationStatus.FAIL)
        inconclusive = sum(1 for r in verifications.values() if r.overall_status == VerificationStatus.INCONCLUSIVE)

        ctx.telemetry["verification_scorecard"] = {
            "passed": passed,
            "failed": failed,
            "inconclusive": inconclusive,
            "total": len(verifications),
        }

        return {
            "passed": passed,
            "failed": failed,
            "inconclusive": inconclusive,
            "status": "PASS" if failed == 0 else "FAIL",
        }

    # ── Stage 10: PACKAGE ─────────────────────────────────────────────────────
    async def _stage_package(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        inventory = self._in_flight_inventories[ctx.execution_id]
        plan = self._in_flight_plans[ctx.execution_id]
        verifications = self._in_flight_verifications[ctx.execution_id]
        target_dir = self._in_flight_target_dirs[ctx.execution_id]
        telemetry = self._in_flight_telemetry[ctx.execution_id]

        logger.info(f"Stage 10 (PACKAGE): Assembling customer delivery package at {ctx.delivery_dir}")
        pkg_start = time.perf_counter()

        # Audit completeness
        manifest = CompletenessAuditor.audit(
            inventory=inventory,
            plan=plan,
            verification_reports=verifications,
            target_dir=target_dir,
        )

        # Finalize metrics
        metrics = telemetry.finalize()

        # Build customer package via Generator
        generator = StandaloneCustomerMigrationGenerator(ctx.delivery_dir)
        pkg_result = generator.generate_customer_package(
            spec=spec,
            target_dir=target_dir,
            manifest=manifest,
            metrics=metrics,
            verification_summary=ctx.telemetry.get("verification_scorecard"),
        )

        telemetry.metrics.packaging_time_s = time.perf_counter() - pkg_start
        return {
            "status": "packaged",
            "delivery_dir": str(ctx.delivery_dir),
            "manifest_entries": len(manifest.entries),
            "completeness_pass": manifest.is_complete,
            "proprietary_violations": pkg_result.get("proprietary_violations_count", 0),
        }

    # ── Stage 11: DELIVER ─────────────────────────────────────────────────────
    async def _stage_deliver(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        spec = self._in_flight_specs[ctx.execution_id]
        telemetry = self._in_flight_telemetry[ctx.execution_id]
        metrics = telemetry.finalize()

        logger.info(f"Stage 11 (DELIVER): Verifying final delivery boundary for '{spec.project_name}'")

        # Sanitize delivery boundary
        generator = StandaloneCustomerMigrationGenerator(ctx.delivery_dir)
        violations = generator.delivery_builder.sanitize_proprietary_boundary()

        ctx.telemetry["final_telemetry"] = metrics.model_dump()

        return {
            "status": "delivered",
            "project_name": spec.project_name,
            "delivery_dir": str(ctx.delivery_dir),
            "proprietary_violations_count": len(violations),
            "migration_nloc_per_hour": metrics.migration_nloc_per_hour,
            "total_wall_time_s": metrics.total_wall_time_s,
        }
