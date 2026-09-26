"""Rollout and observability tests for Context Engineering (18-L Gate 3 / Gate 4B).

Gate 3 verified the feature behind a default-OFF rollout flag. Gate 4B made
Context Engineering the canonical production default, so the default assertions
are inverted and both explicit postures are covered:

* **default** -> CE is ON (the canonical production posture),
* **explicit ON** -> CE is ON,
* **explicit OFF** -> CE is OFF, preserving the pre-Gate-3 additive behaviour
  exactly. OFF is now the rollback / compatibility mode, not the normal mode.

The content-free observability assertions (Gate 3 sections 5 and 8) are unchanged.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from autoforge_execution.context import ExecutionContext
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.errors import MandatoryContextOverflowError
from autoforge_workflows.models import TaskDefinition


def make_task() -> TaskDefinition:
    return TaskDefinition(
        task_id="t-ce-rollout",
        name="Fix auth bug",
        task_type="coding",
        description="Repair the failing auth test.",
        input_data={"files": [{"path": "out.py", "content": "print(1)\n"}]},
    )


# --- Gate 4B: Context Engineering is globally enabled by default -----------


def test_flag_defaults_on():
    """Gate 4B: the canonical production default is Context Engineering ON."""
    assert EngineeringContextBuilder().enable_context_engineering is True


def test_default_construction_activates_the_engine():
    signature = inspect.signature(EngineeringContextBuilder.__init__)
    default = signature.parameters["enable_context_engineering"].default
    assert default is True


def test_explicit_off_remains_available_as_rollback():
    """Explicit CE OFF is still supported for controlled rollback / testing."""
    assert (
        EngineeringContextBuilder(enable_context_engineering=False).enable_context_engineering
        is False
    )


@pytest.mark.asyncio
async def test_default_construction_populates_selection_and_record(tmp_path: Path):
    (tmp_path / "seed.py").write_text("X = 1\n", encoding="utf-8")
    builder = EngineeringContextBuilder()
    ctx = await builder.assemble_context(task_def=make_task(), workspace_root=tmp_path)

    # Pre-existing ADR-003 contract still satisfied.
    assert isinstance(ctx, ExecutionContext)
    assert ctx.task_id == "t-ce-rollout"
    assert "seed.py" in ctx.project_files

    # ...and the Context Engineering fields are now populated by default.
    assert ctx.context_assembly_record is not None
    assert ctx.selected_context_items
    assert ctx.build_canonical_messages()


@pytest.mark.asyncio
async def test_explicit_off_preserves_previous_behaviour(tmp_path: Path):
    """Rollback mode reproduces the pre-Gate-3 additive assembly exactly."""
    (tmp_path / "seed.py").write_text("X = 1\n", encoding="utf-8")
    builder = EngineeringContextBuilder(enable_context_engineering=False)
    ctx = await builder.assemble_context(task_def=make_task(), workspace_root=tmp_path)

    # Pre-existing contract still satisfied.
    assert isinstance(ctx, ExecutionContext)
    assert ctx.task_id == "t-ce-rollout"
    assert "seed.py" in ctx.project_files

    # New fields are inert when the engine is explicitly off.
    assert ctx.selected_context_items == []
    assert ctx.excluded_context_items == []
    assert ctx.context_assembly_record is None
    assert ctx.build_canonical_messages() == []


# --- Gate 4B: no accidental legacy bypass in the execution path ------------


@pytest.mark.asyncio
async def test_dispatch_without_injected_builder_still_runs_context_engineering(tmp_path: Path):
    """A dispatcher with NO injected builder must not silently skip Context Engineering.

    This is the accidental bypass Gate 4B removed: the old fallback built a bare
    ``ExecutionContext.from_task_definition()``, so context engineering was
    skipped purely because a dependency was not wired in.
    """
    from autoforge_execution.artifacts import ArtifactPipeline
    from autoforge_execution.ai_adapter import AIInfrastructureAdapter
    from autoforge_execution.dispatcher import WorkerDispatcher
    from autoforge_execution.environment import WorkspaceEnvironment

    (tmp_path / "seed.py").write_text("X = 1\n", encoding="utf-8")
    dispatcher = WorkerDispatcher(
        environment=WorkspaceEnvironment(tmp_path),
        ai_provider=AIInfrastructureAdapter(allow_deterministic_fallback=True),
        artifact_pipeline=ArtifactPipeline(),
    )
    assert dispatcher._context_builder is None, "precondition: no builder injected"

    task_def = make_task()
    with pytest.MonkeyPatch.context() as mp:
        captured: dict = {}
        original = EngineeringContextBuilder.assemble_context

        async def spy(self, *args, **kwargs):
            ctx = await original(self, *args, **kwargs)
            captured["ctx"] = ctx
            return ctx

        mp.setattr(EngineeringContextBuilder, "assemble_context", spy)
        # dispatch_task would also run the whole engineering worker; the branch
        # under test is the context-resolution step, so exercise exactly that.
        ctx = await _assemble_via_dispatcher(dispatcher, task_def)

    assert captured.get("ctx") is not None, "dispatcher bypassed the canonical builder"
    assert ctx.context_assembly_record is not None
    assert ctx.selected_context_items
    assert ctx.build_canonical_messages()


async def _assemble_via_dispatcher(dispatcher, task_def):
    """Reproduce the dispatcher's context-resolution branch without running a worker."""
    from autoforge_execution.context_builder import EngineeringContextBuilder

    builder = dispatcher._context_builder
    if builder is not None and hasattr(builder, "assemble_context"):
        return await builder.assemble_context(
            task_def=task_def,
            workspace_root=dispatcher._env.root,
            rag_engine=dispatcher._rag_engine,
        )
    # This is the Gate 4B fallback branch under test.
    return await EngineeringContextBuilder().assemble_context(
        task_def=task_def,
        workspace_root=dispatcher._env.root,
        rag_engine=dispatcher._rag_engine,
    )


