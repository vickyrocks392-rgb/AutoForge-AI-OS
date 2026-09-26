"""
Gate 4 MSC runtime evidence — the twelve checks in the Gate 4 mandate §5.

These are *runtime* checks, not assertions about unit tests. Each check drives
the real ``EngineeringContextBuilder`` / ``select_context`` code on a
representative engineering task and records what actually happened, so the
evidence is observed behaviour rather than a restatement of the test suite.

Run:  cd context-engineering-gate4 && ../.venv/bin/python msc_evidence.py
"""


from __future__ import annotations

import asyncio
import inspect
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from autoforge_execution.context import ExecutionContext
from autoforge_execution.context_budget import (
    BudgetSource,
    ContextWindowBudget,
    ModelWindow,
)
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
    sort_context_items,
)
from autoforge_execution.context_selection import (
    SelectionPolicy,
    deduplicate,
    select_context,
)
from autoforge_execution.errors import (
    MandatoryContextOverflowError,
    UnresolvableDependencyError,
)
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
)
from autoforge_execution.prompt_assembly import build_messages
from autoforge_workflows.models import TaskDefinition

CHECKS: list[dict[str, Any]] = []


def record(name: str, passed: bool, detail: Any) -> None:
    CHECKS.append({"check": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def item(
    content: str,
    category: ContextCategory,
    kind: str,
    ref: str = "",
    *,
    required: bool = False,
    relevance: float = 0.5,
    deps: tuple[str, ...] = (),
) -> ContextItem:
    return ContextItem(
        content=content,
        category=category,
        source=ContextSource(kind, ref),
        required=required,
        relevance=relevance,
        depends_on=deps,
        provenance=ContextProvenance(acquired_from=kind, source_ref=ref, inferred=False),
    )


def budget(window: int = 8192, reserve: int = 1024) -> ContextWindowBudget:
    return ContextWindowBudget(
        model_context_window_tokens=window, reserved_for_output_tokens=reserve
    )



# ---------------------------------------------------------------------------
# The twelve §5 checks.
# ---------------------------------------------------------------------------


async def check_engine_path() -> tuple[Path, Any]:
    """Build a real assembly on the canonical path; shared by several checks."""
    tmp = Path(tempfile.mkdtemp(prefix="af_g4_msc_"))
    (tmp / "service.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    builder = EngineeringContextBuilder(enable_context_engineering=True)
    task = TaskDefinition(
        task_id="t-g4-msc",
        name="Repair retry backoff",
        task_type="coding",
        description="The backoff helper returns the wrong delay sequence.",
        input_data={},
    )
    diag = DiagnosisReport(
        root_cause="compute_backoff clamps the final delay instead of doubling it",
        failure_mechanism="expected [1,2,4,8] got [1,2,4,4]",
        affected_files=["src/retry/service.py"],
        suggested_fix="Remove the clamp.",
        confidence_score=0.9,
    )
    ev = EvaluationResult(
        status=EvaluationStatus.FAILED,
        failures=["test_backoff::test_sequence FAILED: expected [1,2,4,8] got [1,2,4,4]"],
    )

    class RAG:
        async def retrieve(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
            return [
                {"content": "redis and kafka run on the cluster.", "score": 0.10},
                {"content": "The backoff helper should double the delay.", "score": 0.80},
            ]

    ctx = await builder.assemble_context(
        task_def=task,
        workspace_root=tmp,
        workflow_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        attempt_number=2,
        rag_engine=RAG(),
        last_evaluation=ev,
        last_diagnosis=diag,
        effective_model_requirements={},
        stage="diagnosis",
        context_window_tokens=8192,
        max_output_tokens=512,
        model_id="test-model",
    )
    return tmp, ctx


def _summary(ctx: Any) -> str:
    return "\n".join(i.content for i in ctx.selected_context_items)



async def main() -> dict[str, Any]:
    print("Gate 4 — MSC runtime evidence (§5)\n")
    tmp, ctx = await check_engine_path()
    rec = ctx.context_assembly_record
    delivered = _summary(ctx)

    # 1. Irrelevant context exclusion -------------------------------------
    # NOTE: with the DEFAULT policy (min_optional_relevance == 0.0) the engine
    # admits every optional item that fits the budget — relevance is a ranking
    # input, not a filter. Exclusion therefore requires either an explicit
    # relevance floor or budget exhaustion. Both are exercised here so the
    # claim is evidence, not assumption.
    floored = EngineeringContextBuilder(
        enable_context_engineering=True,
        selection_policy=SelectionPolicy(min_optional_relevance=0.5),
    )
    class _RAG:
        async def retrieve(self, q, limit=3):
            return [
                {"content": "redis and kafka run on the cluster.", "score": 0.10},
                {"content": "The backoff helper should double the delay.", "score": 0.80},
            ]
    c1 = await floored.assemble_context(
        task_def=TaskDefinition(
            task_id="t-g4-c1", name="Repair retry backoff", task_type="coding",
            description="The backoff helper returns the wrong delay sequence.", input_data={},
        ),
        workspace_root=tmp, rag_engine=_RAG(), context_window_tokens=8192,
    )
    r1 = c1.context_assembly_record
    d1_text = _summary(c1)
    record(
        "1_irrelevant_context_exclusion",
        "redis" not in d1_text and "double the delay" in d1_text,
        {
            "relevance_floor": 0.5,
            "low_relevance_fact_delivered": "redis" in d1_text,
            "high_relevance_fact_delivered": "double the delay" in d1_text,
            "considered": r1.considered_count,
            "selected": r1.selected_count,
            "excluded": r1.excluded_count,
            "reasons": sorted({e.reason for e in r1.excluded}),
            "default_policy_note": (
                "with the default min_optional_relevance=0.0 the engine admits "
                "every optional item that fits; exclusion needs a floor or budget"
            ),
        },
    )

    # 2. Mandatory context preservation -----------------------------------
    mandatory = [i for i in ctx.selected_context_items if i.required]
    record(
        "2_mandatory_context_preservation",
        len(mandatory) == 3
        and any("compute_backoff" in i.content for i in mandatory)
        and any("1,2,4,8" in i.content for i in mandatory),
        {
            "mandatory_count": len(mandatory),
            "categories": sorted({i.category.value for i in mandatory}),
            "root_cause_present": any("compute_backoff" in i.content for i in mandatory),
            "failure_evidence_present": any("1,2,4,8" in i.content for i in mandatory),
        },
    )

    # 3. Dependency expansion ---------------------------------------------
    d_items = [i for i in ctx.selected_context_items if "compute_backoff" in i.content]
    e_items = [i for i in ctx.selected_context_items if "Evaluation failures" in i.content]
    edge = list(d_items[0].depends_on) if d_items else []
    record(
        "3_dependency_expansion",
        bool(edge) and bool(e_items) and edge[0] == e_items[0].context_id,
        {
            "diagnosis_depends_on": edge,
            "target_is_selected_item": bool(e_items) and edge[:1] == [e_items[0].context_id],
            "expansion_depth_reached": rec.expansion_depth_reached,
        },
    )

    # 4. Dependency cycles ------------------------------------------------
    a = item("A body", ContextCategory.TASK, "task", "a", required=True)
    b = item("B body", ContextCategory.EVIDENCE, "ev", "b", required=True)
    a.depends_on = (b.context_id,)
    b.depends_on = (a.context_id,)
    r4 = select_context([a, b], budget(), SelectionPolicy(max_dependency_depth=5))
    record(
        "4_dependency_cycles_handled",
        len(r4.selected) == 2,
        {"selected": len(r4.selected), "raised": False,
         "note": "a<->b cycle terminated; both delivered; no error"},
    )

    # 5. Bounded dependency expansion -------------------------------------
    chain, prev = [], None
    for i in range(6):
        n = item(f"node-{i} " + "x" * 40, ContextCategory.EVIDENCE, "chain", str(i))
        if prev is not None:
            n.depends_on = (prev.context_id,)
        chain.append(n)
        prev = n
    root = item("root", ContextCategory.TASK, "task", "root", required=True)
    root.depends_on = (chain[0].context_id,)
    r5 = select_context(
        [root, *chain], budget(),
        SelectionPolicy(max_dependency_depth=2, max_expanded_items=3),
    )
    record(
        "5_bounded_dependency_expansion",
        r5.expansion_depth_reached <= 2 and r5.expansion_items_added <= 3,
        {
            "max_dependency_depth": 2,
            "depth_reached": r5.expansion_depth_reached,
            "items_added": r5.expansion_items_added,
            "chain_length_available": len(chain),
            "item_bound_truncated": r5.expansion_truncated_by_bound,
            "stopped_by": "depth bound (chain longer than max_dependency_depth)",
        },
    )

    # 6. Provenance preservation ------------------------------------------
    prov_ok = all(e.provenance_ref and not e.provenance_inferred for e in rec.selected)
    record(
        "6_provenance_preservation",
        prov_ok,
        {
            "all_selected_attributable": prov_ok,
            "refs": [e.provenance_ref for e in rec.selected],
            "any_inferred": any(e.provenance_inferred for e in rec.selected),
        },
    )

    # 7. Deterministic ordering -------------------------------------------
    det = EngineeringContextBuilder(enable_context_engineering=True)
    dtask = TaskDefinition(
        task_id="t-g4-det", name="N", task_type="coding", description="D", input_data={}
    )
    runs = [
        await det.assemble_context(
            task_def=dtask, workspace_root=tmp, context_window_tokens=8192
        )
        for _ in range(5)
    ]
    id_orders = {tuple(i.context_id for i in r.selected_context_items) for r in runs}
    prompts = {json.dumps(r.build_canonical_messages()) for r in runs}
    record(
        "7_deterministic_ordering",
        len(id_orders) == 1 and len(prompts) == 1,
        {"runs": len(runs), "distinct_id_orders": len(id_orders),
         "distinct_prompts": len(prompts)},
    )

    # 8. Duplicate removal -------------------------------------------------
    # Dedup is exact-match on normalized content. normalize_content applies
    # NFKC, strips trailing whitespace per line, collapses blank-line runs and
    # casefolds. Internal intra-line spacing is deliberately NOT collapsed, so
    # the fixtures below differ only in ways normalization actually removes.
    d1 = item("Duplicate body text", ContextCategory.EVIDENCE, "ev", "1", relevance=0.9)
    d2 = item("duplicate body text  ", ContextCategory.EVIDENCE, "ev", "2", relevance=0.1)
    d3 = item("Duplicate body text", ContextCategory.TEST_OUTPUT, "t", "3", relevance=0.5)
    kept, dupes = deduplicate([d1, d2, d3])
    record(
        "8_duplicate_removal",
        len(kept) == 1 and dupes == 2,
        {"kept": len(kept), "duplicates_removed": dupes,
         "normalization": "NFKC + casefold + trailing-whitespace/blank-line collapse",
         "scope": "exact match; near-duplicate detection not implemented (documented)"},
    )

    # 9. Budget enforcement ------------------------------------------------
    # Content must be unique per item, otherwise exact-match dedup collapses
    # them first and the budget is never exercised. Prose is used rather than a
    # long unbroken string: the default heuristic prices whitespace-delimited
    # words, so a 400-char run of one letter is (correctly for prose, but
    # misleadingly here) priced as a single token.
    big = [
        item(
            f"Filler record {i}: " + "alpha beta gamma delta " * 50,
            ContextCategory.EVIDENCE,
            "ev",
            str(i),
            relevance=1.0,
        )
        for i in range(20)
    ]
    b9 = budget(window=2048, reserve=256)
    r9 = select_context(big, b9, SelectionPolicy())
    r9_reasons = {reason for _, reason in r9.excluded}
    record(
        "9_budget_enforcement",
        b9.used_tokens <= b9.available_for_context_tokens
        and len(r9.excluded) > 0
        and "budget_exhausted" in r9_reasons,
        {
            "available_for_context": b9.available_for_context_tokens,
            "used": b9.used_tokens,
            "selected": len(r9.selected),
            "excluded": len(r9.excluded),
            "reasons": sorted(r9_reasons),
        },
    )

    # 10. Mandatory overflow fails loudly -----------------------------------
    bulk = [
        item(
            f"Mandatory evidence {i}: " + "epsilon zeta eta theta " * 60,
            ContextCategory.VERIFICATION,
            "ev",
            str(i),
            required=True,
        )
        for i in range(12)
    ]
    try:
        select_context(bulk, budget(window=2048, reserve=256), SelectionPolicy())
        record("10_mandatory_overflow_fails_loudly", False, "NO EXCEPTION RAISED")
    except MandatoryContextOverflowError as exc:
        record(
            "10_mandatory_overflow_fails_loudly",
            True,
            {
                "error": type(exc).__name__,
                "code": exc.code,
                "mandatory_tokens": exc.details.get("mandatory_tokens"),
                "available": exc.details.get("available_for_context_tokens"),
                "overage": exc.details.get("overage_tokens"),
                "mandatory_items_reported": len(exc.details.get("mandatory_context_ids", [])),
                "silently_truncated": False,
            },
        )

    # 11. Model-aware context window handling (two-pass) -------------------
    class Allocator:
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

    alloc = Allocator(32768)
    b11 = EngineeringContextBuilder(enable_context_engineering=True, model_allocator=alloc)
    c11 = await b11.assemble_context(task_def=dtask, workspace_root=tmp)
    r11 = c11.context_assembly_record
    record(
        "11_model_aware_window_handling",
        r11.budget_source == "model_metadata"
        and r11.context_window_tokens == 32768
        and r11.model_id == "allocated-model",
        {
            "budget_source": r11.budget_source,
            "applied_window": r11.context_window_tokens,
            "model_id": r11.model_id,
            "pass1_declared_requirement_seen_by_allocator": alloc.seen_min,
            "declared_recorded_on_observability": r11.declared_required_window_tokens,
            "reserved_output_tokens": r11.budget["reserved_for_output_tokens"],
        },
    )

    # 12. Stable prompt structure -------------------------------------------
    from autoforge_execution.prompt_assembly import SECTION_ORDER

    items = ctx.selected_context_items
    m1 = build_messages(items, task_name="Repair retry backoff")
    m2 = build_messages(list(reversed(items)), task_name="Repair retry backoff")
    record(
        "12_stable_prompt_structure",
        m1 == m2
        and all(set(m) == {"role", "content"} for m in m1)
        and all(m["role"] in {"system", "user"} for m in m1),
        {
            "byte_identical_under_input_reordering": m1 == m2,
            "message_roles": [m["role"] for m in m1],
            "keys": sorted({k for m in m1 for k in m}),
            "sections_present": [
                c.value for c in SECTION_ORDER if any(i.category is c for i in items)
            ],
        },
    )

    passed = sum(1 for c in CHECKS if c["passed"])
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return {
        "checks_passed": passed,
        "checks_total": len(CHECKS),
        "all_passed": passed == len(CHECKS),
        "checks": CHECKS,
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    out = Path(__file__).with_name("msc_evidence.json")
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"written -> {out}")

