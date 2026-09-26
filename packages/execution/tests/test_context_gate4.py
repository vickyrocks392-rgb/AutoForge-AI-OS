"""
Gate 4 verification tests — defects found and fixed during Gate 4.

Each test names the defect it pins. These are regression locks: without them the
Gate 3 behaviour would silently return, because in every case the Gate 3 code
still *passed* its own tests while the behaviour was wrong.

Run:  .venv/bin/python -m pytest packages/execution/tests/test_context_gate4.py -q
"""


from __future__ import annotations

from pathlib import Path

import pytest

from autoforge_execution.context_budget import BudgetSource, ModelWindow
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
)
from autoforge_execution.context_selection import SelectionPolicy
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
)
from autoforge_execution.prompt_assembly import build_messages
from autoforge_workflows.models import TaskDefinition


def _task(task_id: str = "t-g4") -> TaskDefinition:
    return TaskDefinition(
        task_id=task_id,
        name="Repair retry backoff",
        task_type="coding",
        description="The backoff helper returns the wrong delay sequence.",
        input_data={},
    )


def _diagnosis() -> DiagnosisReport:
    return DiagnosisReport(
        root_cause="compute_backoff clamps the final delay instead of doubling it",
        failure_mechanism="expected [1,2,4,8] got [1,2,4,4]",
        affected_files=["src/retry/service.py"],
        suggested_fix="Remove the clamp.",
        confidence_score=0.9,
    )


def _evaluation() -> EvaluationResult:
    return EvaluationResult(
        status=EvaluationStatus.FAILED,
        failures=["test_backoff::test_sequence FAILED: expected [1,2,4,8] got [1,2,4,4]"],
    )


async def _assemble(tmp_path: Path, *, builder=None, **kwargs):
    builder = builder or EngineeringContextBuilder(enable_context_engineering=True)
    return await builder.assemble_context(
        task_def=_task(),
        workspace_root=tmp_path,
        last_evaluation=_evaluation(),
        last_diagnosis=_diagnosis(),
        effective_model_requirements={},
        stage="diagnosis",
        **kwargs,
    )



# --- D1: dependency expansion was dead code on the canonical path ----------


@pytest.mark.asyncio
async def test_canonical_builder_emits_real_dependency_edges(tmp_path: Path):
    """Gate 3 emitted no ``depends_on`` at all, so expansion never ran."""
    ctx = await _assemble(tmp_path, context_window_tokens=8192)
    items = ctx.selected_context_items
    diag = next(i for i in items if "compute_backoff" in i.content)
    evaluation = next(i for i in items if "Evaluation failures" in i.content)
    assert diag.depends_on == (evaluation.context_id,)
    assert ctx.context_assembly_record.expansion_depth_reached >= 1


@pytest.mark.asyncio
async def test_expansion_target_is_actually_delivered(tmp_path: Path):
    """An expansion that does not deliver its target would be a silent drop."""
    ctx = await _assemble(tmp_path, context_window_tokens=8192)
    ids = {i.context_id for i in ctx.selected_context_items}
    for item in ctx.selected_context_items:
        for dep in item.depends_on:
            assert dep in ids, f"{item.context_id} depends on undelivered {dep}"


# --- D2: MODEL_METADATA budget source was never produced -------------------


class _RecordingAllocator:
    def __init__(self, window: int) -> None:
        self.window = window
        self.seen_min: int | None = None

    def allocate_model_window(
        self, *, min_context_window_tokens, model_id=None, requirements=None
    ):
        self.seen_min = min_context_window_tokens
        return ModelWindow(
            model_id="allocated-model",
            context_window_tokens=self.window,
            max_output_tokens=2048,
            provider_id="local-runtime",
        )


@pytest.mark.asyncio
async def test_two_pass_budget_uses_allocated_model_metadata(tmp_path: Path):
    alloc = _RecordingAllocator(32768)
    builder = EngineeringContextBuilder(
        enable_context_engineering=True, model_allocator=alloc
    )
    ctx = await _assemble(tmp_path, builder=builder)
    record = ctx.context_assembly_record
    assert record.budget_source == BudgetSource.MODEL_METADATA.value
    assert record.context_window_tokens == 32768
    assert record.model_id == "allocated-model"
    assert alloc.seen_min == record.declared_required_window_tokens > 0
    assert record.budget["reserved_for_output_tokens"] == 2048


@pytest.mark.asyncio
async def test_caller_window_still_wins_over_allocator(tmp_path: Path):
    """An explicit caller window must not be overridden by allocation."""
    alloc = _RecordingAllocator(32768)
    builder = EngineeringContextBuilder(
        enable_context_engineering=True, model_allocator=alloc
    )
    ctx = await _assemble(tmp_path, builder=builder, context_window_tokens=4096)
    assert ctx.context_assembly_record.budget_source == BudgetSource.CALLER.value
    assert ctx.context_assembly_record.context_window_tokens == 4096


@pytest.mark.asyncio
async def test_absent_allocator_falls_back_and_says_so(tmp_path: Path):
    ctx = await _assemble(tmp_path)
    record = ctx.context_assembly_record
    assert record.budget_source == BudgetSource.CONSERVATIVE_DEFAULT.value
    assert record.declared_required_window_tokens > 0


@pytest.mark.asyncio
async def test_allocator_failure_does_not_mask_a_budget_problem(tmp_path: Path):
    """An allocator bug must not silently become a bigger budget."""

    class Broken:
        def allocate_model_window(self, **kwargs):
            raise RuntimeError("router unavailable")

    builder = EngineeringContextBuilder(
        enable_context_engineering=True, model_allocator=Broken()
    )
    ctx = await _assemble(tmp_path, builder=builder)
    assert ctx.context_assembly_record.budget_source == (
        BudgetSource.CONSERVATIVE_DEFAULT.value
    )


# --- D3: mandatory provenance was never validated --------------------------


@pytest.mark.asyncio
async def test_mandatory_context_carries_explicit_provenance(tmp_path: Path):
    ctx = await _assemble(tmp_path, context_window_tokens=8192)
    for entry in ctx.context_assembly_record.selected:
        if entry.required:
            assert entry.provenance_ref, "mandatory item lost its provenance"
            assert entry.provenance_inferred is False


# --- D5: the canonical prompt constructor was order-dependent --------------


def _item(content: str, category: ContextCategory, relevance: float) -> ContextItem:
    return ContextItem(
        content=content,
        category=category,
        source=ContextSource("test", content[:8]),
        relevance=relevance,
        provenance=ContextProvenance(acquired_from="test", source_ref=content[:8]),
    )


def test_prompt_is_identical_under_input_reordering():
    """Gate 3 rendered items in caller order, so the canonical constructor was
    not actually canonical. Same set, different order, same prompt."""
    a = _item("alpha", ContextCategory.EVIDENCE, 0.9)
    b = _item("beta", ContextCategory.EVIDENCE, 0.1)
    c = _item("gamma", ContextCategory.TASK, 0.5)
    fwd = build_messages([a, b, c], task_name="T")
    rev = build_messages([c, b, a], task_name="T")
    assert fwd == rev
    assert fwd[0]["content"].index("alpha") < fwd[0]["content"].index("beta")
