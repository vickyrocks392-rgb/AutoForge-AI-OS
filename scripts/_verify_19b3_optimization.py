"""Ad-hoc verification of the 19B-3 bounded optimizer (Gate 9)."""

from __future__ import annotations

import uuid

from autoforge_learning.models import ResourceBudget
from autoforge_learning.optimization import (
    NEVER_OPTIMIZABLE,
    OPTIMIZABLE_TARGETS,
    BoundedOptimizer,
    OptimizationRefused,
)


def main() -> None:
    project_id = uuid.uuid4()
    budget = ResourceBudget(
        project_id=project_id,
        max_experiments=5,
        max_recursion_depth=2,
        max_wall_clock_seconds=60.0,
        max_model_calls=5,
        max_concurrent_experiments=1,
        max_disk_bytes=1000,
        max_memory_bytes=1000,
        max_network_bytes=0,
    )
    optimizer = BoundedOptimizer(budget=budget, project_id=project_id)

    leaks = []
    for target in sorted(NEVER_OPTIMIZABLE):
        try:
            optimizer.assert_optimizable(target)
            leaks.append(target)
        except OptimizationRefused:
            pass
    print("forbidden domains refused:", not leaks, "| count:", len(NEVER_OPTIMIZABLE))
    print("leaks:", leaks)

    try:
        optimizer.assert_optimizable("unknown_domain")
    except OptimizationRefused:
        print("unknown domain refused: True")

    print("overlap allow/deny:", OPTIMIZABLE_TARGETS & NEVER_OPTIMIZABLE)

    trace = optimizer.optimize(
        target="prompt_strategy",
        current_value="a",
        candidates=["b", "c", "d"],
        score=lambda v: {"a": 0.1, "b": 0.5, "c": None, "d": 0.3}[v],
    )
    print(
        "best:",
        trace.best_value,
        round(trace.best_score or 0.0, 3),
        "steps:",
        len(trace.steps),
        "accepted:",
        [s.accepted for s in trace.steps],
    )

    try:
        optimizer.optimize(
            target="prompt_strategy",
            current_value="a",
            candidates=["b"],
            score=lambda v: 1.0,
            generation=5,
        )
    except OptimizationRefused:
        print("depth budget enforced: True")

    try:
        optimizer.optimize(
            target="prompt_strategy",
            current_value="a",
            candidates=["b", "c", "d", "e", "f", "g"],
            score=lambda v: 1.0,
        )
    except OptimizationRefused:
        print("experiment budget enforced: True")


if __name__ == "__main__":
    main()