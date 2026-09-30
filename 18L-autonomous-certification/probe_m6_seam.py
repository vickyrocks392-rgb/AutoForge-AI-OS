"""18-L: prove the M6 authority model is reachable through the EXISTING,
provider-neutral deployment seam -- without modifying any product source.

The production catalog registers only M1/HP model ids. The certified 18-L
topology is "M6 Qwen3-Coder-30B authority + 0 continuous workers", so the
certification must point an already-selected LOCAL model at the model the M6
runtime actually serves.

This uses ONLY the documented, already-shipped deployment API:
  * LocalRuntimeProviderAdapter / BaseProviderAdapter.register_model_alias
  * AUTOFORGE_LOCAL_RUNTIME_URL
No source change, no new provider, no new model registration, no topology
change, no worker, no M1, no HP.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in ["events", "event_platform", "runtime", "models", "ai_infrastructure",
          "workflows", "execution", "artifacts", "review", "security",
          "connectors", "orchestration", "kernel", "composition", "workforce",
          "power_engines", "modernization", "observability", "persistence",
          "knowledge_platform"]:
    _src = _REPO / "packages" / p / "src"
    if _src.exists():
        sys.path.insert(0, str(_src))

M6_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
RUNTIME = os.environ.get("AUTOFORGE_LOCAL_RUNTIME_URL", "http://127.0.0.1:8080/v1")


async def main() -> int:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_execution.context import ExecutionContext

    ws = Path("/tmp/18L_alias_probe_ws")
    ws.mkdir(parents=True, exist_ok=True)
    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()
    try:
        # Reach the already-constructed, already-bound provider adapters through
        # the existing execution engine (no new wiring, no new registry).
        reg = system.execution_engine._ai._executor
        adapters = getattr(reg, "_adapters", None) or getattr(reg, "_executors", {})
        print("adapters:", sorted(adapters.keys()))

        # Point the LOCAL model the router already selects at the M6 tag.
        for pid, adapter in adapters.items():
            if hasattr(adapter, "register_model_alias"):
                adapter.register_model_alias("qwen2.5-coder-7b", M6_MODEL)
                adapter.register_model_alias("qwen2.5-coder-3b", M6_MODEL)
                adapter.register_model_alias("ornith-9b", M6_MODEL)
                print(f"  aliased local models -> {M6_MODEL} on {pid}")
                print(f"  resolve_model_tag('qwen2.5-coder-7b') = "
                      f"{adapter.resolve_model_tag('qwen2.5-coder-7b')}")

        # A REAL engineering generation call through the canonical AI adapter.
        ctx = ExecutionContext(
            task_id="probe-1",
            task_name="Implement add(a, b) returning the sum",
            task_type="coding",
            workflow_id=__import__("uuid").uuid4(),
            input_data={
                "description": "Implement add(a, b) returning the sum",
                "required_capabilities": ["code_generation"],
                "privacy_policy": "local_only",
            },
            effective_model_requirements={
                "required_capabilities": ["code_generation"],
                "privacy_policy": "local_only",
                "coding_required": True,
            },
        )
        ai = system.execution_engine._ai
        print("\nfallback_allowed:", ai._should_allow_fallback(ctx))
        plan = await ai.generate_plan(ctx)
        print("\nREAL PLAN FROM M6:\n", plan[:600])
        edits = await ai.generate_implementation(ctx, plan)
        print("\nREAL FILE EDITS FROM M6:", json.dumps(edits, indent=2)[:1500])
        return 0
    finally:
        await system.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