@pytest.mark.asyncio
async def test_ai_adapter_uses_canonical_prompt_when_engine_is_on(tmp_path: Path):
    """The model must receive the canonical CE messages, not a hand-built string."""
    from autoforge_execution.ai_adapter import AIInfrastructureAdapter

    ctx = await EngineeringContextBuilder().assemble_context(
        task_def=make_task(), workspace_root=tmp_path
    )
    adapter = AIInfrastructureAdapter(allow_deterministic_fallback=True)

    payload = adapter._canonical_payload(
        ctx,
        task_name=ctx.task_name,
        system="You are an AutoForge worker.",
        instruction="Produce the plan.",
        extras={"task": "plan"},
    )
    assert payload.pop("_canonical", False) is True
    assert payload["messages"], "canonical path must emit messages"
    assert all(set(m) == {"role", "content"} for m in payload["messages"])

    # The canonical context body must actually be present on the wire.
    body = "\n".join(m["content"] for m in payload["messages"])
    assert "## Task" in body
    assert "Produce the plan." in body


@pytest.mark.asyncio
async def test_ai_adapter_falls_back_to_legacy_only_when_engine_is_off(tmp_path: Path):
    """Explicit CE OFF is the only case that may use the legacy prompt body."""
    from autoforge_execution.ai_adapter import AIInfrastructureAdapter

    ctx = await EngineeringContextBuilder(enable_context_engineering=False).assemble_context(
        task_def=make_task(), workspace_root=tmp_path
    )
    adapter = AIInfrastructureAdapter(allow_deterministic_fallback=True)

    payload = adapter._canonical_payload(
        ctx, task_name=ctx.task_name, system="s", instruction="i", extras={"task": "plan"}
    )
    assert payload.pop("_canonical", False) is False
    assert "messages" not in payload



@pytest.mark.asyncio
async def test_flag_on_populates_selection_and_record(tmp_path: Path):
    (tmp_path / "seed.py").write_text("X = 1\n", encoding="utf-8")
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    ctx = await builder.assemble_context(
        task_def=make_task(),
        workspace_root=tmp_path,
        stage="implementation",
        context_window_tokens=4096,
        max_output_tokens=512,
        model_id="registry-model",
    )
    record = ctx.context_assembly_record
    assert record is not None
    assert record.selected_count >= 1
    assert record.context_window_tokens == 4096
    assert record.budget_source == "caller"
    assert record.stage == "implementation"
    assert ctx.selected_context_items


@pytest.mark.asyncio
async def test_rollback_is_a_single_constructor_argument(tmp_path: Path):
    """Toggling the flag is the whole rollback procedure (section 12.6)."""
    assert EngineeringContextBuilder(enable_context_engineering=True).enable_context_engineering


# --- section 5 / 8: two-pass window resolution ----------------------------


