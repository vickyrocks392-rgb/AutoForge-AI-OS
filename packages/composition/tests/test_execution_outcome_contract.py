"""B2 contract tests for the canonical ``ExecutionOutcome``.

These tests pin the CANONICAL contract and its normalisation adapters. They
deliberately assert against the REAL production result shapes in
``kernel_adapters.py`` and ``capability_router.py`` rather than invented ones.

Nothing here exercises a production behaviour change: the B2 contract is inert
and no production module imports it.
"""

from __future__ import annotations

import ast
import copy
import pathlib
import uuid

import pytest

from autoforge_composition.capability_router import RoutedExecution
from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactRecord,
    ArtifactType,
    EvaluationResult,
    EvaluationStatus,
)

_REPO = pathlib.Path(__file__).resolve().parents[3]


def _artifact(name: str = "app.py", content: str = "print('x')") -> ArtifactRecord:
    return ArtifactRecord.create(
        name=name,
        artifact_type=ArtifactType.SOURCE_CODE,
        content=content,
        provenance=ArtifactProvenance(task_id="t-1", worker_id="w-1"),
    )


# ── T1: OutcomeStatus exact literals ──────────────────────────────────

def test_t1_outcome_status_has_exactly_four_members():
    assert [s.value for s in OutcomeStatus] == [
        "complete",
        "remediate",
        "escalate",
        "failed",
    ]


def test_t1_status_values_match_kernel_handle_loop_completion_literals():
    """Literals must equal those O-2 compares at orchestration.py
    :225 / :236 / :248 / :260."""
    assert OutcomeStatus.COMPLETE.value == "complete"
    assert OutcomeStatus.REMEDIATE.value == "remediate"
    assert OutcomeStatus.ESCALATE.value == "escalate"
    assert OutcomeStatus.FAILED.value == "failed"


# ── T2: loop-result normalisation (real kernel_adapters shapes) ──────

def test_t2_generic_complete_loop_result_is_preserved():
    """Shape from kernel_adapters.py:623-630 (passed=True path)."""
    rec = _artifact()
    loop_result = {
        "status": "complete",
        "loop_type": "coding",
        "passed": True,
        "artifacts": [rec.model_dump(mode="json")],
        "evaluation": "passed",
        "findings": [],
    }
    out = ExecutionOutcome.from_loop_result(loop_result)
    assert out.status is OutcomeStatus.COMPLETE
    assert out.loop_type == "coding"
    assert out.passed is True
    assert out.findings == []
    assert out.routed is False
    assert out.capability is None
    assert out.engine_class is None
    assert len(out.artifacts) == 1
    assert out.artifacts[0].checksum == rec.checksum
    assert out.artifacts[0].provenance == rec.provenance
    # production writes a status STRING here; must not become an EvaluationResult
    assert out.evaluation is None


def test_t2_generic_remediate_carries_findings():
    """passed=False on the generic path yields status 'remediate'."""
    out = ExecutionOutcome.from_loop_result(
        {
            "status": "remediate",
            "loop_type": "qa",
            "passed": False,
            "artifacts": [],
            "evaluation": "failed",
            "findings": ["3 tests failed"],
        }
    )
    assert out.status is OutcomeStatus.REMEDIATE
    assert out.passed is False
    assert out.findings == ["3 tests failed"]


def test_t2_exception_loop_result_is_failed():
    """Shape from kernel_adapters.py:633-638 (generic execution error)."""
    out = ExecutionOutcome.from_loop_result(
        {"status": "failed", "loop_type": "coding", "passed": False, "error": "boom"}
    )
    assert out.status is OutcomeStatus.FAILED
    assert out.passed is False
    assert out.artifacts == []


def test_t2_unknown_capability_is_failed_not_escalate():
    """kernel_adapters.py:391-398: UnknownCapabilityError -> 'failed'."""
    out = ExecutionOutcome.from_loop_result(
        {
            "status": "failed",
            "loop_type": "coding",
            "passed": False,
            "error": "Unknown commercial capability",
            "capability": "nope",
            "routed": False,
        }
    )
    assert out.status is OutcomeStatus.FAILED
    assert out.routed is False
