"""GitHub connector — repository operations behind a replaceable transport.

Architectural boundary (Phase 8 authorization §GitHub):

- **Credential isolation** — the token lives inside a
  :class:`~autoforge_connectors.security.SecretValue`; it becomes an
  ``Authorization`` header at exactly one place (request construction) and is
  redacted in every string conversion, error message and detail payload.
  Transports MUST NOT log headers or bodies.
- **Replaceable transport** — connectors depend on the structural
  :class:`GitHubTransport` port, never on a concrete HTTP library. The
  stdlib default (:class:`UrllibGitHubTransport`) exists for composition
  wiring; fakes satisfy tests offline.
- **Error normalisation** — status codes / network faults map onto the
  connector taxonomy (401→authn, 403→rate-limit-or-authz, 404→not found,
  409/422→conflict/validation, 5xx→unavailable, socket faults→transport).

Supported scope: repository metadata, contents read/write, branch creation,
pull requests, issues. Pagination is NOT yet implemented (first page only);
recorded in ADR-007 limitations.
"""

from __future__ import annotations

import base64
import json as jsonlib
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

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
from autoforge_connectors.instrumentation import observe_connector_operation
from autoforge_connectors.security import SecretValue, redact
from autoforge_connectors.validation import (
    validate_github_owner,
    validate_github_repo,
    validate_http_path,
    validate_ref_name,
)


@dataclass(frozen=True)
class RepoSummary:
    """Core metadata of a GitHub repository."""

    id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool
    html_url: str
    description: str | None


@dataclass(frozen=True)
class ContentItem:
    """One entry of repository contents."""

    name: str
    path: str
    kind: str  # "file" | "dir"
    sha: str
    size_bytes: int
    download_url: str | None
    text: str | None  # decoded text when fetched as a small single file


@dataclass(frozen=True)
class GitRef:
    """A resolved git reference on the remote."""

    ref: str  # e.g. "refs/heads/main"
    sha: str


@dataclass(frozen=True)
class PullRequestInfo:
    """Core pull-request fields."""

    number: int
    title: str
    state: str
    draft: bool
    head_ref: str
    base_ref: str
    html_url: str


@dataclass(frozen=True)
class IssueInfo:
    """Core issue fields."""

    number: int
    title: str
    state: str
    body: str | None
    html_url: str


@dataclass
class GitHubResponse:
    """Raw transport response handed back to the connector layer."""

    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return jsonlib.loads(self.body.decode("utf-8") if self.body else "null")

    def header(self, name: str) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return None


class GitHubTransport:
    """Structural port: one HTTP request against a GitHub deployment.

    Implementations MUST NOT log headers (credentials travel there) and MUST
    NOT retry — retry policy belongs to later resilience layers wrapping the
    connector platform, never inside individual transports.
    """

    def request(
        self,
        *,
        method: str,
        url_path: str,
        headers: dict[str, str],
        query: dict[str, str] | None,
        json_body: Any | None,
        timeout_seconds: float,
    ) -> GitHubResponse:  # pragma: no cover - interface only
        raise NotImplementedError


