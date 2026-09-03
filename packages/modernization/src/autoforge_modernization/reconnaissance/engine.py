"""Production Reconnaissance Engine for Phase 18-G.2.

Wires the complete G.2 reconnaissance pipeline end-to-end.
See module docstring for the full pipeline description.
"""
from __future__ import annotations

import json
import os
import platform
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from autoforge_modernization.reconnaissance.models import (
    BusinessEvidence,
    ComparisonOutcome,
    ContextRetrievalRecord,
    DatabaseInventory,
    DeploymentSpec,
    DetectedTechnology,
    DocumentDiscovery,
    FactConfidence,
    LegacyInventory,
    ProjectCapabilityComparison,
    ProjectSizing,
    RAGQueryRecord,
    ReconnaissanceEngineState,
    ReconnaissanceEvent,
    ReconnaissanceEventType,
    ResearchSanitizationCheck,
    ScannedFile,
    TestDiscovery,
)
from autoforge_modernization.reconnaissance.scanner import (
    ReconnaissanceScanner,
    ScanResult,
    VersionDetector,
    VersionManifest,
)
from autoforge_modernization.reconnaissance.detector import TechnologyDetector
from autoforge_modernization.reconnaissance._sizing_engine import (
    aggregate_sizings,
    measure_text,
)
from autoforge_modernization.reconnaissance._pipeline_helpers import (
    build_architecture_graph,
    build_deployment_spec,
    build_dependency_graph,
    check_lockdown_violation,
    classify_research_safety,
    discover_databases,
    discover_documents,
    discover_specialist_tools,
    sanitize_text,
)

