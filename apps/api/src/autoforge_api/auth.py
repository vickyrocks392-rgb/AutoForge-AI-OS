"""
Canonical API authentication and authorization boundary.

Design constraints (GATE 2)
---------------------------
* **No second authentication framework.** This module *delegates* to the certified
  ``SecurityPlatform``: subjects, tokens, API keys, RBAC and project scoping all
  come from ``autoforge_security``.
* **No silent anonymous privilege.** An unauthenticated caller is anonymous and
  holds only read-only public permissions. Sensitive endpoints are refused.
* **No unconditional bypass.** Local development and the existing test-suite opt
  in *explicitly* via ``AUTOFORGE_API_AUTH_DISABLED=1``. The default is
  authentication required.
* **IDOR resistance.** Authorization runs *after* the requested resource identity
  is resolved and *before* the resource is returned or mutated.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Any, Mapping

from autoforge_security.errors import (
    AuthenticationError,
    IdentityNotFoundError,
    InvalidTokenError,
)
from autoforge_security.models import Subject, SubjectType

#: Environment flag that explicitly disables API authentication. Intended only
#: for local development and automated tests. Never set this in production.
AUTH_DISABLED_ENV = "AUTOFORGE_API_AUTH_DISABLED"

#: Environment variable holding a static API key for machine callers.
API_KEY_ENV = "AUTOFORGE_API_KEY"


class ApiAuthError(Exception):
    """Raised when a request fails authentication or authorization."""

    def __init__(self, message: str, status: int = 401, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details or {}


@dataclass
class AuthenticatedCaller:
    """The resolved identity for an authenticated API request."""

    subject: Subject
    method: str = "api_key"
    is_dev_bypass: bool = False

    @property
    def subject_id(self) -> str:
        return self.subject.subject_id

    def authorized_projects(self) -> frozenset[str] | None:
        """Authorized project set, or ``None`` when unrestricted."""
        raw = self.subject.attributes.get("allowed_projects")
        if raw is None:
            return None
        return frozenset(str(p) for p in raw)


def auth_is_disabled() -> bool:
    """True only when the explicit dev/test opt-out is set."""
    return os.environ.get(AUTH_DISABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ApiAuthenticator:
    """Authenticates API callers using the certified Security Platform."""

    security_platform: Any
    api_key: str | None = None
    default_allowed_projects: tuple[str, ...] | None = None
    audit_sink: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.api_key is None:
            env_key = os.environ.get(API_KEY_ENV)
            if env_key:
                self.api_key = env_key.strip()
        if self.api_key is None and not auth_is_disabled():
            raise ApiAuthError(
                "API authentication is enabled but no API key is configured. Set "
                f"{API_KEY_ENV} to a secret value, or set {AUTH_DISABLED_ENV}=1 "
                "for local development.",
                status=500,
            )

    # ── Authentication ───────────────────────────────────────────────────

    def authenticate(self, headers: Mapping[str, str] | None) -> AuthenticatedCaller:
        """Resolve the caller identity from request headers."""
        if auth_is_disabled():
            caller = self._subject_for(self._dev_subject(), method="dev_bypass", is_dev_bypass=True)
            self._audit("api.auth.dev_bypass", caller.subject, "explicit dev bypass")
            return caller

        if not headers:
            raise ApiAuthError("Authentication required: missing Authorization header.")

        header_value = ""
        for name in ("Authorization", "authorization"):
            if headers.get(name):
                header_value = headers[name]
                break
        if not header_value:
            raise ApiAuthError("Authentication required: missing Authorization header.")

        if not header_value.lower().startswith("bearer "):
            raise ApiAuthError("Unsupported authentication scheme; expected 'Bearer <token>'.")

        token = header_value[7:].strip()
        if not token:
            raise ApiAuthError("Empty bearer token.")

        if self.api_key and secrets.compare_digest(token, self.api_key):
            caller = self._subject_for(self._api_key_subject(), method="api_key")
            self._audit("api.auth.ok", caller.subject, "static API key")
            return caller

        subject = self._subject_from_token(token)
        if subject is not None:
            caller = self._subject_for(subject, method="session_token")
            self._audit("api.auth.ok", caller.subject, "session token")
            return caller

        self._audit("api.auth.denied", None, "invalid or unknown token")
        raise ApiAuthError("Invalid or expired credentials.")

    # ── Authorization ───────────────────────────────────────────────────

    def authorize_project(self, caller: AuthenticatedCaller, project_id: str | None) -> None:
        """Enforce project scoping before returning or mutating a resource.

        Runs after the requested identity is resolved and before any access.
        """
        if caller.is_dev_bypass or not project_id:
            return

        allowed = caller.authorized_projects()
        if allowed is None and self.default_allowed_projects is not None:
            allowed = frozenset(self.default_allowed_projects)
        if allowed is None:
            return

        if project_id not in allowed:
            self._audit(
                "api.authz.denied_project", caller.subject, f"project '{project_id}' not authorized"
            )
            raise ApiAuthError(
                f"Caller is not authorized for project '{project_id}'.", status=403
            )

    def authorize_permission(self, caller: AuthenticatedCaller, permission: str) -> None:
        """Enforce an RBAC permission through the certified authorization engine."""
        if caller.is_dev_bypass:
            return
        decision = self.security_platform.authorize(
            action=permission, resource="api", subject=caller.subject
        )
        if not decision.is_allowed:
            self._audit("api.authz.denied_permission", caller.subject, permission)
            raise ApiAuthError(
                f"Caller lacks required permission '{permission}': {decision.reason}", status=403
            )

    # ── Internals ───────────────────────────────────────────────────────

    def _subject_for(
        self, subject: Subject, *, method: str, is_dev_bypass: bool = False
    ) -> AuthenticatedCaller:
        if self.default_allowed_projects is not None and "allowed_projects" not in subject.attributes:
            subject = subject.model_copy(
                update={
                    "attributes": {
                        **subject.attributes,
                        "allowed_projects": list(self.default_allowed_projects),
                    }
                }
            )
        return AuthenticatedCaller(subject=subject, method=method, is_dev_bypass=is_dev_bypass)

    def _dev_subject(self) -> Subject:
        """Operator identity used only under the explicit dev bypass."""
        return Subject(
            subject_id="local_dev_operator",
            display_name="Local Development Operator",
            subject_type=SubjectType.HUMAN,
            roles=frozenset({"platform_admin"}),
            attributes={"is_root": True, "dev_bypass": True},
        )

    def _api_key_subject(self) -> Subject:
        return Subject(
            subject_id="api_key_operator",
            display_name="API Key Operator",
            subject_type=SubjectType.SERVICE,
            roles=frozenset({"platform_admin"}),
            attributes={"auth_method": "api_key"},
        )

    def _subject_from_token(self, token: str) -> Subject | None:
        """Resolve a certified session token to a subject, or ``None``."""
        try:
            result = self.security_platform.authentication.authenticate_token(token)
        except (InvalidTokenError, AuthenticationError, IdentityNotFoundError, KeyError, TypeError, AttributeError):
            return None
        except Exception:
            return None
        if not getattr(result, "authenticated", False):
            return None
        return getattr(result, "subject", None)

    def _audit(self, event: str, subject: Subject | None, reason: str) -> None:
        self.audit_sink.append(
            {
                "event": event,
                "subject_id": subject.subject_id if subject else None,
                "subject_type": subject.subject_type.value if subject else None,
                "reason": reason,
            }
        )


