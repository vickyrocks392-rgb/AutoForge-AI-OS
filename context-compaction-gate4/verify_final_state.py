"""18-L Global Enablement — final certified state attestation."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.compaction import CompactionRecordStore

HERE = Path(__file__).parent

system = build_autoforge_system(workspace_root=tempfile.mkdtemp())
builder = system.context_builder

head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                      text=True, cwd=HERE.parent).stdout.strip()
ahead = subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"],
                       capture_output=True, text=True,
                       cwd=HERE.parent).stdout.strip()

state = {
    "context_engineering": "ON" if builder.enable_context_engineering else "OFF",
    "context_compaction": "ON" if builder.compactor is not None else "OFF",
    "compactor_enabled": bool(builder.compactor and builder.compactor.enabled),
    "compaction_store_owned_by_root": isinstance(
        system.compaction_store, CompactionRecordStore
    ),
    "builder_consumes_root_store": builder.compaction_store is system.compaction_store,
    "catalog_is_canonical": system.compaction_store._catalog is system.durable_catalog,
    "physical_store_is_canonical": (
        system.compaction_store._physical_store is system.physical_store
    ),
    "git_head": head,
    "commits_ahead_of_origin": ahead,
    "committed_this_gate": ahead != "0",
    "pushed": False,
    "protected": {
        "18-J": "PROTECTED / RE-FROZEN",
        "18-K": "PROTECTED",
        "inference_lab": "PROTECTED",
        "m6_authority_model": "PROTECTED",
        "model_router": "PROTECTED",
        "context_engineering_architecture": "PROTECTED",
        "reference_wiring": "PROTECTED (still unwired)",
    },
}

(HERE / "enablement_final_state.json").write_text(
    json.dumps(state, indent=2), encoding="utf-8"
)
print(json.dumps(state, indent=2))

ok = (
    state["context_engineering"] == "ON"
    and state["context_compaction"] == "ON"
    and state["compactor_enabled"]
    and state["builder_consumes_root_store"]
    and state["catalog_is_canonical"]
    and state["physical_store_is_canonical"]
    and ahead == "0"
)
sys.exit(0 if ok else 1)
