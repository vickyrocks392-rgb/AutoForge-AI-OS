#!/usr/bin/env python3
"""Run all AutoForge tests across all packages and apps."""

import glob
import os
import subprocess
import sys

def main() -> int:
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_paths = [os.path.abspath(p) for p in glob.glob(os.path.join(workspace_root, "packages/*/src")) + glob.glob(os.path.join(workspace_root, "apps/*/src"))]
    env = os.environ.copy()
    env["PYTHONPATH"] = ":".join(src_paths) + ":" + env.get("PYTHONPATH", "")

    test_dirs = sorted(glob.glob(os.path.join(workspace_root, "packages/*/tests")) + glob.glob(os.path.join(workspace_root, "apps/*/tests")))
    
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    failures = []

    print("=" * 80)
    print("AUTOFROGE MONOREPO TEST SUITE EXECUTION")
    print(f"Total test targets found: {len(test_dirs)}")
    print("=" * 80)

    for tdir in test_dirs:
        rel = os.path.relpath(tdir, workspace_root)
        pkg_root = os.path.dirname(tdir)
        cmd = [sys.executable, "-m", "pytest", tdir, "-q", "--disable-warnings"]
        res = subprocess.run(cmd, cwd=pkg_root, env=env, capture_output=True, text=True)
        
        output_line = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else res.stderr.strip()
        print(f"[{rel}] -> {output_line}")
        
        if res.returncode == 0:
            # Parse passed count if available
            parts = output_line.split(",")
            for p in parts:
                p_str = p.strip()
                if "passed" in p_str:
                    try:
                        total_passed += int(p_str.split()[0])
                    except Exception:
                        pass
        else:
            total_failed += 1
            failures.append((rel, res.stdout + "\n" + res.stderr))

    print("=" * 80)
    print(f"SUMMARY: Tests execution completed.")
    print(f"Passed Packages: {len(test_dirs) - len(failures)} / {len(test_dirs)}")
    print(f"Total Individual Tests Count Recorded: ~{total_passed}")
    
    if failures:
        print(f"\nFAILED PACKAGES ({len(failures)}):")
        for pkg, out in failures:
            print(f"\n--- FAILURE IN {pkg} ---")
            print(out)
        return 1
    
    print("\nALL MONOREPO TESTS PASSED SUCCESSFULLY! (100% Pass Rate)")
    print("=" * 80)
    return 0

if __name__ == "__main__":
    sys.exit(main())
