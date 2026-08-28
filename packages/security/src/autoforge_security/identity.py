"""
Identity provider and Subject management for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import abc
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any

from autoforge_security.errors import IdentityNotFoundError
from autoforge_security.models import Subject, SubjectType
from autoforge_security.roles import Roles


def hash_secret_token(token: str) -> str:
    """Deterministic cryptographic hash for authentication tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class IdentityProvider(abc.ABC):
    """Abstract identity management boundary."""

    @abc.abstractmethod
    def get_subject(self, subject_id: str) -> Subject | None:
        """Retrieve subject by ID."""
        ...

    @abc.abstractmethod
    def authenticate_api_key(self, api_key: str) -> Subject | None:
        """Authenticate by API key."""
        ...


class LocalIdentityProvider(IdentityProvider):
    """
    Local-first, in-memory/embedded identity provider.
    Maintains subjects, API keys, and service identities.
    """

    def __init__(self) -> None:
        self._subjects: dict[str, Subject] = {}
        self._api_key_hashes: dict[str, str] = {}  # key_hash -> subject_id
        self._subject_passwords: dict[str, str] = {}  # subject_id -> password_hash

        # Initialize default system admin and default observer
        self._init_defaults()

    def _init_defaults(self) -> None:
        # Default local root administrator
        admin = Subject(
            subject_id="subject_admin_root",
            display_name="AutoForge Root Administrator",
            subject_type=SubjectType.HUMAN,
            roles=frozenset({Roles.ADMINISTRATOR}),
            attributes={"email": "admin@autoforge.local", "is_root": True},
        )
        self.register_subject(admin)

        # Default system service
        system_svc = Subject(
            subject_id="subject_system_service",
            display_name="AutoForge System Service",
            subject_type=SubjectType.SERVICE,
            roles=frozenset({Roles.ADMINISTRATOR}),
            attributes={"service": "system"},
        )
        self.register_subject(system_svc)

        # Default read-only anonymous observer
        anon = Subject(
            subject_id="subject_anonymous",
            display_name="Anonymous Observer",
            subject_type=SubjectType.ANONYMOUS,
            roles=frozenset({Roles.READ_ONLY_OBSERVER}),
            attributes={},
        )
        self.register_subject(anon)

    def register_subject(self, subject: Subject, password: str | None = None) -> Subject:
        """Register a new subject in the local store."""
        self._subjects[subject.subject_id] = subject
        if password:
            self._subject_passwords[subject.subject_id] = hash_secret_token(password)
        return subject

    def create_human_user(
        self,
        username: str,
        display_name: str,
        roles: set[str] | frozenset[str],
        password: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Subject:
        """Create and register a human user."""
        subject_id = f"user_{username}"
        subject = Subject(
            subject_id=subject_id,
            display_name=display_name,
            subject_type=SubjectType.HUMAN,
            roles=frozenset(roles),
            attributes=attributes or {},
        )
        return self.register_subject(subject, password=password)

    def create_worker_identity(
        self,
        worker_id: str,
        worker_type: str,
        roles: set[str] | frozenset[str],
        attributes: dict[str, Any] | None = None,
    ) -> Subject:
        """Create an identity for an autonomous workforce worker."""
        subject_id = f"worker_{worker_id}"
        attrs = attributes or {}
        attrs["worker_type"] = worker_type
        subject = Subject(
            subject_id=subject_id,
            display_name=f"Worker-{worker_type}-{worker_id}",
            subject_type=SubjectType.WORKER,
            roles=frozenset(roles),
            attributes=attrs,
        )
        return self.register_subject(subject)

    def issue_api_key(self, subject_id: str) -> str:
        """Generate and associate a secure API key with a subject."""
        if subject_id not in self._subjects:
            raise IdentityNotFoundError(f"Subject '{subject_id}' not found")

        raw_key = f"afg_{secrets.token_urlsafe(32)}"
        key_hash = hash_secret_token(raw_key)
        self._api_key_hashes[key_hash] = subject_id
        return raw_key

    def verify_password(self, subject_id: str, password: str) -> bool:
        """Verify password for a subject."""
        stored_hash = self._subject_passwords.get(subject_id)
        if not stored_hash:
            return False
        return hmac.compare_digest(stored_hash, hash_secret_token(password))

    def get_subject(self, subject_id: str) -> Subject | None:
        """Retrieve subject by ID."""
        return self._subjects.get(subject_id)

    def authenticate_api_key(self, api_key: str) -> Subject | None:
        """Authenticate by API key."""
        key_hash = hash_secret_token(api_key)
        subject_id = self._api_key_hashes.get(key_hash)
        if not subject_id:
            return None
        return self.get_subject(subject_id)

    def list_subjects(self) -> list[Subject]:
        """List all registered subjects."""
        return list(self._subjects.values())
