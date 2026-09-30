"""
DEF-18LR-B2 — legacy modernization must transform the REAL legacy source.

The first 18-L run reported blocker B-2, "legacy modernization does not
modernize", after observing that a synthetic placeholder
(``f"# legacy {tech} unit {id}"``) was passed into transformation instead of the
actual legacy file.

This suite pins the repaired contract at the orchestration boundary:

    reconnaissance (real files) -> plan (bound to real files)
        -> transformation input == the customer's actual bytes

The certified G.3 engine itself is NOT modified. These tests assert the
pipeline supplies it real source and chooses a transformation type the engine
actually supports.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import tempfile

import pytest

from autoforge_modernization.g3_real_run import run_g3_real
from autoforge_modernization.pipeline import ModernizationPipeline
from autoforge_modernization.reconnaissance.engine import run_reconnaissance

LEDGER_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEDGER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT      PIC 9(7)V99.
       01  WS-ENTRY-TOTAL PIC 9(9)V99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1250.50 TO WS-AMOUNT.
           ADD WS-AMOUNT TO WS-ENTRY-TOTAL.
           IF WS-ENTRY-TOTAL > 1000
               MOVE "HIGH" TO WS-STATUS
           END-IF.
           STOP RUN.
"""

LEDGER_JCL = """//LEDGER  JOB (ACCT),'LEDGER BATCH',CLASS=A
//STEP1   EXEC PGM=IEFBR14
//DD1     DD DSN=LEDGER.INPUT,DISP=SHR
//
"""


@pytest.fixture
def legacy_repo() -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp(prefix="18lr_legacy_"))
    (root / "cbl").mkdir()
    (root / "jcl").mkdir()
    (root / "cbl" / "LEDGER.cbl").write_text(LEDGER_COBOL, encoding="utf-8")
    (root / "jcl" / "LEDGER.jcl").write_text(LEDGER_JCL, encoding="utf-8")
    return root


# ── 1. No synthetic placeholder survives in the transformation boundary ──────