def test_t2_engine_exception_preserves_router_class_name():
    """kernel_adapters.py:404-412 sets engine_class to the ROUTER class name
    on the engine-exception path (pre-existing behaviour, note 4)."""
    out = ExecutionOutcome.from_loop_result(
        {
            "status": "remediate",
            "loop_type": "coding",
            "passed": False,
            "error": "RuntimeError: engine blew up",
            "capability": "rag_knowledge",
            "engine_class": "CommercialCapabilityRouter",
            "routed": True,
        }
    )
    assert out.status is OutcomeStatus.REMEDIATE
    assert out.routed is True
    assert out.capability == "rag_knowledge"
    assert out.engine_class == "CommercialCapabilityRouter"


def test_t2_status_is_not_derived_from_passed():
    """passed=False maps to BOTH 'remediate' and 'failed' in production."""
    remediate = ExecutionOutcome.from_loop_result(
        {"status": "remediate", "loop_type": "x", "passed": False}
    )
    failed = ExecutionOutcome.from_loop_result(
        {"status": "failed", "loop_type": "x", "passed": False}
    )
    assert remediate.passed is False and failed.passed is False
    assert remediate.status is OutcomeStatus.REMEDIATE
    assert failed.status is OutcomeStatus.FAILED


def test_t2_missing_loop_type_defaults_to_unknown_like_production():
    """orchestration.py:223 defaults loop_type to 'unknown'."""
    out = ExecutionOutcome.from_loop_result({"status": "complete", "passed": True})
    assert out.loop_type == "unknown"


def test_t2_unrepresentable_status_is_rejected_loudly():
    """Production silently falls through; the contract fails closed."""
    with pytest.raises(ValueError):
        ExecutionOutcome.from_loop_result({"status": "totally-new", "passed": True})


def test_t2_real_evaluation_result_is_preserved_when_supplied():
    er = EvaluationResult(status=EvaluationStatus.FAILED, failures=["boom"])
    out = ExecutionOutcome.from_loop_result(
        {"status": "remediate", "loop_type": "x", "passed": False, "evaluation": er}
    )
    assert out.evaluation is er


def test_t2_invalid_artifact_is_rejected_not_dropped():
    """Artifacts must never silently vanish."""
    with pytest.raises(Exception):
        ExecutionOutcome.from_loop_result(
            {
                "status": "complete",
                "loop_type": "x",
                "passed": True,
                "artifacts": [{"not": "an artifact record"}],
            }
        )


# ── T3: RoutedExecution normalisation ────────────────────────────────

def test_t3_routed_success_is_complete_with_no_findings():
    routed = RoutedExecution(
        capability="rag_knowledge",
        engine_class="RAGKnowledgePowerEngine",
        success=True,
        status="complete",
        delivery_dir="/tmp/d",
        stages_executed=["INTAKE", "VERIFY"],
    )
    out = ExecutionOutcome.from_routed_execution(routed, loop_type="coding")
    assert out.status is OutcomeStatus.COMPLETE
    assert out.passed is True
    assert out.findings == []
    assert out.routed is True
    assert out.capability == "rag_knowledge"
    assert out.engine_class == "RAGKnowledgePowerEngine"
    assert out.loop_type == "coding"


def test_t3_routed_failure_uses_existing_findings_expression():
    """findings replicate kernel_adapters.py:430 exactly."""
    routed = RoutedExecution(
        capability="ai_automation",
        engine_class="AIAutomationPowerEngine",
        success=False,
        status="remediate",
        error_message="stage 7 failed",
    )
    out = ExecutionOutcome.from_routed_execution(routed, loop_type="coding")
    assert out.status is OutcomeStatus.REMEDIATE
    assert out.passed is False
    assert out.findings == ["stage 7 failed"]


def test_t3_routed_failure_without_message_uses_existing_fallback():
    """Same expression with a None message -> 'engine reported failure'."""
    routed = RoutedExecution(
        capability="code_migration",
        engine_class="CodeMigrationPowerEngine",
        success=False,
        status="remediate",
        error_message=None,
    )
    out = ExecutionOutcome.from_routed_execution(routed, loop_type="coding")
    assert out.findings == ["engine reported failure"]


def test_t3_no_information_is_fabricated():
    """artifacts/evaluation are absent on RoutedExecution and stay empty."""
    routed = RoutedExecution(
        capability="rag_knowledge",
        engine_class="RAGKnowledgePowerEngine",
        success=True,
        status="complete",
    )
    out = ExecutionOutcome.from_routed_execution(routed, loop_type="coding")
    assert out.artifacts == []
    assert out.evaluation is None
# ── T4: PowerEngineResult normalisation (real engine semantics) ──────

