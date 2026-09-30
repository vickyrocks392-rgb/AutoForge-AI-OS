"""18-L diagnostic: what does the M6 model actually return for
``generate_implementation``? Determines whether a missing ``file_edits`` list is
a model-output shape issue or a parsing defect. Read-only; writes nothing."""
import asyncio
import json
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

M6 = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"


async def main() -> int:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_execution.context import ExecutionContext

    ws = Path("/tmp/18L_diag_ws")
    ws.mkdir(parents=True, exist_ok=True)
    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()
    try:
        reg = system.execution_engine._ai._executor
        adapters = getattr(reg, "_executors", None) or {}
        print("adapters:", sorted(adapters.keys()))
        for pid, ad in adapters.items():
            if hasattr(ad, "register_model_alias"):
                for m in ("qwen2.5-coder-7b", "qwen2.5-coder-3b", "ornith-9b"):
                    ad.register_model_alias(m, M6)

        ctx = ExecutionContext(
            task_id="diag-1",
            task_name="Build tokenizer_lite package",
            task_type="coding",
            workflow_id=uuid.uuid4(),
            input_data={"description": "Build a small tokenizer library with a CLI and tests"},
            effective_model_requirements={
                "required_capabilities": ["code_generation"],
                "privacy_policy": "local_only",
                "coding_required": True,
            },
        )
        ai = system.execution_engine._ai
        plan = await ai.generate_plan(ctx)
        print("PLAN (first 400):\n", plan[:400])

        # Capture the RAW model output before the adapter's parsing.
        hist = ai.execution_history
        print("\nEXECUTION HISTORY ENTRIES:", len(hist))
        for h in hist[-2:]:
            out = getattr(h, "output", None)
            print("RAW OUTPUT TYPE:", type(out).__name__)
            print("RAW OUTPUT KEYS:", list(out.keys()) if isinstance(out, dict) else out)
            print("RAW OUTPUT (2500):\n", json.dumps(out, default=str)[:2500])

        try:
            edits = await ai.generate_implementation(ctx, plan)
            print("\nPARSED EDITS:", json.dumps(edits, default=str)[:2000])
        except Exception as exc:
            print("\nGENERATE_IMPLEMENTATION RAISED:", type(exc).__name__, exc)
        return 0
    finally:
        await system.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
