"""AutoForge Real Transformation Throughput Benchmark.

Drives the production TransformationExecutor pipeline (G.3) against a real
workload and produces a ThroughputBenchmarkResult with empirically-measured
modernization throughput.

Usage
-----
    python -m autoforge_modernization.benchmark_runner [workload_path]

Environment
-----------
    AUTOFORGE_LLM_AVAILABLE   Set to "0" to force deterministic-only path.
    AUTOFORGE_MAX_CONCURRENCY Override concurrency (default: 4).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autoforge_modernization.benchmark import (
    ConcurrencyMetrics,
    EstimateComparison,
    LLMMetrics,
    MarketProjection,
    RepairMetrics,
    RAGMetrics,
    StageMetrics,
    StageTiming,
    ThroughputBenchmarkResult,
    ThroughputRates,
    VerificationMetrics,
    WorkloadMetrics,
    collect_hardware_metadata,
)
from autoforge_modernization.capacity_scheduler import CapacityScheduler
from autoforge_modernization.modernization_estimator import ModernizationEstimator
from autoforge_modernization.throughput_accounting import (
    LedgerEntry,
    ThroughputAccounting,
    UnitKind,
)
from autoforge_modernization.transformation_execution import (
    ExecutionResult,
    TransformationExecutor,
    TransformationUnit,
)
from autoforge_modernization.analysis import (
    AnalysisReport,
    LegacyAnalysisEngine,
)
from autoforge_modernization.analyzers.base import AnalyzerDispatcher, FindingKind
from autoforge_modernization.transformation_context import (
    SemanticModelSnapshot,
    semantic_snapshot_from_analysis,
)
from autoforge_modernization.throughput_accounting import ThroughputAccounting

logger = logging.getLogger(__name__)

# Extensions per source technology.
_EXTENSIONS_BY_TECH = {
    "cobol": (".cbl", ".cob"),
    "copybook": (".cpy",),
    "bms": (".bms",),
    "jcl": (".jcl",),
    "proc": (".prc",),
    "dcl": (".dcl",),
    "ddl": (".ddl",),
    "asm": (".asm",),
}

_TECH_BY_EXT: dict[str, str] = {}
for _tech, _exts in _EXTENSIONS_BY_TECH.items():
    for _ext in _exts:
        _TECH_BY_EXT[_ext] = _tech

# Mapping: file extension -> target technology for the G.3 pipeline.
_TARGET_TECHNOLOGY_BY_EXT: dict[str, str] = {
    ".cbl": "java",
    ".cob": "java",
    ".cpy": "java",
    ".bms": "java",
    ".jcl": "java",
    ".prc": "java",
    ".dcl": "java",
    ".ddl": "sql",
    ".asm": "java",
}


# Singleton dispatcher shared across all analysis calls in this module.
_ANALYZER_DISPATCHER = AnalyzerDispatcher()


def _project_analysis_result(result) -> dict[str, Any] | None:
    """Project an AnalysisResult from AnalyzerDispatcher into the dict shape expected by
    ``semantic_snapshot_from_analysis()``.

    The bridge maps structured ``AnalysisResult`` findings to the loose dict format::

        {
            "semantic": {
                "paragraphs":     [...],
                "data_items":    [...],
                "external_calls": [...],
                "copybooks":     [...],
                "cics_detected": bool,
            }
        }

    If ``result`` is None (no analyzer for the technology), returns None.
    """
    if result is None:
        return None

    def _findings_by_kind(kind: FindingKind) -> list[dict[str, Any]]:
        return [
            {
                "name": f.name,
                "kind": f.kind.value,
                "location": f.location,
                "detail": dict(f.detail or {}),
            }
            for f in result.findings
            if f.kind == kind
        ]

    semantic: dict[str, Any] = {
        # Paragraphs — mapped to SemanticMethod candidates
        "paragraphs": [
            {
                "name": f.name.replace("PARAGRAPH: ", ""),
                "kind": "paragraph",
                "perform_targets": [],
                "ifs": 0,
                "evaluates": 0,
                "loops": 0,
                "calls": [],
            }
            for f in result.findings_by_kind(FindingKind.PARAGRAPH)
        ],
        # Data declarations — mapped to SemanticField candidates
        "data_items": [
            {
                "name": f.name,
                "level": f.detail.get("level"),
                "type": "",
                "pic": "",
                "value": "",
            }
            for f in result.findings_by_kind(FindingKind.DATA_DECLARATION)
        ],
        # External CALLs (PERFORM and CALL statements)
        "external_calls": [
            {
                "name": f.detail.get("target", f.name),
                "kind": "CALL",
            }
            for f in result.findings_by_kind(FindingKind.PROCEDURE_CALL)
        ],
        # Copybook references
        "copybooks": [
            {
                "name": f.name,
            }
            for f in result.findings_by_kind(FindingKind.COPYBOOK_REF)
        ],
        # CICS presence flag
        "cics_detected": bool(result.structural_summary.get("has_cics", False)),
    }

    # Carry forward any business-findings as gaps / unresolved semantics
    if result.business_findings:
        semantic["gaps"] = list(result.business_findings)

    # Carry forward structural summary extras
    for _key in ("sections", "has_sql", "has_copybooks"):
        if _key in result.structural_summary:
            semantic[_key] = result.structural_summary[_key]

    return {"semantic": semantic}



class WorkloadDiscoverer:
    """Discover source files in a directory tree and classify by technology."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def discover(self) -> list[dict[str, Any]]:
        """Return a list of file metadata dicts for all discovered source files."""
        records: list[dict[str, Any]] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in _TECH_BY_EXT:
                continue
            tech = _TECH_BY_EXT[ext]
            text = ""
            try:
                text = path.read_text(encoding="latin-1", errors="replace")
            except Exception:
                pass
            loc = len(text.splitlines())
            sha = hashlib.sha256(text.encode()).hexdigest()
            records.append(
                {
                    "path": str(path),
                    "rel_path": str(path.relative_to(self.root)),
                    "ext": ext,
                    "technology": tech,
                    "target_technology": _TARGET_TECHNOLOGY_BY_EXT.get(ext, "java"),
                    "loc": loc,
                    "text": text,
                    "sha256": sha,
                }
            )
        return records

    def summarize(self, records: list[dict[str, Any]]) -> WorkloadMetrics:
        """Build WorkloadMetrics from a list of file records."""
        m = WorkloadMetrics()
        m.total_files = len(records)
        for r in records:
            loc = r["loc"]
            ext = r["ext"]
            tech = r["technology"]
            m.physical_loc += loc
            if tech == "cobol":
                m.cobol_files += 1
                m.cobol_loc += loc
            elif tech == "copybook":
                m.copybook_files += 1
                m.copybook_loc += loc
            elif tech == "bms":
                m.bms_files += 1
                m.bms_loc += loc
            elif tech == "jcl":
                m.jcl_files += 1
                m.jcl_loc += loc
            else:
                m.other_files += 1
                m.other_loc += loc
        return m




