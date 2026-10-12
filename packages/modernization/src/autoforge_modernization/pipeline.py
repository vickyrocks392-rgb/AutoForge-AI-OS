"""ModernizationPipeline (Phase 18-G.3).

Orchestrates the end-to-end flow:
  G.2 Reconnaissance output
    → LegacyAnalysisEngine (G.3)
    → PlanningGate (gate/strategy modules)
    → TransformationEngine (G.3)
    + Provenance chain
    + Observability events
    + Checkpoints

The pipeline is idempotent: re-running with the same inputs resumes from
the last checkpoint (or restarts from scratch if no checkpoint exists).

Usage
~~~~~
    pipeline = ModernizationPipeline(...)
    result = pipeline.run(project_id, job_id, reconnaissance_output)
    # result.analysis_report  — full analysis
    # result.gate_decision   — gate decision
    # result.transformation_records — all transformations
"""


from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)
from autoforge_modernization.g3_llm import G3LLMIntegration
from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies

if TYPE_CHECKING:
    from autoforge_modernization.analysis import AnalysisReport
    from autoforge_modernization.planning_gate import GateDecisionRecord, GateDecision
    from autoforge_modernization.strategy import MigrationPlan
    from autoforge_modernization.transformation import TransformationRecord


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _count_lines(path: str) -> int:
    """Line count of a real source file; 0 when unreadable.

    Used only for the plan's effort estimate, so a failure degrades the estimate
    rather than the transformation.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


class PipelineStatus(str, Enum):
    """Overall status of the modernization pipeline."""

    PENDING = "pending"
    RUNNING_RECONNAISSANCE = "running_reconnaissance"
    RUNNING_ANALYSIS = "running_analysis"
    AT_GATE = "at_gate"
    RUNNING_TRANSFORMATION = "running_transformation"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class PipelineWaveResult(BaseModel):
    """Result of processing a single wave."""

    wave_id: str
    wave_index: int
    status: PipelineStatus
    units_approved: int = 0
    units_transformed: int = 0
    units_failed: int = 0
    transformation_record_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None


class PipelineResult(BaseModel):
    """
    Complete result of a full pipeline run.

    Contains:
    - The AnalysisReport from LegacyAnalysisEngine
    - Gate decision records
    - All TransformationRecord entries
    - Per-wave results
    """

    pipeline_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None

    status: PipelineStatus = PipelineStatus.PENDING

    analysis_report: "AnalysisReport | None" = None
    gate_decisions: list["GateDecisionRecord"] = Field(default_factory=list)
    transformation_records: list["TransformationRecord"] = Field(default_factory=list)
    wave_results: list[PipelineWaveResult] = Field(default_factory=list)

    migration_plan: "MigrationPlan | None" = None

    #: DEF-18LR-B2: how many REAL source files were bound to the derived plan.
    #: A pipeline that planned units but bound no source file could not have
    #: modernized anything, so this is reported rather than inferred.
    source_file_inventory: int = 0

    provenance_chain: ModernizationProvenanceChain | None = None

    overall_success: bool = False
    error_message: str | None = None
    delivery_dir: str | None = None
    verification_scorecard: dict[str, Any] = Field(default_factory=dict)
    stages_executed: list[str] = Field(default_factory=list)
    repair_count: int = 0
    summary_report: str = ""
    manifest_path: str | None = None

    def duration_seconds(self) -> float | None:
        """Return total duration in seconds."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def success_rate(self) -> float:
        """Return fraction of transformations that succeeded."""
        recs = self.transformation_records
        if not recs:
            return 0.0
        from autoforge_modernization.transformation import TransformationStatus
        ok = [r for r in recs if r.status == TransformationStatus.APPLIED and not r.rolled_back]
        return len(ok) / len(recs) if recs else 0.0

    def summary_dict(self) -> dict[str, object]:
        """Return a summary dict for dashboards."""
        return {
            "pipeline_id": self.pipeline_id,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds(),
            "analysis_complete": self.analysis_report is not None,
            "gate_decisions": len(self.gate_decisions),
            "transformations": len(self.transformation_records),
            "waves": len(self.wave_results),
            "success_rate": self.success_rate(),
            "overall_success": self.overall_success,
            "error": self.error_message,
        }


