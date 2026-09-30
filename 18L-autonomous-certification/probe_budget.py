"""18-L read-only probe: can the M6 model emit the FULL greenfield deliverable
in one ``generate_implementation`` call? Distinguishes an output-budget limit
from a model-capability limit. Writes nothing outside the temp workspace."""
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

REQUEST = (
    "Build a greenfield Python package named 'tokenizer_lite'. It is a small, "
    "self-contained text token-counting library with a CLI. Create exactly these "
    "four files:\n"
    "1. 'tokenizer_lite/__init__.py' - exports TokenizerLite and count_tokens.\n"
    "2. 'tokenizer_lite/core.py' - defines class TokenizerLite with methods "
    "count(text), count_words(text), and a module-level function count_tokens(text) "
    "that returns a dict with keys 'tokens', 'characters' and 'words'. Splitting "
    "must be whitespace based, must treat consecutive whitespace as one "
    "separator, and must return zeros for empty or whitespace-only input.\n"
    "3. 'tokenizer_lite/cli.py' - a 'main()' function with an argparse parser "
    "accepting one positional 'text' argument, printing 'tokens=<n> characters=<n> "
    "words=<n>' and returning exit code 0.\n"
    "4. 'test_tokenizer_lite.py' - pytest tests covering: empty string, "
    "whitespace-only string, single word, multiple words, and character count.\n"
    "Also create 'README.md' with a title line, an Overview section and a Usage "
    "section. All code must be plain Python 3 with no third-party dependencies "
    "except pytest for the tests."
)


async def main() -> int:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_execution.context import ExecutionContext

    ws = Path("/tmp/18L_budget_probe_ws")
    ws.mkdir(parents=True, exist_ok=True)
    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()
    try:
        reg = system.execution_engine._ai._executor
        for ad in (getattr(reg, "_executors", None) or {}).values():
            if hasattr(ad, "register_model_alias"):
                for m in ("qwen2.5-coder-7b", "qwen2.5-coder-3b", "ornith-9b"):
                    ad.register_model_alias(m, M6)

        ctx = ExecutionContext(
            task_id="probe-budget",
            task_name="Build tokenizer_lite package",
            task_type="coding",
            workflow_id=uuid.uuid4(),
            input_data={"description": REQUEST},
            effective_model_requirements={
                "required_capabilities": ["code_generation"],
                "privacy_policy": "local_only",
                "coding_required": True,
            },
        )
        ai = system.execution_engine._ai
        plan = await ai.generate_plan(ctx)
        print("PLAN length:", len(plan))

        edits = await ai.generate_implementation(ctx, plan)
        print("\nEDIT COUNT:", len(edits))
        for e in edits:
            print(f"  - {e['path']}  ({len(e['content'])} chars)")

        h = ai.execution_history[-1]
        print("\nfinish_reason:", h.output.get("finish_reason"))
        print("output_tokens:", h.output.get("output_tokens"))
        print("tokens_per_second:", h.output.get("tokens_per_second"))
        print("duration_ms:", h.output.get("duration_ms"))
        return 0
    finally:
        await system.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
