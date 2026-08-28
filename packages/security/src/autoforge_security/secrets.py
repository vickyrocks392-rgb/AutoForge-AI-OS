"""
Centralized Secrets Management & Deep Redaction for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from autoforge_security.errors import SecretAccessError
from autoforge_security.models import SecretScope, Subject, SubjectType
from autoforge_security.permissions import Permissions


class SecretValue:
    """
    Secure wrapper around a sensitive string.
    __repr__ and __str__ are permanently redacted to prevent accidental leaks.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("SecretValue requires a non-empty string.")
        self._value = value

    @property
    def raw_value(self) -> str:
        """Access raw value only at outbound network / connector seams."""
        return self._value

    @property
    def value(self) -> str:
        """Alias for compatibility with connector SecretValue."""
        return self._value

    def __repr__(self) -> str:
        return "SecretValue(***)"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretValue):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)


class SecretsManager:
    """
    Centralized authority for registering, retrieving, and redacting sensitive values.
    """

    def __init__(self) -> None:
        self._secrets: dict[str, tuple[SecretValue, SecretScope]] = {}
        self._known_raw_secrets: set[str] = set()

    def register_secret(
        self,
        name: str,
        value: str | SecretValue,
        scope: SecretScope = SecretScope.SYSTEM,
    ) -> None:
        """Register a secret under a scoped identifier."""
        if not name:
            raise ValueError("Secret name cannot be empty.")

        sec_val = value if isinstance(value, SecretValue) else SecretValue(value)
        self._secrets[name] = (sec_val, scope)
        self._known_raw_secrets.add(sec_val.raw_value)

    def get_secret(
        self,
        name: str,
        subject: Subject,
        scope: SecretScope = SecretScope.SYSTEM,
    ) -> SecretValue:
        """
        Retrieve a secret if the subject is authorized for the given scope.
        """
        if name not in self._secrets:
            raise SecretAccessError(f"Secret '{name}' not found.")

        sec_val, sec_scope = self._secrets[name]

        # Scope enforcement
        if sec_scope != scope and scope != SecretScope.SYSTEM:
            raise SecretAccessError(f"Secret '{name}' scope '{sec_scope.value}' does not match requested scope '{scope.value}'.")

        # Worker access constraint: Workers can only access connector/project secrets, not system secrets
        if subject.subject_type == SubjectType.WORKER and sec_scope == SecretScope.SYSTEM:
            raise SecretAccessError(f"Worker '{subject.subject_id}' is forbidden from accessing SYSTEM-scoped secrets.")

        return sec_val

    def redact_text(self, text: str) -> str:
        """
        Redact all known secrets and high-entropy patterns from text.
        """
        if not isinstance(text, str) or not text:
            return text

        result = text
        for raw in self._known_raw_secrets:
            if raw and len(raw) >= 3:
                result = result.replace(raw, "***")

        # General regex redaction for common key formats
        # e.g. Bearer tokens, api keys like sk-..., afg_...
        result = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{12,}", r"\1***", result)
        result = re.sub(r"(afg_[A-Za-z0-9_\-]{16,})", r"***", result)
        result = re.sub(r"(sk-[A-Za-z0-9_\-]{20,})", r"***", result)
        return result

    def redact_structure(self, data: Any) -> Any:
        """
        Recursively redact sensitive data from nested dicts, lists, tuples, or primitives.
        """
        if isinstance(data, str):
            return self.redact_text(data)
        elif isinstance(data, SecretValue):
            return "***"
        elif isinstance(data, dict):
            redacted_dict: dict[str, Any] = {}
            for k, v in data.items():
                if any(s in k.lower() for s in ("secret", "token", "password", "key", "credential", "auth")):
                    redacted_dict[k] = "***"
                else:
                    redacted_dict[k] = self.redact_structure(v)
            return redacted_dict
        elif isinstance(data, list):
            return [self.redact_structure(item) for item in data]
        elif isinstance(data, tuple):
            return tuple(self.redact_structure(item) for item in data)
        elif isinstance(data, set):
            return {self.redact_structure(item) for item in data}
        return data
