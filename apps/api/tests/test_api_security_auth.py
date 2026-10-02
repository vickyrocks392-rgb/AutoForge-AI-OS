"""
Adversarial API authentication / authorization / IDOR tests (SHC-02).

These exercise the real HTTP request handler over a real socket, not helper
functions, so they prove the enforcement point is wired into the request path.

Authentication is ENABLED for this module (the package conftest disables it for
the legacy Phase 16 suite; these tests explicitly re-enable it).
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from autoforge_api.auth import (
    AUTH_DISABLED_ENV,
    ApiAuthError,
    ApiAuthenticator,
    auth_is_disabled,
)
from autoforge_api.server import _extract_project_id, create_server
from autoforge_api.service import AutoForgeApiService
from autoforge_security.engine import SecurityPlatform
from autoforge_security.models import Subject, SubjectType

API_KEY = "test-api-key-for-shc02"


@pytest.fixture(autouse=True)
def _auth_enabled(monkeypatch):
    """Enable authentication for every test in this module."""
    monkeypatch.delenv(AUTH_DISABLED_ENV, raising=False)
    monkeypatch.setenv("AUTOFORGE_API_KEY", API_KEY)
    yield


def _server(authenticator=None):
    service = AutoForgeApiService()
    auth = authenticator or ApiAuthenticator(security_platform=SecurityPlatform())
    server = create_server(host="127.0.0.1", port=0, service=service, authenticator=auth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _shutdown(server):
    server.shutdown()
    server.server_close()


def _request(port, path, *, token=None, method="GET", body=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _scoped_auth(projects):
    """Build an authenticator whose session token is scoped to `projects`."""
    platform = SecurityPlatform()
    subject = Subject(
        subject_id="scoped_operator",
        display_name="Scoped Operator",
        subject_type=SubjectType.SERVICE,
        roles=frozenset({"platform_admin"}),
        attributes={"allowed_projects": list(projects)},
    )
    # The subject must exist in the identity provider: session validation
    # re-resolves the subject by id, so an unregistered subject is rejected.
    platform.authentication.identity_provider.register_subject(subject)
    token, _session = platform.authentication._create_session(subject)
    return ApiAuthenticator(security_platform=platform, api_key=API_KEY), token


# ── Authentication ────────────────────────────────────────────────────────


def test_missing_auth_is_rejected():
    """No token on a sensitive endpoint -> 401."""
    server, _ = _server()
    try:
        status, _ = _request(server.server_address[1], "/api/projects")
        assert status == 401, f"expected 401, got {status}"
    finally:
        _shutdown(server)


def test_invalid_token_is_rejected():
    server, _ = _server()
    try:
        status, _ = _request(server.server_address[1], "/api/projects", token="totally-wrong-key")
        assert status == 401
    finally:
        _shutdown(server)


def test_valid_api_key_is_accepted():
    server, _ = _server()
    try:
        status, _ = _request(server.server_address[1], "/api/projects", token=API_KEY)
        assert status == 200, f"expected 200, got {status}"
    finally:
        _shutdown(server)


def test_read_only_status_path_is_public():
    """The public allowlist is limited to read-only liveness metadata."""
    server, _ = _server()
    try:
        status, _ = _request(server.server_address[1], "/api/system/status")
        assert status == 200
    finally:
        _shutdown(server)


def test_mutating_endpoint_requires_auth():
    server, _ = _server()
    try:
        status, _ = _request(
            server.server_address[1], "/api/projects", method="POST", body={"name": "x"}
        )
        assert status == 401
    finally:
        _shutdown(server)


def test_delete_endpoint_requires_auth():
    server, _ = _server()
    try:
        status, _ = _request(server.server_address[1], "/api/models/some-model", method="DELETE")
        assert status == 401
    finally:
        _shutdown(server)


# ── IDOR / project scoping ────────────────────────────────────────────────


def test_cross_project_read_is_denied():
    """A caller scoped to project A must not read project B (IDOR)."""
    auth, token = _scoped_auth(["proj-alpha"])
    server, _ = _server(authenticator=auth)
    try:
        status, body = _request(
            server.server_address[1], "/api/projects/proj-beta/output", token=token
        )
        assert status == 403, f"expected 403 for cross-project read, got {status}: {body[:200]}"
        assert "not authorized for project" in body
    finally:
        _shutdown(server)


def test_cross_project_write_is_denied():
    auth, token = _scoped_auth(["proj-alpha"])
    server, _ = _server(authenticator=auth)
    try:
        status, _ = _request(
            server.server_address[1], "/api/projects/proj-beta/stop", method="POST",
            body={}, token=token,
        )
        assert status == 403
    finally:
        _shutdown(server)


def test_authorized_project_is_allowed():
    auth, token = _scoped_auth(["proj-alpha"])
    server, _ = _server(authenticator=auth)
    try:
        status, _ = _request(
            server.server_address[1], "/api/projects/proj-alpha/output", token=token
        )
        assert status == 200, f"expected 200 for authorized project, got {status}"
    finally:
        _shutdown(server)


def test_cross_project_download_is_denied():
    """Artifact/export download is the highest-value IDOR target."""
    auth, token = _scoped_auth(["proj-alpha"])
    server, _ = _server(authenticator=auth)
    try:
        status, _ = _request(
            server.server_address[1], "/api/projects/proj-beta/download-source", token=token
        )
        assert status == 403
    finally:
        _shutdown(server)


def test_cross_project_run_is_denied():
    auth, token = _scoped_auth(["proj-alpha"])
    server, _ = _server(authenticator=auth)
    try:
        status, _ = _request(
            server.server_address[1], "/api/projects/proj-beta/run", method="POST",
            body={}, token=token,
        )
        assert status == 403
    finally:
        _shutdown(server)

# -- Project identity resolution -------------------------------------------


def test_project_id_extraction_handles_encoding():
    assert _extract_project_id("/api/projects/proj-1/output") == "proj-1"
    assert _extract_project_id("/api/projects/proj%2D1/run") == "proj-1"
    assert _extract_project_id("/api/projects") is None
    assert _extract_project_id("/api/models/m1") is None


# -- Fail-closed startup ----------------------------------------------------


def test_server_refuses_to_start_without_credentials(monkeypatch):
    """Auth enabled + no API key must fail closed, not serve unauthenticated."""
    monkeypatch.delenv(AUTH_DISABLED_ENV, raising=False)
    monkeypatch.delenv("AUTOFORGE_API_KEY", raising=False)
    with pytest.raises(ApiAuthError):
        ApiAuthenticator(security_platform=SecurityPlatform())


def test_auth_is_disabled_only_via_explicit_env(monkeypatch):
    monkeypatch.delenv(AUTH_DISABLED_ENV, raising=False)
    assert auth_is_disabled() is False
    monkeypatch.setenv(AUTH_DISABLED_ENV, "1")
    assert auth_is_disabled() is True


# -- Audit trail ------------------------------------------------------------


def test_auth_denial_is_audited():
    auth = ApiAuthenticator(security_platform=SecurityPlatform(), api_key=API_KEY)
    with pytest.raises(ApiAuthError):
        auth.authenticate({"Authorization": "Bearer wrong"})
    assert any(e["event"] == "api.auth.denied" for e in auth.audit_sink)


def test_project_denial_is_audited():
    auth, token = _scoped_auth(["proj-alpha"])
    caller = auth.authenticate({"Authorization": f"Bearer {token}"})
    with pytest.raises(ApiAuthError):
        auth.authorize_project(caller, "proj-beta")
    assert any(e["event"] == "api.authz.denied_project" for e in auth.audit_sink)

