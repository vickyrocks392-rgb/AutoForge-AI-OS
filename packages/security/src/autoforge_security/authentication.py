"""
Authentication boundary & session management for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from autoforge_security.errors import (
    AuthenticationError,
    IdentityNotFoundError,
    InvalidTokenError,
)
from autoforge_security.identity import IdentityProvider, LocalIdentityProvider, hash_secret_token
from autoforge_security.models import AuthenticationResult, Session, Subject, SubjectType


class AuthenticationService:
    """
    Centralized authentication manager.
    Handles session tokens, credential verification, and brute-force mitigation.
    """

    def __init__(
        self,
        identity_provider: IdentityProvider | None = None,
        default_session_ttl_seconds: int = 86400,  # 24 hours
        max_failed_attempts: int = 5,
        lockout_duration_seconds: int = 300,
    ) -> None:
        self._idp = identity_provider or LocalIdentityProvider()
        self._session_ttl = default_session_ttl_seconds
        self._max_failed_attempts = max_failed_attempts
        self._lockout_duration = lockout_duration_seconds

        self._active_sessions: dict[str, Session] = {}  # token_hash -> Session
        self._failed_attempts: dict[str, list[datetime]] = {}  # subject_id -> [timestamp]

    @property
    def identity_provider(self) -> IdentityProvider:
        return self._idp

    def _is_locked_out(self, subject_id: str) -> bool:
        now = datetime.now(timezone.utc)
        attempts = self._failed_attempts.get(subject_id, [])
        # filter within lockout window
        recent = [
            ts for ts in attempts
            if (now - ts).total_seconds() < self._lockout_duration
        ]
        self._failed_attempts[subject_id] = recent
        return len(recent) >= self._max_failed_attempts

    def _record_failure(self, subject_id: str) -> None:
        now = datetime.now(timezone.utc)
        if subject_id not in self._failed_attempts:
            self._failed_attempts[subject_id] = []
        self._failed_attempts[subject_id].append(now)

    def _record_success(self, subject_id: str) -> None:
        self._failed_attempts.pop(subject_id, None)

    def authenticate_password(self, subject_id: str, password: str) -> AuthenticationResult:
        """Authenticate a subject using password credentials."""
        if self._is_locked_out(subject_id):
            return AuthenticationResult(
                authenticated=False,
                error_message=f"Account '{subject_id}' temporarily locked due to excessive failed attempts.",
            )

        subject = self._idp.get_subject(subject_id)
        if not subject or not subject.is_active:
            self._record_failure(subject_id)
            return AuthenticationResult(
                authenticated=False,
                error_message="Invalid credentials or inactive account.",
            )

        if isinstance(self._idp, LocalIdentityProvider):
            if not self._idp.verify_password(subject_id, password):
                self._record_failure(subject_id)
                return AuthenticationResult(
                    authenticated=False,
                    error_message="Invalid credentials.",
                )

        self._record_success(subject_id)
        token, session = self._create_session(subject)
        return AuthenticationResult(
            authenticated=True,
            subject=subject,
            token=token,
            metadata={"session_id": session.session_id},
        )

    def authenticate_api_key(self, api_key: str) -> AuthenticationResult:
        """Authenticate using an API key."""
        if not api_key or not isinstance(api_key, str):
            return AuthenticationResult(
                authenticated=False,
                error_message="API key must be a non-empty string.",
            )

        subject = self._idp.authenticate_api_key(api_key)
        if not subject or not subject.is_active:
            return AuthenticationResult(
                authenticated=False,
                error_message="Invalid API key or inactive account.",
            )

        token, session = self._create_session(subject)
        return AuthenticationResult(
            authenticated=True,
            subject=subject,
            token=token,
            metadata={"session_id": session.session_id},
        )

    def authenticate_token(self, token: str) -> AuthenticationResult:
        """Verify an existing session token."""
        if not token:
            return AuthenticationResult(
                authenticated=False,
                error_message="Token cannot be empty.",
            )

        token_hash = hash_secret_token(token)
        session = self._active_sessions.get(token_hash)
        if not session:
            return AuthenticationResult(
                authenticated=False,
                error_message="Invalid or unknown session token.",
            )

        if session.is_revoked:
            return AuthenticationResult(
                authenticated=False,
                error_message="Session token has been revoked.",
            )

        if session.is_expired:
            self._active_sessions.pop(token_hash, None)
            return AuthenticationResult(
                authenticated=False,
                error_message="Session token has expired.",
            )

        subject = self._idp.get_subject(session.subject_id)
        if not subject or not subject.is_active:
            return AuthenticationResult(
                authenticated=False,
                error_message="Subject is inactive or no longer exists.",
            )

        return AuthenticationResult(
            authenticated=True,
            subject=subject,
            token=token,
            metadata={"session_id": session.session_id},
        )

    def _create_session(self, subject: Subject) -> tuple[str, Session]:
        raw_token = f"afs_{secrets.token_urlsafe(32)}"
        token_hash = hash_secret_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._session_ttl)

        session = Session(
            session_id=f"sess_{secrets.token_hex(8)}",
            subject_id=subject.subject_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=expires_at,
        )
        self._active_sessions[token_hash] = session
        return raw_token, session

    def revoke_session(self, token: str) -> bool:
        """Revoke an active session token."""
        token_hash = hash_secret_token(token)
        if token_hash in self._active_sessions:
            session = self._active_sessions[token_hash]
            # Replace with revoked state
            revoked = Session(
                session_id=session.session_id,
                subject_id=session.subject_id,
                token_hash=session.token_hash,
                created_at=session.created_at,
                expires_at=session.expires_at,
                is_revoked=True,
                metadata=session.metadata,
            )
            self._active_sessions[token_hash] = revoked
            return True
        return False

    def revoke_all_for_subject(self, subject_id: str) -> int:
        """Revoke all active sessions for a subject."""
        count = 0
        for th, s in list(self._active_sessions.items()):
            if s.subject_id == subject_id and not s.is_revoked:
                self.revoke_session_by_hash(th)
                count += 1
        return count

    def revoke_session_by_hash(self, token_hash: str) -> bool:
        if token_hash in self._active_sessions:
            session = self._active_sessions[token_hash]
            self._active_sessions[token_hash] = Session(
                session_id=session.session_id,
                subject_id=session.subject_id,
                token_hash=session.token_hash,
                created_at=session.created_at,
                expires_at=session.expires_at,
                is_revoked=True,
                metadata=session.metadata,
            )
            return True
        return False