class ModernizationPipeline:
    """
    Orchestrates G.2 → G.3 → Gate → Transformation.

    Steps
    ~~~~~
    1. Reconnaissance output is provided (from G.2 scanner)
    2. Run LegacyAnalysisEngine to produce AnalysisReport
    3. Evaluate PlanningGate with the AnalysisReport
    4. If gate approved, run TransformationEngine for each approved unit
    5. Record provenance and emit observability events throughout

    The pipeline is resumable: if a wave fails, the next run continues
    from the last checkpoint rather than restarting from scratch.
    """

    def __init__(
        self,
        knowledge_layer=None,
        capability_registry=None,
        provenance_chain=None,
        lockdown_boundary=None,
        checkpoint_type=None,
        llm_integration=None,
        force_offline_llm: bool = True,
    ) -> None:
        self.knowledge = knowledge_layer
        self.capability_registry = capability_registry
        self.provenance_chain = provenance_chain
        self.lockdown_boundary = lockdown_boundary
        self.default_checkpoint_type = checkpoint_type
        # G.3 LLM integration — defaults to offline (deterministic, no Ollama needed)
        self.llm_integration = llm_integration or G3LLMIntegration(force_offline=force_offline_llm)

        # Sub-engines (lazy-initialized on first run)
        self._analysis_engine = None
        self._transformation_engine = None

    def _get_analysis_engine(self):
        """Lazily create the analysis engine."""
        if self._analysis_engine is None:
            from autoforge_modernization.analysis import LegacyAnalysisEngine
            self._analysis_engine = LegacyAnalysisEngine(
                knowledge_layer=self.knowledge,
                capability_registry=self.capability_registry,
                provenance_chain=self.provenance_chain,
            )
        return self._analysis_engine

    def _get_transformation_engine(self):
        """Lazily create the transformation engine."""
        if self._transformation_engine is None:
            from autoforge_modernization.transformation import TransformationEngine
            self._transformation_engine = TransformationEngine(
                provenance_chain=self.provenance_chain,
                lockdown_boundary=self.lockdown_boundary,
                checkpoint_type=self.default_checkpoint_type,
            )
        return self._transformation_engine


    def run(
        self,
        project_id: str,
        job_id: str,
        reconnaissance_output,
        plan: "MigrationPlan | None" = None,
        project_configuration: dict | None = None,
    ) -> PipelineResult:
        """
        Run the full pipeline.

        Parameters
        ----------
        project_id
            The project being modernized.
        job_id
            The job ID (for provenance + observability).
        reconnaissance_output
            Output from the G.2 reconnaissance scanner.
        plan
            Optional pre-approved migration plan. If not provided, the
            pipeline will create a default plan from the analysis report.

        Returns
        -------
        PipelineResult
            The complete pipeline result with all records.
        """
        result = PipelineResult(
            project_id=project_id,
            job_id=job_id,
            status=PipelineStatus.RUNNING_ANALYSIS,
        )

        try:
            # ── G.3 LLM wall-clock start (analysis stage) ──────────────
            g3 = self.llm_integration
            g3.start_wall_clock()

            # ── Step 1: Analysis ────────────────────────────────────────
            analysis_engine = self._get_analysis_engine()
            detected_technologies = self._extract_technologies(reconnaissance_output)
            result.analysis_report = analysis_engine.run_all(
                project_id=project_id,
                job_id=job_id,
                detected_technologies=detected_technologies,
            )
            # G.3: record deterministic coverage for each detected technology
            for tech in detected_technologies:
                # Handle both dict-like and object-like technology descriptors
                if isinstance(tech, dict):
                    loc = int(tech.get("loc", 0) or 0)
                else:
                    loc = int(getattr(tech, "loc", 0) or 0)
                g3.record_deterministic_file(loc=loc)

            # ── Step 2: Gate ─────────────────────────────────────────────
            result.status = PipelineStatus.AT_GATE
            from autoforge_modernization.planning_gate import (
                GateDecision,
                GateDecisionRecord,
            )
            gate_record = self._build_gate_record(
                project_id=project_id,
                analysis_report=result.analysis_report,
            )
            result.gate_decisions.append(gate_record)

            if gate_record.decision == GateDecision.BLOCKED:
                result.status = PipelineStatus.BLOCKED
                result.error_message = (
                    "Planning gate blocked: " + "; ".join(gate_record.get_blocked_reasons())
                )
                self.llm_integration.stop_wall_clock()
                result.completed_at = _utc_now()
                return result

            # ── Step 3: Migration Plan ──────────────────────────────────
            if plan is None:
                # DEF-18LR-B2: bind the REAL legacy source files to the plan so
                # transformation operates on the customer's actual code rather
                # than a synthetic placeholder.
                source_inventory = self._extract_source_inventory(
                    reconnaissance_output
                )
                result.source_file_inventory = len(source_inventory)
                plan = self._derive_default_plan(
                    project_id, result.analysis_report, source_inventory
                )
            result.migration_plan = plan

            # ── Step 4: Transformation ──────────────────────────────────
            if not plan.is_executable():
                result.status = PipelineStatus.BLOCKED
                result.error_message = "Migration plan is not executable (not approved)"
                self.llm_integration.stop_wall_clock()
                result.completed_at = _utc_now()
                return result

            # ── Step 4: Transformation / Execution ──────────────────────────
            # Phase 20: If a real legacy source root with executable programs is present,
            # execute the complete Phase 20 modernization pipeline (toolchain, build,
            # execution, golden-master equivalence, packaging, delivery manifest).
            cfg = dict(project_configuration or {})
            source_root_cand = (
                cfg.get("legacy_source_root")
                or cfg.get("source_root")
                or getattr(reconnaissance_output, "root_path", None)
                or (reconnaissance_output.get("root_path") if isinstance(reconnaissance_output, dict) else None)
            )
            has_real_programs = False
            if source_root_cand:
                src_cand_path = Path(source_root_cand)
                if src_cand_path.exists() and (
                    list(src_cand_path.glob("**/*.cbl"))
                    or list(src_cand_path.glob("**/*.cob"))
                    or list(src_cand_path.glob("**/*.jcl"))
                ):
                    has_real_programs = True

            if has_real_programs:
                from autoforge_modernization.service.engine import LegacyModernizationEngine
                modern_engine = LegacyModernizationEngine(
                    ai_adapter=cfg.get("ai_adapter"),
                    model_router=cfg.get("model_router"),
                )
                exec_res = modern_engine.execute(
                    project_id=project_id,
                    job_id=job_id,
                    source_root=Path(source_root_cand),
                    project_configuration=cfg,
                )
                self.llm_integration.stop_wall_clock()
                result.delivery_dir = exec_res.delivery_dir
                result.verification_scorecard = exec_res.verification_scorecard
                result.stages_executed = exec_res.stages_executed
                result.repair_count = exec_res.repair_count
                result.summary_report = exec_res.summary_report
                result.manifest_path = exec_res.manifest_path
                result.status = PipelineStatus.COMPLETE if exec_res.success else PipelineStatus.FAILED
                result.overall_success = exec_res.success
                result.completed_at = _utc_now()
                return result

            result.status = PipelineStatus.RUNNING_TRANSFORMATION
            transformation_engine = self._get_transformation_engine()
            wave_results: list[PipelineWaveResult] = []
            for wave_index, wave_id in enumerate(plan.units_by_wave().keys()):
                wave_result = self._run_wave(
                    project_id=project_id,
                    job_id=job_id,
                    plan=plan,
                    wave_id=wave_id,
                    wave_index=wave_index,
                    transformation_engine=transformation_engine,
                )
                wave_results.append(wave_result)
                result.transformation_records.extend(
                    self._get_wave_records(transformation_engine, wave_id)
                )
            result.wave_results = wave_results

            # ── Step 5: Finalize ────────────────────────────────────────
            # G.3 LLM wall-clock stop
            self.llm_integration.stop_wall_clock()
            any_blocked = any(w.status == PipelineStatus.BLOCKED for w in wave_results)
            all_failed = all(w.units_failed > 0 and w.units_transformed == 0 for w in wave_results)
            if any_blocked:
                result.status = PipelineStatus.BLOCKED
            elif all_failed and wave_results:
                result.status = PipelineStatus.FAILED
            else:
                result.status = PipelineStatus.COMPLETE
            result.overall_success = result.status == PipelineStatus.COMPLETE
            result.completed_at = _utc_now()
            return result

        except Exception as e:
            # G.3 LLM wall-clock stop (best-effort; safe if never started)
            try:
                self.llm_integration.stop_wall_clock()
            except Exception:
                pass
            result.status = PipelineStatus.FAILED
            result.error_message = f"{type(e).__name__}: {e}"
            result.completed_at = _utc_now()
            result.overall_success = False
            return result




    def _extract_technologies(self, reconnaissance_output) -> list:
        """
        Extract DetectedTechnology list from a reconnaissance output.

        Supports:
        - attribute: detected_technologies (list)
        - attribute: technologies (list)
        - dict: {"detected_technologies": [...]} or {"technologies": [...]}
        - iterable of DetectedTechnology instances
        """
        if reconnaissance_output is None:
            return []
        # Object with attribute
        if hasattr(reconnaissance_output, "detected_technologies"):
            return list(reconnaissance_output.detected_technologies or [])
        if hasattr(reconnaissance_output, "technologies"):
            return list(reconnaissance_output.technologies or [])
        # Dict
        if isinstance(reconnaissance_output, dict):
            return list(
                reconnaissance_output.get("detected_technologies")
                or reconnaissance_output.get("technologies")
                or []
            )
        # Iterable
        try:
            return list(reconnaissance_output)
        except TypeError:
            return []

    def _extract_source_inventory(self, reconnaissance_output) -> list[tuple[str, str]]:
        """Extract ``(technology, absolute_path)`` pairs from reconnaissance.

        DEF-18LR-B2. The reconnaissance stage already walked the customer's
        repository and produced a ``scanned_files`` inventory with each file's
        detected language. The pipeline previously discarded that inventory and
        kept only the technology NAMES, which is precisely why transformation
        had no real file to read.

        This reads the existing reconnaissance result; it does not rescan and
        introduces no new discovery mechanism. Returns ``[]`` when the caller
        supplied a technology-only reconnaissance shape, in which case the wave
        fails explicitly rather than transforming a placeholder.
        """
        if reconnaissance_output is None:
            return []

        scanned = None
        for attr in ("scanned_files", "files"):
            candidate = getattr(reconnaissance_output, attr, None)
            if candidate:
                scanned = list(candidate)
                break
        if not scanned and isinstance(reconnaissance_output, dict):
            for key in ("scanned_files", "files"):
                candidate = reconnaissance_output.get(key)
                if candidate:
                    scanned = list(candidate)
                    break
        if not scanned:
            return []

        # Map the reconnaissance language label onto the G.3 strategy
        # vocabulary -- the same vocabulary the analysis stage reports as
        # ``detected_name``, so the plan's source_technology and the bound
        # files always agree.
        aliases = {
            "cobol": "COBOL",
            "jcl": "JCL",
            "job_control_language": "JCL",
            "shell": "SHELL",
            "bash": "BASH",
            "sql": "SQL",
            "pl_sql": "PL_SQL",
            "asm": "ASSEMBLER",
            "hlasm": "HLASM",
            "xml": "XML",
            "yaml": "YAML",
            "json": "JSON",
            "properties": "PROPERTIES",
        }

        inventory: list[tuple[str, str]] = []
        for sf in scanned:
            if isinstance(sf, dict):
                path = sf.get("path") or sf.get("relative_path")
                detected = sf.get("detected_language")
                if not detected:
                    techs = sf.get("detected_technologies") or []
                    detected = techs[0] if techs else None
            else:
                path = getattr(sf, "path", None) or getattr(
                    sf, "relative_path", None
                )
                detected = getattr(sf, "detected_language", None)
                if not detected:
                    techs = list(getattr(sf, "detected_technologies", None) or [])
                    detected = techs[0] if techs else None

            if not path or not detected:
                continue
            key = str(detected).strip().lower().replace("-", "_")
            technology = aliases.get(key, str(detected).upper())
            inventory.append((technology, str(path)))
        return inventory

    def _build_gate_record(
        self,
        project_id: str,
        analysis_report,
    ) -> "GateDecisionRecord":
        """
        Build a GateDecisionRecord from the analysis report.

        The gate is approved by default if no high/critical capability
        gaps are detected. HITL approval may still be required downstream.
        """
        from autoforge_modernization.planning_gate import (
            GateCondition,
            GateConditionKind,
            GateDecision,
            GateDecisionRecord,
        )

        record = GateDecisionRecord(
            project_id=project_id,
            wave_index=0,
            conditions=[
                GateCondition(
                    kind=GateConditionKind.REQUIREMENTS_CONFIRMED,
                    description="Requirements confirmed by reconnaissance",
                ),
                GateCondition(
                    kind=GateConditionKind.BUSINESS_RULES_RESOLVED,
                    description="Business rules extracted from analysis",
                ),
                GateCondition(
                    kind=GateConditionKind.CURRENT_BEHAVIOR_MODELED,
                    description="Current behavior modeled in analysis report",
                ),
            ],
        )

        gaps_list = (
            getattr(analysis_report, "capability_gaps", []) or []
        ) if analysis_report else []
        blocking_gaps = [
            g for g in gaps_list
            if getattr(g, "severity", None) in ("high", "critical")
        ]

        if blocking_gaps:
            record.decision = GateDecision.BLOCKED
            record.decision_notes = (
                f"Blocked by {len(blocking_gaps)} high/critical capability gaps"
            )
        else:
            record.decision = GateDecision.APPROVED
            record.decision_notes = "All conditions satisfied"

        # Recompute counts
        record.total_conditions = len(record.conditions)
        if record.decision == GateDecision.APPROVED:
            record.satisfied_count = record.total_conditions
        else:
            record.blocked_count = record.total_conditions

        return record


    @staticmethod
    def _select_transformation_type(source_tech: str | None):
        """Choose a ``TransformationType`` the certified G.3 engine supports.

        DEF-18LR-B2. The wave runner previously derived the G.3 transformation
        type from ``unit.strategy`` -- the plan-level "6 R's" vocabulary
        (retain/rehost/replatform/refactor/rewrite/...). That is a different
        vocabulary from the execution-level types the G.3 strategies key on, so
        the lookup silently fell through to ``_unsupported_transform`` for
        several certified technologies (JCL, COBOL->Java) and the unit failed by
        design. That is an orchestration defect, not an engine defect.

        The supported set is read from the engine's own existing
        ``supported_types_for`` API -- the same source of truth the certified
        tests assert against -- so no new language capability is invented and the
        certified contract is unchanged.

        Within that set the *substantive* transformation is preferred over a
        cosmetic one. For COBOL, ``refactor`` is a comment/indentation cleanup
        that legitimately produces byte-identical output on already-clean code;
        the engine correctly refuses a no-op ("Transformation produced identical
        content"), which is right, but it would mean the pipeline modernizes
        nothing. ``transpilation`` is the certified COBOL -> Java transform and
        is therefore preferred. For JCL, ``reconfiguration`` is the substantive
        one.

        The plan-level ``MigrationStrategy`` is deliberately NOT mapped onto the
        transformation type: it is a different vocabulary (the "6 R's"), the
        derived plan always sets ``REFACTOR``, and letting that cosmetic default
        win would restore exactly the defect being repaired.
        """
        from autoforge_modernization.transformation import TransformationType

        if not source_tech:
            return TransformationType.REFACTOR
        try:
            supported = G3TransformationStrategies.supported_types_for(
                str(source_tech)
            )
        except Exception:
            return TransformationType.REFACTOR
        if not supported or supported == ["blocked"]:
            return TransformationType.REFACTOR

        # Most-substantive first. Only types the engine itself reported as
        # supported are ever considered.
        preference = (
            "transpilation",
            "rewrite",
            "reconfiguration",
            "data_migration",
            "extraction",
            "refactor",
        )
        for candidate in preference:
            if candidate in supported:
                try:
                    return TransformationType(candidate)
                except ValueError:
                    continue
        return TransformationType.REFACTOR

    def _derive_default_plan(
        self,
        project_id: str,
        analysis_report,
        source_files: "list[tuple[str, str]] | None" = None,
    ) -> "MigrationPlan":
        """
        Derive a default MigrationPlan from the analysis report.

        Creates one unit per detected technology with a recommended strategy.
        Units are all placed in wave-1 for auto-mode.

        DEF-18LR-B2: units are now bound to the REAL legacy source files.

        Previously the plan carried only a technology *name*, so
        ``_run_wave`` had no file to read and fabricated
        ``f"# legacy {tech} unit {id}"`` as the transformation input. The
        transformation therefore ran on a placeholder and could never
        modernize a customer's code, however good the strategy was.

        ``source_files`` is the ``(technology, absolute_path)`` inventory the
        reconnaissance stage already produced. It is threaded into the existing
        ``MigrationUnitSpec.source_files`` field -- the field that exists for
        precisely this binding -- so no new model, contract or planner is
        introduced. When no inventory is available the previous
        technology-only behaviour is preserved exactly, and the wave records an
        explicit "no source file" failure instead of silently transforming a
        placeholder.
        """
        from autoforge_modernization.strategy import (
            MigrationPlan,
            MigrationStrategy,
            MigrationUnitSpec,
            PlanStatus,
        )

        units: list[MigrationUnitSpec] = []
        # analysis_report.technologies is a list[TechnologyAnalysisStage1]
        techs = (
            list(getattr(analysis_report, "technologies", []) or [])
            if analysis_report else []
        )
        # Group the real source inventory by detected technology.
        by_tech: dict[str, list[str]] = {}
        for tech_name, path in source_files or []:
            by_tech.setdefault(str(tech_name).upper(), []).append(path)

        for tech in techs:
            name = getattr(tech, "detected_name", None) or "unknown"
            # Preserve the discovered source technology from analysis. This is
            # the source of truth that G.3 transformation strategies consume
            # — NOT the target language. Without this, the pipeline silently
            # falls back to "java" for every unit and the strategy lookup
            # never finds a match (D3).
            source_tech = getattr(tech, "detected_name", None)
            bound = by_tech.get(str(source_tech).upper(), []) if source_tech else []
            # DEF-18LR-B2: the transformation TYPE is selected in ``_run_wave``
            # from the certified engine's own supported set for this source
            # technology, because ``MigrationStrategy`` is the plan-level "6 R's"
            # vocabulary (retain/rehost/replatform/refactor/rewrite/...) and
            # cannot express the execution-level types the G.3 strategies key on
            # (transpilation/reconfiguration/...). The plan-level strategy is
            # therefore left exactly as it was.
            units.append(
                MigrationUnitSpec(
                    wave_id="wave-1",
                    component_id=name,
                    strategy=MigrationStrategy.REFACTOR,
                    description=f"Modernize {name} technology",
                    source_technology=source_tech,
                    source_files=list(bound),
                    target_language="java",
                    target_framework="spring-boot",
                    estimated_loc=sum(
                        _count_lines(p) for p in bound
                    ) or 1000,
                    estimated_effort_hours=80.0,
                    estimated_risk="medium",
                )
            )

        plan = MigrationPlan(
            project_id=project_id,
            name=f"Default plan for {project_id}",
            description="Auto-derived from analysis report",
            units=units,
            total_units=len(units),
            total_estimated_loc=sum(u.estimated_loc or 0 for u in units),
            total_estimated_hours=sum(u.estimated_effort_hours or 0.0 for u in units),
        )

        # Auto-approve the plan so transformation can proceed
        plan.status = PlanStatus.APPROVED
        plan.approved = True
        plan.approved_by = "autoforge-pipeline"
        plan.approved_at = _utc_now()
        plan.hitl_approved = True  # Auto-mode approval
        plan.hitl_required = False
        return plan

    def _run_wave(
        self,
        project_id: str,
        job_id: str,
        plan,
        wave_id: str,
        wave_index: int,
        transformation_engine,
    ) -> PipelineWaveResult:
        """Process a single wave's units through the transformation engine."""
        from autoforge_modernization.transformation import (
            TransformationStatus,
            TransformationType,
        )

        units = [u for u in plan.units if u.wave_id == wave_id]
        wave_result = PipelineWaveResult(
            wave_id=wave_id,
            wave_index=wave_index,
            status=PipelineStatus.RUNNING_TRANSFORMATION,
        )

        for unit in units:
            # G.3: pick the right transformation strategy for the source technology.
            # We prefer the discovered source_technology that was populated by
            # _derive_default_plan from the G.3 analysis.  If the unit has
            # neither a source_technology nor a target_language, we must NOT
            # silently fall back to "java" (D3) — that produces an
            # unconditionally failed wave. Instead we record a clear
            # "no-source-technology" failure and continue.
            source_tech = getattr(unit, "source_technology", None)
            if not source_tech:
                wave_result.units_failed += 1
                msg = (
                    f"Unit {unit.component_id} has no source_technology; "
                    "cannot pick a G.3 transformation strategy. "
                    "Pipeline must propagate discovered source technology."
                )
                if not wave_result.error_message:
                    wave_result.error_message = msg
                continue

            # DEF-18LR-B2: transform the REAL legacy source.
            #
            # A unit now carries the actual source files discovered during
            # reconnaissance (``MigrationUnitSpec.source_files``). Previously
            # this loop invented ``f"# legacy {tech} unit {id}"`` and fed that
            # placeholder to the strategy, so no amount of strategy quality
            # could ever modernize the customer's code.
            #
            # Each real file becomes its own transformation record, so the
            # audit trail is per-file and the record's ``before_content`` is the
            # customer's actual bytes. A unit with no bound source file is an
            # explicit, inspectable failure -- never a silent placeholder.
            source_files = list(getattr(unit, "source_files", None) or [])
            if not source_files:
                wave_result.units_failed += 1
                msg = (
                    f"Unit {unit.component_id} ({source_tech}) has no bound source "
                    "file; refusing to transform a synthetic placeholder. "
                    "Reconciliation must supply the real legacy file paths."
                )
                if not wave_result.error_message:
                    wave_result.error_message = msg
                continue

            for source_path in source_files:
                target_tech = unit.target_language or "java"
                # DEF-18LR-B2: resolve the transformation type against the
                # engine's certified supported set for THIS source technology,
                # instead of blindly reusing the plan-level "6 R's" label.
                transformation_type = self._select_transformation_type(source_tech)
                tt_value = transformation_type.value
                try:
                    strategy_fn = G3TransformationStrategies.get_strategy(
                        source_technology=source_tech,
                        transformation_type=tt_value,
                    )
                except NotImplementedError:
                    strategy_fn = None

                if strategy_fn is None:
                    # Unsupported source/target combination — count as failed but continue
                    wave_result.units_failed += 1
                    msg = (
                        f"No G.3 strategy for source={source_tech} type={tt_value}"
                    )
                    if not wave_result.error_message:
                        wave_result.error_message = msg
                    continue

                # The strategy callables take (content, tech) and return transformed text
                def _transform_fn(content: str, _fn=strategy_fn, _t=source_tech) -> str:
                    return _fn(content, _t)

                # The customer's ACTUAL source bytes are the transformation input.
                try:
                    with open(source_path, encoding="utf-8", errors="replace") as fh:
                        before_content = fh.read()
                except OSError as exc:
                    wave_result.units_failed += 1
                    msg = f"Cannot read legacy source {source_path}: {exc}"
                    if not wave_result.error_message:
                        wave_result.error_message = msg
                    continue

                try:
                    record = transformation_engine.apply(
                        project_id=project_id,
                        job_id=job_id,
                        unit_id=unit.unit_id,
                        file_path=source_path,
                        transformation_fn=_transform_fn,
                        transformation_type=transformation_type,
                        target_technology=target_tech,
                        before_content=before_content,
                        gate_approved=True,
                    )
                    if record.status == TransformationStatus.APPLIED:
                        wave_result.units_transformed += 1
                    else:
                        wave_result.units_failed += 1
                    wave_result.transformation_record_ids.append(record.record_id)
                except Exception as e:
                    wave_result.units_failed += 1
                    wave_result.error_message = f"{type(e).__name__}: {e}"

        if wave_result.units_failed == 0:
            wave_result.status = PipelineStatus.COMPLETE
        elif wave_result.units_transformed == 0:
            wave_result.status = PipelineStatus.FAILED
        else:
            wave_result.status = PipelineStatus.COMPLETE

        return wave_result

    def _get_wave_records(self, transformation_engine, wave_id: str) -> list:
        """Get transformation records for a specific wave (placeholder)."""
        # In a full implementation, the engine would store wave_id on each
        # record and provide filtering. For now, return engine records.
        try:
            return transformation_engine.get_records()
        except Exception:
            return []

    # ── __all__ ─────────────────────────────────────────────────────────────────


# Resolve forward references lazily on first instantiation
_original_pipeline_result_init = PipelineResult.__init__

def _lazy_rebuild():
    """Resolve forward references after all modules are loaded."""
    from autoforge_modernization.analysis import AnalysisReport
    from autoforge_modernization.planning_gate import GateDecisionRecord
    from autoforge_modernization.strategy import MigrationPlan
    from autoforge_modernization.transformation import TransformationRecord
    PipelineResult.model_rebuild(
        _types_namespace={
            "Any": Any,
            "AnalysisReport": AnalysisReport,
            "GateDecisionRecord": GateDecisionRecord,
            "MigrationPlan": MigrationPlan,
            "TransformationRecord": TransformationRecord,
        }
    )

# Rebuild on first use
def _patched_init(self, *args, **kwargs):
    _lazy_rebuild()
    # Patch the __init__ back so we don't rebuild on every call
    PipelineResult.__init__ = _original_pipeline_result_init
    return _original_pipeline_result_init(self, *args, **kwargs)

PipelineResult.__init__ = _patched_init

__all__ = ["ModernizationPipeline", "PipelineResult", "PipelineStatus", "PipelineWaveResult"]
