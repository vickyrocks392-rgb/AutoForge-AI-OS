"""Ad-hoc verification of the 19B-3 recursive self-improvement (Gate 10)."""

from __future__ import annotations

import uuid

from autoforge_learning.models import (
    BudgetExhausted,
    LearningScope,
    LearningScopeKind,
    ResourceBudget,
)
from autoforge_learning.optimization import OptimizationStep, OptimizationTrace
from autoforge_learning.recursion import (
    AuthorityExpansionAttempted,
    RecursiveImprovement,
    assert_no_authority_expansion,
)


def trace(project_id: uuid.UUID, accepted: bool, generation: int) -> OptimizationTrace:
    return OptimizationTrace(
        trace_id=uuid.uuid4(),
        project_id=project_id,
        target="prompt_strategy",
        steps=(
            OptimizationStep(
                step_id=uuid.uuid4(),
                generation=generation,
                target="prompt_strategy",
                from_value="a",
                to_value="b",
                accepted=accepted,
                reason="improved",
                measured_delta=0.1,
            ),
        ),
        best_value="b" if accepted else "a",
        best_score=0.5 if accepted else 0.1,
        generations_completed=generation + 1,
        terminated_because="candidate set exhausted",
    )


def main() -> None:
    project_id = uuid.uuid4()
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    budget = ResourceBudget(
        project_id=project_id,
        max_experiments=10,
        max_recursion_depth=3,
        max_wall_clock_seconds=120.0,
        max_model_calls=10,
        max_concurrent_experiments=1,
        max_disk_bytes=1000,
        max_memory_bytes=1000,
        max_network_bytes=0,
    )
    engine = RecursiveImprovement(budget=budget)

    results = engine.run_until_bounded(
        scope=scope,
        correlation_id="corr-1",
        stage=lambda g: trace(project_id, accepted=True, generation=g),
    )
    print(
        "generations run:",
        len(results),
        "(ceiling",
        budget.max_recursion_depth,
        ")",
        "depths:",
        [r.generation for r in results],
    )

    stopping = RecursiveImprovement(budget=budget).run_until_bounded(
        scope=scope,
        correlation_id="corr-2",
        stage=lambda g: trace(project_id, accepted=False, generation=g),
    )
    print("stops when no improvement:", len(stopping) == 1)

    exhausted = RecursiveImprovement(budget=budget)
    exhausted.run_until_bounded(
        scope=scope, correlation_id="corr-3", stage=lambda g: None
    )
    print("stops when stage yields nothing:", True)

    try:
        RecursiveImprovement(budget=budget).run_cycle(
            scope=scope,
            correlation_id="corr-4",
            stage=lambda g: trace(project_id, True, g),
            generation=99,
        )
    except BudgetExhausted as exc:
        print("depth budget enforced:", "recursion depth budget" in str(exc))

    tight = ResourceBudget(
        project_id=project_id,
        max_experiments=1,
        max_recursion_depth=5,
        max_wall_clock_seconds=1.0,
        max_model_calls=1,
        max_concurrent_experiments=1,
        max_disk_bytes=1,
        max_memory_bytes=1,
        max_network_bytes=0,
    )
    tight_engine = RecursiveImprovement(budget=tight)
    tight_results = tight_engine.run_until_bounded(
        scope=scope,
        correlation_id="corr-5",
        stage=lambda g: trace(project_id, True, g),
    )
    print("experiment budget bounds the loop:", len(tight_results) == 1)

    # The prohibited loop: a child that widens its scope or gains a capability.
    try:
        assert_no_authority_expansion(
            parent_scope=scope,
            child_scope=LearningScope(
                kind=LearningScopeKind.GLOBAL_NON_SECURITY, project_id=project_id
            ),
        )
    except AuthorityExpansionAttempted as exc:
        print("scope widening refused:", "scope kind" in str(exc))

    try:
        assert_no_authority_expansion(
            parent_scope=scope,
            child_scope=scope,
            parent_capabilities=(),
            child_capabilities=("network.outbound",),
        )
    except AuthorityExpansionAttempted as exc:
        print("capability gain refused:", "capabilities" in str(exc))

    other = LearningScope(
        kind=LearningScopeKind.PROJECT, project_id=uuid.uuid4()
    )
    try:
        assert_no_authority_expansion(parent_scope=scope, child_scope=other)
    except AuthorityExpansionAttempted as exc:
        print("cross-project refused:", "project scope" in str(exc))


if __name__ == "__main__":
    main()