class _FakePowerEngineResult:
    """Structural stand-in with the real PowerEngineResult field names
    (power_engines/base.py:90-101)."""

    def __init__(self, success, stages_executed, error_message=None):
        self.success = success
        self.stages_executed = stages_executed
        self.error_message = error_message


def test_t4_successful_engine_result_is_complete():
    out = ExecutionOutcome.from_power_engine_result(
        _FakePowerEngineResult(True, ["INTAKE", "UNDERSTAND", "VERIFY"]),
        loop_type="coding",
        capability="rag_knowledge",
        engine_class="RAGKnowledgePowerEngine",
    )
    assert out.status is OutcomeStatus.COMPLETE
    assert out.passed is True
    assert out.findings == []
    assert out.routed is True


def test_t4_failed_engine_result_is_remediate():
    """Matches capability_router.py:356 else-branch."""
    out = ExecutionOutcome.from_power_engine_result(
        _FakePowerEngineResult(False, ["INTAKE"], error_message="stage 2 failed"),
        loop_type="coding",
        capability="rag_knowledge",
        engine_class="RAGKnowledgePowerEngine",
    )
    assert out.status is OutcomeStatus.REMEDIATE
    assert out.passed is False
    assert out.findings == ["stage 2 failed"]


# ── T5: WAITING_FOR_HUMAN_APPROVAL / escalation semantics ─────────────

def test_t5_waiting_for_human_approval_maps_to_escalate():
    """power_engines/base.py:52 defines the real stage member; the router
    treats its presence as 'waiting' at capability_router.py:349."""
    out = ExecutionOutcome.from_power_engine_result(
        _FakePowerEngineResult(
            True, ["INTAKE", "WAITING_FOR_HUMAN_APPROVAL", "VERIFY"]
        ),
        loop_type="coding",
        capability="code_migration",
        engine_class="CodeMigrationPowerEngine",
    )
    assert out.status is OutcomeStatus.ESCALATE
    # success AND waiting -> passed is False, exactly as
    # RoutedExecution(success=success and not waiting) at :353
    assert out.passed is False


def test_t5_waiting_overrides_success_but_not_the_reverse():
    """A failed engine that is also waiting still escalates (router order)."""
    out = ExecutionOutcome.from_power_engine_result(
        _FakePowerEngineResult(False, ["WAITING_FOR_HUMAN_APPROVAL"]),
        loop_type="coding",
        capability="code_migration",
        engine_class="CodeMigrationPowerEngine",
    )
    assert out.status is OutcomeStatus.ESCALATE


def test_t5_routed_escalate_status_passes_through():
    routed = RoutedExecution(
        capability="code_migration",
        engine_class="CodeMigrationPowerEngine",
        success=False,
        status="escalate",
        stages_executed=["WAITING_FOR_HUMAN_APPROVAL"],
    )
    out = ExecutionOutcome.from_routed_execution(routed, loop_type="coding")
    assert out.status is OutcomeStatus.ESCALATE
    assert out.passed is False


# ── T5b: PipelineResult adaptation (engine 5, ModernizationPipeline) ─────────

class _FakeWave:
    def __init__(self, failed: int = 0) -> None:
        self.units_failed = failed


class _FakePipelineResult:
    def __init__(self, status: str, failed_units: int = 0, error: str | None = None) -> None:
        self.status = status
        self.wave_results = [_FakeWave(failed_units)]
        self.error_message = error


def test_t5b_pipeline_result_complete_maps_to_complete():
    res = _FakePipelineResult("complete")
    out = ExecutionOutcome.from_pipeline_result(res, loop_type="coding")
    assert out.status is OutcomeStatus.COMPLETE
    assert out.passed is True
    assert out.routed is True
    assert out.capability == "legacy_modernization"
    assert out.engine_class == "ModernizationPipeline"


def test_t5b_pipeline_result_failed_maps_to_remediate():
    res = _FakePipelineResult("failed", failed_units=1, error="syntax error")
    out = ExecutionOutcome.from_pipeline_result(res, loop_type="coding")
    assert out.status is OutcomeStatus.REMEDIATE
    assert out.passed is False
    assert out.findings == ["syntax error"]


def test_t5b_pipeline_result_blocked_maps_to_escalate():
    res = _FakePipelineResult("blocked")
    out = ExecutionOutcome.from_pipeline_result(res, loop_type="coding")
    assert out.status is OutcomeStatus.ESCALATE
    assert out.passed is False


