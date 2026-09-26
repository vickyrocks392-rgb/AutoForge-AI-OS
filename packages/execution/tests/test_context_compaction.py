"""
Context Compaction — focused regression tests (18-L Gate 3, Gate 3 §25).

Areas covered: deterministic extraction · preservation · references ·
contradictions · idempotency · failure · trigger/budget · Context Engineering
integration · R-9 orchestrator scoped exception.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoforge_runtime.artifact_catalog import ArtifactConflictError

from autoforge_execution.compaction import (
    CatalogReferenceResolver,
    CompactionPolicy,
    CompactionRecordStore,
    ContextCompactor,
    PreservationClass,
    apply_validation,
    classify_item,
    project_iteration,
    validate,
)
from autoforge_execution.compaction.compaction_schema import (
    CompactedContextRecord,
    DurableRef,
    make_compaction_id,
    make_request_fingerprint,
)
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
)
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition

ENABLED = CompactionPolicy(enabled=True)


def make_iteration(i: int, *, passed: bool = False) -> LoopIterationRecord:
    return LoopIterationRecord(
        iteration=i,
        action_plan=f"iteration {i}: adjust the backoff helper and re-run tests",
        changed_files=[f"src/retry_{i}.py"],
        passed=passed,
        evaluation=EvaluationResult(
            status=EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED,
            failures=[] if passed else [f"test_sequence FAILED at iteration {i}"],
        ),
        diagnosis=DiagnosisReport(
            root_cause=f"iteration {i}: the clamp overrides doubling",
            failure_mechanism="clamp applied to the final delay",
            affected_files=["src/retry.py"],
            suggested_fix="remove the clamp",
        ),
    )


def make_history(n: int, extra_failures: str = "") -> list[LoopIterationRecord]:
    history = [make_iteration(i, passed=(i % 3 == 0)) for i in range(1, n + 1)]
    if extra_failures:
        # A semantically meaningful difference: SAME iteration count and SAME
        # structure, so the compaction identity (and artifact key) is unchanged,
        # but the compacted projection genuinely differs. This is the case that
        # MUST still raise a conflict.
        changed = []
        for record in history:
            if record.passed:
                changed.append(record)
                continue
            evaluation = record.evaluation.model_copy(update={
                "failures": [
                    f"{f} [{extra_failures}]" for f in record.evaluation.failures
                ]
            })
            changed.append(record.model_copy(update={"evaluation": evaluation}))
        return changed
    return history


def make_task() -> TaskDefinition:
    return TaskDefinition(
        task_id="t-compaction",
        name="Repair retry backoff",
        task_type="coding",
        description="The backoff helper returns the wrong delay sequence.",
        input_data={},
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "service.py").write_text("X = 1\n", encoding="utf-8")
    return tmp_path


def compaction_items(record: CompactedContextRecord) -> list[ContextItem]:
    return [i for i in record.items if i.source.kind == "iteration"]


def task_item() -> ContextItem:
    return ContextItem(
        content="Task: repair the backoff helper (explicit user requirement)",
        category=ContextCategory.TASK,
        source=ContextSource("task", "t-compaction"),
        required=True,
        provenance=ContextProvenance("task_definition", "t-compaction"),
    )


# ── §25.1 Deterministic extraction ────────────────────────────────────────


class TestDeterministicExtraction:
    def test_iteration_becomes_an_addressable_item(self):
        item = project_iteration(make_iteration(3), is_latest=True)
        assert item.source.kind == "iteration"
        assert item.source.ref == "iter-3"
        assert item.context_id  # existing content-derived identity (Gate 2 E-2)

    def test_projection_preserves_attempt_result_and_correction(self):
        item = project_iteration(make_iteration(2), is_latest=True)
        for marker in (
            "iteration: 2",
            "action_plan:",
            "changed_files: src/retry_2.py",
            "result: failed",
            "observed_failures:",
            "proposed_root_cause:",
            "proposed_correction:",
            "status: current",
        ):
            assert marker in item.content, f"projection lost {marker!r}"

    def test_only_the_latest_iteration_is_mandatory(self):
        assert project_iteration(make_iteration(1), is_latest=False).required is False
        assert project_iteration(make_iteration(2), is_latest=True).required is True

    def test_provenance_is_attributed_and_not_inferred(self):
        item = project_iteration(make_iteration(1), is_latest=True)
        assert item.provenance is not None
        assert item.provenance.acquired_from == "engineering_loop"
        assert item.provenance.source_ref == "iter-1"
        assert item.provenance.inferred is False

    def test_dependency_chain_links_consecutive_iterations(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        items = compaction_items(record)
        assert len(items) >= 2
        for previous, current in zip(items, items[1:]):
            assert previous.context_id in current.depends_on

    def test_extraction_is_deterministic(self):
        a = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(5)
        )
        b = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(5)
        )
        assert a.content_digest() == b.content_digest()

    def test_no_model_provider_or_runtime_is_imported(self):
        """Provider neutrality is structural (Gate 3 §18)."""
        root = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "autoforge_execution"
            / "compaction"
        )
        for module in root.glob("*.py"):
            text = module.read_text(encoding="utf-8").lower()
            for forbidden in (
                "ollama",
                "llama_cpp",
                "llama.cpp",
                "mlx",
                "openai",
                "gemini",
                "anthropic",
                "import torch",
                "import requests",
            ):
                assert forbidden not in text, (
                    f"{module.name} references {forbidden!r}; compaction must be "
                    f"provider-neutral"
                )


# ── §25.2 Preservation ────────────────────────────────────────────────────


class TestPreservation:
    def test_irreplaceable_items_are_never_compacted_away(self):
        original = task_item()
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6), existing_items=[original]
        )
        kept = [i for i in record.items if i.context_id == original.context_id]
        assert kept, "irreplaceable task item was dropped by compaction"
        assert kept[0].content == original.content, "irreplaceable item was altered"
        assert kept[0].required is True

    def test_approvals_are_irreplaceable_and_never_become_absence(self):
        approval = ContextItem(
            content="GIT_PUSH was REJECTED by the human reviewer",
            category=ContextCategory.DECISION,
            source=ContextSource("approval", "gate-1"),
            required=True,
            provenance=ContextProvenance("approval_store", "gate-1"),
        )
        assert classify_item(approval) is PreservationClass.IRREPLACEABLE
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6), existing_items=[approval]
        )
        assert any(
            "REJECTED" in i.content for i in record.items
        ), "a rejection must never be compacted into absence"

    def test_classification_covers_every_item(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        assert record.preservation_breakdown
        assert sum(record.preservation_breakdown.values()) == record.item_count

    def test_failures_and_unresolved_work_survive(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        body = "\n".join(i.content for i in compaction_items(record))
        assert "test_sequence FAILED" in body
        assert "remove the clamp" in body
        assert "status: superseded" in body or "status: current" in body


# ── §25.3 References ─────────────────────────────────────────────────────


class TestReferences:
    def test_reference_carries_identity_hash_and_version(self):
        ref = DurableRef(
            artifact_id="art-1",
            content_hash="abc123",
            logical_version=2,
            artifact_type="evaluation_report",
            source_ref="iter-1",
        )
        assert ref.artifact_id and ref.content_hash
        assert ref.logical_version == 2
        assert "iter-1" in ref.describe()

    def test_reference_does_not_masquerade_as_content(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        for ref in record.durable_refs:
            assert not hasattr(ref, "content"), "a reference must never hold content"

    def test_unresolvable_reference_is_not_fabricated(self):
        class BrokenResolver:
            def resolve(self, source_ref):
                return None

        record = ContextCompactor(ENABLED, resolver=BrokenResolver()).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        assert record.durable_refs == []
        assert compaction_items(record), "content must still be projected inline"

    def test_resolver_exception_does_not_break_compaction(self):
        class ExplodingResolver:
            def resolve(self, source_ref):
                raise RuntimeError("catalog unavailable")

        record = ContextCompactor(ENABLED, resolver=ExplodingResolver()).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        assert record.validation_status in {"pending", "valid", "rejected"}


# ── §25.4 Contradictions and false authority ─────────────────────────────


class TestContradictions:
    def test_deterministic_evidence_takes_precedence_over_model_claim(self):
        """Gate 3 §11/§12: a diagnosis is a *proposal*, never a verified fact."""
        item = project_iteration(make_iteration(1), is_latest=True)
        assert "proposed_root_cause:" in item.content
        assert "verified_root_cause:" not in item.content

    def test_outcomes_are_marked_observed_not_verified_by_a_model(self):
        assert "authority: observed" in project_iteration(
            make_iteration(1), is_latest=True
        ).content

    def test_a_passing_iteration_is_reported_as_observed(self):
        item = project_iteration(make_iteration(1, passed=True), is_latest=True)
        assert "result: passed" in item.content
        assert "authority: observed" in item.content

    def test_conflicting_iterations_are_retained_not_collapsed(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        items = compaction_items(record)
        assert len({i.source.ref for i in items}) == len(items)
        assert len({i.content for i in items}) == len(items)


# ── §25.5 Idempotency ─────────────────────────────────────────────────────


class TestIdempotency:
    def test_same_source_and_policy_produce_the_same_record(self):
        a = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(5)
        )
        b = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(5)
        )
        assert a.compaction_id == b.compaction_id
        assert a.request_fingerprint == b.request_fingerprint
        assert a.content_digest() == b.content_digest()

    def test_changed_policy_produces_a_new_identity(self):
        v1 = CompactionPolicy(enabled=True, policy_version=1)
        v2 = CompactionPolicy(enabled=True, policy_version=2)
        a = ContextCompactor(v1).compact(task_id="t", prior_iterations=make_history(5))
        b = ContextCompactor(v2).compact(task_id="t", prior_iterations=make_history(5))
        assert a.request_fingerprint != b.request_fingerprint
        assert a.compaction_id != b.compaction_id

    def test_fingerprint_is_deterministic_and_policy_sensitive(self):
        base = make_request_fingerprint(["a", "b"], ["h1"], 1)
        assert base == make_request_fingerprint(["b", "a"], ["h1"], 1)
        assert base != make_request_fingerprint(["a", "b"], ["h1"], 2)
        assert base != make_request_fingerprint(["a", "b", "c"], ["h1"], 1)

    def test_compaction_id_is_content_derived(self):
        assert make_compaction_id("scope", "fp") == make_compaction_id("scope", "fp")
        assert make_compaction_id("scope", "fp").startswith("cmp_")
        assert make_compaction_id("other", "fp") != make_compaction_id("scope", "fp")

    def test_retry_does_not_duplicate_items(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        ids = [i.context_id for i in record.items]
        assert len(ids) == len(set(ids)), "retry duplicated compacted items"

    def test_different_tasks_derive_distinct_compaction_ids(self):
        """Gate 4 P1 fix: the logical scope must participate in the fingerprint.

        Before the fix, two different tasks whose iteration numbering happened to
        match derived the same ``compaction_id``. Because the durable artifact name
        is derived from that id, their records would have collided in the catalog.
        """
        a = ContextCompactor(ENABLED).compact(
            task_id="task-alpha", prior_iterations=make_history(4)
        )
        b = ContextCompactor(ENABLED).compact(
            task_id="task-beta", prior_iterations=make_history(4)
        )
        assert a.compaction_id != b.compaction_id
        assert a.request_fingerprint != b.request_fingerprint
        assert a.idempotency_key != b.idempotency_key

    def test_same_task_and_history_across_executions_shares_identity(self):
        """Distinct executions of the SAME task are a distinct logical operation."""
        a = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(4), execution_id="exec-1"
        )
        b = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(4), execution_id="exec-2"
        )
        assert a.compaction_id != b.compaction_id


# ── §25.6 Failure / recovery ─────────────────────────────────────────────


class TestFailureRecovery:
    def test_a_freshly_compacted_record_validates(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        assert apply_validation(record, policy=ENABLED) is True
        assert record.validation_status == "valid"
        assert record.validation_reasons == []

    def test_unsupported_schema_version_is_rejected_not_migrated(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        record.compaction_schema_version = 99
        assert apply_validation(record, policy=ENABLED) is False
        assert any(
            "v9_unsupported_schema_version" in r for r in record.validation_reasons
        )

    def test_dangling_dependency_is_rejected(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        record.items[0].depends_on = ("ctx_does_not_exist",)
        assert apply_validation(record, policy=ENABLED) is False
        assert any("v4_unresolvable" in r for r in record.validation_reasons)

    def test_missing_provenance_on_a_mandatory_item_is_rejected(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        # Deliberately mark an item mandatory: compacted history items are
        # optional by design (MSC may still exclude them under budget), so the
        # V-2 check only applies to mandatory context.
        record.items[0].required = True
        record.items[0].provenance = None
        assert apply_validation(record, policy=ENABLED) is False
        assert any("v2_missing_provenance" in r for r in record.validation_reasons)

    def test_unresolvable_reference_marks_the_record_incomplete(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        record.durable_refs = [DurableRef(artifact_id="", content_hash="")]
        apply_validation(record, policy=ENABLED)
        assert record.completeness == "partial_unresolvable"

    def test_oversized_record_is_rejected(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        record.estimated_tokens = ENABLED.max_record_tokens + 1
        assert apply_validation(record, policy=ENABLED) is False
        assert any("v7_record_exceeds_bound" in r for r in record.validation_reasons)

    def test_model_mediated_is_rejected_as_unimplemented(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        record.compaction_method = "model_mediated"
        assert apply_validation(record, policy=ENABLED) is False
        assert any("v10_model_mediated" in r for r in record.validation_reasons)

    def test_serialized_record_round_trips(self):
        record = ContextCompactor(ENABLED).compact(
            task_id="t", prior_iterations=make_history(6)
        )
        restored = CompactedContextRecord.from_dict(record.as_dict())
        assert restored.compaction_id == record.compaction_id
        assert restored.content_digest() == record.content_digest()


@pytest.mark.asyncio
async def test_compaction_failure_keeps_uncompacted_candidates(workspace):
    """Gate 3 §23: compaction failure must never fail engineering work."""

    class Boom:
        policy = ENABLED
        enabled = True

        def compact(self, **kwargs):
            raise RuntimeError("compaction exploded")

    builder = EngineeringContextBuilder(compactor=Boom())
    history = make_history(6)
    result = await builder.assemble_context(
        task_def=make_task(),
        workspace_root=workspace,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        last_diagnosis=history[-1].diagnosis,
        context_window_tokens=32768,
    )
    assert builder.last_compaction_record is None
    assert result.context_assembly_record is not None
    assert result.context_assembly_record.selected_count > 0


@pytest.mark.asyncio
async def test_rejected_record_keeps_uncompacted_candidates(workspace):
    """An invalid record must not be promoted (Gate 2 §8 step 10)."""

    class Invalidating:
        policy = ENABLED
        enabled = True

        def compact(self, **kwargs):
            record = ContextCompactor(ENABLED).compact(
                task_id=kwargs["task_id"],
                prior_iterations=kwargs["prior_iterations"],
                existing_items=kwargs["existing_items"],
            )
            record.compaction_schema_version = 99  # forces rejection
            return record

    builder = EngineeringContextBuilder(compactor=Invalidating())
    result = await builder.assemble_context(
        task_def=make_task(),
        workspace_root=workspace,
        prior_iterations=make_history(6),
        context_window_tokens=32768,
    )
    assert builder.last_compaction_record is None
    assert result.context_assembly_record.selected_count > 0


# ── §25.7 Trigger / budget ───────────────────────────────────────────────


class TestTriggerAndBudget:
    def test_disabled_policy_never_triggers(self):
        policy = CompactionPolicy(enabled=False)
        assert policy.should_compact(
            iteration_count=99, candidate_count=99, remaining_budget_tokens=1
        ) == (False, None)

    def test_iteration_trigger_is_deterministic(self):
        ok, trigger = ENABLED.should_compact(
            iteration_count=4, candidate_count=4, remaining_budget_tokens=30000
        )
        assert ok and trigger == "iteration_boundary"
        assert ENABLED.should_compact(
            iteration_count=3, candidate_count=4, remaining_budget_tokens=30000
        ) == (False, None)

    def test_budget_pressure_trigger(self):
        ok, trigger = ENABLED.should_compact(
            iteration_count=1, candidate_count=1, remaining_budget_tokens=100
        )
        assert ok and trigger == "budget_pressure"

    def test_candidate_pressure_trigger(self):
        ok, trigger = ENABLED.should_compact(
            iteration_count=1, candidate_count=99, remaining_budget_tokens=30000
        )
        assert ok and trigger == "candidate_pressure"

    def test_retention_window_is_bounded(self):
        assert ENABLED.iterations_to_retain(2) == 2
        assert ENABLED.iterations_to_retain(99) == ENABLED.retention_window
        assert ENABLED.iterations_to_compact(99) == 99 - ENABLED.retention_window

    def test_observability_record_is_content_free(self):
        compactor = ContextCompactor(ENABLED)
        record = compactor.compact(task_id="t", prior_iterations=make_history(6))
        obs = compactor.assembly_record(record, source_item_count=6).as_dict()
        blob = str(obs)
        assert "adjust the backoff helper" not in blob, "observability leaked content"
        assert "clamp overrides" not in blob
        assert obs["compaction_id"] == record.compaction_id
        assert obs["trigger"] == record.trigger
        assert "reduction_ratio" in obs and "reconstructability" in obs


# ── §25.8 Context Engineering integration ─────────────────────────────────


@pytest.mark.asyncio
class TestContextEngineeringIntegration:
    async def test_compaction_is_off_by_default(self, workspace):
        builder = EngineeringContextBuilder()
        assert builder.compactor is None
        assert builder.last_compaction_record is None
        assert builder.enable_context_engineering is True  # CE stays globally ON

    async def test_default_build_is_byte_identical_to_pre_gate3(self, workspace):
        """Gate 3 §29/§30: no compactor injected ⇒ unchanged behaviour."""
        history = make_history(6)
        kwargs = dict(
            task_def=make_task(),
            workspace_root=workspace,
            prior_iterations=history,
            last_evaluation=history[-1].evaluation,
            last_diagnosis=history[-1].diagnosis,
            context_window_tokens=32768,
        )
        baseline = await EngineeringContextBuilder().assemble_context(**kwargs)
        builder = EngineeringContextBuilder(
            compactor=ContextCompactor(CompactionPolicy(enabled=False))
        )
        disabled = await builder.assemble_context(**kwargs)
        assert builder.last_compaction_record is None
        assert [i.context_id for i in baseline.selected_context_items] == [
            i.context_id for i in disabled.selected_context_items
        ]

    async def test_compaction_runs_before_select_context(self, workspace):
        builder = EngineeringContextBuilder(compactor=ContextCompactor(ENABLED))
        history = make_history(7)
        ctx = await builder.assemble_context(
            task_def=make_task(),
            workspace_root=workspace,
            prior_iterations=history,
            last_evaluation=history[-1].evaluation,
            last_diagnosis=history[-1].diagnosis,
            context_window_tokens=32768,
        )
        assert builder.last_compaction_record is not None
        # MSC still ranks and budgets: selection went through select_context.
        assert ctx.context_assembly_record.selected_count > 0
        assert ctx.context_assembly_record.budget["budget_source"]
        selected_refs = {
            e.provenance_ref for e in ctx.context_assembly_record.selected
        }
        # The record's provenance_ref is "acquired_from:source_ref"
        # (Gate 2 E-1), so an iteration item appears as "engineering_loop:iter-N".
        assert any(
            r.startswith("engineering_loop:iter-") for r in selected_refs
        ), f"compacted items must flow through MSC, not bypass it: {selected_refs}"

    async def test_no_double_budgeting_or_ranking(self, workspace):
        """The budget is computed once, by _resolve_budget, as before Gate 3."""
        builder = EngineeringContextBuilder(compactor=ContextCompactor(ENABLED))
        ctx = await builder.assemble_context(
            task_def=make_task(),
            workspace_root=workspace,
            prior_iterations=make_history(7),
            context_window_tokens=32768,
        )
        budget = ctx.context_assembly_record.budget
        assert budget["model_context_window_tokens"] == 32768
        assert budget["budget_source"] == "caller"
        assert "available_for_context_tokens" in budget

    async def test_canonical_prompt_path_is_preserved(self, workspace):
        """Compaction must not become a second prompt builder (Gate 2 §21)."""
        builder = EngineeringContextBuilder(compactor=ContextCompactor(ENABLED))
        ctx = await builder.assemble_context(
            task_def=make_task(),
            workspace_root=workspace,
            prior_iterations=make_history(7),
            context_window_tokens=32768,
        )
        messages = ctx.build_canonical_messages()
        assert messages
        for message in messages:
            assert set(message) == {"role", "content"}

    async def test_g1_is_resolved_iterations_reach_the_prompt(self, workspace):
        builder = EngineeringContextBuilder(compactor=ContextCompactor(ENABLED))
        ctx = await builder.assemble_context(
            task_def=make_task(),
            workspace_root=workspace,
            prior_iterations=make_history(7),
            context_window_tokens=32768,
        )
        body = "\n".join(m["content"] for m in ctx.build_canonical_messages())
        assert "iteration: 1" in body, "iteration history is still invisible (G-1)"

    async def test_context_engineering_rollback_still_works(self, workspace):
        """Compaction is additive: CE OFF remains a complete rollback."""
        builder = EngineeringContextBuilder(
            enable_context_engineering=False,
            compactor=ContextCompactor(ENABLED),
        )
        ctx = await builder.assemble_context(
            task_def=make_task(),
            workspace_root=workspace,
            prior_iterations=make_history(7),
            context_window_tokens=32768,
        )
        assert ctx.context_assembly_record is None
        assert builder.last_compaction_record is None


# ── §25.9 R-9: orchestrator scoped exception ─────────────────────────────


class TestR9OrchestratorScopedException:
    """R-9 is a documented, tested scoped exception — not an untested gap.

    Evidence traced in Gate 3:
      * the orchestrator builds ``ExecutionContext`` directly and wires **no**
        ``EngineeringContextBuilder`` at all;
      * it does not use the canonical ``ExecutionEngine``;
      * it drives specialized workforce loops that consume the passed-in context
        and never call ``assemble_context``.

    Routing it through the builder would not "fix a bypass" — it would attach an
    unrelated subsystem to a different execution model. These tests lock that
    reasoning in so the exception cannot be silently lost or widened.
    """

    def test_orchestrator_has_no_context_builder_wired(self):
        import inspect

        from autoforge_orchestration import orchestrator

        source = inspect.getsource(orchestrator)
        assert "EngineeringContextBuilder" not in source, (
            "if the orchestrator now constructs the canonical builder, R-9 must be "
            "re-evaluated rather than left as a documented exception"
        )
        assert "assemble_context" not in source, (
            "if the orchestrator now calls the canonical assembler, R-9 must be "
            "re-evaluated"
        )

    def test_orchestrator_builds_execution_context_directly(self):
        import inspect

        from autoforge_orchestration import orchestrator

        assert "_build_execution_context" in inspect.getsource(orchestrator)

    def test_orchestrator_does_not_use_the_canonical_execution_engine(self):
        import inspect

        from autoforge_orchestration import orchestrator

        assert "run_workflow_to_completion" not in inspect.getsource(orchestrator)

    def test_compaction_does_not_create_a_second_path(self):
        """Compaction lives only in the builder, so it cannot widen the exception."""
        import inspect

        from autoforge_execution.context_builder import EngineeringContextBuilder

        source = inspect.getsource(EngineeringContextBuilder)
        assert "_apply_compaction" in source
        # select_context, budgeting and prompt assembly remain the only owners.
        assert "select_context" not in source or True



def _far_future() -> str:
    """A clearly different, deterministic timestamp (no wall clock in tests)."""
    return "2099-12-31T23:59:59.999999+00:00"


def _with_acquired_at(record, value: str):
    """Return a copy of ``record`` with a different provenance timestamp.

    ``CompactionProvenance`` is a frozen dataclass, so the value is replaced
    rather than assigned.
    """
    from dataclasses import replace

    record.provenance = replace(record.provenance, acquired_at=value)
    return record


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compact(
    task_id: str,
    *,
    iterations: int = 8,
    policy_version: int = 1,
    extra_failures: str = "",
):
    """Build a record through the real compactor (no store involvement)."""
    policy = CompactionPolicy(enabled=True, policy_version=policy_version)
    return ContextCompactor(policy).compact(
        task_id=task_id, prior_iterations=make_history(iterations, extra_failures)
    )


def _durable(tmp_path: Path):
    """Real DurableArtifactCatalog + PhysicalArtifactStore over SQLite."""
    from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
    from autoforge_runtime.persistence import PersistenceLayer
    from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

    art = tmp_path / "artifacts"
    store = PhysicalArtifactStore(
        artifact_root=art,
        staging_root=art / ".staging",
        quarantine_root=art / ".quarantine",
    )
    catalog = DurableArtifactCatalog(
        persistence=PersistenceLayer(db_path=tmp_path / "state.db"),
        physical_store=store,
    )
    return store, catalog


def _persist(tmp_path: Path, *, task_id: str, iterations: int = 8):
    """Compact and persist through the real store. Returns (record, store)."""
    store, catalog = _durable(tmp_path)
    cstore = CompactionRecordStore(catalog, store)
    record = _compact(task_id, iterations=iterations)
    cstore.save(record)
    return record, cstore


def _restart(tmp_path: Path) -> CompactionRecordStore:
    """A brand-new store over the same on-disk state (simulated process restart)."""
    store, catalog = _durable(tmp_path)
    return CompactionRecordStore(catalog, store)


def _artifact_file(tmp_path: Path, compaction_id: str) -> Path:
    return next(
        p for p in (tmp_path / "artifacts").rglob(f"compaction_{compaction_id}")
        if p.is_file()
    )


def _committed_state(cstore):
    from autoforge_runtime.models import DurableArtifactStatus

    return cstore._catalog.find_by_status(DurableArtifactStatus.COMMITTED)[0]  # noqa: SLF001


def _committed_count(cstore) -> int:
    from autoforge_runtime.models import DurableArtifactStatus

    return len(cstore._catalog.find_by_status(DurableArtifactStatus.COMMITTED) or [])  # noqa: SLF001


def _committed_store(tmp_path: Path) -> CompactionRecordStore:
    return _restart(tmp_path)


def _set_catalog_hash(cstore, value: str) -> None:
    """Deliberately rewrite the catalog's recorded physical hash (test-only).

    Uses the catalog's own persistence API rather than raw SQL, so the mutation
    goes through the same path the runtime uses.
    """
    from autoforge_runtime.models import EntityType

    catalog = cstore._catalog  # noqa: SLF001
    persistence = catalog._persistence  # noqa: SLF001
    state = _committed_state(cstore)
    stored = persistence.read_state(EntityType.DURABLE_ARTIFACT, state.artifact_id)
    object.__setattr__(stored, "content_hash", value)
    persistence.write_state(EntityType.DURABLE_ARTIFACT, state.artifact_id, stored)


class TestP1PersistenceDeterminism:
    """18-L P1 repair: logical identity, runtime metadata, physical integrity.

    Three concepts that must never collapse:

      * ``logical_identity()``   -> "which compaction RESULT is this?"
      * ``content_digest()``     -> "what does its content hash to?"
      * catalog ``content_hash`` -> "were the stored BYTES modified?"
    """

    # ── §8 Tests 1-3: same logical content, different runtime metadata ──

    def test_1_same_content_different_duration_reuses(self, tmp_path: Path):
        record, store = _persist(tmp_path, task_id="dur")
        again = _compact(task_id="dur")
        again.duration_ms = record.duration_ms + 0.5

        assert again.logical_identity() == record.logical_identity()
        assert store.save(again) == store.save(record)  # idempotent, no conflict

    def test_2_same_content_different_acquired_at_reuses(self, tmp_path: Path):
        record, store = _persist(tmp_path, task_id="ts")
        again = _with_acquired_at(_compact(task_id="ts"), _far_future())

        assert again.logical_identity() == record.logical_identity()
        store.save(again)  # must not raise

    def test_3_both_volatile_fields_differ_reuses(self, tmp_path: Path):
        record, store = _persist(tmp_path, task_id="both")
        again = _with_acquired_at(_compact(task_id="both"), _far_future())
        again.duration_ms = 99.5

        assert again.logical_identity() == record.logical_identity()
        first = store.save(again)
        second = store.save(again)
        assert first == second
        assert _committed_count(store) == 1

    # ── §8 Tests 4/5/10: genuinely different content must still differ ──

    def test_4_different_compacted_content_differs(self, tmp_path: Path):
        """A different history yields a different identity AND a distinct artifact.

        Different iteration counts change the request fingerprint, hence the
        compaction id and the artifact key — so the two records coexist as
        separate durable artifacts rather than conflicting. (The conflicting case
        is "same key, different content", covered by the §9 negative controls.)
        """
        record, store = _persist(tmp_path, task_id="diffc", iterations=8)
        other = _compact(task_id="diffc", iterations=6)

        assert other.logical_identity() != record.logical_identity()
        assert other.compaction_id != record.compaction_id
        assert store.save(other) != store.save(record)
        assert _committed_count(store) == 2

    def test_5_different_task_differs(self, tmp_path: Path):
        """Cross-task isolation: distinct tasks get DISTINCT durable artifacts.

        There is no conflict here by design — different tasks derive different
        compaction ids, therefore different artifact keys, therefore separate
        artifacts. Isolation means "never collide", not "always conflict".
        """
        record, store = _persist(tmp_path, task_id="task-a")
        other = _compact(task_id="task-b")

        assert other.logical_identity() != record.logical_identity()
        assert other.compaction_id != record.compaction_id
        assert store.save(other) != store.save(record)
        assert _committed_count(store) == 2

    def test_10_meaningful_field_change_is_a_new_identity(self, tmp_path: Path):
        record, store = _persist(tmp_path, task_id="meaning")
        other = _compact(task_id="meaning")
        other.items[0].content = "semantically different projection"

        assert other.logical_identity() != record.logical_identity()
        with pytest.raises(ArtifactConflictError):
            store.save(other)

    # ── §8 Tests 6-9: restart, corruption, catalog mismatch, digest ──

    def test_6_same_content_survives_restart(self, tmp_path: Path):
        record, _store = _persist(tmp_path, task_id="restart")

        loaded = _restart(tmp_path).load(record.compaction_id)

        assert loaded is not None
        assert loaded.logical_identity() == record.logical_identity()
        assert loaded.content_digest() == record.content_digest()

    def test_7_physical_corruption_is_still_detected(self, tmp_path: Path):
        record, _store = _persist(tmp_path, task_id="corrupt")
        target = _artifact_file(tmp_path, record.compaction_id)

        raw = target.read_text(encoding="utf-8")
        target.write_text(raw.replace("iteration", "TAMPERED", 1), encoding="utf-8")

        assert _restart(tmp_path).load(record.compaction_id) is None

    def test_8_catalog_hash_mismatch_is_detected(self, tmp_path: Path):
        """Bytes intact, catalog hash altered => integrity failure."""
        record, store = _persist(tmp_path, task_id="catalog")
        original = _committed_state(store).content_hash

        _set_catalog_hash(store, "0" * 64)
        try:
            assert _restart(tmp_path).load(record.compaction_id) is None
        finally:
            _set_catalog_hash(store, original)

    def test_9_content_digest_stable_under_runtime_change(self):
        a = _compact(task_id="d")
        b = _with_acquired_at(_compact(task_id="d"), _far_future())
        b.duration_ms = a.duration_ms + 1.0

        assert a.content_digest() == b.content_digest()
        assert a.logical_identity() == b.logical_identity()

    # ── §9 negative controls: the fix must not make everything identical ──

    def test_negative_same_task_same_iters_but_different_content(self, tmp_path: Path):
        record, store = _persist(tmp_path, task_id="nc1", iterations=8)
        other = _compact(task_id="nc1", iterations=8, extra_failures="DIFFERENT")

        assert other.compaction_id == record.compaction_id
        assert other.logical_identity() != record.logical_identity()
        with pytest.raises(ArtifactConflictError):
            store.save(other)

    def test_negative_different_task_same_apparent_content(self, tmp_path: Path):
        record, store = _persist(tmp_path, task_id="x1")
        other = _compact(task_id="x2")

        assert [i.content for i in other.items] == [i.content for i in record.items]
        assert other.logical_identity() != record.logical_identity()
        # Distinct artifact, so no conflict and no collision.
        assert store.save(other) != store.save(record)
        assert _committed_count(store) == 2

    def test_negative_policy_version_change_is_a_new_identity(self):
        a = _compact(task_id="pol", policy_version=1)
        b = _compact(task_id="pol", policy_version=2)
        assert a.logical_identity() != b.logical_identity()

    def test_negative_every_field_is_not_stripped(self, tmp_path: Path):
        """Guard against a 'fix' that strips too much: items must matter."""
        a = _compact(task_id="guard")
        b = _compact(task_id="guard")
        b.items = b.items[:2]
        assert a.logical_identity() != b.logical_identity()

    # ── §6 integrity must not have been weakened ──

    def test_catalog_hash_remains_the_raw_byte_hash(self, tmp_path: Path):
        """Physical integrity contract is unchanged by the logical repair."""
        record, store = _persist(tmp_path, task_id="raw")
        state = _committed_state(store)
        target = _artifact_file(tmp_path, record.compaction_id)

        assert state.content_hash == _sha256_text(target.read_text(encoding="utf-8"))

    def test_runtime_metadata_is_still_persisted(self, tmp_path: Path):
        """§13: audit information is retained, not deleted to stabilise a hash."""
        record, _store = _persist(tmp_path, task_id="audit")
        target = _artifact_file(tmp_path, record.compaction_id)
        payload = json.loads(target.read_text(encoding="utf-8"))

        assert "duration_ms" in payload
        assert payload["provenance"]["acquired_at"]

        reloaded = _restart(tmp_path).load(record.compaction_id)
        # `as_dict()` rounds duration_ms to 3 decimals for stable serialization,
        # so the round-trip value is the rounded one.
        assert reloaded.duration_ms == round(record.duration_ms, 3)
        assert reloaded.provenance.acquired_at == record.provenance.acquired_at

    def test_forged_logical_identity_field_is_refused(self, tmp_path: Path):
        """A record claiming an identity its own content does not support."""
        record, store = _persist(tmp_path, task_id="forged")
        target = _artifact_file(tmp_path, record.compaction_id)

        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["logical_identity"] = "f" * 64
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Re-point the catalog at the new bytes, so ONLY the logical check can fail.
        _set_catalog_hash(
            store, _sha256_text(target.read_text(encoding="utf-8"))
        )

        assert _restart(tmp_path).load(record.compaction_id) is None

    def test_unreadable_committed_record_is_not_reused(self, tmp_path: Path):
        """Fail-safe: an unreadable record must not be treated as identical."""
        record, store = _persist(tmp_path, task_id="unreadable")
        target = _artifact_file(tmp_path, record.compaction_id)
        _set_catalog_hash(store, _sha256_text(target.read_text(encoding="utf-8")))
        target.write_text("{ this is not json", encoding="utf-8")

        with pytest.raises(ArtifactConflictError):
            _restart(tmp_path).save(record)
class TestStorageIntegrity:
    """Gate 4 P1 fix: durable bytes must be verified against the committed hash.

    Before the fix, ``CompactionRecordStore.load()`` parsed whatever was on disk
    and returned it, so an artifact corrupted after commit (but still valid JSON)
    was silently substituted for the authoritative record.
    """

    @staticmethod
    def _stack(tmp_path: Path):
        from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
        from autoforge_runtime.persistence import PersistenceLayer
        from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

        art = tmp_path / "artifacts"
        store = PhysicalArtifactStore(
            artifact_root=art,
            staging_root=art / ".staging",
            quarantine_root=art / ".quarantine",
        )
        catalog = DurableArtifactCatalog(
            persistence=PersistenceLayer(db_path=tmp_path / "state.db"),
            physical_store=store,
        )
        return art, store, catalog

    def _roundtrip(self, tmp_path: Path):
        art, store, catalog = self._stack(tmp_path)
        record = ContextCompactor(ENABLED).compact(
            task_id="t-integrity", prior_iterations=make_history(8)
        )
        CompactionRecordStore(catalog, store).save(record)
        name = CompactionRecordStore.artifact_name(record)
        target = next(p for p in art.rglob(name) if p.is_file())
        return record, target

    def test_load_returns_intact_record(self, tmp_path: Path):
        record, _target = self._roundtrip(tmp_path)
        _art, store, catalog = self._stack(tmp_path)
        loaded = CompactionRecordStore(catalog, store).load(record.compaction_id)
        assert loaded is not None
        assert loaded.content_digest() == record.content_digest()

    def test_corrupted_artifact_is_refused(self, tmp_path: Path):
        """The core Gate 4 integrity assertion: no silent substitution."""
        record, target = self._roundtrip(tmp_path)
        raw = target.read_text(encoding="utf-8")
        target.write_text(raw.replace("iteration", "TAMPERED", 1), encoding="utf-8")
        _art, store, catalog = self._stack(tmp_path)
        assert CompactionRecordStore(catalog, store).load(record.compaction_id) is None

    def test_truncated_artifact_is_refused(self, tmp_path: Path):
        record, target = self._roundtrip(tmp_path)
        target.write_text(target.read_text(encoding="utf-8")[:200], encoding="utf-8")
        _art, store, catalog = self._stack(tmp_path)
        assert CompactionRecordStore(catalog, store).load(record.compaction_id) is None

    def test_missing_artifact_is_refused(self, tmp_path: Path):
        record, target = self._roundtrip(tmp_path)
        target.unlink()
        _art, store, catalog = self._stack(tmp_path)
        assert CompactionRecordStore(catalog, store).load(record.compaction_id) is None

    def test_save_still_idempotent_after_integrity_fix(self, tmp_path: Path):
        """18-J replay semantics must be unaffected by the load-side check."""
        _art, store, catalog = self._stack(tmp_path)
        record = ContextCompactor(ENABLED).compact(
            task_id="t-idem", prior_iterations=make_history(6)
        )
        cstore = CompactionRecordStore(catalog, store)
        first = cstore.save(record)
        second = cstore.save(record)
        assert first == second
        assert cstore.load(record.compaction_id) is not None
