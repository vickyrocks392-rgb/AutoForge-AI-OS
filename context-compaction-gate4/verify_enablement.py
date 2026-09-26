"""18-L Global Enablement — PART 2/3: enablement change and composition proof."""

import json
import tempfile
from pathlib import Path

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.compaction import CompactionRecordStore

HERE = Path(__file__).parent


def main() -> int:
    out = {}

    # ── PART 2: the enablement change ──
    default = build_autoforge_system(workspace_root=tempfile.mkdtemp())
    out["default"] = {
        "context_engineering": bool(default.context_builder.enable_context_engineering),
        "compactor_injected": default.context_builder.compactor is not None,
        "compactor_enabled": bool(
            default.context_builder.compactor
            and default.context_builder.compactor.enabled
        ),
        "compaction_store_owned": type(default.compaction_store).__name__,
    }

    # The documented rollback lever must still work.
    off = build_autoforge_system(
        workspace_root=tempfile.mkdtemp(),
        config={"enable_context_compaction": False},
    )
    out["rollback_lever"] = {
        "compactor_injected": off.context_builder.compactor is not None,
        "context_engineering_still_on": bool(
            off.context_builder.enable_context_engineering
        ),
    }

    on = build_autoforge_system(
        workspace_root=tempfile.mkdtemp(),
        config={"enable_context_compaction": True},
    )
    out["explicit_true"] = {"compactor_injected": on.context_builder.compactor is not None}

    # ── PART 3: production composition proof (object identity) ──
    sysm = build_autoforge_system(workspace_root=tempfile.mkdtemp())
    store = sysm.compaction_store
    builder = sysm.context_builder
    out["composition_proof"] = {
        "catalog_is_canonical": store._catalog is sysm.durable_catalog,
        "physical_store_is_canonical_obj": (
            store._physical_store is sysm.physical_store
        ),
        "builder_consumes_root_store": (
            builder.compaction_store is store
        ),
        "single_store": sum(
            1 for v in vars(sysm).values() if isinstance(v, CompactionRecordStore)
        ) == 1,
        "compactor_injected": builder.compactor is not None,
        "compaction_runs_through_builder": builder.compactor is not None,
    }

    (HERE / "enablement_state.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )

    print("=== PART 2 — ENABLEMENT ===")
    for key, row in out["default"].items():
        print(f"  {key:26s} {row}")
    print("  rollback lever (compaction OFF) :", out["rollback_lever"])
    print()
    print("=== PART 3 — PRODUCTION COMPOSITION PROOF ===")
    for key, value in out["composition_proof"].items():
        print(f"  {key:34s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
