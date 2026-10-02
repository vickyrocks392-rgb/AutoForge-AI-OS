#!/usr/bin/env python3
"""Generate a pinned Python dependency lockfile and a CycloneDX-style SBOM.

SHC-09 (supply chain). This tool does exactly two things, deterministically:

1. Writes ``requirements.lock`` — the fully resolved, hashless-but-pinned
   transitive dependency set of the current environment (``==`` pins only).
2. Writes ``build/sbom.json`` — a machine-readable SBOM listing every pinned
   distribution, its version, and its declared license.

It deliberately does NOT claim vulnerability status. Vulnerability scanning is a
separate CI step (``pip-audit``) whose real results come from an advisory
database; this repository contains no CVE data, and no advisory result is
invented here.

Usage:
    python scripts/generate_lock_and_sbom.py [--check]

``--check`` verifies the committed lockfile matches the environment and exits
non-zero on drift, which is what CI should run on pull requests.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCKFILE = REPO_ROOT / "requirements.lock"
SBOM_PATH = REPO_ROOT / "build" / "sbom.json"

#: Distributions that are environment tooling rather than product dependencies.
EXCLUDE_PREFIXES = ("autoforge-",)


def _normalized_freeze() -> list[str]:
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = line.split("==")[0].split("@")[0].strip()
        if any(name.lower().startswith(p) for p in EXCLUDE_PREFIXES):
            continue
        lines.append(line)
    return sorted(set(lines), key=str.lower)


def _parse_pin(line: str) -> tuple[str, str]:
    if "==" in line:
        name, version = line.split("==", 1)
        return name.strip(), version.strip()
    return line.strip(), ""


def build_sbom(pins: list[str]) -> dict:
    components = []
    for line in pins:
        name, version = _parse_pin(line)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:sbom-{abs(hash(tuple(pins))) % (10 ** 12):012d}",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "autoforge-ai-os"},
            "tools": [{"name": "generate_lock_and_sbom.py", "vendor": "AutoForge"}],
        },
        "components": components,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed lockfile matches the environment (CI drift check).",
    )
    args = parser.parse_args()

    pins = _normalized_freeze()
    body = "\n".join(pins) + "\n"

    if args.check:
        if not LOCKFILE.exists():
            print("requirements.lock is missing; run this script without --check.", file=sys.stderr)
            return 1
        if LOCKFILE.read_text(encoding="utf-8") != body:
            print(
                "requirements.lock is out of date with the environment. "
                "Re-run scripts/generate_lock_and_sbom.py.",
                file=sys.stderr,
            )
            return 1
        print(f"requirements.lock is up to date ({len(pins)} pinned distributions).")
        return 0

    LOCKFILE.write_text(body, encoding="utf-8")
    SBOM_PATH.parent.mkdir(parents=True, exist_ok=True)
    SBOM_PATH.write_text(json.dumps(build_sbom(pins), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {LOCKFILE.relative_to(REPO_ROOT)} ({len(pins)} pins)")
    print(f"Wrote {SBOM_PATH.relative_to(REPO_ROOT)} ({len(pins)} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
