"""Custom AI Agent Power Engine — Phase 18-COMMERCIAL-B Canonical Implementation."""

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
from autoforge_power_engines.agent.spec import CustomerAgentSpecification
from autoforge_power_engines.agent.generator import StandaloneCustomerAgentGenerator
from autoforge_power_engines.risk import PowerEngineRiskEvaluator

logger = logging.getLogger("autoforge.power_engines.agent.engine")


class CustomAIAgentPowerEngine(PowerEngine):
    """
    18-COMMERCIAL-B: Custom AI Agent Power Engine.
    Autonomous turnkey customer deliverable engine for self-deployable AI agents.
    Executes the canonical 11-stage lifecycle.
    """

    def __init__(
        self,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        risk_evaluator: Optional[PowerEngineRiskEvaluator] = None,
    ):
        super().__init__(event_sink=event_sink, risk_evaluator=risk_evaluator)
        self._in_flight_generators: Dict[str, StandaloneCustomerAgentGenerator] = {}
        self._in_flight_specs: Dict[str, CustomerAgentSpecification] = {}
        self._in_flight_defects: Dict[str, List[Any]] = {}

    def _resolve_spec(self, ctx: PowerEngineContext) -> CustomerAgentSpecification:
        if isinstance(ctx.specification, CustomerAgentSpecification):
            return ctx.specification
        # If generic CustomerProjectSpecification passed, adapt it
        custom = ctx.specification.custom_parameters or {}
        kwargs: Dict[str, Any] = {
            "project_name": ctx.specification.project_name,
            "project_description": ctx.specification.project_description,
            "agent_purpose": custom.get("agent_purpose", ctx.specification.project_description),
            "system_instructions": ctx.specification.desired_assistant_behavior,
            "allowed_tools": custom.get("allowed_tools", ["calculator", "current_time", "document_lookup", "file_read", "structured_http"]),
            "output_root": ctx.specification.output_root,
        }
        if "port" in custom:
            kwargs["port"] = int(custom["port"])
        if "host" in custom:
            kwargs["host"] = str(custom["host"])
        if "model_config_spec" in custom and isinstance(custom["model_config_spec"], dict):
            from autoforge_power_engines.agent.spec import AgentModelConfig
            kwargs["model_config_spec"] = AgentModelConfig(**custom["model_config_spec"])
        if "execution_limits" in custom and isinstance(custom["execution_limits"], dict):
            from autoforge_power_engines.agent.spec import ExecutionLimits
            kwargs["execution_limits"] = ExecutionLimits(**custom["execution_limits"])
        return CustomerAgentSpecification(**kwargs)

    # ── Stage 1: INTAKE ───────────────────────────────────────────────────────
    async def _stage_intake(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        agent_spec = self._resolve_spec(ctx)
        self._in_flight_specs[ctx.execution_id] = agent_spec
        logger.info(f"Executing Stage 1 (INTAKE) for Agent: {agent_spec.project_name}")

        if not agent_spec.agent_purpose or len(agent_spec.agent_purpose.strip()) < 5:
            raise ValueError("Customer specification missing meaningful agent_purpose.")
        if not agent_spec.system_instructions or len(agent_spec.system_instructions.strip()) < 10:
            raise ValueError("Customer specification missing meaningful system_instructions.")
        if agent_spec.model_config_spec.provider == "ollama":
            raise ValueError(
                "AutoForge frozen inference policy violation: provider 'ollama' is disabled. "
                "Use 'generic_http' targeting authorized MLX authority (http://127.0.0.1:19801/v1)."
            )

        ctx.telemetry["intake"] = {
            "project_name": agent_spec.project_name,
            "agent_purpose": agent_spec.agent_purpose,
            "model_name": agent_spec.model_config_spec.model_name,
            "provider": agent_spec.model_config_spec.provider,
            "tools_count": len(agent_spec.allowed_tools),
            "deny_shell": agent_spec.safety_constraints.deny_shell,
        }

        return {
            "status": "accepted",
            "project_name": agent_spec.project_name,
            "tools_declared": len(agent_spec.allowed_tools),
        }

    # ── Stage 2: UNDERSTAND / ANALYZE ─────────────────────────────────────────
    async def _stage_understand_analyze(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        agent_spec = self._in_flight_specs[ctx.execution_id]
        logger.info(f"Executing Stage 2 (UNDERSTAND/ANALYZE) for Agent: {agent_spec.project_name}")

        # Analyze tool requirements and model parameters
        declared_tools = agent_spec.tool_definitions
        tool_names = [t.name for t in declared_tools]

        ctx.telemetry["analysis"] = {
            "resolved_tools": tool_names,
            "system_instruction_chars": len(agent_spec.system_instructions),
            "estimated_tokens": len(agent_spec.system_instructions) // 4,
            "memory_type": agent_spec.memory_policy.persistence_type,
            "max_iterations": agent_spec.execution_limits.max_iterations,
        }

        return {
            "resolved_tools": tool_names,
            "memory_enabled": agent_spec.memory_policy.enabled,
            "safety_profile": "STRICT_SANDBOX_DENY_SHELL",
        }

    # ── Stage 3: PLAN ─────────────────────────────────────────────────────────
    async def _stage_plan(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        agent_spec = self._in_flight_specs[ctx.execution_id]
        logger.info(f"Executing Stage 3 (PLAN) for Agent: {agent_spec.project_name}")

        gen = StandaloneCustomerAgentGenerator(ctx.delivery_dir)
        self._in_flight_generators[ctx.execution_id] = gen
        dep_spec = gen.build_deployment_spec(agent_spec)

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
        agent_spec = self._in_flight_specs[ctx.execution_id]
        gen = self._in_flight_generators[ctx.execution_id]
        logger.info(f"Executing Stage 4 (EXECUTE) for Agent: {agent_spec.project_name}")

        t0 = time.perf_counter()
        gen_result = gen.generate_customer_project(agent_spec)
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

        src_files = list((delivery_dir / "src").glob("*.py"))
        config_files = list((delivery_dir / "config").glob("*"))
        launchers = [
            delivery_dir / "deploy.sh",
            delivery_dir / "Deploy.command",
            delivery_dir / "Deploy.bat",
            delivery_dir / "manage.sh",
        ]

        # Verify launchers are executable on POSIX
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
        for py_file in (delivery_dir / "src").glob("*.py"):
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
        test_file = delivery_dir / "tests" / "test_agent_runtime.py"
        if not test_file.exists():
            defects.append({"type": "MISSING_TEST_FILE", "file": str(test_file)})
        else:
            try:
                ast.parse(test_file.read_text(encoding="utf-8"))
            except Exception as e:
                defects.append({"type": "SYNTAX_ERROR", "file": str(test_file), "error": str(e)})

        # 4. Execute customer automated test suite
        import subprocess
        test_passed = False
        test_output = ""
        try:
            cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(delivery_dir / "tests"), "-p", "test_*.py"]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(delivery_dir)
            proc = subprocess.run(cmd, cwd=str(delivery_dir), env=env, capture_output=True, text=True, timeout=60.0)
            test_passed = (proc.returncode == 0)
            test_output = (proc.stderr or proc.stdout).strip()
            if not test_passed:
                defects.append({
                    "type": "TEST_FAILURE",
                    "file": str(test_file),
                    "error": test_output,
                })
        except Exception as e:
            defects.append({"type": "TEST_EXECUTION_ERROR", "error": str(e)})

        self._in_flight_defects[ctx.execution_id] = defects
        ctx.telemetry["verification_scorecard"] = {
            "defects_count": len(defects),
            "passed": len(defects) == 0,
            "proprietary_violations": len(violations),
            "customer_tests_passed": test_passed,
            "test_output": test_output,
        }

        if defects:
            logger.warning(f"Verification discovered {len(defects)} defects; proceeding to DIAGNOSE/REPAIR.")
        else:
            logger.info("Verification passed with 0 defects.")

        return {
            "passed": len(defects) == 0,
            "defects_count": len(defects),
            "customer_tests_passed": test_passed,
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
        # Regenerate clean files if defects found
        agent_spec = self._in_flight_specs[ctx.execution_id]
        gen = self._in_flight_generators[ctx.execution_id]
        gen.generate_customer_project(agent_spec)

        return {"repaired": True, "repair_count": 1, "status": "regenerated"}

    # ── Stage 9: RE-VERIFY ────────────────────────────────────────────────────
    async def _stage_re_verify(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 9 (RE-VERIFY)")
        delivery_dir = ctx.delivery_dir
        gen = self._in_flight_generators[ctx.execution_id]
        violations = gen.delivery_builder.sanitize_proprietary_boundary()
        if violations:
            raise RuntimeError(f"Re-verification failed: proprietary boundary violations persist: {violations}")

        # Re-run customer tests to confirm clean execution
        import subprocess
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(delivery_dir / "tests"), "-p", "test_*.py"]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(delivery_dir)
        proc = subprocess.run(cmd, cwd=str(delivery_dir), env=env, capture_output=True, text=True, timeout=60.0)
        if proc.returncode != 0:
            raise RuntimeError(f"Re-verification failed: customer tests failed: {proc.stderr or proc.stdout}")

        return {"passed": True, "status": "confirmed_zero_defects"}

    # ── Stage 10: PACKAGE ─────────────────────────────────────────────────────
    async def _stage_package(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 10 (PACKAGE)")
        gen = self._in_flight_generators[ctx.execution_id]

        # 1. Update manifest and checksums on disk with all deliverable artifacts
        manifest = gen.delivery_builder.create_manifest()
        (ctx.delivery_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (ctx.delivery_dir / "artifacts" / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        checksum_lines = [f"{sha}  {f}" for f, sha in manifest.sha256_checksums.items()]
        (ctx.delivery_dir / "artifacts" / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

        # 2. Package into a reproducible .tar.gz distribution archive
        archive_path, archive_sha = gen.delivery_builder.create_archive(reproducible=True)

        ctx.telemetry["packaging"] = {
            "total_files": len(manifest.files_created),
            "manifest_file": str(ctx.delivery_dir / "artifacts" / "manifest.json"),
            "archive_path": str(archive_path),
            "archive_sha256": archive_sha,
            "manifest_hash": manifest.manifest_signature or manifest.compute_manifest_hash(),
        }

        return {
            "files_packaged": len(manifest.files_created),
            "manifest_created": True,
            "archive_path": str(archive_path),
            "archive_sha256": archive_sha,
        }

    # ── Stage 11: DELIVER ─────────────────────────────────────────────────────
    async def _stage_deliver(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        logger.info("Executing Stage 11 (DELIVER)")
        delivery_dir = ctx.delivery_dir
        readme = delivery_dir / "README.md"
        report = delivery_dir / "DELIVERY_REPORT.md"
        sec_doc = delivery_dir / "SECURITY_AND_LIMITATIONS.md"

        if not readme.exists() or not report.exists():
            raise FileNotFoundError("Delivery documentation files missing from delivery directory.")

        gen = self._in_flight_generators[ctx.execution_id]
        violations = gen.delivery_builder.sanitize_proprietary_boundary()
        if violations:
            raise RuntimeError(f"Delivery blocked: proprietary boundary violations detected: {violations}")

        archive_path = ctx.delivery_dir.parent / f"{ctx.delivery_dir.name}.tar.gz"

        ctx.telemetry["delivery"] = {
            "destination": str(delivery_dir),
            "readme_bytes": readme.stat().st_size,
            "report_bytes": report.stat().st_size,
            "security_doc_bytes": sec_doc.stat().st_size if sec_doc.exists() else 0,
            "archive_path": str(archive_path) if archive_path.exists() else None,
            "status": "DELIVERED",
        }

        return {
            "status": "delivered",
            "destination": str(delivery_dir),
            "readme_bytes": readme.stat().st_size,
            "report_bytes": report.stat().st_size,
            "archive_path": str(archive_path) if archive_path.exists() else None,
        }
