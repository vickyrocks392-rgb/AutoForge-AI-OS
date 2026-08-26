"""GitHub connector tests — offline through the injected transport seam.

No test in this module touches the network: the transport boundary is the
architectural seam under validation, exercised with a deterministic fake
that records every request. Credential isolation and error classification
are asserted exhaustively.
"""

from __future__ import annotations

import base64
import json as jsonlib
from typing import Any

import pytest

from autoforge_connectors.errors import (
    ConnectorAuthenticationError,
    ConnectorAuthorizationError,
    ConnectorConflictError,
    ConnectorNotFoundError,
    ConnectorOperationFailedError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorTransportError,
    ConnectorUnavailableError,
    ConnectorValidationError,
)
from autoforge_connectors.events import ConnectorEvents
from autoforge_connectors.github import (
    GitHubConnector,
    GitHubResponse,
    UrllibGitHubTransport,
)
from autoforge_connectors.security import SecretValue

from tests.helpers import RecordingEventSink


class FakeTransport:
    """Deterministic in-memory :class:`GitHubTransport`.

    Requests are recorded as dicts; responses are taken from a script list.
    An optional ``inspect`` hook receives each call for cross-cutting checks.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.script: list[GitHubResponse | Exception] = []

    def queue(self, status_code: int, payload: Any, headers: dict[str, str] | None = None):
        body = jsonlib.dumps(payload).encode("utf-8")
        self.script.append(
            GitHubResponse(
                status_code=status_code,
                headers=headers or {},
                body=body,
            )
        )

    def request(self, *, method, url_path, headers, query, json_body, timeout_seconds):
        if not self.script:
            raise AssertionError("unexpected extra transport call")
        item = self.script.pop(0)
        record = {
            "method": method,
            "url_path": url_path,
            "headers": dict(headers),
            "query": query,
            "json_body": json_body,
            "timeout_seconds": timeout_seconds,
        }
        self.calls.append(record)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def last_call(self):
        return self.calls[-1] if self.calls else None


@pytest.fixture()
def repo_payload() -> dict[str, Any]:
    return {
        "id": 5071,
        "owner": {"login": "autoforge-owner"},
        "name": "demo-repo",
        "full_name": "autoforge-owner/demo-repo",
        "default_branch": "main",
        "private": False,
        "html_url": "https://github.example/autoforge-owner/demo-repo",
        "description": "demo",
    }


TOKEN = "ghs_testtoken0123456789abcdefABCDEF"


def _connector(transport, token=None, events=None) -> GitHubConnector:
    return GitHubConnector(
        transport=transport,
        token=SecretValue(token) if token else None,
        events=events,
    )


# ---------------------------------------------------------------------------
# Repository metadata
# ---------------------------------------------------------------------------


def test_get_repository_parses_metadata(repo_payload):
    fake = FakeTransport()
    fake.queue(200, repo_payload)
    connector = _connector(fake, token=TOKEN)
    summary = connector.get_repository("autoforge-owner", "demo-repo")
    assert summary.id == 5071
    assert summary.default_branch == "main"
    assert summary.private is False
    call = fake.last_call
    assert call["method"] == "GET"
    assert call["url_path"] == "/repos/autoforge-owner/demo-repo"
    assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_unauthenticated_connector_sends_no_auth_header(repo_payload):
    fake = FakeTransport()
    fake.queue(200, repo_payload)
    connector = _connector(fake)
    connector.get_repository("autoforge-owner", "demo-repo")
    assert "Authorization" not in fake.last_call["headers"]


def test_get_contents_single_file_decodes_text():
    fake = FakeTransport()
    encoded = base64.b64encode(b"# readme\n").decode("ascii")
    fake.queue(
        200,
        {
            "name": "README.md",
            "path": "README.md",
            "type": "file",
            "sha": "abc123",
            "size": 9,
            "content": f"{encoded}\n" if False else encoded,
            "download_url": "https://raw.example/README.md",
        },
    )
    item = _connector(fake).get_contents("owner", "repo", "README.md")
    assert item.text == "# readme\n"
    assert (item.name, item.kind) == ("README.md", "file")


def test_get_contents_directory_returns_listing():
    fake = FakeTransport()
    fake.queue(
        200,
        [
            {"name": "src", "path": "src", "type": "dir", "sha": "d1", "size": 0},
            {"name": "main.py", "path": "main.py", "type": "file", "sha": "f1", "size": 10},
        ],
    )
    listing = _connector(fake).get_contents("owner", "repo")
    assert [i.path for i in listing] == ["src", "main.py"]
    assert listing[1].text is None  # listings carry no bodies


def test_put_contents_encodes_body_and_returns_commit_sha():
    fake = FakeTransport()
    fake.queue(
        201,
        {"commit": {"sha": "cafe1234"}, "content": {"sha": "blob123"}},
    )
    sha = _connector(fake, TOKEN).put_contents(
        "owner",
        "repo",
        path="src/new.py",
        message="add new module",
        content="print('hi')\n",
        branch="feature/x",
    )
    assert sha == "cafe1234"
    body = fake.last_call["json_body"]
    decoded = base64.b64decode(body["content"]).decode("utf-8")
    assert decoded == "print('hi')\n"
    assert body["message"] == "add new module"
    assert body["branch"] == "feature/x"
    assert fake.last_call["url_path"] == "/repos/owner/repo/contents/src/new.py"


def test_branch_creation_fetches_head_then_posts_ref(repo_payload):
    fake = FakeTransport()
    fake.queue(200, repo_payload)  # default branch lookup
    fake.queue(200, {"ref": "refs/heads/main", "object": {"sha": "head000"}})
    fake.queue(
        201,
        {"ref": "refs/heads/autoforge/task-1", "object": {"sha": "newsha99"}},
    )
    ref = _connector(fake, TOKEN).create_branch(
        "owner", "repo", name="autoforge/task-1"
    )
    assert ref.ref == "refs/heads/autoforge/task-1"
    assert ref.sha == "newsha99"
    methods = [(c["method"], c["url_path"]) for c in fake.calls]
    assert methods[0] == ("GET", "/repos/owner/repo")
    assert methods[1][0] == "GET" and "git/ref/heads/main" in methods[1][1]
    assert methods[2] == (
        "POST",
        "/repos/owner/repo/git/refs",
    )
    assert fake.calls[2]["json_body"]["ref"] == "refs/heads/autoforge/task-1"


def test_pull_request_lifecycle(repo_payload):
    fake = FakeTransport()
    pr_payload = {
        "number": 7,
        "title": "Implement feature",
        "state": "open",
        "draft": False,
        "head": {"ref": "autoforge/task-1"},
        "base": {"ref": "main"},
        "html_url": "https://github.example/o/r/pull/7",
    }
    fake.queue(201, pr_payload)
    fake.queue(200, pr_payload)
    fake.queue(200, {"merged": True, "sha": "merged888"})
    connector = _connector(fake, TOKEN)
    created = connector.create_pull_request(
        "owner", "repo", title="Implement feature", head="autoforge/task-1", base="main"
    )
    fetched = connector.get_pull_request("owner", "repo", 7)
    merge_sha = connector.merge_pull_request("owner", "repo", 7, method="squash")
    assert created.head_ref == "autoforge/task-1"
    assert fetched.number == 7
    assert merge_sha == "merged888"
    assert fake.calls[-1]["method"] == "PUT"


def test_create_issue_validates_title():
    fake = FakeTransport()
    with pytest.raises(ConnectorValidationError):
        _connector(fake).create_issue("owner", "repo", title="   ")
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Error classification matrix
# ---------------------------------------------------------------------------


def test_401_maps_to_authentication_error():
    fake = FakeTransport()
    fake.queue(401, {"message": "Bad credentials"})
    with pytest.raises(ConnectorAuthenticationError) as excinfo:
        _connector(fake, TOKEN).get_repository("owner", "repo")
    assert excinfo.value.details["status_code"] == 401


def test_403_rate_limit_maps_to_rate_limit_error():
    fake = FakeTransport()
    fake.queue(
        403,
        {"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0"},
    )
    with pytest.raises(ConnectorRateLimitError):
        _connector(fake).get_repository("owner", "repo")


def test_403_plain_maps_to_authorization_error():
    fake = FakeTransport()
    fake.queue(403, {"message": "Resource not accessible by integration"})
    with pytest.raises(ConnectorAuthorizationError):
        _connector(fake, TOKEN).get_repository("owner", "repo")


def test_404_maps_to_not_found():
    fake = FakeTransport()
    fake.queue(404, {"message": "Not Found"})
    with pytest.raises(ConnectorNotFoundError):
        _connector(fake).get_contents("owner", "repo", "ghost.txt")


def test_409_and_422_mappings():
    conflict = FakeTransport()
    conflict.queue(409, {"message": "Merge conflict"})
    with pytest.raises(ConnectorConflictError):
        _connector(conflict).merge_pull_request("o", "r", 1)

    validation = FakeTransport()
    validation.queue(
        422,
        {
            "message": "Validation Failed",
            "errors": [{"message": "No commits between main and feature"}],
        },
    )
    with pytest.raises(ConnectorValidationError) as excinfo:
        _connector(validation).create_pull_request(
            "o", "r", title="t", head="feature", base="main"
        )
    assert excinfo.value.details["api_errors"] == [
        "No commits between main and feature"
    ]


def test_5xx_maps_to_unavailable():
    fake = FakeTransport()
    fake.queue(503, {"message": "Service unavailable"})
    with pytest.raises(ConnectorUnavailableError):
        _connector(fake).get_repository("owner", "repo")


def test_unexpected_status_maps_to_operation_failed():
    fake = FakeTransport()
    fake.queue(418, {"message": "teapot"})
    with pytest.raises(ConnectorOperationFailedError):
        _connector(fake).get_repository("owner", "repo")


@pytest.mark.parametrize(
    "transport_error",
    [ConnectorTimeoutError("socket slow"), ConnectorTransportError("dns down")],
)
def test_transport_faults_propagate_as_classified(transport_error):
    fake = FakeTransport()
    fake.script.append(transport_error)
    connector = _connector(fake)
    with pytest.raises(type(transport_error)):
        connector.get_repository("owner", "repo")


# ---------------------------------------------------------------------------
# Credential isolation
# ---------------------------------------------------------------------------


def test_token_never_appears_in_errors_or_details(repo_payload):
    fake = FakeTransport()
    fake.queue(401, {"message": f"Bad credentials for token {TOKEN}"})
    connector = _connector(fake, TOKEN)
    with pytest.raises(ConnectorAuthenticationError) as excinfo:
        connector.get_repository("owner", "repo")
    rendered = [
        str(excinfo.value),
        repr(excinfo.value),
        jsonlib.dumps(excinfo.value.summary, default=str),
        jsonlib.dumps(excinfo.value.details, default=str),
    ]
    assert all(TOKEN not in chunk for chunk in rendered), rendered
    # The sanitised API message is preserved minus the secret.
    assert "Bad credentials for token ***" in excinfo.value.details["api_message"]


def test_secret_value_redacts_every_conversion():
    secret = SecretValue(TOKEN)
    assert TOKEN not in repr(secret) and TOKEN not in str(secret)


def test_connector_rejects_raw_string_tokens():
    fake = FakeTransport()
    with pytest.raises(ConnectorValidationError):
        GitHubConnector(transport=fake, token=TOKEN)  # type: ignore[arg-type]


def test_invalid_owner_repo_rejected_without_calls():
    fake = FakeTransport()
    connector = _connector(fake)
    for owner in ("", "../evil", "bad space"):
        with pytest.raises(ConnectorValidationError):
            connector.get_repository(owner, "repo")
    for repo_name in ("", "../etc/passwd"):
        with pytest.raises(ConnectorValidationError):
            connector.get_repository("owner", repo_name)
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------


def test_failed_operations_emit_canonical_events():
    sink = RecordingEventSink()
    fake = FakeTransport()
    fake.queue(500, {"message": "down"})
    connector = _connector(fake, events=ConnectorEvents(sink=sink))
    with pytest.raises(ConnectorUnavailableError):
        connector.get_repository("owner", "repo")
    failed = [e for e in sink.events if e.event_type.value == "failure.detected"]
    assert len(failed) == 1
    meta = failed[0].metadata
    assert meta["component"] == "connectors"
    assert meta["connector"] == "github"
    assert meta["error_category"] == "connector.unavailable"


def test_successful_operations_record_observation_but_no_events(repo_payload):
    sink = RecordingEventSink()
    fake = FakeTransport()
    fake.queue(200, repo_payload)
    connector = _connector(fake, events=ConnectorEvents(sink=sink))
    connector.get_repository("owner", "repo")
    assert connector.last_operation.status == "ok"
    assert connector.last_operation.operation == "get_repository"
    assert sink.events == []


def test_urllib_transport_is_the_shipped_default_surface():
    transport = UrllibGitHubTransport()
    assert transport.base_url == "https://api.github.com"
