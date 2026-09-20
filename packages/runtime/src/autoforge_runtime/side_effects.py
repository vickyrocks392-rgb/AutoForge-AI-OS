"""Provider-Agnostic Side-Effect Executor (Phase 18-J.4).

Provides a composable, infrastructure-independent abstraction for executing
side-effecting operations (HTTP calls, external API mutations, tool calls,
artifact writes) under durable idempotency protection.

Core Responsibilities:
----------------------
1. Derive canonical idempotency key (independent of execution attempt).
2. Compute deterministic request fingerprint and guard against parameter drift.
3. Transactionally claim operation via :class:`DurableIdempotencyStore`.
4. If already COMPLETED: return durable prior result directly without executing.
5. If claimed: invoke side-effect handler, propagating provider idempotency key.
6. Commit durable completion before observational success events are published.
7. Durably record failure on handler exception.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from typing import Any, Callable, Coroutine

from autoforge_runtime.idempotency import (
    AmbiguousSideEffectError,
    ClaimResult,
    ConcurrentOperationError,
    DurableIdempotencyStore,
    FingerprintConflictError,
    compute_request_fingerprint,
    derive_idempotency_key,
    operation_id_for_key,
)
from autoforge_runtime.models import IdempotentOperationState, OperationStatus

logger = logging.getLogger("autoforge.runtime.side_effects")


class SideEffectExecutor:
    """Coordinates execution of side effects with durable idempotency.

    Args:
        idempotency_store: The backing durable idempotency store.
    """

    def __init__(self, idempotency_store: DurableIdempotencyStore) -> None:
        self._store = idempotency_store

    @property
    def store(self) -> DurableIdempotencyStore:
        """The underlying durable idempotency store."""
        return self._store

    def execute(
        self,
        operation_name: str,
        payload: Any,
        handler: Callable[..., Any],
        *,
        idempotency_key: str | None = None,
        execution_id: uuid.UUID | str | None = None,
        attempt_id: uuid.UUID | str | None = None,
        workflow_id: uuid.UUID | str | None = None,
        task_id: str | None = None,
        step_or_call_id: Any = None,
        operation_type: str = "generic",
        supports_provider_idempotency: bool = True,
        provider_idempotency_key: str | None = None,
        allow_failed_retry: bool = True,
        result_reference: str | None = None,
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
        **handler_kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a synchronous side-effecting operation with durable idempotency.

        Returns:
            The structured dictionary result of the operation (either freshly
            computed or retrieved from the durable completion record).
        """
        key = idempotency_key or derive_idempotency_key(
            execution_id=execution_id,
            operation_type=operation_type,
            operation_name=operation_name,
            step_or_call_id=step_or_call_id,
            workflow_id=workflow_id,
            task_id=task_id,
        )
        fingerprint = compute_request_fingerprint(payload)
        effective_provider_key = provider_idempotency_key or key

        claim = self._store.claim_operation(
            idempotency_key=key,
            request_payload=payload,
            request_fingerprint=fingerprint,
            execution_id=execution_id,
            attempt_id=attempt_id,
            workflow_id=workflow_id,
            task_id=task_id,
            operation_type=operation_type,
            supports_provider_idempotency=supports_provider_idempotency,
            provider_idempotency_key=effective_provider_key,
            allow_failed_retry=allow_failed_retry,
            metadata=metadata,
            transition_id=transition_id,
        )

        if not claim.claimed:
            if claim.status == OperationStatus.COMPLETED:
                logger.debug(
                    "Idempotency hit for %s (op_id=%s). Returning durable cached result.",
                    key,
                    claim.operation_id,
                )
                return claim.cached_result or {}
            raise ConcurrentOperationError(
                f"Operation {key!r} could not be claimed (status={claim.status.value})."
            )

        # ── Claimed: execute side-effect handler ──────────────────────────
        try:
            call_kwargs = dict(handler_kwargs)
            sig = inspect.signature(handler)
            if "provider_idempotency_key" in sig.parameters:
                call_kwargs["provider_idempotency_key"] = effective_provider_key
            elif "idempotency_key" in sig.parameters:
                call_kwargs["idempotency_key"] = effective_provider_key

            raw_result = handler(payload, **call_kwargs)
            result_dict = raw_result if isinstance(raw_result, dict) else {"data": raw_result}

            # Durably commit completion
            self._store.complete_operation(
                claim.operation_id,
                result=result_dict,
                result_reference=result_reference,
                metadata=metadata,
                transition_id=transition_id,
            )
            return result_dict
        except Exception as exc:
            logger.error("Side effect %s failed: %s", key, exc, exc_info=True)
            self._store.fail_operation(
                claim.operation_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
                metadata=metadata,
                transition_id=transition_id,
            )
            raise

    async def execute_async(
        self,
        operation_name: str,
        payload: Any,
        handler: Callable[..., Coroutine[Any, Any, Any] | Any],
        *,
        idempotency_key: str | None = None,
        execution_id: uuid.UUID | str | None = None,
        attempt_id: uuid.UUID | str | None = None,
        workflow_id: uuid.UUID | str | None = None,
        task_id: str | None = None,
        step_or_call_id: Any = None,
        operation_type: str = "generic",
        supports_provider_idempotency: bool = True,
        provider_idempotency_key: str | None = None,
        allow_failed_retry: bool = True,
        result_reference: str | None = None,
        metadata: dict[str, Any] | None = None,
        transition_id: uuid.UUID | None = None,
        **handler_kwargs: Any,
    ) -> dict[str, Any]:
        """Execute an asynchronous side-effecting operation with durable idempotency.

        Returns:
            The structured dictionary result of the operation.
        """
        key = idempotency_key or derive_idempotency_key(
            execution_id=execution_id,
            operation_type=operation_type,
            operation_name=operation_name,
            step_or_call_id=step_or_call_id,
            workflow_id=workflow_id,
            task_id=task_id,
        )
        fingerprint = compute_request_fingerprint(payload)
        effective_provider_key = provider_idempotency_key or key

        claim = self._store.claim_operation(
            idempotency_key=key,
            request_payload=payload,
            request_fingerprint=fingerprint,
            execution_id=execution_id,
            attempt_id=attempt_id,
            workflow_id=workflow_id,
            task_id=task_id,
            operation_type=operation_type,
            supports_provider_idempotency=supports_provider_idempotency,
            provider_idempotency_key=effective_provider_key,
            allow_failed_retry=allow_failed_retry,
            metadata=metadata,
            transition_id=transition_id,
        )

        if not claim.claimed:
            if claim.status == OperationStatus.COMPLETED:
                logger.debug(
                    "Idempotency hit for %s (op_id=%s). Returning durable cached result.",
                    key,
                    claim.operation_id,
                )
                return claim.cached_result or {}
            raise ConcurrentOperationError(
                f"Operation {key!r} could not be claimed (status={claim.status.value})."
            )

        # ── Claimed: execute side-effect handler ──────────────────────────
        try:
            call_kwargs = dict(handler_kwargs)
            sig = inspect.signature(handler)
            if "provider_idempotency_key" in sig.parameters:
                call_kwargs["provider_idempotency_key"] = effective_provider_key
            elif "idempotency_key" in sig.parameters:
                call_kwargs["idempotency_key"] = effective_provider_key

            res = handler(payload, **call_kwargs)
            raw_result = await res if inspect.isawaitable(res) else res
            result_dict = raw_result if isinstance(raw_result, dict) else {"data": raw_result}

            # Durably commit completion
            self._store.complete_operation(
                claim.operation_id,
                result=result_dict,
                result_reference=result_reference,
                metadata=metadata,
                transition_id=transition_id,
            )
            return result_dict
        except Exception as exc:
            logger.error("Async side effect %s failed: %s", key, exc, exc_info=True)
            self._store.fail_operation(
                claim.operation_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
                metadata=metadata,
                transition_id=transition_id,
            )
            raise
