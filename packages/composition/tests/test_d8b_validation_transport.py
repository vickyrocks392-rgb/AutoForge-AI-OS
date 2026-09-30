"""
DEF-18LE-D8b regression tests.

D-8b: ``WorkspaceValidationPort._project_configuration`` called the ASYNC
``KernelRuntimeFacade.get_project_state`` synchronously, received an
un-awaited coroutine, and therefore returned ``{}`` for EVERY project. The
consequence was that ``validate_project`` reported ``required: False`` even
when a project had explicitly declared a verification command, which made the
D-8 deterministic completion gate inert in production.

These tests lock the repair:
  1. a project that declares a verification command reports ``required=True``
  2. a project that declares none still reports ``required=False`` (unchanged)
  3. no "coroutine ... was never awaited" RuntimeWarning is emitted
  4. the state is read through the canonical async facade
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _pkg in [
    "events", "event_platform", "runtime", "models", "ai_infrastructure",
    "workflows", "execution", "artifacts", "review", "security",
    "connectors", "orchestration", "kernel", "composition", "workforce",
]:
    _src = _REPO / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_composition.validation_wiring import (  # noqa: E402
    WorkspaceValidationPort,
    resolve_verification_command,
)
from autoforge_execution.environment import WorkspaceEnvironment  # noqa: E402


class _AsyncStateReader:
    """Minimal stand-in exposing the CANONICAL async reader shape."""

    def __init__(self, state: dict | None) -> None:
        self._state = state
        self.calls = 0

    async def get_project_state(self, project_id):  # noqa: ANN001
        self.calls += 1
        if self._state is None:
            raise KeyError(f"Project with ID {project_id} not found")
        return self._state


class _SyncStateReader:
    """A non-async reader must keep working (compatibility accommodation)."""

    def __init__(self, state: dict | None) -> None:
        self._state = state

    def get_project_state(self, project_id):  # noqa: ANN001
        if self._state is None:
            raise KeyError(f"Project with ID {project_id} not found")
        return self._state


def _port(tmp_path: Path, reader) -> WorkspaceValidationPort:
    return WorkspaceValidationPort(
        environment=WorkspaceEnvironment(tmp_path),
        runtime_state_manager=reader,
    )


def _state(configuration: dict) -> dict:
    return {"project_id": "p", "configuration": configuration}


# ── 1. declared verification produces required=True ───────────────────────────

async def test_declared_verification_is_required(tmp_path):
    reader = _AsyncStateReader(
        _state({"configuration": {"verification_command": "python -c \"print(1)\""}})
    )
    result = await _port(tmp_path, reader).validate_project("p")

    assert result["required"] is True
    assert result["performed"] is True
    assert result["command"] == ["python", "-c", "print(1)"]
    assert reader.calls == 1


@pytest.mark.parametrize(
    "key", ["verification_command", "verify_command", "test_command"]
)
async def test_every_accepted_declaration_key_is_required(tmp_path, key):
    reader = _AsyncStateReader(_state({"configuration": {key: "python -c \"print(1)\""}}))
    result = await _port(tmp_path, reader).validate_project("p")
    assert result["required"] is True


async def test_declared_verification_failure_is_reported_as_failure(tmp_path):
    reader = _AsyncStateReader(
        _state({"configuration": {"verification_command": "python -c \"raise SystemExit(3)\""}})
    )
    result = await _port(tmp_path, reader).validate_project("p")

    assert result["required"] is True
    assert result["performed"] is True
    assert result["passed"] is False
    assert result["exit_code"] != 0


# ── 2. absent verification keeps the existing contract ────────────────────────

async def test_absent_verification_is_not_required(tmp_path):
    reader = _AsyncStateReader(_state({"configuration": {"language": "python"}}))
    result = await _port(tmp_path, reader).validate_project("p")

    assert result["required"] is False
    assert result["performed"] is False
    assert result["passed"] is True
    assert "no verification command" in result["reason"].lower()


async def test_unknown_project_is_not_required_and_does_not_raise(tmp_path):
    result = await _port(tmp_path, _AsyncStateReader(None)).validate_project("missing")
    assert result["required"] is False


async def test_no_runtime_configured_is_not_required(tmp_path):
    port = WorkspaceValidationPort(environment=WorkspaceEnvironment(tmp_path))
    result = await port.validate_project("p")
    assert result["required"] is False


# ── 3. no un-awaited-coroutine RuntimeWarning ────────────────────────────────

async def test_no_never_awaited_coroutine_warning(tmp_path):
    reader = _AsyncStateReader(
        _state({"configuration": {"verification_command": "python -c \"print(1)\""}})
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await _port(tmp_path, reader).validate_project("p")
    messages = [str(w.message) for w in caught]
    assert not any("never awaited" in m for m in messages), messages


# ── 4. state is read through the canonical async path ────────────────────────

async def test_state_read_through_async_facade(tmp_path):
    """The canonical async facade is genuinely awaited.

    ``_project_configuration`` returns the project's ``configuration`` container
    (which nests the original ``Request.configuration`` one level deep, exactly as
    the existing intake persists it). Asserting on the nested payload proves the
    await happened: before the repair this returned ``{}``.
    """
    reader = _AsyncStateReader(
        _state({"configuration": {"verification_command": "python -c \"print(1)\""}})
    )
    port = _port(tmp_path, reader)
    config = await port._project_configuration("p")
    assert config == {"configuration": {"verification_command": "python -c \"print(1)\""}}
    assert reader.calls == 1


async def test_sync_reader_still_supported(tmp_path):
    reader = _SyncStateReader(
        _state({"configuration": {"verification_command": "python -c \"print(1)\""}})
    )
    result = await _port(tmp_path, reader).validate_project("p")
    assert result["required"] is True


def test_resolve_verification_command_unchanged():
    assert resolve_verification_command({"verification_command": "pytest -q"}) == [
        "pytest", "-q",
    ]
    assert resolve_verification_command({}) is None
    assert resolve_verification_command(None) is None
    # nested one level deep, as the existing intake persists it
    assert resolve_verification_command(
        {"configuration": {"verification_command": "pytest -q"}}
    ) == ["pytest", "-q"]
