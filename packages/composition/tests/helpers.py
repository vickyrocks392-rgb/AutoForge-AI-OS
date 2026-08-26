"""Shared test doubles for composition tests."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from autoforge_ai_infrastructure.execution import ExecutionRequest, ExecutionTarget
from autoforge_ai_infrastructure.errors import (
    ExecutionTimeoutError,
    ProviderUnavailableError,
)


class FakeExecutor:
    """Configurable model executor double."""

    def __init__(self, *, fail_then_succeed: int = 0, delay_ms: float = 0.0):
        self.fail_then_succeed = fail_then_succeed
        self.delay_ms = delay_ms
        self.calls: list[tuple[ExecutionRequest, ExecutionTarget]] = []
        self._attempts: dict[tuple[str, str], int] = {}

    async def execute(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> dict[str, Any]:
        key = (target.provider_id, target.model_id)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        self.calls.append((request, target))
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms)
        if self.fail_then_succeed > 0 and self._attempts[key] <= self.fail_then_succeed:
            raise ProviderUnavailableError(
                f"provider '{target.provider_id}' transiently unavailable",
                details={"attempt": self._attempts[key]},
            )
        return {
            "text": f"output from {target.model_id}",
            "attempt": self._attempts[key],
        }


class AlwaysFailExecutor:
    """Always raises ProviderUnavailableError."""

    async def execute(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> dict[str, Any]:
        raise ProviderUnavailableError(
            f"provider '{target.provider_id}' unavailable",
            details={"model_id": target.model_id},
        )


class RecordingEventSink:
    """CanonicalEventSink double that records published events."""

    def __init__(self) -> None:
        self.published: list[Any] = []
        self._events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.published.append(event)
        self._events.append(event)

    @property
    def events(self) -> list[Any]:
        return self._events

    def reset(self) -> None:
        self.published.clear()
        self._events.clear()


async def noop_sleeper(_seconds: float) -> None:
    """Deterministic, instant backoff."""
