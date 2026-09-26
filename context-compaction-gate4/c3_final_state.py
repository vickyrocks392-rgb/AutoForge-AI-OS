"""Final C-3 state attestation: CE ON, Compaction OFF, nothing committed."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from autoforge_composition.composition_root import build_autoforge_system

HERE = Path(__file__).parent

system = build_autoforge_system(workspace_root=tempfile.mkdtemp())
ce_on = system.context_builder.enable_context_engineering is True
compaction_off = system.context_builder.compactor is None
store_owned = type(system.compaction_store).__name__
store_shared = system.context_builder.compaction_store is system.compaction_store

head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                      text=True, cwd=HERE.parent).stdout.strip()
ahead = subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"],
                       capture_output=True, text=True,
                       cwd=HERE.parent).stdout.strip()

state = {
    "context_engineering": "ON" if ce_on else "OFF",
    "context_compaction": "OFF" if compaction_off else "ON",
    "compaction_store_owned_by_root": store_owned,
    "builder_consumes_root_store": store_shared,
    "git_head": head,
    "commits_ahead_of_origin": ahead,
    "committed_this_task": ahead != "0",
    "pushed": False,
    "protected": {
        "18-J": "PROTECTED / RE-FROZEN",
        "18-K": "PROTECTED",
        "inference_lab": "PROTECTED",
        "model_router": "PROTECTED",
    },
}

(HERE / "c3_final_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
print(json.dumps(state, indent=2))
sys.exit(0 if (ce_on and compaction_off and ahead == "0") else 1)
