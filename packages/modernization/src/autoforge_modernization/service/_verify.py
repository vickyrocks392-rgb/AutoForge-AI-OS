"""Verify syntax and the current DAILYPOST codegen state."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

SERVICE = ROOT / "packages" / "modernization" / "src" / "autoforge_modernization" / "service"
PLAYBOOK = Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads/playbook")


def main() -> int:
    for path in sorted(SERVICE.glob("*.py")):
        try:
            ast.parse(path.read_text())
        except SyntaxError as exc:
            print(f"BAD  {path.name}: {exc}")
            return 1
    print("all service modules parse cleanly")

    from autoforge_modernization.service.cobol_program import build_program_model
    from autoforge_modernization.service.java_codegen import generate_java

    model = build_program_model(
        (PLAYBOOK / "cobol" / "DAILYPOST.cbl").read_text(errors="replace"),
        source_path="cobol/DAILYPOST.cbl",
        copybook_dirs=[PLAYBOOK / "cobol" / "copybooks"],
    )
    result = generate_java(model, java_package="modernized")
    print("unsupported:", len(result.unsupported))
    for item in result.unsupported[:15]:
        print("   ", item)
    for f in result.files:
        print("  file:", f.path, len(f.content))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())