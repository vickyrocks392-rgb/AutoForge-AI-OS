"""18-L read-only probe: does the ORIGINAL request text actually reach the
engineering model through the production O-2 -> adapter -> AI path?

Verifies DEF-18L-03 end to end without contacting a model for the result: it
inspects the task ``input_data`` the production path builds.
"""
import asyncio
import sys
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in ["events", "event_platform", "runtime", "models", "ai_infrastructure",
          "workflows", "execution", "artifacts", "review", "security",
          "connectors", "orchestration", "kernel", "composition", "workforce",
          "power_engines", "modernization", "observability", "persistence",
          "knowledge_platform"]:
    src = _REPO / "packages" / p / "src"
    if src.exists():
        sys.path.insert(0, str(src))

REQUEST = "Build a greenfield Python package named 'tokenizer_lite' with a CLI."


async def main() -> int:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    ws = Path("/tmp/18L_req_probe_ws")
    ws.mkdir(parents=True, exist_ok=True)
    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()
    try:
        res = await system.kernel.submit_request(
            Request(
                user_id=uuid.uuid4(),
                request_text=REQUEST,
                configuration={"environment": "production", "execute": False},
            )
        )
        pid = res["project_id"]
        state = await system.runtime_facade.get_project_state(pid)

        print("state keys:", sorted(state.keys()))
        print("description present:", bool(state.get("description")))
        print("description == REQUEST:", state.get("description") == REQUEST)
        md = state.get("metadata") or {}
        print("metadata.original_request == REQUEST:",
              md.get("original_request") == REQUEST)
        print("metadata keys:", sorted(md.keys()))
        rq = state.get("request") or {}
        print("request keys:", sorted(rq.keys()) if isinstance(rq, dict) else type(rq))
        print("request == REQUEST:", rq == REQUEST if isinstance(rq, dict) else None)
        print("request preview:", str(rq)[:200])

        # Now check what the O-2 loop context would carry.
        wf_id = system.kernel.completion_module._project_workflow_id(state)
        print("workflow_id:", wf_id)

        captured = {}

        orig = system.kernel.orchestration_engine.loop_orchestrator.orchestrate_loop

        async def spy(project_id, loop_type, loop_context):
            captured.setdefault("contexts", []).append(loop_context)
            return {"status": "complete", "loop_type": loop_type}

        system.kernel.orchestration_engine.loop_orchestrator.orchestrate_loop = spy

        # Stop the model from being called: we only inspect what was passed.
        ai = system.execution_engine._ai

        async def _noop(*_a, **_k):
            return []

        ai.generate_plan = _noop
        ai.generate_implementation = _noop

        # Test the EXECUTION ADAPTER boundary directly with the same context
        # shape O-2 produces (loop has no input_data; context carries the request).
        from autoforge_composition.kernel_adapters import (
            KernelExecutionEngineAdapter,
        )
        seen = {}

        class _SpyEngine:
            async def execute_task_definition(self, task_def, workflow_id=None,
                                              worker_type=None):
                seen["input_data"] = task_def.input_data
                seen["name"] = task_def.name
                return True, [], None

        ad = KernelExecutionEngineAdapter(concrete_engine=_SpyEngine())
        ctx = {"project_id": str(pid), "workflow_id": str(wf_id),
               "loop": {"type": "coding", "name": "Core Implementation"},
               "request_text": REQUEST}
        await ad.execute_loop("coding", ctx["loop"], ctx)
        print("\nADAPTER task input_data keys:", sorted((seen.get('input_data') or {}).keys()))
        desc = (seen.get("input_data") or {}).get("description", "")
        print("ADAPTER description == REQUEST:", desc == REQUEST)
        print("ADAPTER description preview:", str(desc)[:120])
        return 0
    finally:
        await system.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
