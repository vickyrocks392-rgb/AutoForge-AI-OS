"""18-LR LAYER-A :: LEGACY MODERNIZATION EXISTING CERTIFICATION REPRODUCTION.

B-2 in the first 18-L run claimed "legacy modernization does not modernize"
because ``ModernizationPipeline._run_wave`` fed
``f"# legacy {source_tech} unit {unit.component_id}"`` into transformation.

This probe does NOT assume the engine is broken. It separates two claims:

  A. Does the Legacy Modernization engine transform REAL legacy source when
     invoked through its already-certified workflow?
  B. Does the pipeline that 18-L invoked feed it real source or a placeholder?

Every boundary is traced with the ACTUAL value/type/identity:

    actual legacy input -> ingestion -> analysis -> planning -> transformation

REAL FIXTURE: a genuine COBOL batch program plus a real JCL job -- the two
technologies the certified G.3 transformation strategies support.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_EVIDENCE = _REPO / "18LR-defect-repair" / "evidence"
_EVIDENCE.mkdir(parents=True, exist_ok=True)

for _pkg in [
    "events", "event_platform", "runtime", "models", "ai_infrastructure",
    "workflows", "execution", "artifacts", "review", "security", "connectors",
    "orchestration", "kernel", "composition", "workforce", "power_engines",
    "modernization", "observability", "persistence", "knowledge_platform",
]:
    _src = _REPO / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


LEDGER_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEDGER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT      PIC 9(7)V99.
       01  WS-ENTRY-TOTAL PIC 9(9)V99 VALUE 0.
       01  WS-COUNT       PIC 9(4) VALUE 0.
       01  WS-STATUS      PIC X(10) VALUE "OK".
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1250.50 TO WS-AMOUNT.
           ADD WS-AMOUNT TO WS-ENTRY-TOTAL.
           ADD 1 TO WS-COUNT.
           IF WS-ENTRY-TOTAL > 1000
               MOVE "HIGH" TO WS-STATUS
           END-IF.
           DISPLAY "LEDGER TOTAL: " WS-ENTRY-TOTAL.
           STOP RUN.
"""

