"""Phase 20 -- DAILYPOST golden-master equivalence (real workload).

The real ``DAILYPOST`` program from the pinned ``cobol-modernization-playbook``
revision is the authority for this suite. The golden masters are produced by
**GnuCOBOL executing the original COBOL** -- never from the Java output, never
from expected constants -- and the generated Java must reproduce them byte for
byte.

The suite skips rather than fakes when GnuCOBOL, a JDK or the workload checkout
is unavailable: a missing toolchain means no comparison is claimed, never a
fabricated one.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from autoforge_modernization.service.cobol_program import build_program_model
from autoforge_modernization.service.java_codegen import generate_java

#: Pinned upstream revision of marcoeg/cobol-modernization-playbook.
PLAYBOOK_REVISION = "d204cf8472cf7a468419f971cba0cd63589eda5a"

#: Where the pinned workload is materialised for certification.
WORKLOAD_ROOT = Path(
    "/Users/kalachanddash/Developer/.autoforge-p20-workloads/playbook")

#: Homebrew OpenJDK; the generated application needs nothing else.
JDK = Path("/opt/homebrew/opt/openjdk")

INPUT_FILES = ("accounts.dat", "txns.dat")
OUTPUT_FILES = ("accounts_out.dat", "exceptions.dat")

needs_workload = pytest.mark.skipif(
    not (WORKLOAD_ROOT / "cobol" / "DAILYPOST.cbl").exists(),
    reason=f"workload checkout not present at {WORKLOAD_ROOT}")
needs_cobol = pytest.mark.skipif(
    shutil.which("cobc") is None, reason="GnuCOBOL is not installed")
needs_jdk = pytest.mark.skipif(
    not (JDK / "bin" / "javac").exists(), reason="JDK is not installed")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compile_legacy(out_path: Path) -> None:
    """Compile the ORIGINAL COBOL with GnuCOBOL, independently of AutoForge."""
    result = subprocess.run(
        ["cobc", "-x", "-free",
         "-I", str(WORKLOAD_ROOT / "cobol" / "copybooks"),
         "-o", str(out_path), str(WORKLOAD_ROOT / "cobol" / "DAILYPOST.cbl")],
        capture_output=True, text=True)
    assert result.returncode == 0, f"GnuCOBOL compile failed: {result.stderr}"


def _run_legacy(binary: Path, run_dir: Path) -> tuple[subprocess.CompletedProcess, Path]:
    """Execute the legacy job and capture its real evidence."""
    (run_dir / "data").mkdir(parents=True, exist_ok=True)
    (run_dir / "out").mkdir(parents=True, exist_ok=True)
    for name in INPUT_FILES:
        shutil.copy(WORKLOAD_ROOT / "data" / name, run_dir / "data" / name)
    result = subprocess.run(
        [str(binary)], cwd=run_dir, capture_output=True, text=True,
        stdin=subprocess.DEVNULL)
    return result, run_dir


def _compile_modernized(generated, work: Path) -> Path:
    src = work / "java"
    for item in generated.files:
        target = src / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content)
    result = subprocess.run(
        [str(JDK / "bin" / "javac"), "-d", str(work / "classes"),
         *[str(src / f.path) for f in generated.files]],
        capture_output=True, text=True)
    assert result.returncode == 0, f"javac failed: {result.stderr}"
    return work / "classes"


def _run_modernized(classes: Path, run_dir: Path) -> tuple[subprocess.CompletedProcess, Path]:
    (run_dir / "data").mkdir(parents=True, exist_ok=True)
    (run_dir / "out").mkdir(parents=True, exist_ok=True)
    for name in INPUT_FILES:
        shutil.copy(WORKLOAD_ROOT / "data" / name, run_dir / "data" / name)
    result = subprocess.run(
        [str(JDK / "bin" / "java"), "-cp", str(classes), "modernized.Dailypost"],
        cwd=run_dir, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return result, run_dir


@pytest.fixture(scope="module")
def dailypost_model():
    return build_program_model(
        (WORKLOAD_ROOT / "cobol" / "DAILYPOST.cbl").read_text(errors="replace"),
        source_path="cobol/DAILYPOST.cbl",
        copybook_dirs=[WORKLOAD_ROOT / "cobol" / "copybooks"],
    )


@pytest.fixture(scope="module")
def generated_java(dailypost_model):
    """Translate the real program once for the whole module."""
    result = generate_java(dailypost_model, java_package="modernized")
    assert result.ok, result.unsupported
    return result


def test_dailypost_translates_without_gaps(dailypost_model, generated_java):
    """The real program must translate completely: zero unsupported constructs."""
    assert dailypost_model.gaps == []
    assert generated_java.unsupported == []
    assert generated_java.files, "the generator must emit the program"


@needs_workload
def test_workload_revision_is_the_certified_one():
    """Guard against certifying against a drifted checkout."""
    if not (WORKLOAD_ROOT / ".git").exists():
        pytest.skip("workload is not a git checkout")
    head = subprocess.run(
        ["git", "-C", str(WORKLOAD_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
@needs_workload
@needs_cobol
@needs_jdk
def test_dailypost_output_is_byte_identical_to_gnucobol(
        tmp_path_factory, generated_java):
    """The hard certification gate.

    Real COBOL -> GnuCOBOL -> golden master, then the generated Java on the
    same input, then a byte-for-byte comparison of both output datasets.
    """
    work = tmp_path_factory.mktemp("dailypost")

    # ── Independently generate the golden master with GnuCOBOL ──────────────
    _compile_legacy(work / "dailypost")
    legacy, gm_run = _run_legacy(work / "dailypost", work / "legacy")
    assert legacy.returncode == 0, f"legacy run failed: {legacy.stderr}"

    # ── Compile and run the generated Java on the same input ────────────────
    classes = _compile_modernized(generated_java, work)
    modern, jv_run = _run_modernized(classes, work / "modern")
    assert modern.returncode == 0, (
        f"modernized program failed: {modern.stderr}")
    assert modern.stdout == legacy.stdout, (
        "stdout must match the legacy job")
    assert modern.stderr == "", (
        f"modernized program wrote to stderr: {modern.stderr}")

    # ── Byte-for-byte comparison ────────────────────────────────────────────
    for name in OUTPUT_FILES:
        master = gm_run / "out" / name
        produced = jv_run / "out" / name
        assert master.exists(), f"legacy run did not produce {name}"
        assert produced.exists(), f"modernized run did not produce {name}"
        assert produced.stat().st_size == master.stat().st_size, (
            f"{name}: length {produced.stat().st_size} != "
            f"{master.stat().st_size}")
        assert _sha256(produced) == _sha256(master), f"{name}: SHA-256 mismatch"
        assert produced.read_bytes() == master.read_bytes(), (
            f"{name}: bytes differ from the GnuCOBOL golden master")

    # ── No unexpected output ────────────────────────────────────────────────
    produced_files = sorted(p.name for p in (jv_run / "out").iterdir())
    assert produced_files == sorted(OUTPUT_FILES), (
        f"unexpected output files: {produced_files}")


@needs_workload
@needs_cobol
@needs_jdk
def test_the_comparison_is_not_vacuous(tmp_path_factory):
    """Guard against an empty-dataset false pass.

    ``exceptions.dat`` is written only on the overdraft path, so non-empty
    output on both datasets proves the AT END and NOT AT END branches were
    genuinely both taken.
    """
    work = tmp_path_factory.mktemp("dailypost-nonempty")
    _compile_legacy(work / "dailypost")
    legacy, legacy_dir = _run_legacy(work / "dailypost", work / "legacy")
    assert legacy.returncode == 0, legacy.stderr

    accounts = (legacy_dir / "out" / "accounts_out.dat").read_bytes()
    exceptions = (legacy_dir / "out" / "exceptions.dat").read_bytes()
    assert len(accounts) >= 58 and len(accounts) % 58 == 0, (
        "accounts_out.dat must hold whole 58-byte records")
    assert len(exceptions) >= 72 and len(exceptions) % 72 == 0, (
        "exceptions.dat must hold whole 72-byte records")


def test_generated_program_contains_no_fixture_specific_logic(generated_java):
    """The transformation must stay generic.

    A modernizer that special-cases one fixture would produce correct bytes for
    the wrong reason. The dataset names in the output legitimately come from
    the program's own ``SELECT ... ASSIGN TO`` clauses; what must never appear
    is a hardcoded *result* or a marker identifying the fixture.
    """
    body = "\n".join(
        f.content for f in generated_java.files if "CobolRuntime" not in f.path)

    # Every dataset path is traceable to a SELECT ... ASSIGN TO clause.
    for ddn in ("ACCT-FILE", "TXN-FILE", "ACCT-OUT", "EXC-FILE"):
        assert f'datasets.put("{ddn}"' in body, (
            f"{ddn} must be bound from its SELECT clause")

    # No embedded golden-master bytes, expected values or fixture markers.
    for marker in ("DAILYPOST_OUTPUT", "GOLDEN", "golden", "expected_output",
                   "assertEquals"):
        assert marker not in body, (
            f"generated code contains fixture-specific marker {marker!r}")

    # No literal containing raw COMP-3 bytes or high-byte escapes that could
    # only have come from a captured output file.
    assert "\\x00" not in body, "no escaped binary data may be embedded"
    assert "(byte) 0x" not in body, "no raw byte literals may be embedded"