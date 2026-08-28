"""
Structured logging system with security redaction and error normalization.
"""

from __future__ import annotations
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from autoforge_observability.models import Severity, StructuredLogEntry

# Try to reuse connectors redact, fallback if unavailable
try:
    from autoforge_connectors.security import redact as _connector_redact
except ImportError:
    _connector_redact = None


class StructuredLogger:
    """
    Structured log collector and publisher.
    Redacts secrets and ensures credentials/API keys never leak to logs.
    """

    def __init__(self, name: str = "autoforge") -> None:
        self.name = name
        self._logs: List[StructuredLogEntry] = []
        self._secrets: Set[str] = set()
        self._lock = threading.Lock()

    def register_secret(self, secret: str) -> None:
        """Register a sensitive token/string to be redacted from all future logs."""
        if secret and len(secret) > 3:
            with self._lock:
                self._secrets.add(secret)

    def _redact_message(self, message: str) -> str:
        if _connector_redact is not None:
            # Re-use connector redact
            message = _connector_redact(message, self._secrets)
        else:
            # Fallback redact
            for secret in self._secrets:
                if secret in message:
                    message = message.replace(secret, "***")
        return message

    def _redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Scrub keys and values matching secret patterns or registered secrets."""
        redacted = {}
        for k, v in data.items():
            # Check key name for sensitive suffixes
            kl = k.lower()
            if any(term in kl for term in ("key", "secret", "token", "password", "auth", "credential")):
                redacted[k] = "***"
                continue

            if isinstance(v, str):
                redacted[k] = self._redact_message(v)
            elif isinstance(v, dict):
                redacted[k] = self._redact_dict(v)
            elif isinstance(v, list):
                redacted[k] = [self._redact_dict(item) if isinstance(item, dict) else (self._redact_message(item) if isinstance(item, str) else item) for item in v]
            else:
                redacted[k] = v
        return redacted

    def log(
        self,
        severity: Severity,
        component: str,
        message: str,
        correlation_id: Optional[uuid.UUID] = None,
        project_id: Optional[uuid.UUID] = None,
        workflow_id: Optional[uuid.UUID] = None,
        task_id: Optional[uuid.UUID] = None,
        execution_id: Optional[uuid.UUID] = None,
        attempt_id: Optional[uuid.UUID] = None,
        worker_id: Optional[str] = None,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
        node_id: Optional[str] = None,
        artifact_id: Optional[uuid.UUID] = None,
        review_id: Optional[uuid.UUID] = None,
        approval_id: Optional[uuid.UUID] = None,
        error_category: Optional[str] = None,
        retryable: Optional[bool] = None,
        duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StructuredLogEntry:
        # Redact message and metadata
        redacted_message = self._redact_message(message)
        redacted_metadata = self._redact_dict(metadata or {})

        entry = StructuredLogEntry(
            timestamp=datetime.now(timezone.utc),
            severity=severity,
            component=component,
            message=redacted_message,
            correlation_id=correlation_id,
            project_id=project_id,
            workflow_id=workflow_id,
            task_id=task_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            model_id=model_id,
            provider_id=provider_id,
            deployment_id=deployment_id,
            node_id=node_id,
            artifact_id=artifact_id,
            review_id=review_id,
            approval_id=approval_id,
            error_category=error_category,
            retryable=retryable,
            duration_ms=duration_ms,
            metadata=redacted_metadata,
        )

        with self._lock:
            self._logs.append(entry)

        # Output structured log to console/stdout if needed (optional)
        # print(entry.model_dump_json(exclude_none=True))

        return entry

    def debug(self, component: str, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(Severity.DEBUG, component, message, **kwargs)

    def info(self, component: str, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(Severity.INFO, component, message, **kwargs)

    def warning(self, component: str, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(Severity.WARNING, component, message, **kwargs)

    def error(self, component: str, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(Severity.ERROR, component, message, **kwargs)

    def critical(self, component: str, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(Severity.CRITICAL, component, message, **kwargs)

    def get_logs(self, limit: int = 100, offset: int = 0) -> List[StructuredLogEntry]:
        with self._lock:
            return list(self._logs[offset : offset + limit])

    def clear(self) -> None:
        with self._lock:
            self._logs.clear()
            self._secrets.clear()
