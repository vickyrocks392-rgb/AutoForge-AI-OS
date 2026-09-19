"""Tests for Closed-Loop Autonomous Diagnosis & Repair Engine."""

import pytest
from pathlib import Path
from autoforge_power_engines.rag.repair import RAGClosedLoopRepairEngine


def test_repair_corrupt_json(tmp_path):
    deliv_dir = tmp_path / "customer_proj"
    deliv_dir.mkdir()
    cfg_dir = deliv_dir / "config"
    cfg_dir.mkdir()

    bad_json = cfg_dir / "settings.json"
    # Write trailing comma corruption
    bad_json.write_text('{"host": "127.0.0.1", "port": 8000,}', encoding="utf-8")

    engine = RAGClosedLoopRepairEngine(deliv_dir)
    defects = engine.diagnose_defects()
    assert len(defects) >= 1
    assert any(d.defect_type == "json_syntax" for d in defects)

    # Apply repair
    result = engine.apply_repairs(defects)
    assert result.repaired is True
    assert result.repair_count >= 1

    # Verify no remaining defects
    re_defects = engine.diagnose_defects()
    assert len(re_defects) == 0


def test_repair_missing_script_shebang(tmp_path):
    deliv_dir = tmp_path / "customer_proj"
    deliv_dir.mkdir()
    scripts_dir = deliv_dir / "scripts"
    scripts_dir.mkdir()

    bad_script = scripts_dir / "run.sh"
    bad_script.write_text("echo 'Starting server'\npython3 src/app.py\n", encoding="utf-8")

    engine = RAGClosedLoopRepairEngine(deliv_dir)
    defects = engine.diagnose_defects()
    assert any(d.defect_type == "script_header" for d in defects)

    result = engine.apply_repairs(defects)
    assert result.repaired is True

    fixed_text = bad_script.read_text(encoding="utf-8")
    assert fixed_text.startswith("#!/usr/bin/env bash")