class UrllibGitHubTransport(GitHubTransport):
    """Stdlib-``urllib`` transport used by the composition root by default."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.github.com",
        user_agent: str = "autoforge-connectors",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent

    @property
    def base_url(self) -> str:
        return self._base_url

    def request(
        self,
        *,
        method: str,
        url_path: str,
        headers: dict[str, str],
        query: dict[str, str] | None,
        json_body: Any | None,
        timeout_seconds: float,
    ) -> GitHubResponse:
        validate_http_path(url_path)
        url = f"{self._base_url}{url_path}"
        if query:
            pairs = "&".join(
                f"{urllib.request.quote(str(k), safe='')}="
                f"{urllib.request.quote(str(v), safe='')}"
                for k, v in query.items()
            )
            url = f"{url}?{pairs}"
        payload = None
        request_headers = {"Accept": "application/vnd.github+json"}
        request_headers.update(headers)
        if json_body is not None:
            payload = jsonlib.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=payload, method=method)
        for key, value in request_headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:
                return GitHubResponse(
                    status_code=resp.status,
                    headers={k: v for k, v in resp.headers.items()},
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:  # non-2xx is still a response
            return GitHubResponse(
                status_code=exc.code,
                headers={k: v for k, v in exc.headers.items()},
                body=exc.read(),
            )
        except socket.timeout as exc:
            raise ConnectorTimeoutError(
                "github request exceeded its time budget"
            ) from exc
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            if "timed out" in reason.lower():
                raise ConnectorTimeoutError(
                    "github request exceeded its time budget"
                ) from exc
            raise ConnectorTransportError(
                "github transport failure",
                details={"reason": reason[:200]},
            ) from exc


class GitHubConnector:
    """GitHub operations bound to one optional credential set."""

    def __init__(
        self,
        *,
        transport: GitHubTransport,
        token: SecretValue | None = None,
        default_timeout_seconds: float = 30.0,
        events: ConnectorEvents | None = None,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ConnectorValidationError("default_timeout_seconds must be positive")
        if token is not None and not isinstance(token, SecretValue):
            # Never accept raw strings: credentials must stay redactable.
            raise ConnectorValidationError(
                "token must be a security.SecretValue instance"
            )
        self._transport = transport
        self._token = token
        self._timeout = float(default_timeout_seconds)
        self._events = events
        #: Most recent OperationObservation on this connector.
        self.last_operation: Any = None

    @property
    def connector_name(self) -> str:
        return "github"

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    # ------------------------------------------------------------------
    # Request core
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url_path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> GitHubResponse:
        validate_http_path(url_path)
        headers: dict[str, str] = {
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "autoforge-connectors",
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token.value}"
        response = self._transport.request(
            method=method,
            url_path=url_path,
            headers=headers,
            query=query,
            json_body=json_body,
            timeout_seconds=self._timeout,
        )
        if response.status_code < 200 or response.status_code > 299:
            self._raise_for_status(response, method=method, url_path=url_path)
        return response

    def _raise_for_status(
        self, response: GitHubResponse, *, method: str, url_path: str
    ) -> None:
        status = response.status_code
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - body shape is untrusted
            payload = {}
        api_message = ""
        if isinstance(payload, dict):
            api_message = str(payload.get("message", ""))
        secrets = (self._token,) if self._token is not None else ()
        api_message = redact(api_message, secrets)
        detail: dict[str, Any] = {
            "status_code": status,
            "method": method,
            "url_path": redact(url_path, secrets),
        }
        if api_message:
            detail["api_message"] = api_message[:300]
        remaining = response.header("x-ratelimit-remaining")
        if status == 401:
            raise ConnectorAuthenticationError(
                "GitHub rejected the credentials", details=detail
            )
        if status == 403:
            if remaining == "0" or "rate limit" in api_message.lower():
                raise ConnectorRateLimitError(
                    "GitHub rate limit exhausted", details=detail
                )
            raise ConnectorAuthorizationError(
                "GitHub denied permission for this operation",
                details=detail,
            )
        if status == 404:
            raise ConnectorNotFoundError(
                "GitHub resource not found", details=detail
            )
        if status == 409:
            raise ConnectorConflictError(
                "GitHub conflict on target resource", details=detail
            )
        if status == 422:
            message = "GitHub rejected the request payload"
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if errors:
                detail["api_errors"] = [
                    e.get("message", "")[:120]
                    for e in errors
                    if isinstance(e, dict)
                ]
            raise ConnectorValidationError(message, details=detail)
        if 500 <= status <= 599:
            raise ConnectorUnavailableError(
                f"GitHub upstream unavailable ({status})", details=detail
            )
        raise ConnectorOperationFailedError(
            f"GitHub request failed with HTTP {status}", details=detail
        )

    @staticmethod
    def _repo_segments(owner: str, repo: str) -> tuple[str, str]:
        validate_github_owner(owner)
        validate_github_repo(repo)
        return owner, repo

    # ------------------------------------------------------------------
    # Repository metadata
    # ------------------------------------------------------------------

    def get_repository(self, owner: str, repo: str) -> RepoSummary:
        """Fetch core repository metadata."""
        owner, repo = self._repo_segments(owner, repo)
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="get_repository",
        ):
            response = self._request("GET", f"/repos/{owner}/{repo}")
            payload = response.json()
            return RepoSummary(
                id=int(payload["id"]),
                owner=payload["owner"]["login"],
                name=payload["name"],
                full_name=payload["full_name"],
                default_branch=payload.get("default_branch") or "main",
                private=bool(payload.get("private", False)),
                html_url=payload.get("html_url", ""),
                description=payload.get("description"),
            )

    # ------------------------------------------------------------------
    # Contents
    # ------------------------------------------------------------------

    def get_contents(
        self,
        owner: str,
        repo: str,
        path: str = "",
        *,
        ref: str | None = None,
    ) -> ContentItem | list[ContentItem]:
        """Read repository contents — a directory listing or one file.

        Text files are decoded into ``text`` (utf-8); directories return the
        first page of entries.
        """
        owner, repo = self._repo_segments(owner, repo)
        clean_path = path.strip("/")
        url_path = (
            f"/repos/{owner}/{repo}/contents/{clean_path}"
            if clean_path
            else f"/repos/{owner}/{repo}/contents"
        )
        query = {"ref": ref} if ref else None
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="get_contents",
            detail={"path": clean_path},
        ):
            response = self._request("GET", url_path, query=query)
            payload = response.json()
            if isinstance(payload, list):
                return [
                    ContentItem(
                        name=item["name"],
                        path=item["path"],
                        kind=item.get("type", "file"),
                        sha=item.get("sha", ""),
                        size_bytes=int(item.get("size", 0)),
                        download_url=item.get("download_url"),
                        text=None,
                    )
                    for item in payload
                    if isinstance(item, dict)
                ]
            content_b64 = payload.get("content") or ""
            text = (
                base64.b64decode(content_b64).decode("utf-8") if content_b64 else None
            )
            return ContentItem(
                name=payload["name"],
                path=payload["path"],
                kind=payload.get("type", "file"),
                sha=payload.get("sha", ""),
                size_bytes=int(payload.get("size", 0)),
                download_url=payload.get("download_url"),
                text=text,
            )

    def put_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        message: str,
        content: bytes | str,
        branch: str,
        sha: str | None = None,
    ) -> str:
        """Create/update a file; returns the new commit SHA.

        ``sha`` is required when updating an existing file (GitHub contract).
        """
        owner, repo = self._repo_segments(owner, repo)
        clean_path = path.strip("/")
        if not clean_path:
            raise ConnectorValidationError("file path is required")
        cleaned_message = message.strip() if isinstance(message, str) else ""
        if not cleaned_message:
            raise ConnectorValidationError("commit message must be non-empty")
        raw = content.encode("utf-8") if isinstance(content, str) else content
        body: dict[str, Any] = {
            "message": cleaned_message,
            "branch": branch,
            "content": base64.b64encode(raw).decode("ascii"),
        }
        if sha is not None:
            body["sha"] = sha
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="put_contents",
            detail={"bytes": len(raw)},
        ):
            response = self._request(
                "PUT", f"/repos/{owner}/{repo}/contents/{clean_path}", json_body=body
            )
            commit_info = response.json().get("commit") or {}
            return str(commit_info.get("sha", ""))

    # ------------------------------------------------------------------
    # Branches / refs
    # ------------------------------------------------------------------

    def get_ref(self, owner: str, repo: str, branch: str) -> GitRef:
        """Resolve a remote branch reference to its current SHA."""
        owner, repo = self._repo_segments(owner, repo)
        safe_branch = validate_ref_name(branch)
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="get_ref",
        ):
            response = self._request(
                "GET", f"/repos/{owner}/{repo}/git/ref/heads/{safe_branch}"
            )
            payload = response.json()
            return GitRef(ref=str(payload["ref"]), sha=str(payload["object"]["sha"]))

    def create_branch(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        from_branch: str | None = None,
    ) -> GitRef:
        """Create a remote branch from HEAD of the default branch unless a
        source branch is given."""
        owner, repo = self._repo_segments(owner, repo)
        safe_name = validate_ref_name(name)
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="create_branch",
        ):
            source = from_branch or self.get_repository(owner, repo).default_branch
            resolved = self.get_ref(owner, repo, source)
            response = self._request(
                "POST",
                f"/repos/{owner}/{repo}/git/refs",
                json_body={"ref": f"refs/heads/{safe_name}", "sha": resolved.sha},
            )
            payload = response.json()
            return GitRef(ref=str(payload["ref"]), sha=str(payload["object"]["sha"]))

    # ------------------------------------------------------------------
    # Pull requests and issues
    # ------------------------------------------------------------------

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        head: str,
        base: str,
        body: str | None = None,
        draft: bool = False,
    ) -> PullRequestInfo:
        """Open a pull request from ``head`` into ``base``."""
        owner, repo = self._repo_segments(owner, repo)
        safe_head = validate_ref_name(head)
        safe_base = validate_ref_name(base)
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="create_pull_request",
        ):
            response = self._request(
                "POST",
                f"/repos/{owner}/{repo}/pulls",
                json_body={
                    "title": title.strip(),
                    "head": safe_head,
                    "base": safe_base,
                    **({"body": body} if body else {}),
                    "draft": draft,
                },
            )
            return _parse_pull_request(response.json())

    def get_pull_request(self, owner: str, repo: str, number: int) -> PullRequestInfo:
        owner, repo = self._repo_segments(owner, repo)
        if number < 1:
            raise ConnectorValidationError("pull request number must be positive")
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="get_pull_request",
        ):
            response = self._request(
                "GET", f"/repos/{owner}/{repo}/pulls/{int(number)}"
            )
            return _parse_pull_request(response.json())

    def merge_pull_request(
        self, owner: str, repo: str, number: int, *, method: str = "merge"
    ) -> str:
        """Merge an open pull request; returns the merge commit SHA."""
        owner, repo = self._repo_segments(owner, repo)
        if method not in {"merge", "squash", "rebase"}:
            raise ConnectorValidationError(
                "merge method must be merge|squash|rebase",
                details={"method": method},
            )
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="merge_pull_request",
        ):
            response = self._request(
                "PUT",
                f"/repos/{owner}/{repo}/pulls/{int(number)}/merge",
                json_body={"merge_method": method},
            )
            payload = response.json()
            if not payload.get("merged"):
                raise ConnectorConflictError(
                    "GitHub reported the pull request as not merged"
                )
            return str(payload.get("sha", ""))

    def create_issue(
        self, owner: str, repo: str, *, title: str, body: str | None = None
    ) -> IssueInfo:
        owner, repo = self._repo_segments(owner, repo)
        cleaned_title = title.strip() if isinstance(title, str) else ""
        if not cleaned_title:
            raise ConnectorValidationError("issue title must be non-empty")
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="create_issue",
        ):
            response = self._request(
                "POST",
                f"/repos/{owner}/{repo}/issues",
                json_body={
                    "title": cleaned_title,
                    **({"body": body} if body else {}),
                },
            )
            payload = response.json()
            return IssueInfo(
                number=int(payload["number"]),
                title=payload["title"],
                state=payload.get("state", "open"),
                body=payload.get("body"),
                html_url=payload.get("html_url", ""),
            )


def _parse_pull_request(payload: dict[str, Any]) -> PullRequestInfo:
    return PullRequestInfo(
        number=int(payload["number"]),
        title=payload.get("title", ""),
        state=payload.get("state", "open"),
        draft=bool(payload.get("draft", False)),
        head_ref=(payload.get("head") or {}).get("ref", ""),
        base_ref=(payload.get("base") or {}).get("ref", ""),
        html_url=payload.get("html_url", ""),
    )


__all__ = [
    "ContentItem",
    "GitRef",
    "GitHubConnector",
    "GitHubResponse",
    "GitHubTransport",
    "IssueInfo",
    "PullRequestInfo",
    "RepoSummary",
    "UrllibGitHubTransport",
]