class ReconnaissanceEngine:
    """The production reconnaissance engine for Phase 18-G.2."""

    def __init__(
        self,
        project_path: str,
        job_id: str | None = None,
        max_files: int = 50000,
        max_depth: int = 20,
        capability_registry: dict[str, str] | None = None,
        lockdown_enabled: bool = False,
        checkpoint_dir: str | None = None,
        rag_engine: Any = None,
    ) -> None:
        self.project_path = project_path
        self.job_id = job_id
        self.max_files = max_files
        self.max_depth = max_depth
        self.capability_registry = capability_registry or {}
        self.lockdown_enabled = lockdown_enabled
        self.checkpoint_dir = checkpoint_dir
        self.rag_engine = rag_engine
        self._state = ReconnaissanceEngineState(
            project_path=project_path, job_id=job_id
        )
        self._state.lockdown_active = lockdown_enabled
        self._state.research_blocked = lockdown_enabled
        self._events: list[ReconnaissanceEvent] = []
        self._retrievals: list[ContextRetrievalRecord] = []
        self._rag_queries: list[RAGQueryRecord] = []
        self._sanitization_checks: list[ResearchSanitizationCheck] = []
        self._checkpoint_records: list[dict[str, Any]] = []
        self._dashboard_state: dict[str, Any] = {}

    def run(self) -> LegacyInventory:
        self._state.is_running = True
        self._state.started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
        self._state.current_operation = "scanning_repository"
        self._emit(ReconnaissanceEventType.SCAN_STARTED, {
            "project_path": self.project_path,
            "lockdown": self.lockdown_enabled,
        })
        scan_result = self._scan()
        content_iter = self._read_all_text(scan_result)
        self._state.current_operation = "detecting_versions"
        version_manifests = self._detect_versions()
        for m in version_manifests:
            if m.parsed and m.primary_version:
                self._emit(ReconnaissanceEventType.VERSION_DETECTED, {
                    "manifest": m.manifest_type,
                    "language": m.language,
                    "primary_version": m.primary_version,
                    "confidence": m.primary_version_confidence.value,
                })
        self._state.current_operation = "detecting_technologies"
        detector = TechnologyDetector(scanned_files=scan_result.scanned_files)
        detected = detector.detect_all()
        for tech in detected:
            self._emit(ReconnaissanceEventType.TECHNOLOGY_DETECTED, {
                "name": tech.name, "kind": tech.kind.value,
            })
        self._state.current_operation = "comparing_capabilities"
        comparisons = detector.compare_capabilities(
            detected, self.capability_registry
        )
        self._state.current_operation = "building_dependency_graph"
        dep_graph = build_dependency_graph(
            scan_result.scanned_files, list(content_iter)
        )
        for edge in dep_graph.edges[:20]:
            self._emit(ReconnaissanceEventType.DEPENDENCY_FOUND, {
                "from": edge.from_node, "to": edge.to_node,
                "kind": edge.kind.value,
            })
        self._state.current_operation = "building_architecture_graph"
        arch_graph = build_architecture_graph(scan_result.scanned_files)
        self._state.current_operation = "discovering_databases"
        db_inventory = discover_databases(
            (rel, text) for rel, text in content_iter
        )
        self._state.current_operation = "discovering_deployment"
        deployment_spec = build_deployment_spec(
            [sf.relative_path for sf in scan_result.scanned_files],
            lambda rel: self._read_text_relative(scan_result, rel),
        )
        self._state.current_operation = "computing_sizing"
        sizing = self._compute_sizing(scan_result, list(content_iter))
        self._state.loc_analyzed = sizing.total_physical_loc
        self._state.current_operation = "discovering_documents"
        doc_discovery, business_evidence = discover_documents(list(content_iter))
        test_discovery = self._discover_tests(scan_result)
        self._state.current_operation = "discovering_tools"
        tool_requirements = discover_specialist_tools(detected)
        build_systems, build_targets, runtime_specs = self._build_specs(
            version_manifests, scan_result
        )
        self._state.current_operation = "assembling_inventory"
        inventory = LegacyInventory(
            project_path=self.project_path,
            project_name=scan_result.project_metadata.name,
            metadata=scan_result.project_metadata,
            scanned_files=scan_result.scanned_files,
            detected_technologies=detected,
            dependency_graph=dep_graph,
            build_systems=build_systems,
            build_targets=build_targets,
            runtime_specs=runtime_specs,
            deployment_spec=deployment_spec,
            database_inventory=db_inventory,
            architecture_graph=arch_graph,
            test_discovery=test_discovery,
            document_discovery=doc_discovery,
            business_evidence=business_evidence,
            sizing=sizing,
            capability_comparisons=comparisons,
            tool_requirements=tool_requirements,
            dashboard_state={},
            scan_duration_seconds=time.monotonic() - t0,
            overall_confidence=self._compute_confidence(
                scan_result, detected, comparisons
            ),
            incomplete_detections=self._identify_incompleteness(
                scan_result, detected, db_inventory
            ),
            blockers=self._identify_blockers(comparisons),
        )
        inventory.dashboard_state = self._build_dashboard(inventory)
        if self.checkpoint_dir:
            self._write_checkpoint(inventory)
        if self.rag_engine is not None:
            self._maybe_query_rag(inventory)
        self._state.elapsed_seconds = time.monotonic() - t0
        self._state.is_running = False
        self._state.operations_completed = [
            "scanning_repository",
            "detecting_technologies",
            "comparing_capabilities",
            "sizing",
            "assembling_inventory",
        ]
        self._emit(ReconnaissanceEventType.INVENTORY_COMPLETE, {
            "files_scanned": len(scan_result.scanned_files),
            "technologies": len(detected),
            "duration_seconds": self._state.elapsed_seconds,
        })
        return inventory

    def _scan(self) -> ScanResult:
        scanner = ReconnaissanceScanner(
            project_path=self.project_path,
            max_files=self.max_files,
            max_depth=self.max_depth,
        )
        result = scanner.scan()
        self._state.files_scanned = len(result.scanned_files)
        self._emit(ReconnaissanceEventType.SCAN_COMPLETE, result.to_summary())
        return result

    def _detect_versions(self) -> list[VersionManifest]:
        vd = VersionDetector(self.project_path)
        return vd.scan_manifests()

    def _read_text_relative(self, sr: ScanResult, rel: str) -> str | None:
        for sf in sr.scanned_files:
            if sf.relative_path == rel:
                try:
                    with open(sf.path, "r", encoding="utf-8", errors="replace") as fh:
                        return fh.read()
                except Exception:
                    return None
        return None

    def _read_all_text(self, sr: ScanResult) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for sf in sr.scanned_files:
            if sf.size_bytes > 2 * 1024 * 1024:
                continue
            if sf.category.value == "binary":
                continue
            try:
                with open(sf.path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                results.append((sf.relative_path, text))
            except Exception:
                continue
        return results

    def _compute_sizing(
        self, sr: ScanResult, content_iter: list[tuple[str, str]]
    ) -> ProjectSizing:
        from autoforge_modernization.reconnaissance._sizing_engine import FileSizing
        from autoforge_modernization.reconnaissance.models import (
            CountingMethodology, SizingSource,
        )
        rel_to_lang: dict[str, str | None] = {
            sf.relative_path: sf.detected_language for sf in sr.scanned_files
        }
        sizes: list[FileSizing] = []
        language_counts: dict[str, int] = {}
        test_loc = 0
        generated_loc = 0
        for rel, text in content_iter:
            lang = rel_to_lang.get(rel)
            sizing = measure_text(text, lang)
            sizes.append(sizing)
            if lang:
                language_counts[lang] = (
                    language_counts.get(lang, 0) + sizing.physical_loc
                )
            parts = rel.split("/")
            if any(seg.lower() == "test" for seg in parts):
                test_loc += sizing.physical_loc
            if any(
                seg in rel.lower()
                for seg in ("generated", "autogen", "node_modules")
            ):
                generated_loc += sizing.physical_loc
        agg = aggregate_sizings(sizes, language_counts, len(sr.scanned_files))
        return ProjectSizing(
            total_physical_loc=agg["total_physical_loc"],
            blank_loc=agg["blank_loc"],
            comments_loc=agg["comments_loc"],
            active_loc=agg["active_loc"],
            test_loc=test_loc,
            generated_loc=generated_loc,
            total_files=agg["total_files"],
            loc_by_language=agg["loc_by_language"],
            primary_methodology=agg["primary_methodology"],
            methodologies_used=agg["methodologies_used"],
            sources=agg["sources"],
            is_generated_excluded=False,
            confidence=agg["confidence"],
        )

    def _discover_tests(self, sr: ScanResult) -> TestDiscovery:
        td = TestDiscovery()
        for sf in sr.scanned_files:
            if sf.is_test:
                td.test_locations.append(sf.relative_path)
                td.test_count += 1
        td.confidence = (
            FactConfidence.MEDIUM if td.test_count else FactConfidence.UNKNOWN
        )
        return td

    def _build_specs(
        self, manifests: list[VersionManifest], sr: ScanResult,
    ) -> tuple[list, list, list]:
        from autoforge_modernization.reconnaissance.models import (
            BuildSystem, BuildTarget, RuntimeSpec,
        )
        seen: dict[str, Any] = {
            "maven": BuildSystem.MAVEN, "gradle": BuildSystem.GRADLE,
            "npm": BuildSystem.NPM, "pip": BuildSystem.PIP,
            "poetry": BuildSystem.POETRY, "cargo": BuildSystem.CARGO,
            "bundler": BuildSystem.BUNDLER,
            "dockerfile": BuildSystem.DOCKERFILE,
        }
        build_systems: list[Any] = []
        build_targets: list[Any] = []
        runtime_specs: list[Any] = []
        for m in manifests:
            if not m.parsed:
                continue
            if m.build_tool and m.build_tool in seen:
                bs = seen[m.build_tool]
                if bs not in build_systems:
                    build_systems.append(bs)
                build_targets.append(BuildTarget(
                    target_name=m.manifest_type,
                    build_system=bs,
                    build_file=m.manifest_path,
                ))
            if m.language and m.primary_version:
                runtime_specs.append(RuntimeSpec(
                    runtime_name=m.language,
                    version=m.primary_version,
                    version_confidence=m.primary_version_confidence,
                    evidence=[f"{m.manifest_type}:{m.manifest_path}"],
                ))
        return build_systems, build_targets, runtime_specs

    def _compute_confidence(
        self, sr: ScanResult,
        detected: list[DetectedTechnology],
        comparisons: list[ProjectCapabilityComparison],
    ) -> FactConfidence:
        if not sr.scanned_files:
            return FactConfidence.UNKNOWN
        high = sum(
            1 for sf in sr.scanned_files
            if sf.confidence == FactConfidence.HIGH
        )
        ratio = high / len(sr.scanned_files)
        if ratio > 0.8 and len(detected) > 0:
            return FactConfidence.HIGH
        if ratio > 0.5:
            return FactConfidence.MEDIUM
        if ratio > 0.2:
            return FactConfidence.LOW
        return FactConfidence.UNKNOWN

    def _identify_incompleteness(
        self, sr: ScanResult,
        detected: list[DetectedTechnology],
        db_inv: DatabaseInventory,
    ) -> list[str]:
        items: list[str] = []
        if not detected:
            items.append("no_technologies_detected")
        for sf in sr.scanned_files:
            if sf.detected_language and not sf.detected_technologies:
                items.append(f"no_technologies:{sf.detected_language}")
                break
        return items

    def _identify_blockers(
        self, comparisons: list[ProjectCapabilityComparison],
    ) -> list[str]:
        return [
            f"{c.technology}:{c.outcome.value}"
            for c in comparisons if c.blocks_modernization
        ]

    def _build_dashboard(self, inv: LegacyInventory) -> dict[str, Any]:
        from autoforge_modernization.observability import (
            ModernizationDashboard, ModernizationDashboardJob,
            ModernizationDashboardTime, ModernizationDashboardProgress,
            ModernizationDashboardHealth, ModernizationDashboardCheckpoint,
        )
        blocked = sum(
            1 for c in inv.capability_comparisons if c.blocks_modernization
        )
        modules = (
            len(inv.architecture_graph.nodes)
            if inv.architecture_graph else 0
        )
        dashboard = ModernizationDashboard(
            job_id=self.job_id or "local",
            project_id=self.project_path,
            job=ModernizationDashboardJob(
                job_id=self.job_id or "local",
                project_id=self.project_path,
                name=os.path.basename(self.project_path.rstrip("/")),
                status="running" if self._state.is_running else "complete",
                current_phase="reconnaissance",
                current_operation=self._state.current_operation,
            ),
            time=ModernizationDashboardTime(
                start_time=self._state.started_at,
                elapsed_seconds=self._state.elapsed_seconds,
                last_checkpoint_at=self._state.last_checkpoint_at,
                is_running=self._state.is_running,
            ),
            progress=ModernizationDashboardProgress(
                total_loc=(inv.sizing.total_physical_loc if inv.sizing else 0),
                processed_loc=(inv.sizing.total_physical_loc if inv.sizing else 0),
                remaining_loc=0,
                files_total=(inv.sizing.total_files if inv.sizing else 0),
                files_processed=(inv.sizing.total_files if inv.sizing else 0),
                modules_total=modules,
                modules_completed=modules,
                percentage_complete=100.0,
            ),
            health=ModernizationDashboardHealth(
                successes=len(inv.detected_technologies),
                failures=len(inv.incomplete_detections),
                skipped=0,
                blocked=blocked,
                retries=0,
                verification_passed=0,
                verification_failed=0,
                unresolved_findings=len(inv.business_evidence),
                open_capability_gaps=blocked,
                open_business_intent_gaps=0,
                risk_level="medium" if blocked else "low",
            ),
            checkpoint=ModernizationDashboardCheckpoint(
                last_checkpoint_at=self._state.last_checkpoint_at,
                can_resume_from_checkpoint=self.checkpoint_dir is not None,
                resume_blocker=(
                    None if self.checkpoint_dir
                    else "checkpoint_dir_not_configured"
                ),
            ),
            operating_mode=(
                "lockdown" if self.lockdown_enabled else "normal"
            ),
            lockdown_active=self.lockdown_enabled,
        )
        return dashboard.model_dump(mode="json", exclude_none=True)

    def _maybe_query_rag(self, inv: LegacyInventory) -> None:
        if self.lockdown_enabled:
            self._sanitization_checks.append(ResearchSanitizationCheck(
                is_sanitized=True,
                client_data_indicators_found=[],
                research_question="rag_query_skipped_lockdown",
            ))
            return
        try:
            check_lockdown_violation("external_retrieval", self.lockdown_enabled)
        except Exception as e:
            self._sanitization_checks.append(ResearchSanitizationCheck(
                is_sanitized=False,
                client_data_indicators_found=[str(e)],
                research_question="rag_query_blocked",
            ))
            return
        fn = getattr(self.rag_engine, "retrieve_for_context", None)
        if not fn:
            return
        try:
            import inspect
            if inspect.iscoroutinefunction(fn):
                import asyncio
                result = asyncio.run(fn(
                    query="legacy project overview",
                    project_id=self.project_path,
                    top_k=3,
                ))
            else:
                result = fn(
                    query="legacy project overview",
                    project_id=self.project_path,
                    top_k=3,
                )
            hits = getattr(result, "hits", None) or getattr(
                result, "results", []) or []
            self._rag_queries.append(RAGQueryRecord(
                query_text="legacy project overview",
                results=[str(h) for h in hits[:5]],
                result_count=len(hits),
                scope="reconnaissance",
            ))
            self._retrievals.append(ContextRetrievalRecord(
                operation="rag_legacy_overview",
                query="legacy project overview",
                retrieved_files=[str(h) for h in hits[:5]],
                retrieval_count=len(hits),
            ))
        except Exception as e:
            self._state.errors.append(f"rag_query_error:{e}")

    def _write_checkpoint(self, inv: LegacyInventory) -> None:
        if not self.checkpoint_dir:
            return
        try:
            os.makedirs(self.checkpoint_dir, exist_ok=True)
        except Exception:
            return
        try:
            payload = inv.model_dump(mode="json", exclude_none=True)
            ckid = str(uuid.uuid4())
            payload["checkpoint_id"] = ckid
            payload["checkpoint_at"] = datetime.now(timezone.utc).isoformat()
            payload["job_id"] = self.job_id
            payload["elapsed_seconds"] = self._state.elapsed_seconds
            chk_path = os.path.join(
                self.checkpoint_dir, f"recon_{ckid}.json",
            )
            with open(chk_path, "w") as f:
                json.dump(payload, f, indent=2, default=str)
            self._checkpoint_records.append({"path": chk_path, **payload})
            self._state.last_checkpoint_at = datetime.now(timezone.utc)
        except Exception as e:
            self._state.errors.append(f"checkpoint_write_failed:{e}")

    def _emit(
        self, event_type: ReconnaissanceEventType, payload: dict[str, Any]
    ) -> None:
        self._events.append(ReconnaissanceEvent(
            event_type=event_type,
            project_id=self.project_path,
            job_id=self.job_id,
            payload=payload,
        ))

    @property
    def events(self) -> list[ReconnaissanceEvent]:
        return list(self._events)

    @property
    def state(self) -> ReconnaissanceEngineState:
        return self._state

    @property
    def retrievals(self) -> list[ContextRetrievalRecord]:
        return list(self._retrievals)

    @property
    def rag_queries(self) -> list[RAGQueryRecord]:
        return list(self._rag_queries)

    @property
    def sanitization_checks(self) -> list[ResearchSanitizationCheck]:
        return list(self._sanitization_checks)

    @property
    def checkpoints(self) -> list[dict[str, Any]]:
        return list(self._checkpoint_records)

    def resume_from_checkpoint(
        self, checkpoint_path: str
    ) -> LegacyInventory | None:
        try:
            with open(checkpoint_path, "r") as f:
                payload = json.load(f)
            return LegacyInventory.model_validate(payload)
        except Exception as e:
            self._state.errors.append(f"checkpoint_restore_failed:{e}")
            return None


def run_reconnaissance(project_path: str, **kwargs: Any) -> LegacyInventory:
    return ReconnaissanceEngine(project_path, **kwargs).run()
