"""
Pytest configuration for orchestration E2E tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure packages are on the import path
_root = Path(__file__).resolve().parents[2].parent
_src = _root / "packages"
sys.path.insert(0, str(_src / "orchestration" / "src"))
sys.path.insert(0, str(_src / "events" / "src"))
sys.path.insert(0, str(_src / "workforce" / "src"))
sys.path.insert(0, str(_src / "execution" / "src"))
sys.path.insert(0, str(_src / "ai_infrastructure" / "src"))
sys.path.insert(0, str(_src / "evaluation" / "src"))
sys.path.insert(0, str(_src / "artifacts" / "src"))
sys.path.insert(0, str(_src / "knowledge" / "src"))
sys.path.insert(0, str(_src / "connectors" / "src"))
sys.path.insert(0, str(_src / "workflows" / "src"))

import pytest


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """Provide a temporary workspace root for each test."""
    return tmp_path


@pytest.fixture
def simple_event_sink():
    """Provide a fresh SimpleEventSink for each test."""
    from test_helpers import SimpleEventSink
    return SimpleEventSink()
