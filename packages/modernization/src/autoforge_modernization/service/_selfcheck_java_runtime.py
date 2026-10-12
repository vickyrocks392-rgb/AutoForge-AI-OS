"""Emit CobolRuntime.java and compile it with the real JDK."""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

from autoforge_modernization.service.java_runtime import render_runtime  # noqa: E402

JAVA_HOME = Path("/opt/homebrew/opt/openjdk@21")


def main() -> int:
    source = render_runtime("cobolrt")
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "cobolrt"
        pkg.mkdir()
        (pkg / "CobolRuntime.java").write_text(source)
        classes = Path(tmp) / "classes"
        classes.mkdir()
        result = subprocess.run(
            [str(JAVA_HOME / "bin" / "javac"), "-d", str(classes),
             str(pkg / "CobolRuntime.java")],
            capture_output=True, text=True,
        )
        print("javac exit:", result.returncode)
        if result.stdout.strip():
            print(result.stdout)
        if result.stderr.strip():
            print(result.stderr[:3000])
        if result.returncode == 0:
            produced = sorted(p.name for p in classes.rglob("*.class"))
            print("classes:", produced)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())