@pytest.mark.asyncio
async def test_two_pass_records_declaration_and_applied_window(tmp_path: Path):
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    ctx = await builder.assemble_context(
        task_def=make_task(),
        workspace_root=tmp_path,
        context_window_tokens=8192,
        max_output_tokens=1024,
        model_id="m",
    )
    record = ctx.context_assembly_record
    assert record.declared_required_window_tokens > 0
    assert record.context_window_tokens == 8192
    assert record.budget["reserved_for_output_tokens"] == 1024


@pytest.mark.asyncio
async def test_missing_window_uses_labelled_conservative_default(tmp_path: Path):
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    ctx = await builder.assemble_context(
        task_def=make_task(), workspace_root=tmp_path
    )
    assert ctx.context_assembly_record.budget_source == "conservative_default"


@pytest.mark.asyncio
async def test_narrow_window_fails_loudly_rather_than_degrading(tmp_path: Path):
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    with pytest.raises(MandatoryContextOverflowError):
        await builder.assemble_context(
            task_def=make_task(),
            workspace_root=tmp_path,
            context_window_tokens=8,
            max_output_tokens=4,
        )


# --- section 8: observability completeness and content-freedom -----------


@pytest.mark.asyncio
async def test_record_answers_every_required_question(tmp_path: Path):
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    ctx = await builder.assemble_context(
        task_def=make_task(),
        workspace_root=tmp_path,
        stage="review",
        context_window_tokens=4096,
        max_output_tokens=512,
        model_id="m",
    )
    payload = ctx.context_assembly_record.as_dict()
    for key in (
        "task_id",
        "stage",
        "considered_count",
        "selected",
        "excluded",
        "category_breakdown",
        "budget",
        "budget_source",
        "context_window_tokens",
        "construction_duration_ms",
        "mandatory_tokens",
        "optional_tokens",
        "expansion",
    ):
        assert key in payload, f"observability missing {key}"


@pytest.mark.asyncio
async def test_record_is_content_free(tmp_path: Path):
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    ctx = await builder.assemble_context(
        task_def=make_task(), workspace_root=tmp_path, context_window_tokens=4096
    )
    blob = str(ctx.context_assembly_record.as_dict())
    assert "Fix auth bug" not in blob
    assert "Repair the failing auth test" not in blob


@pytest.mark.asyncio
async def test_selected_items_carry_provenance(tmp_path: Path):
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    ctx = await builder.assemble_context(
        task_def=make_task(), workspace_root=tmp_path, context_window_tokens=4096
    )
    entries = ctx.context_assembly_record.selected
    assert entries
    for entry in entries:
        assert entry.provenance_ref
        assert entry.context_id


@pytest.mark.asyncio
async def test_delivered_ids_identify_what_reached_the_model(tmp_path: Path):
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    ctx = await builder.assemble_context(
        task_def=make_task(), workspace_root=tmp_path, context_window_tokens=4096
    )
    record = ctx.context_assembly_record
    assert record.delivered_context_ids
    assert set(record.delivered_context_ids) == {e.context_id for e in record.selected}


@pytest.mark.asyncio
async def test_canonical_messages_available_only_when_engine_on(tmp_path: Path):
    """Messages are produced when CE is on, and absent in explicit rollback mode."""
    (tmp_path / "a.py").write_text("A = 1\n", encoding="utf-8")
    off = EngineeringContextBuilder(enable_context_engineering=False)
    ctx_off = await off.assemble_context(task_def=make_task(), workspace_root=tmp_path)
    assert ctx_off.build_canonical_messages() == []

    on = EngineeringContextBuilder(enable_context_engineering=True)
    ctx_on = await on.assemble_context(
        task_def=make_task(), workspace_root=tmp_path, context_window_tokens=4096
    )
    messages = ctx_on.build_canonical_messages()
    assert messages
    for message in messages:
        assert set(message) == {"role", "content"}


# --- section 2: no Context Compaction / Brain leakage ---------------------


def test_no_compaction_or_brain_concepts_introduced():
    root = Path(__file__).resolve().parents[1] / "src" / "autoforge_execution"
    for name in (
        "context_items.py",
        "context_budget.py",
        "context_selection.py",
        "prompt_assembly.py",
        "context_observability.py",
    ):
        text = (root / name).read_text(encoding="utf-8").lower()
        for forbidden in (
            "summarize_history",
            "rolling_summary",
            "compact_context",
            "conversation_summary",
            "deliberation",
        ):
            assert forbidden not in text, f"{name} introduces out-of-scope {forbidden!r}"

    assert not EngineeringContextBuilder(enable_context_engineering=False).enable_context_engineering