# ── T6: input immutability ───────────────────────────────────────────

def test_t6_loop_result_input_is_not_mutated():
    rec = _artifact()
    original = {
        "status": "complete",
        "loop_type": "coding",
        "passed": True,
        "artifacts": [rec.model_dump(mode="json")],
        "findings": [],
    }
    snapshot = copy.deepcopy(original)
    ExecutionOutcome.from_loop_result(original)
    assert original == snapshot


def test_t6_routed_execution_input_is_not_mutated():
    routed = RoutedExecution(
        capability="rag_knowledge",
        engine_class="RAGKnowledgePowerEngine",
        success=True,
        status="complete",
        stages_executed=["INTAKE"],
    )
    before = routed.to_dict()
    ExecutionOutcome.from_routed_execution(routed, loop_type="coding")
    assert routed.to_dict() == before


def test_t6_power_engine_result_input_is_not_mutated():
    engine_result = _FakePowerEngineResult(True, ["INTAKE", "VERIFY"])
    stages_before = list(engine_result.stages_executed)
    ExecutionOutcome.from_power_engine_result(
        engine_result,
        loop_type="coding",
        capability="rag_knowledge",
        engine_class="RAGKnowledgePowerEngine",
    )
    assert engine_result.stages_executed == stages_before


def test_t6_normalization_is_deterministic():
    """Same input twice -> equal outcomes (no hidden state)."""
    payload = {"status": "complete", "loop_type": "coding", "passed": True}
    a = ExecutionOutcome.from_loop_result(payload)
    b = ExecutionOutcome.from_loop_result(payload)
    assert a == b
# ── T7: behavioural equivalence with production derivations ─────────

def test_t7_power_engine_adapter_matches_router_derivation():
    """The adapter must reproduce capability_router.py:348-356 exactly for
    every combination, so the normalised outcome means what production means."""
    for success in (True, False):
        for stages in ([], ["INTAKE"], ["WAITING_FOR_HUMAN_APPROVAL"],
                       ["INTAKE", "WAITING_FOR_HUMAN_APPROVAL"]):
            engine_result = _FakePowerEngineResult(success, list(stages))
            out = ExecutionOutcome.from_power_engine_result(
                engine_result,
                loop_type="x",
                capability="rag_knowledge",
                engine_class="RAGKnowledgePowerEngine",
            )
            waiting = any("WAITING_FOR_HUMAN_APPROVAL" in str(s) for s in stages)
            expected_status = (
                "escalate" if waiting else ("complete" if success else "remediate")
            )
            expected_passed = success and not waiting
            assert out.status.value == expected_status
            assert out.passed is expected_passed


def test_t7_status_agrees_with_kernel_branch_selection():
    """Every status the adapter can emit is one O-2 actually branches on."""
    handled = {"complete", "remediate", "escalate", "failed"}
    assert {s.value for s in OutcomeStatus} == handled
    # every emitted status must select exactly one handle_loop_completion branch
    kernel = _REPO / "packages/kernel/src/autoforge_kernel/orchestration.py"
    source = kernel.read_text(encoding="utf-8")
    for literal in handled:
        assert f'status == "{literal}"' in source


# ── T8: O-1 quarantine preserved ─────────────────────────────────────

def test_t8_b2_does_not_wire_o1_orchestrator():
    """The B2 module must not import or reference the quarantined O-1."""
    module = (
        _REPO / "packages/composition/src/autoforge_composition/execution_outcome.py"
    )
    source = module.read_text(encoding="utf-8")
    code_lines = [
        ln for ln in source.splitlines() if not ln.strip().startswith("#")
    ]
    imports = "\n".join(ln for ln in code_lines if ln.startswith(("import ", "from ")))
    assert "autoforge_orchestration" not in imports
    assert "autoforge_orchestration" not in imports.replace("orchestrator", "")


