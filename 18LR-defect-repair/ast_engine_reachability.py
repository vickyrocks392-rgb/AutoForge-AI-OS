"""18LR-AST-01: does any PRODUCTION file reach the five commercial engines?

Proven by AST import analysis (not documentation). For each engine package,
list every file OUTSIDE that package whose import graph names it.
"""
from __future__ import annotations

import ast
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = ("autoforge_power_engines", "autoforge_modernization")
ENGINE_OWNER = {
    "autoforge_power_engines": "power_engines",
    "autoforge_modernization": "modernization",
}


def imports_of(path: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def main() -> int:
    out: dict[str, object] = {}
    for target in TARGETS:
        owner = ENGINE_OWNER[target]
        internal: set[str] = set()
        external: dict[str, list[str]] = {}
        for p in sorted(ROOT.glob("packages/*/src/**/*.py")):
            pkg = p.relative_to(ROOT).parts[1]
            for m in imports_of(p):
                if m == target or m.startswith(target + "."):
                    rel = str(p.relative_to(ROOT))
                    if pkg == owner:
                        internal.add(rel)
                    else:
                        external.setdefault(pkg, []).append(rel)
        out[target] = {
            "internal_importing_files": len(internal),
            "external_importing_packages": {k: sorted(v) for k, v in external.items()},
        }

    # The canonical production path, enumerated explicitly.
    canonical = [
        "packages/kernel/src/autoforge_kernel/kernel.py",
        "packages/kernel/src/autoforge_kernel/orchestration.py",
        "packages/kernel/src/autoforge_kernel/completion.py",
        "packages/kernel/src/autoforge_kernel/strategic_engine.py",
        "packages/composition/src/autoforge_composition/composition_root.py",
        "packages/composition/src/autoforge_composition/kernel_adapters.py",
        "packages/execution/src/autoforge_execution/engine.py",
    ]
    reached = {}
    for rel in canonical:
        mods = imports_of(ROOT / rel)
        hits = sorted({t for t in TARGETS if any(m == t or m.startswith(t + ".") for m in mods)})
        reached[rel] = hits
    out["canonical_path_engine_reachability"] = reached
    out["canonical_path_reaches_any_engine"] = any(reached.values())

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