LEDGER_JCL = """//LEDGER  JOB (ACCT),'LEDGER BATCH',CLASS=A
//STEP1   EXEC PGM=IEFBR14
//DD1     DD DSN=LEDGER.INPUT,DISP=SHR
//SYSPRINT DD SYSOUT=*
//SYSIN   DD DSN=LEDGER.CTRL,DISP=SHR
//
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write_fixture() -> Path:
    src_root = Path(tempfile.mkdtemp(prefix="18LR_legacy_src_"))
    (src_root / "cbl").mkdir()
    (src_root / "jcl").mkdir()
    (src_root / "cbl" / "LEDGER.cbl").write_text(LEDGER_COBOL, encoding="utf-8")
    (src_root / "jcl" / "LEDGER.jcl").write_text(LEDGER_JCL, encoding="utf-8")
    return src_root


def _boundary_ingestion(src_root: Path) -> dict:
    from autoforge_modernization.reconnaissance.scanner import scan_repository

    scan = scan_repository(str(src_root))
    scanned = list(getattr(scan, "scanned_files", []) or [])
    return {
        "scanned_file_count": len(scanned),
        "scanned_files": [
            {
                "relative_path": sf.relative_path,
                "category": str(getattr(sf.category, "value", sf.category)),
                "detected_language": sf.detected_language,
                "detected_technologies": list(sf.detected_technologies or []),
            }
            for sf in scanned
        ],
    }



def _boundary_pipeline(src_root: Path) -> dict:
    """Analysis + planning + transformation through the 18-L pipeline path.

    Uses the REAL reconnaissance output (the customer's actual scanned files),
    which is what the canonical path now supplies.
    """
    from autoforge_modernization.pipeline import ModernizationPipeline
    from autoforge_modernization.reconnaissance.engine import run_reconnaissance

    # The REAL G.2 reconnaissance output: the customer's actual scanned files
    # plus the technologies detected from them.
    recon = run_reconnaissance(str(src_root))
    captured: list[dict] = []
    # Instrument the transformation boundary to capture the ACTUAL value/type
    # that reaches the engine, not what the record happens to retain.
    real_apply = ModernizationPipeline._get_transformation_engine

    def _spy(self):  # noqa: ANN001
        engine = real_apply(self)
        original = engine.apply

        def wrapper(*a, **kw):
            captured.append(
                {
                    "file_path_arg": kw.get("file_path"),
                    "before_content_arg": kw.get("before_content"),
                    "before_content_type": type(kw.get("before_content")).__name__,
                }
            )
            return original(*a, **kw)

        engine.apply = wrapper
        return engine

    ModernizationPipeline._get_transformation_engine = _spy
    try:
        result = ModernizationPipeline().run(
            project_id="18LR-pipeline", job_id="18LR-job", reconnaissance_output=recon
        )
    finally:
        ModernizationPipeline._get_transformation_engine = real_apply
    wave0 = result.wave_results[0] if result.wave_results else None
    records = result.transformation_records or []
    return {
        "status": str(getattr(result.status, "value", result.status)),
        "analysis_present": result.analysis_report is not None,
        "plan_units": len(result.migration_plan.units) if result.migration_plan else 0,
        "wave_units_transformed": wave0.units_transformed if wave0 else 0,
        "wave_units_failed": wave0.units_failed if wave0 else 0,
        "wave_error": wave0.error_message if wave0 else None,
        "pipeline_error": result.error_message,
        "transformation_boundary_capture": captured,
        "records": [
            {
                "unit_id": r.unit_id,
                "file_path": r.file_path,
                "before_content": r.before_content,
                "before_is_placeholder": (r.before_content or "").startswith("# legacy "),
                "after_content_head": (r.after_content or "")[:80],
            }
            for r in records
        ],
    }


def _boundary_engine(src_root: Path) -> tuple[dict, dict]:
    """The ENGINE itself, invoked on the real legacy source."""
    from autoforge_modernization.g3_real_run import run_g3_real

    out_dir = Path(tempfile.mkdtemp(prefix="18LR_legacy_out_"))
    g3 = run_g3_real(str(src_root), str(out_dir))
    xf = g3.get("transformation", {})
    applied = [r for r in xf.get("records", []) if r.get("status") == "applied"]
    engine = {
        "scan": g3.get("scan"),
        "applied_count": xf.get("applied"),
        "blocked_count": xf.get("blocked"),
        "failed_count": xf.get("failed"),
        "applied": [
            {
                "path": Path(r["path"]).name,
                "before_sha256": r.get("bc"),
                "after_sha256": r.get("ac"),
                "output": r.get("output"),
                "is_identity": r.get("is_id"),
            }
            for r in applied
        ],
    }
    java_files = sorted((out_dir / "transformed").glob("*.java"))
    text = java_files[0].read_text() if java_files else ""
    derived = {
        "java_files": [p.name for p in java_files],
        "contains_program_id_LEDGER": "LEDGER" in text,
        "contains_ws_amount": "WS_AMOUNT" in text or "wsAmount" in text,
        "contains_main_para": "MAIN" in text.upper(),
        "contains_placeholder_marker": "# legacy " in text,
        "head": text[:600],
    }
    return engine, derived


def main() -> int:
    src_root = _write_fixture()
    out: dict = {
        "phase": "18-LR Layer-A legacy modernization",
        "real_legacy_input": {
            "root": str(src_root),
            "files": {
                "cbl/LEDGER.cbl": {"bytes": len(LEDGER_COBOL), "sha256": _sha(LEDGER_COBOL)},
                "jcl/LEDGER.jcl": {"bytes": len(LEDGER_JCL), "sha256": _sha(LEDGER_JCL)},
            },
        },
        "boundary_1_ingestion": _boundary_ingestion(src_root),
        "boundary_2_3_pipeline": _boundary_pipeline(src_root),
    }
    engine, derived = _boundary_engine(src_root)
    out["boundary_4_engine_on_real_source"] = engine
    out["engine_output_derives_from_real_source"] = derived

    engine_ok = bool(engine["applied_count"]) and derived["contains_program_id_LEDGER"]
    placeholder = any(
        (c.get("before_content_arg") or "").startswith("# legacy ")
        for c in out["boundary_2_3_pipeline"]["transformation_boundary_capture"]
    )
    out["verdict"] = {
        "A_engine_on_real_source": "PASS" if engine_ok else "FAIL",
        "B_pipeline_uses_placeholder": placeholder,
        "conclusion": (
            "ENGINE IMPLEMENTATION = PASS (transforms real legacy source); the "
            "defect is the PIPELINE/ORCHESTRATION boundary that supplies a "
            "synthetic placeholder instead of the real file content"
            if engine_ok and placeholder
            else "see per-boundary results"
        ),
    }
    print(json.dumps(out, indent=2, default=str))
    (_EVIDENCE / "layer_a_modernization.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
