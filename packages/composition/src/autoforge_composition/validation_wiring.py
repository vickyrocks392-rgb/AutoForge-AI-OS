"""DEF-18LR-D8 — deterministic project validation port for the completion gate.

Why this exists
---------------
The first 18-L run generated a real deliverable whose own test suite reported
``4 passed, 2 failed``, the final review was handed only the source files, and
the project still reached ``Finished`` with an explicit ``APPROVED``. The
review was never told the tests failed, and nothing deterministic was allowed
to overrule it.

The contract fixed here is:

    source artifacts + test results + validation results + execution evidence
        -> final review (evaluates)
    deterministic validation failure -> completion gate (enforces)

The LLM is **not** authoritative for whether tests passed. This port is a pure
deterministic system: it executes the project's own declared verification
command through the existing :class:`WorkspaceEnvironment` and parses the real
runner output with the existing
:func:`autoforge_execution.evaluation.parse_test_output`. It adds no new runner,
no new parser and no second execution path.

Where the command comes from
----------------------------
The verification command is *project configuration*, supplied at
``Request.configuration["verification_command"]`` and persisted by the existing
intake into ``ProjectState.configuration``. This module only reads it. When a
project declares no verification command there is no mandatory deterministic
validation to enforce, and the port reports ``required=False`` so the gate stays
exactly as strict (and no stricter) as before.
"""
from __future__ import annotations

import inspect
import logging
import shlex
from pathlib import Path
from typing import Any

from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.evaluation import parse_test_output
from autoforge_execution.models import CommandSpec

logger = logging.getLogger("autoforge.composition.validation_wiring")

#: Bounded wall clock for a project's own verification command.
DEFAULT_TIMEOUT_SECONDS = 600.0

#: Keys accepted for the declared verification command, in priority order.
_COMMAND_KEYS = (
    "verification_command",
    "verify_command",
    "test_command",
)

__all__ = [
    "WorkspaceValidationPort",
    "resolve_verification_command",
    "DEFAULT_TIMEOUT_SECONDS",
]


def resolve_verification_command(configuration: dict[str, Any] | None) -> list[str] | None:
    """Extract the project's declared verification command.

    Accepts a list of argv tokens or a single shell-style string. Returns
    ``None`` when the project declares none, which the port reports as
    ``required=False``.
    """
    if not isinstance(configuration, dict):
        return None

    # Request configuration is nested one level deep by the existing intake
    # (``Project.metadata["configuration"]``); a flat shape is accepted too.
    nested = configuration.get("configuration")
    sources = [configuration]
    if isinstance(nested, dict):
        sources.insert(0, nested)

    for source in sources:
        for key in _COMMAND_KEYS:
            raw = source.get(key)
            if isinstance(raw, (list, tuple)) and raw:
                return [str(part) for part in raw]
            if isinstance(raw, str) and raw.strip():
                parts = shlex.split(raw.strip())
                if parts:
                    return parts
    return None


class WorkspaceValidationPort:
    """Executes a project's own verification command and reports the truth.

    Implements the ``validate_project`` port the completion module consumes. It
    is deliberately thin: everything it calls is existing, certified production
    machinery.
    """

    def __init__(
        self,
        environment: WorkspaceEnvironment,
        runtime_state_manager: Any | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._env = environment
        self._runtime = runtime_state_manager
        self._timeout = timeout_seconds

    @property
    def environment(self) -> WorkspaceEnvironment:
        return self._env

    async def _project_configuration(self, project_id: Any) -> dict[str, Any]:
        """Read the project's durable configuration through the canonical path.

        DEF-18LE-D8b. This method previously called
        ``self._runtime.get_project_state(project_id)`` SYNCHRONOUSLY. The
        object wired by the composition root is the ``KernelRuntimeFacade``
        (``composition_root.py``), whose ``get_project_state`` is declared
        ``async def`` (``runtime_facade.py``), so the call returned an un-awaited
        coroutine. ``isinstance(state, dict)`` was therefore ``False`` and the
        method returned ``{}`` for EVERY project -- which made
        ``validate_project`` report ``required: False`` even when the project had
        explicitly declared a verification command. The D-8 deterministic
        completion gate was therefore inert in production, and the repository's
        own test run emitted ``RuntimeWarning: coroutine
        'KernelRuntimeFacade.get_project_state' was never awaited``.

        The fix uses the repository's EXISTING async architecture: the reader is
        awaited. No second project-state API, no new state model, and no change
        to validation semantics beyond correctly retrieving the state.

        A *synchronous* reader is still accepted so a caller that owns a
        non-async store (or a test double) keeps working unchanged; that is a
        compatibility accommodation, not a second authority.
        """
        if self._runtime is None:
            return {}
        try:
            reader = self._runtime.get_project_state
            state = reader(project_id)
            if inspect.isawaitable(state):
                state = await state
        except Exception as exc:  # pragma: no cover - defensive only
            logger.warning("Validation port could not read project state: %s", exc)
            return {}
        if not isinstance(state, dict):
            return {}
        return state.get("configuration") or {}

    async def validate_project(self, project_id: Any) -> dict[str, Any] | None:
        """Run the project's declared verification command.

        Returns a result dict. ``required`` is False when the project declares
        no verification command, so the completion gate can distinguish
        "nothing to validate" from "validation failed".
        """
        argv = resolve_verification_command(
            await self._project_configuration(project_id)
        )
        if not argv:
            return {
                "required": False,
                "performed": False,
                "passed": True,
                "reason": "Project declares no verification command.",
            }

        root = getattr(self._env, "root_path", None)
        result = await self._env.execute_command(
            CommandSpec(argv=list(argv), cwd=None),
            timeout_seconds=self._timeout,
        )

        summary = parse_test_output(result.stdout or "", result.stderr or "")
        failed = result.exit_code != 0
        errored = summary.error_tests > 0
        test_failures = summary.failed_tests > 0 or errored

        return {
            "required": True,
            "performed": True,
            "command": list(argv),
            "cwd": str(Path(root)) if root is not None else None,
            "exit_code": result.exit_code,
            "passed": not failed,
            "has_test_failures": test_failures,
            "has_errors": errored,
            "reason": (
                f"Verification command exited {result.exit_code}"
                if failed
                else f"Verification command passed ({summary.total_tests} tests)."
            ),
            "output": (result.stdout or "")[-4000:],
            "error_output": (result.stderr or "")[-4000:],
            "test_results": {
                "total_tests": summary.total_tests,
                "passed_tests": summary.passed_tests,
                "failed_tests": summary.failed_tests,
                "error_tests": summary.error_tests,
                "skipped_tests": summary.skipped_tests,
                "failure_details": list(summary.failure_details or [])[:20],
                "raw_summary_line": summary.raw_summary_line,
            },
        }


#: Bounded wall clock for a project's own verification command.
DEFAULT_TIMEOUT_SECONDS = 600.0

#: Keys accepted for the declared verification command, in priority order.
_COMMAND_KEYS = (
    "verification_command",
    "verify_command",
    "test_command",
)