def test_pipeline_source_contains_no_placeholder_transformation_input():
    """The B-2 defect line must not exist in executable code any more."""
    src = inspect.getsource(ModernizationPipeline._run_wave)
    literals = [
        n.value
        for n in ast.walk(ast.parse(inspect.cleandoc(src)))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert not any("# legacy " in lit for lit in literals), (
        "the synthetic '# legacy ... unit ...' transformation input must not be "
        "reintroduced"
    )


# ── 2. Plan binds the real source files ─────────────────────────────────────


def test_derived_plan_binds_real_source_files(legacy_repo: pathlib.Path):
    pipeline = ModernizationPipeline()
    recon = run_reconnaissance(str(legacy_repo))
    inventory = pipeline._extract_source_inventory(recon)

    assert inventory, "reconnaissance source inventory must not be empty"
    for _tech, path in inventory:
        assert pathlib.Path(path).is_file(), "bound path must be a real file"

    result = pipeline.run(project_id="p", job_id="j", reconnaissance_output=recon)
    assert result.source_file_inventory == len(inventory)
    bound = [p for u in result.migration_plan.units for p in u.source_files]
    assert sorted(bound) == sorted(path for _t, path in inventory)
    for path in bound:
        assert pathlib.Path(path).is_file()


# ── 3. Transformation receives the customer's ACTUAL bytes ───────────────────


def test_transformation_input_is_the_real_legacy_source(legacy_repo: pathlib.Path):
    captured: list[dict] = []
    real_get = ModernizationPipeline._get_transformation_engine

    def _spy(self):  # noqa: ANN001
        engine = real_get(self)
        original = engine.apply

        def wrapper(*a, **kw):  # noqa: ANN002
            captured.append({
                "file_path": kw.get("file_path"),
                "before_content": kw.get("before_content"),
            })
            return original(*a, **kw)

        engine.apply = wrapper
        return engine

    ModernizationPipeline._get_transformation_engine = _spy
    try:
        ModernizationPipeline().run(
            project_id="p",
            job_id="j",
            reconnaissance_output=run_reconnaissance(str(legacy_repo)),
        )
    finally:
        ModernizationPipeline._get_transformation_engine = real_get

    assert captured, "transformation must actually have been invoked"
    on_disk = {
        str(legacy_repo / "cbl" / "LEDGER.cbl"): LEDGER_COBOL,
        str(legacy_repo / "jcl" / "LEDGER.jcl"): LEDGER_JCL,
    }
    seen: set[str] = set()
    for call in captured:
        content = call["before_content"]
        assert content is not None
        assert not content.startswith("# legacy "), (
            "transformation must not receive a synthetic placeholder"
        )
        assert call["file_path"] in on_disk, (
            "transformation must run against the real discovered file"
        )
        assert content == on_disk[call["file_path"]], (
            "transformation input must be the customer's actual bytes"
        )
        seen.add(call["file_path"])
    assert len(seen) == len(on_disk), "every real source file must be transformed"


# ── 4. The plan chooses a transformation type the engine supports ───────────


@pytest.mark.parametrize(
    "technology,expected",
    [("COBOL", "transpilation"), ("JCL", "rewrite")],
)
def test_selected_transformation_type_is_certified_and_supported(technology, expected):
    """The pipeline must route to a transformation the engine actually supports.

    For JCL both ``rewrite`` and ``reconfiguration`` map to the same certified
    ``_jcl_to_workflow_config`` strategy; the assertion that matters is that the
    chosen type is inside the engine's own certified supported set, and that a
    SUBSTANTIVE type is preferred over the cosmetic ``refactor``.
    """
    from autoforge_modernization.g3_transform_strategies import (
        G3TransformationStrategies,
    )

    chosen = ModernizationPipeline._select_transformation_type(technology)
    assert chosen.value == expected
    # The chosen type must be one the certified engine actually supports.
    assert G3TransformationStrategies.is_supported(technology, chosen.value)
    # ... and it must not be the cosmetic default that produces a no-op.
    assert chosen.value != "refactor", (
        "a cosmetic refactor is not a modernization and is correctly rejected "
        "by the engine's no-op detection"
    )


def test_unsupported_technology_degrades_to_explicit_default():
    from autoforge_modernization.transformation import TransformationType

    chosen = ModernizationPipeline._select_transformation_type("RPG")
    assert chosen is TransformationType.REFACTOR


# ── 5. End-to-end: real source in, real modernized source out ───────────────


def test_pipeline_modernizes_real_source_end_to_end(legacy_repo: pathlib.Path):
    result = ModernizationPipeline().run(
        project_id="p", job_id="j",
        reconnaissance_output=run_reconnaissance(str(legacy_repo)),
    )

    assert result.status.value == "complete", result.error_message
    assert result.source_file_inventory == 2

    applied = [
        r for r in result.transformation_records if r.status.value == "applied"
    ]
    assert applied, "at least one real transformation must be applied"

    cobol = [r for r in applied if r.file_path.endswith(".cbl")]
    assert cobol, "the real COBOL source must be transformed"
    rec = cobol[0]
    assert rec.before_content == LEDGER_COBOL
    assert rec.after_content != rec.before_content
    assert "# legacy " not in rec.after_content


def test_certified_engine_still_modernizes_real_source(legacy_repo: pathlib.Path):
    """LAYER A regression: the certified G.3 workflow is unchanged."""
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="18lr_out_"))
    g3 = run_g3_real(str(legacy_repo), str(out_dir))

    assert g3["transformation"]["applied"] >= 1
    java = list((out_dir / "transformed").glob("*.java"))
    assert java, "a real modernized Java artifact must be produced"
    text = java[0].read_text()
    assert "LEDGER" in text
    assert "# legacy " not in text
