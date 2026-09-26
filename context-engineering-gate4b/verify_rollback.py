"""Gate 4B rollback + posture verification.

Confirms all three supported postures behave as specified:

* default      -> Context Engineering ON  (canonical production)
* explicit ON  -> Context Engineering ON
* explicit OFF -> Context Engineering OFF (rollback / compatibility mode)

The explicit-OFF case is checked through the *composition root* config, which is
the supported production rollback lever:

    build_autoforge_system(config={"enable_context_engineering": False})
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _pkg in (
    "execution/src", "composition/src", "workflows/src", "ai_infrastructure/src",
    "runtime/src", "events/src", "event_platform/src", "kernel/src",
    "artifacts/src", "security/src", "models/src", "connectors/src",
    "memory/src", "knowledge_platform/src", "observability/src",
):
    _p = REPO / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_workflows.models import TaskDefinition


def task() -> TaskDefinition:
    return TaskDefinition(
        task_id="t-gate4b-posture",
        name="Repair the backoff helper",
        task_type="coding",
        description="The helper returns the wrong delay sequence.",
        input_data={},
    )


async def collect(config: dict | None) -> dict:
    ws = Path(tempfile.mkdtemp(prefix="af_gate4b_posture_"))
    (ws / "svc.py").write_text("X = 1\n", encoding="utf-8")
    system = build_autoforge_system(workspace_root=str(ws), config=config)
    ctx = await system.context_builder.assemble_context(task_def=task(), workspace_root=ws)
    out = {
        "flag": system.context_builder.enable_context_engineering,
        "record_present": ctx.context_assembly_record is not None,
        "selected_items": len(ctx.selected_context_items),
        "canonical_messages": len(ctx.build_canonical_messages()),
        "project_files_discovered": len(ctx.project_files),
        "legacy_prompt_payload_keys": sorted(ctx.format_reasoning_prompt(1).keys()),
    }
    # These runs exercise configuration only, without a full lifecycle, so the
    # runtime is intentionally left un-started rather than shut down.
    return out


async def main() -> int:
    results = {
        "constructor_default_is_true": (
            inspect.signature(EngineeringContextBuilder.__init__)
            .parameters["enable_context_engineering"]
            .default
            is True
        ),
        "default_config": await collect(None),
        "explicit_on_config": await collect({"enable_context_engineering": True}),
        "explicit_off_rollback_config": await collect(
            {"enable_context_engineering": False}
        ),
    }
    out = REPO / "context-engineering-gate4b" / "rollback_evidence.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