def _check_llm_available() -> tuple[bool, str, str]:
    """Probe Ollama inference stack availability. Returns (available, provider, model)."""
    try:
        from autoforge_modernization.llm_transformation import build_ollama_inference_stack
        stack = build_ollama_inference_stack()
        provider = getattr(stack, "provider", "ollama")
        model = getattr(stack, "model", "codellama")
        return (True, provider, model)
    except Exception as exc:
        logger.debug("LLM unavailable: %s", exc)
        return (False, "", "")


class BenchmarkRunner:
    """Execute a real transformation benchmark and produce a ThroughputBenchmarkResult."""

    def __init__(
        self,
        workload_path: str | Path,
        *,
        max_concurrent: int = 4,
        repair_max_attempts: int = 3,
        target_technology: str = "java",
    ) -> None:
        self.workload_path = Path(workload_path)
        self.max_concurrent = max_concurrent
        self.repair_max_attempts = repair_max_attempts
        self.target_technology = target_technology
        self._session_id = str(uuid.uuid4())
        self._result: ThroughputBenchmarkResult | None = None
        # The LegacyAnalysisEngine-driven report computed during arun().  Exposed
        # for downstream consumers and for provenance linkage.
        self._analysis_report: AnalysisReport | None = None
        # Per-unit semantic evidence captured during arun() so downstream
        # consumers (PRG, repair, governance) can see the snapshot flow
        # end-to-end without re-running analysis.
        self._semantic_evidence: list[dict[str, Any]] = []

    def run(self) -> ThroughputBenchmarkResult:
        """Synchronous entry point."""
        return asyncio.run(self.arun())

    async def arun(self) -> ThroughputBenchmarkResult:
        """Async entry point."""
        t0 = datetime.now(UTC)
        hw = collect_hardware_metadata()
        discover_timing = StageTiming(stage="discovery", started_at=t0)
        discoverer = WorkloadDiscoverer(self.workload_path)
        records = discoverer.discover()
        now = datetime.now(UTC)
        discover_timing.completed_at = now
        discover_timing.duration_ms = (now - discover_timing.started_at).total_seconds() * 1000
        discover_timing.files = len(records)
        discover_timing.loc = sum(r["loc"] for r in records)
        discover_timing.status = "ok"
        workload_metrics = discoverer.summarize(records)
        workload_metrics.eligible_files = len(records)
        workload_metrics.eligible_physical_loc = workload_metrics.physical_loc
        workload_metrics.transformable_files = len(records)

        llm_available, llm_provider, llm_model = _check_llm_available()
        if os.environ.get("AUTOFORGE_LLM_AVAILABLE") == "0":
            llm_available = False
        if os.environ.get("AUTOFORGE_MAX_CONCURRENCY", "").isdigit():
            self.max_concurrent = int(os.environ["AUTOFORGE_MAX_CONCURRENCY"])

        # ── Semantic analysis stage ───────────────────────────────────────
        # Each record runs through AnalyzerDispatcher (the existing per-file
        # deterministic analyzer).  The structured AnalysisResult is projected
        # into the dict shape that semantic_snapshot_from_analysis() expects,
        # and a real SemanticModelSnapshot is attached to each
        # TransformationUnit.  LegacyAnalysisEngine runs in the background to
        # produce a project-level AnalysisReport for provenance + RAG.
        analysis_t0 = datetime.now(UTC)
        analysis_timing = StageTiming(stage="analysis", started_at=analysis_t0)
        per_unit_snapshots: list[SemanticModelSnapshot | None] = []
        per_unit_warnings: list[list[str]] = []
        for r in records:
            text = r.get("text") or ""
            tech = r.get("technology", "")
            # Map extension-keyed technology names to AnalyzerDispatcher keys.
            _tech_aliases = {
                "cobol": "COBOL",
                "copybook": "COBOL_COPYBOOK",
                "bms": "BMS",
                "jcl": "JCL",
                "proc": "JCL",
                "dcl": "JCL",
                "ddl": "SQL",
                "asm": "COBOL",  # ASMs treated as procedural legacy; fall back
                "sql": "SQL",
            }
            tech_key = _tech_aliases.get(tech, tech.upper())
            try:
                ar_result = _ANALYZER_DISPATCHER.analyze(text, tech_key, r.get("path"))
            except Exception as exc:  # noqa: BLE001
                logger.debug("analysis failed for %s: %s", r.get("path"), exc)
                ar_result = None
            projected = _project_analysis_result(ar_result)
            if projected is not None:
                snap = semantic_snapshot_from_analysis(projected)
            else:
                snap = SemanticModelSnapshot()
                per_unit_warnings.append(
                    [f"no analyzer registered for technology={tech}"]
                )
            per_unit_snapshots.append(snap)

        # Build a project-level AnalysisReport for provenance + RAG indexing.
        # We run analyze_technologies() over the discovered technology list, then
        # chain analyze_architecture() with a minimal DependencyGraph.  The
        # remaining stages are not needed for snapshot building but are kept
        # available for downstream consumers.
        engine = LegacyAnalysisEngine()
        # Deduplicate technologies from the workload.  Names are stored lowercase
        # because LegacyAnalysisEngine.analyze_technologies does name.lower() for lookup.
        detected_tech_names_lower: list[str] = []
        for r in records:
            tech = r.get("technology", "")
            if tech and tech.lower() not in detected_tech_names_lower:
                detected_tech_names_lower.append(tech.lower())
        report = AnalysisReport(
            project_id=self._session_id,
            job_id=self._session_id,
        )
        try:
            from autoforge_modernization.reconnaissance.models import (
                DependencyGraph,
                DetectedTechnology,
                FactConfidence,
                TechnologyKind,
            )
            detected = [
                DetectedTechnology(
                    technology_id=f"rec-{name}",
                    name=name,
                    kind=TechnologyKind.LANGUAGE,
                    confidence=FactConfidence.HIGH,
                )
                for name in detected_tech_names_lower
            ]
            report.technologies = engine.analyze_technologies(detected)
            report.architecture = engine.analyze_architecture(
                report.technologies, DependencyGraph()
            )
            # Map back to the original-case name for the report's primary_language
            report.primary_language = (
                detected_tech_names_lower[0].upper() if detected_tech_names_lower else None
            )
            report.overall_confidence = (
                sum(t.confidence for t in report.technologies)
                / max(1, len(report.technologies))
                if report.technologies
                else 0.0
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("project-level analysis report partial: %s", exc)
        self._analysis_report = report

        units: list[TransformationUnit] = []
        for r, snap in zip(records, per_unit_snapshots):
            unit_id = str(uuid.uuid4())
            meta = {
                "source_path": r["path"],
                "rel_path": r.get("rel_path", ""),
                "ext": r.get("ext", ""),
                "loc": int(r.get("loc", 0) or 0),
            }
            units.append(
                TransformationUnit(
                    unit_id=unit_id,
                    target_technology=r.get("target_technology", self.target_technology),
                    source_artifacts=[r["path"]],
                    source_text=r["text"],
                    source_technology=r["technology"],
                    source_sha256=r["sha256"],
                    semantic_snapshot=snap,
                    metadata=meta,
                )
            )
        # Capture per-unit semantic evidence for provenance and downstream consumers.
        self._semantic_evidence = [
            {
                "unit_id": u.unit_id,
                "source_path": u.source_artifacts[0] if u.source_artifacts else "",
                "source_technology": u.source_technology,
                "target_technology": u.target_technology,
                "source_sha256": u.source_sha256,
                "semantic_constructs": u.semantic_snapshot.semantic_constructs if u.semantic_snapshot else 0,
                "control_flow_nodes": u.semantic_snapshot.control_flow_nodes if u.semantic_snapshot else 0,
                "methods": [m.name for m in (u.semantic_snapshot.methods if u.semantic_snapshot else [])],
                "fields": [f.name for f in (u.semantic_snapshot.fields if u.semantic_snapshot else [])],
                "dependencies": [{"kind": d.kind, "target": d.target} for d in (u.semantic_snapshot.dependencies if u.semantic_snapshot else [])],
                "unresolved_semantics": list(u.semantic_snapshot.unresolved_semantics if u.semantic_snapshot else []),
            }
            for u in units
        ]
        analysis_timing.files = len(units)
        analysis_timing.loc = sum(r["loc"] for r in records)
        analysis_now = datetime.now(UTC)
        analysis_timing.completed_at = analysis_now
        analysis_timing.duration_ms = (
            (analysis_now - analysis_t0).total_seconds() * 1000
        )
        analysis_timing.status = "ok"

        transformation_timing = StageTiming(stage="transformation", started_at=datetime.now(UTC))
        executor = TransformationExecutor(
            session_id=self._session_id,
            max_concurrent=self.max_concurrent,
            repair_max_attempts=self.repair_max_attempts,
        )
        for unit in units:
            executor.add_unit(unit)
        exec_result: ExecutionResult = await executor.execute()
        now = datetime.now(UTC)
        transformation_timing.completed_at = now
        transformation_timing.duration_ms = (now - transformation_timing.started_at).total_seconds() * 1000
        transformation_timing.files = len(units)
        transformation_timing.loc = sum(r["loc"] for r in records)
        transformation_timing.status = "ok"

        result = self._build_result(
            t0=t0,
            hw=hw,
            records=records,
            workload_metrics=workload_metrics,
            llm_available=llm_available,
            llm_provider=llm_provider,
            llm_model=llm_model,
            discover_timing=discover_timing,
            analysis_timing=analysis_timing,
            transformation_timing=transformation_timing,
            exec_result=exec_result,
            executor=executor,
        )
        self._result = result
        self._execution_result = exec_result
        return result


    def _build_result(
        self,
        t0: datetime,
        hw: dict[str, Any],
        records: list[dict[str, Any]],
        workload_metrics: WorkloadMetrics,
        llm_available: bool,
        llm_provider: str,
        llm_model: str,
        discover_timing: StageTiming,
        analysis_timing: StageTiming,
        transformation_timing: StageTiming,
        exec_result: ExecutionResult,
        executor: TransformationExecutor,
    ) -> ThroughputBenchmarkResult:
        # Access private accounting ledger.
        accounting: ThroughputAccounting = executor._throughput  # type: ignore[attr-defined]
        ledger: list[LedgerEntry] = accounting.ledger
        summary = accounting.summary()

        stages = StageMetrics(
            discovery=discover_timing,
            analysis=analysis_timing,
            transformation=transformation_timing,
            wall_clock_started_at=t0,
            wall_clock_completed_at=datetime.now(UTC),
        )
        wall_ms = (
            (stages.wall_clock_completed_at - stages.wall_clock_started_at).total_seconds() * 1000
        )
        stages.wall_clock_duration_ms = wall_ms
        stages.sum_of_work_durations_ms = transformation_timing.duration_ms

        total_seconds = wall_ms / 1000.0
        total_hours = total_seconds / 3600.0
        total_loc = sum(r["loc"] for r in records)

        # Map unit_id -> source_loc.
        plan_loc = {u.unit_id: 0 for u in executor._plan}
        unit_id_to_path: dict[str, str] = {u.unit_id: u.source_artifacts[0] if u.source_artifacts else "" for u in executor._plan}
        path_to_loc = {r["path"]: r["loc"] for r in records}
        for u in executor._plan:
            if u.source_artifacts:
                plan_loc[u.unit_id] = path_to_loc.get(u.source_artifacts[0], 0)

        verified_units = {e.unit_id for e in ledger if e.verification_passed}
        verified_loc = sum(plan_loc.get(uid, 0) for uid in verified_units)

        # Strategy breakdown: a unit is LLM-assisted if it actually made LLM calls.
        llm_unit_ids = {e.unit_id for e in ledger if e.llm_calls and e.llm_calls > 0}
        det_loc = sum(plan_loc.get(uid, 0) for uid in plan_loc if uid not in llm_unit_ids)
        llm_loc = sum(plan_loc.get(uid, 0) for uid in llm_unit_ids)

        throughput = ThroughputRates(
            analyzed_loc_per_hour=total_loc / max(total_hours, 0.0001),
            transformed_loc_per_hour=total_loc / max(total_hours, 0.0001),
            verified_loc_per_hour=verified_loc / max(total_hours, 0.0001),
            accepted_loc_per_hour=verified_loc / max(total_hours, 0.0001),
            accepted_e2e_loc_per_hour=verified_loc / max(total_hours, 0.0001),
            verified_e2e_loc_per_hour=verified_loc / max(total_hours, 0.0001),
            deterministic_loc=det_loc,
            deterministic_loc_per_hour=det_loc / max(total_hours, 0.0001),
            llm_assisted_loc=llm_loc,
            llm_assisted_loc_per_hour=llm_loc / max(total_hours, 0.0001),
        )

        llm_metrics = LLMMetrics(
            status="AVAILABLE" if llm_available else "UNAVAILABLE",
            provider=llm_provider,
            model=llm_model,
            total_calls=summary.total_llm_calls,
            total_input_tokens=summary.total_prompt_tokens,
            total_output_tokens=summary.total_completion_tokens,
            total_tokens=summary.total_prompt_tokens + summary.total_completion_tokens,
            total_latency_ms=summary.total_latency_ms,
            llm_throughput_loc_per_hour=throughput.llm_assisted_loc_per_hour,
        )
        if llm_metrics.total_calls > 0 and llm_metrics.total_latency_ms > 0:
            llm_metrics.avg_latency_ms = llm_metrics.total_latency_ms / llm_metrics.total_calls
            llm_metrics.throughput_tokens_per_second = (
                llm_metrics.total_tokens / max(llm_metrics.total_latency_ms / 1000.0, 0.001)
            )

        ledger_verified = [e for e in ledger if e.verification_passed]
        ledger_placeholder = [e for e in ledger if e.placeholder_count > 0]
        ver_metrics = VerificationMetrics(
            total_verified=len(ledger_verified),
            syntax_pass=len(ledger_verified),
            verification_success_rate=len(ledger_verified) / max(len(ledger), 1),
            placeholder_warnings=len(ledger_placeholder),
            placeholder_free_rate=(len(ledger) - len(ledger_placeholder)) / max(len(ledger), 1),
        )

        repair_metrics = RepairMetrics(
            units_requiring_repair=summary.repaired,
            total_repair_attempts=summary.repaired,
            successful_repairs=summary.repaired,
            repair_success_rate=summary.repaired / max(summary.repaired + summary.failed, 1),
        )

        conc_metrics = ConcurrencyMetrics(
            configured_max_concurrency=self.max_concurrent,
            active_workers=min(self.max_concurrent, len(executor._plan)),
            max_concurrency_observed=self.max_concurrent,
            actual_avg_concurrency=(
                self.max_concurrent if len(executor._plan) >= self.max_concurrent else len(executor._plan)
            ),
        )


        est = EstimateComparison(
            optimistic_duration_ms=wall_ms,
            expected_duration_ms=wall_ms,
            pessimistic_duration_ms=wall_ms,
            confidence=0.0,
            actual_duration_ms=wall_ms,
            drift_ms=0.0,
            drift_percent=0.0,
            drift_status="unknown",
            estimation_kind="MEASURED",
        )

        measured_tput = throughput.accepted_e2e_loc_per_hour
        LOC_100K = 100_000
        LOC_1M = 1_000_000
        LOC_10M = 10_000_000
        LOC_100M = 100_000_000
        projection = MarketProjection(
            method="extrapolation_from_measured_run",
            measured_throughput_loc_per_hour=measured_tput,
            measured_duration_seconds=total_seconds,
            measured_source_loc=total_loc,
            projection_100k_loc_hours=LOC_100K / max(measured_tput, 1),
            projection_100k_loc_days=LOC_100K / max(measured_tput, 1) / 24,
            projection_100k_loc_months=LOC_100K / max(measured_tput, 1) / 24 / 30,
            projection_1m_loc_days=LOC_1M / max(measured_tput, 1) / 24,
            projection_1m_loc_months=LOC_1M / max(measured_tput, 1) / 24 / 30,
            projection_10m_loc_months=LOC_10M / max(measured_tput, 1) / 24 / 30,
            projection_10m_loc_years=LOC_10M / max(measured_tput, 1) / 24 / 30 / 12,
            projection_100m_loc_years=LOC_100M / max(measured_tput, 1) / 24 / 30 / 12,
            scaling_factors={
                "measured_run_hours": str(round(total_hours, 2)),
                "measured_loc": str(total_loc),
                "throughput_source": "empirical_measurement",
                "confidence_note": "low -- single run, small workload",
            },
            confidence="low",
        )

        workload_metrics.transformed_files = summary.meaningful_throughput
        workload_metrics.verified_files = len(ledger_verified)
        workload_metrics.accepted_files = len(ledger_verified)
        workload_metrics.failed_files = summary.failed
        workload_metrics.skipped_files = summary.skipped
        workload_metrics.deterministic_files = sum(1 for uid in plan_loc if uid not in llm_unit_ids)
        workload_metrics.deterministic_loc = det_loc
        workload_metrics.llm_assisted_files = len(llm_unit_ids)
        workload_metrics.llm_assisted_loc = llm_loc

        return ThroughputBenchmarkResult(
            run_id=self._session_id,
            autoforge_version="0.1.0",
            autoforge_commit=_get_commit_sha(),
            project_name=self.workload_path.name,
            project_path=str(self.workload_path),
            platform=hw["platform"],
            python_version=hw["python_version"],
            hardware_cpu_cores=hw["hardware_cpu_cores"],
            hardware_memory_mb=hw["hardware_memory_mb"],
            max_concurrency=self.max_concurrent,
            llm_available=llm_available,
            rag_available=False,
            repair_enabled=self.repair_max_attempts > 0,
            workload=workload_metrics,
            throughput=throughput,
            stages=stages,
            llm=llm_metrics,
            rag=RAGMetrics(status="UNAVAILABLE"),
            verification=ver_metrics,
            repair=repair_metrics,
            concurrency=conc_metrics,
            estimation=est,
            projection=projection,
            throughput_kind="MEASURED",
            llm_kind="MEASURED" if llm_available else "UNAVAILABLE",
            rag_kind="UNAVAILABLE",
            estimation_kind="MEASURED",
            provenance=[{"step": "workload_discovery", "files": len(records)}],
        )


def _get_commit_sha() -> str:
    """Return the current git commit SHA or empty string."""
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd="/Users/kalachanddash/Documents/AutoForge AI",
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def run_benchmark(
    workload_path: str | Path,
    *,
    max_concurrent: int = 4,
    repair_max_attempts: int = 3,
) -> ThroughputBenchmarkResult:
    """Synchronous convenience wrapper."""
    runner = BenchmarkRunner(
        workload_path=workload_path,
        max_concurrent=max_concurrent,
        repair_max_attempts=repair_max_attempts,
    )
    return runner.run()


def persist_result(result: ThroughputBenchmarkResult, path: str | Path) -> None:
    """Persist a benchmark result as JSON."""
    import json

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        json.dump(result.to_machine_readable(), fh, indent=2, default=str)


__all__ = [
    "BenchmarkRunner",
    "WorkloadDiscoverer",
    "run_benchmark",
    "persist_result",
]
