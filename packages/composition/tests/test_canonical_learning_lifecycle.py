"""
Composition Regression Tests: Canonical Learning & Reflection Lifecycle (Part 7 & 8).

Proves that:
1. A canonical task/request executes through the Kernel lifecycle.
2. The learning/reflection stage (EngineeringLearningEngine) is canonically invoked.
3. Relevant execution/review evidence is supplied to the learning engine.
4. Memory receives appropriate persistent learning.
5. Knowledge receives appropriate reusable knowledge where applicable.
6. Learning does not happen merely because a test manually calls the engine.
7. The test fails if the Kernel lifecycle stops invoking the learning engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid
import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_kernel.interfaces import Request
from autoforge_kernel.learning_engine import EngineeringLearningEngine
from tests.review_evidence_helpers import register_project_deliverable


@pytest.mark.asyncio
async def test_canonical_learning_lifecycle_wired_and_invoked(tmp_path: Path):
    # 1. Build canonical AutoForge system
    system = build_autoforge_system(workspace_root=str(tmp_path))
    await system.initialize()

    try:
        # Verify learning engine is canonical component attached to both AutoForgeSystem and Kernel
        assert system.learning_engine is not None, "learning_engine missing from AutoForgeSystem"
        assert isinstance(system.learning_engine, EngineeringLearningEngine)
        assert system.kernel.learning_engine is system.learning_engine

        # 2. Spy on learning_engine.reflect_and_learn to verify lifecycle invocation
        learning_invocations = []
        original_reflect = system.learning_engine.reflect_and_learn

        async def spy_reflect_and_learn(*args: Any, **kwargs: Any):
            res = await original_reflect(*args, **kwargs)
            learning_invocations.append({
                "args": args,
                "kwargs": kwargs,
                "lessons": res,
            })
            return res

        system.learning_engine.reflect_and_learn = spy_reflect_and_learn  # type: ignore

        # 3. Plan through the canonical Kernel lifecycle, then execute.
        #
        # DEF-P1-EVIDENCE: planning and execution are separated so the project can
        # first produce its real reviewable deliverable. The Kernel's completion
        # gate requires an explicit final-review approval, and the Learning
        # Engine is invoked by the Kernel only after that gate genuinely passes.
        # Learning is therefore still triggered by the platform, never by the
        # test calling the engine directly.
        req = Request(
            user_id=uuid.uuid4(),
            request_text="Build an authenticated payment webhook endpoint with tests",
            configuration={"environment": "production", "execute": False},
        )
        res = await system.kernel.submit_request(req)

        assert "project_id" in res
        project_id = res["project_id"]
        assert project_id is not None

        # Register the project's real deliverables through the authoritative 18-K
        # durable artifact pipeline so the real Review Engine evaluates real bytes.
        state = await system.runtime_facade.get_project_state(project_id)
        workflow_id = system.kernel.completion_module._project_workflow_id(state)
        assert workflow_id, "the project must record its workflow correlation"
        register_project_deliverable(system, workflow_id)

        # Run the canonical Kernel execution lifecycle: orchestration ->
        # completion validation -> final review gate -> learning/reflection.
        await system.kernel.execute_project(project_id)

        # 4. Verify learning stage was automatically invoked by Kernel (NOT manually called by test!)
        assert len(learning_invocations) >= 1, (
            "EngineeringLearningEngine.reflect_and_learn MUST be invoked as part of the "
            "canonical Kernel project execution lifecycle! "
            "If learning_invocations is empty, the Kernel completed execution without learning."
        )

        invocation = learning_invocations[0]
        inv_kwargs = invocation["kwargs"]
        assert inv_kwargs.get("project_id") == project_id, "Learning must be tied to the executed project_id"
        assert "execution_summary" in inv_kwargs, "Execution evidence must be supplied to learning engine"

        # 5. Verify Memory received appropriate persistent learning
        memory_records = await system.kernel.memory_engine.retrieve_memory("project", limit=10)
        assert len(memory_records) > 0, "MemoryEngine must receive persistent learning from learning engine"
        assert any(
            str(project_id) in str(m) or "lessons" in m or "execution_summary" in m
            for m in memory_records
        )

        # 6. Verify Knowledge received promoted reusable knowledge
        promoted = await system.kernel.knowledge_engine.query("project execution")
        assert len(promoted) > 0, "KnowledgeEngine must receive promoted high-confidence lessons"
        assert any("project_summary" in str(p) or "Project execution" in str(p) for p in promoted)

    finally:
        await system.shutdown()