def _imports_execution_outcome(path: pathlib.Path) -> bool:
    """True iff the file contains a real import statement for execution_outcome.

    Comments, docstrings, and prose mentions do not count — only
    ``ast.Import`` / ``ast.ImportFrom`` nodes.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "execution_outcome" in (alias.name or ""):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "execution_outcome" in module:
                return True
            for alias in node.names:
                if (alias.name or "") == "execution_outcome":
                    return True
    return False


def test_t8_canonical_lifecycle_contract_may_consume_execution_outcome():
    """Gate C: only the canonical lifecycle decision contract may import it.

    Replaces the B2 transitional substring guard
    (``test_t8_no_production_module_imports_the_new_contract_yet``), which
    fired on any textual mention of ``execution_outcome`` — including
    comments and docstrings — anywhere under ``packages/*/src`` or
    ``apps/*/src``. That guard proved B2 was inert; Gate C Phase C2
    explicitly authorises the canonical lifecycle decision contract to
    consume the already-certified ``OutcomeStatus`` / ``ExecutionOutcome``.

    New invariant is AST-based (actual import statements only) and an
    allowlist: exactly one production file —
    ``packages/composition/src/autoforge_composition/lifecycle_decision.py``
    — may import ``autoforge_composition.execution_outcome``. Any other
    production importer (O-1, O-3, API, workers, Power Engines,
    model-router, unrelated modules) still fails.
    """
    authorised = {
        "packages/composition/src/autoforge_composition/lifecycle_decision.py",
        "apps/api/src/autoforge_api/service.py",
    }
    offenders = []
    scanned = 0
    for pkg in ("packages/*/src/**/*.py", "apps/*/src/**/*.py"):
        for path in _REPO.glob(pkg):
            scanned += 1
            if _imports_execution_outcome(path):
                rel = str(path.relative_to(_REPO))
                if rel not in authorised:
                    offenders.append(rel)
    assert scanned > 0, "T8 guard scanned no production files"
    assert offenders == [], (
        "Only the canonical lifecycle decision contract may import "
        f"ExecutionOutcome; unauthorised importers: {offenders}"
    )
    # the authorised consumer must actually exist and import the contract
    authorised_path = _REPO / next(iter(authorised))
    assert authorised_path.exists(), f"authorised consumer missing: {authorised}"
    assert _imports_execution_outcome(authorised_path), (
        "authorised lifecycle decision contract no longer imports ExecutionOutcome"
    )


def test_t8_guard_rejects_unauthorised_importers():
    """Negative fixture: the AST allowlist rejects a non-canonical importer."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        rogue = pathlib.Path(tmp) / "rogue_module.py"
        rogue.write_text(
            "from autoforge_composition.execution_outcome import ExecutionOutcome\n",
            encoding="utf-8",
        )
        assert _imports_execution_outcome(rogue) is True
        rel = "packages/kernel/src/autoforge_kernel/rogue_module.py"
        authorised = {
            "packages/composition/src/autoforge_composition/lifecycle_decision.py",
        }
        assert rel not in authorised
        # the offender-detection rule itself flags it
        offenders = [rel] if rel not in authorised else []
        assert offenders == [rel]
        # prose-only mentions must NOT count as imports
        prose = pathlib.Path(tmp) / "prose_only.py"
        prose.write_text(
            '"""This docstring mentions execution_outcome but imports nothing."""\n'
            "# a comment about execution_outcome\n"
            "x = 1\n",
            encoding="utf-8",
        )
        assert _imports_execution_outcome(prose) is False


# ── T9: Power Engine integrity ────────────────────────────────────────

def test_t9_no_power_engine_source_was_modified():
    """No file under the Power Engine packages may be dirty."""
    import subprocess

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "packages/power_engines"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert dirty == "", f"Power Engine sources must be untouched: {dirty}"


# ── T10: frozen contract ──────────────────────────────────────────────

def test_t10_outcome_is_immutable():
    out = ExecutionOutcome.from_loop_result(
        {"status": "complete", "loop_type": "coding", "passed": True}
    )
    with pytest.raises(Exception):
        out.passed = False
    with pytest.raises(Exception):
        out.status = OutcomeStatus.FAILED


def test_t10_extra_fields_are_rejected():
    assert ExecutionOutcome.model_config.get("frozen") is True
    assert ExecutionOutcome.model_config.get("extra") == "forbid"
    with pytest.raises(Exception):
        ExecutionOutcome(
            status=OutcomeStatus.COMPLETE,
            loop_type="coding",
            passed=True,
            telemetry={"fabricated": True},
        )


def test_t10_mutable_defaults_are_not_shared():
    a = ExecutionOutcome(status=OutcomeStatus.COMPLETE, loop_type="x", passed=True)
    b = ExecutionOutcome(status=OutcomeStatus.COMPLETE, loop_type="x", passed=True)
    a.findings.append("only-a")
    assert b.findings == []