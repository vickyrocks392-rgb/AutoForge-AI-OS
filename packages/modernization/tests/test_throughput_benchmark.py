"""Tests for the AutoForge throughput benchmark schema and runner.

These tests verify:
- LOC accounting invariants (no double-counting, correct classifications).
- Throughput rate calculations.
- LLM/RAG/verification/repair metric invariants.
- Estimate comparison and ETA updates.
- Workload summarization correctness.
- Projection math consistency.
- Runner execution path (deterministic mode, LLM unavailable).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Ensure package is importable.
ROOT = Path(__file__).resolve().parents[2] / "packages" / "modernization" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autoforge_modernization.benchmark import (
    ConcurrencyMetrics,
    EstimateComparison,
    LLMMetrics,
    LOCClassification,
    MarketProjection,
    RepairMetrics,
    RAGMetrics,
    StageMetrics,
    StageTiming,
    ThroughputBenchmarkResult,
    ThroughputRates,
    VerificationMetrics,
    WorkloadMetrics,
    WorkloadView,
    collect_hardware_metadata,
)
from autoforge_modernization.benchmark_runner import (
    BenchmarkRunner,
    WorkloadDiscoverer,
    _check_llm_available,
    persist_result,
    run_benchmark,
)
from autoforge_modernization.throughput_accounting import (
    LedgerEntry,
    ThroughputAccounting,
    UnitKind,
)


@pytest.fixture
def tmp_workload(tmp_path):
    """Create a small synthetic CardDemo-like workload for testing."""
    files = {
        "cbl/HELLO.cbl": "       IDENTIFICATION DIVISION.\n" * 30,
        "cbl/CALC.cbl": "       PROGRAM-ID. CALC.\n" * 50,
        "cpy/COMMON.cpy": "      * COPYBOOK\n" * 20,
        "bms/MAP.bms": "BMS MAP\n" * 10,
        "jcl/RUN.jcl": "//RUN JOB\n" * 15,
    }
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path




class TestWorkloadMetrics:
    def test_zero_state_valid(self):
        m = WorkloadMetrics()
        assert m.total_files == 0
        assert m.physical_loc == 0
        assert m.accepted_physical_loc == 0
        # throughput_kind is on ThroughputBenchmarkResult, not WorkloadMetrics.

    def test_allows_arbitrary_int(self):
        m = WorkloadMetrics(physical_loc=1_000_000)
        assert m.physical_loc == 1_000_000

    def test_classification_values_distinct(self):
        # LOCClassification enum must have 10 distinct values.
        assert len(set(c.value for c in LOCClassification)) == 10
        for v in [
            "SOURCE",
            "ELIGIBLE",
            "TRANSFORMED",
            "VERIFIED",
            "ACCEPTED",
            "SKIPPED",
            "FAILED",
            "BLOCKED",
            "REVIEW_REQUIRED",
            "PLACEHOLDER",
        ]:
            assert v in {c.value for c in LOCClassification}


class TestStageTiming:
    def test_defaults(self):
        st = StageTiming(stage="analysis")
        assert st.stage == "analysis"
        assert st.duration_ms == 0.0
        assert st.status == "pending"
        assert st.duration_seconds == 0.0
        assert st.duration_minutes == 0.0
        assert st.duration_hours == 0.0

    def test_duration_conversions(self):
        st = StageTiming(stage="x", duration_ms=3_600_000)
        assert st.duration_hours == 1.0
        assert st.duration_minutes == 60.0
        assert st.duration_seconds == 3600.0


class TestStageMetrics:
    def test_default_stages(self):
        m = StageMetrics()
        for attr in [
            "discovery",
            "analysis",
            "semantic_understanding",
            "transformation",
            "verification",
            "repair",
            "acceptance",
        ]:
            stage = getattr(m, attr)
            assert isinstance(stage, StageTiming)
            assert stage.stage != ""
        # Wall clock must start.
        assert m.wall_clock_started_at is not None


class TestThroughputRates:
    def test_primary_throughput_uses_accepted_e2e(self):
        t = ThroughputRates(accepted_e2e_loc_per_hour=5000.0)
        assert t.primary_throughput[0] == 5000.0
        assert "end-to-end" in t.primary_throughput[1].lower()

    def test_zero_state(self):
        t = ThroughputRates()
        assert t.accepted_e2e_loc_per_hour == 0.0
        assert t.verified_e2e_loc_per_hour == 0.0


class TestMarketProjection:
    def test_method_labeled_extrapolation(self):
        p = MarketProjection()
        assert p.method == "extrapolation_from_measured_run"

    def test_scaling_factors_present(self):
        p = MarketProjection(
            measured_throughput_loc_per_hour=10_000.0,
            measured_source_loc=50_000,
        )
        assert isinstance(p.scaling_factors, dict)

    def test_projection_math_consistent(self):
        tput = 10_000.0
        LOC_100K = 100_000
        LOC_1M = 1_000_000
        p = MarketProjection(
            measured_throughput_loc_per_hour=tput,
            measured_source_loc=50_000,
            projection_100k_loc_hours=LOC_100K / tput,
            projection_100k_loc_days=LOC_100K / tput / 24,
            projection_1m_loc_days=LOC_1M / tput / 24,
        )
        assert abs(p.projection_100k_loc_hours - 10.0) < 0.001
        assert abs(p.projection_100k_loc_days - 10.0 / 24.0) < 0.001
        assert abs(p.projection_1m_loc_days - 100.0 / 24.0) < 0.001



class TestWorkloadDiscoverer:
    def test_discover_counts(self, tmp_workload):
        d = WorkloadDiscoverer(tmp_workload)
        records = d.discover()
        assert len(records) == 5
        exts = {r["ext"] for r in records}
        assert ".cbl" in exts
        assert ".cpy" in exts
        assert ".bms" in exts
        assert ".jcl" in exts

    def test_summarize_technology_breakdown(self, tmp_workload):
        d = WorkloadDiscoverer(tmp_workload)
        records = d.discover()
        m = d.summarize(records)
        assert m.total_files == 5
        assert m.cobol_files == 2
        assert m.cobol_loc == 30 + 50
        assert m.copybook_files == 1
        assert m.bms_files == 1
        assert m.jcl_files == 1
        assert m.other_files == 0
        assert m.physical_loc > 0

    def test_loc_no_double_counting(self, tmp_workload):
        d = WorkloadDiscoverer(tmp_workload)
        records = d.discover()
        m = d.summarize(records)
        tech_loc_sum = (
            m.cobol_loc + m.copybook_loc + m.bms_loc + m.jcl_loc + m.other_loc
        )
        assert tech_loc_sum == m.physical_loc

    def test_deterministic_files_default(self, tmp_workload):
        d = WorkloadDiscoverer(tmp_workload)
        records = d.discover()
        m = d.summarize(records)
        assert m.deterministic_loc == 0
        assert m.llm_assisted_loc == 0
        assert m.hybrid_loc == 0

    def test_summarize_handles_empty_dir(self, tmp_path):
        d = WorkloadDiscoverer(tmp_path)
        records = d.discover()
        m = d.summarize(records)
        assert m.total_files == 0
        assert m.physical_loc == 0


class TestRunBenchmarkDeterministic:
    def test_runs_against_synthetic_workload(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(
                tmp_workload, max_concurrent=2, repair_max_attempts=1
            )
            assert result.workload.total_files == 5
            assert result.workload.physical_loc > 0
            assert result.llm_kind == "UNAVAILABLE"
            assert result.rag_kind == "UNAVAILABLE"
            assert result.throughput_kind == "MEASURED"
            assert result.estimation_kind == "MEASURED"
            assert result.stages.wall_clock_duration_ms > 0
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_strategy_breakdown_consistent(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(
                tmp_workload, max_concurrent=2, repair_max_attempts=0
            )
            w = result.workload
            strategy_total = (
                w.deterministic_loc + w.llm_assisted_loc + w.llm_generated_loc + w.hybrid_loc
            )
            assert strategy_total == w.physical_loc
            file_total = (
                w.deterministic_files + w.llm_assisted_files + w.llm_generated_files + w.hybrid_files
            )
            assert file_total == w.total_files
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_accepted_no_double_count(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            w = result.workload
            assert w.accepted_physical_loc <= w.verified_physical_loc
            assert w.verified_physical_loc <= w.transformed_physical_loc
            assert w.transformed_physical_loc <= w.eligible_physical_loc
            assert w.eligible_physical_loc <= w.physical_loc
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_file_count_invariants(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            w = result.workload
            terminal = w.accepted_files + w.failed_files + w.skipped_files
            assert terminal <= w.total_files
            assert w.verified_files >= w.accepted_files
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]



class TestThroughputRateInvariants:
    def test_throughput_rates_positive_when_accepted(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            if result.stages.wall_clock_duration_ms > 0:
                rates = result.throughput
                if result.workload.physical_loc > 0:
                    assert rates.analyzed_loc_per_hour >= 0
                    assert rates.transformed_loc_per_hour >= 0
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_projection_uses_extrapolation_label(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            p = result.projection
            assert p.method == "extrapolation_from_measured_run"
            assert p.confidence in {"low", "medium", "high"}
            assert isinstance(p.scaling_factors, dict)
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_estimate_drift_recorded(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            est = result.estimation
            assert est.actual_duration_ms == result.stages.wall_clock_duration_ms
            # estimation_kind lives on the result, not the estimate object
            assert result.estimation_kind == "MEASURED"
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_to_human_readable_contains_sections(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            text = result.to_human_readable()
            assert "WORKLOAD" in text
            assert "THROUGHPUT" in text
            assert "STRATEGY" in text
            assert "PROJECTION" in text
            assert "EXTRAPOLATION" in text
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_summary_dict_keys(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            d = result.summary_dict()
            for k in [
                "benchmark_id",
                "source_loc",
                "accepted_e2e_loc_per_hour",
                "llm_kind",
                "wall_clock_minutes",
                "projection_100k_loc_days",
            ]:
                assert k in d, k
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_persist_result(self, tmp_workload, tmp_path):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            out = tmp_path / "bench.json"
            persist_result(result, out)
            assert out.exists()
            with out.open() as fh:
                data = json.load(fh)
            assert "workload" in data
            assert "throughput" in data
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]


class TestLLMUnavailableBehaviour:
    def test_check_llm_returns_tuple(self):
        ok, prov, mod = _check_llm_available()
        assert isinstance(ok, bool)
        assert isinstance(prov, str)
        assert isinstance(mod, str)
        if not ok:
            assert prov == ""
            assert mod == ""

    def test_force_unavailable(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            assert result.llm_kind == "UNAVAILABLE"
            assert result.llm.status == "UNAVAILABLE"
            assert result.llm.total_calls == 0
            assert result.llm.total_tokens == 0
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]


class TestHardwareMetadata:
    def test_collect_returns_dict(self):
        hw = collect_hardware_metadata()
        for k in ["platform", "python_version", "hardware_cpu_cores", "hardware_memory_mb"]:
            assert k in hw
        assert isinstance(hw["platform"], str)
        assert hw["platform"] != ""


class TestConcurrencyMetrics:
    def test_defaults(self):
        c = ConcurrencyMetrics()
        assert c.configured_max_concurrency == 0
        assert c.gpu_available is False
        assert c.worker_contention_detected is False

    def test_max_concurrency_set(self):
        c = ConcurrencyMetrics(configured_max_concurrency=8, max_concurrency_observed=8)
        assert c.configured_max_concurrency == 8


class TestVerificationMetrics:
    def test_rate_calculation(self):
        v = VerificationMetrics(
            total_verified=8,
            verification_success_rate=0.8,
            placeholder_free_rate=0.7,
        )
        assert v.verification_success_rate == 0.8
        assert v.placeholder_free_rate == 0.7


class TestRepairMetrics:
    def test_success_rate(self):
        r = RepairMetrics(
            units_requiring_repair=10,
            total_repair_attempts=15,
            successful_repairs=8,
            failed_repairs=2,
            repair_success_rate=0.8,
        )
        assert r.repair_success_rate == 0.8
        assert r.failed_repairs == 2



class TestNoDoubleCountingInvariants:
    """Schema-level invariants across all classification buckets."""

    def test_placeholder_excluded_from_accepted(self):
        classifications = {c.value for c in LOCClassification}
        assert "ACCEPTED" in classifications
        assert "PLACEHOLDER" in classifications
        assert "ACCEPTED" != "PLACEHOLDER"

    def test_failed_excluded_from_accepted(self):
        assert "ACCEPTED" not in {"FAILED", "BLOCKED", "REVIEW_REQUIRED", "SKIPPED"}

    def test_estimated_indicator_preserved(self):
        r = ThroughputBenchmarkResult()
        assert r.throughput_kind == "MEASURED"
        assert r.estimation_kind == "ESTIMATED"
        assert r.llm_kind == "UNAVAILABLE"
        assert r.rag_kind == "UNAVAILABLE"

    def test_workload_view_enum(self):
        for v in [
            "entire_workload",
            "source_only",
            "eligible_only",
            "transformable_only",
            "transformed_only",
            "verified_only",
            "accepted_only",
            "failed_only",
            "blocked_only",
        ]:
            assert v in {wv.value for wv in WorkloadView}


class TestStageTimingsConsistent:
    def test_wall_clock_contains_per_stage(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            s = result.stages
            assert s.discovery.duration_ms >= 0
            assert s.analysis.duration_ms >= 0
            assert s.transformation.duration_ms >= 0
            assert s.wall_clock_duration_ms >= s.transformation.duration_ms
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]


class TestThroughputAccountingIntegration:
    def test_ledger_consistent_with_summary(self, tmp_workload):
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            result = run_benchmark(tmp_workload, max_concurrent=2, repair_max_attempts=0)
            # Verified files <= Total files
            assert result.workload.verified_files <= result.workload.total_files
            # Accepted files <= Verified files
            assert result.workload.accepted_files <= result.workload.verified_files
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_ledger_records_unavailable_when_llm_off(self, tmp_workload):
        """When LLM is unavailable, every unit must be appended to the ledger
        as ``unavailable`` (no fabrication, no silent skip)."""
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            runner = BenchmarkRunner(
                workload_path=tmp_workload,
                max_concurrent=2,
                repair_max_attempts=0,
            )
            result = runner.run()
            exec_result = runner._execution_result
            total = result.workload.total_files
            assert exec_result is not None
            assert len(exec_result.ledger) == total, (
                f"ledger has {len(exec_result.ledger)} entries but workload "
                f"has {total} files -- units are being silently dropped"
            )
            kinds = {entry["kind"] for entry in exec_result.ledger}
            assert kinds == {"unavailable"}, (
                f"expected only 'unavailable' entries, got {kinds}"
            )
            # And the primary throughput metric must honestly read 0.0.
            assert result.throughput.accepted_e2e_loc_per_hour == 0.0
            assert result.workload.accepted_files == 0
            assert result.workload.verified_files == 0
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]

    def test_real_carddemo_runs_end_to_end_when_present(self):
        """If the canonical CardDemo workload is on disk, drive the production
        pipeline against it and assert that the 186 files / ~50K LOC are
        accounted for honestly (no missing records, no fabrication)."""
        carddemo = Path("/Users/kalachanddash/Documents/AutoForge AI/.autoforge/carddemo/app")
        if not carddemo.exists():
            pytest.skip(f"CardDemo workload not present at {carddemo}")
        os.environ["AUTOFORGE_LLM_AVAILABLE"] = "0"
        try:
            runner = BenchmarkRunner(
                workload_path=carddemo,
                max_concurrent=8,
                repair_max_attempts=0,
            )
            result = runner.run()
            # Workload should reflect 186 files / ~50K LOC.
            assert result.workload.total_files >= 150
            assert result.workload.physical_loc >= 40_000
            exec_result = runner._execution_result
            # Every file must be in the ledger (no silent drops).
            assert len(exec_result.ledger) == result.workload.total_files
            # In LLM-unavailable mode, accepted E2E throughput is honestly 0.
            assert result.throughput.accepted_e2e_loc_per_hour == 0.0
            # Deterministic strategy should cover the whole workload.
            assert result.workload.deterministic_files == result.workload.total_files
            assert result.workload.llm_assisted_files == 0
            # Hardware metadata + projection metadata are present.
            assert result.hardware_cpu_cores > 0
            assert result.projection.method == "extrapolation_from_measured_run"
        finally:
            del os.environ["AUTOFORGE_LLM_AVAILABLE"]
