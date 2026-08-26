"""Input validation primitives shared by connector implementations.

Validators raise :class:`ConnectorValidationError` on violation. They exist to
make option-injection and path/ref smuggling structurally impossible rather
than merely discouraged.
"""

from __future__ import annotations

import re

from autoforge_connectors.errors import ConnectorValidationError

#: Safe git refname/pathspec charset: alphanumeric plus ``_ . - /``, no
#: leading dash (option injection), no ``..`` traversal, no trailing ``.``
#: or ``.lock``.
_REF_NAME_RE = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9_.\-/]+(?<!\.)(?<!\.lock)$")

_GITHUB_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def validate_ref_name(name: str, *, what: str = "ref") -> str:
    """Validate a git-style ref/branch name and return it unchanged."""
    if not isinstance(name, str) or not name:
        raise ConnectorValidationError(f"{what} must be a non-empty string")
    if len(name) > 250:
        raise ConnectorValidationError(f"{what} exceeds maximum length")
    if "\x00" in name:
        raise ConnectorValidationError(f"{what} contains a null byte")
    if not _REF_NAME_RE.match(name):
        raise ConnectorValidationError(
            f"{what} contains characters or sequences forbidden for refnames",
            details={"what": what},
        )
    return name


def validate_pathspec(path: str) -> str:
    """Validate a filesystem pathspec used as a git argument.

    Unlike refnames, file paths may contain spaces and most punctuation;
    they must simply be non-empty, free of null/control characters, and must
    never begin with a dash (option injection).
    """
    if not isinstance(path, str) or not path.strip():
        raise ConnectorValidationError("pathspec must be a non-empty string")
    if len(path) > 4096:
        raise ConnectorValidationError("pathspec exceeds maximum length")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        raise ConnectorValidationError("pathspec contains control characters")
    first_segment = path.replace("\\", "/").split("/", 1)[0]
    if first_segment.startswith("-"):
        raise ConnectorValidationError(
            "pathspec segments must not begin with '-' (option injection)"
        )
    return path


def validate_relative_path(path: str, *, what: str = "path") -> str:
    """Validate a plain relative path usable as an argument (no escaping,
    no option injection via leading dash)."""
    if not isinstance(path, str) or not path.strip():
        raise ConnectorValidationError(f"{what} must be a non-empty string")
    if "\x00" in path:
        raise ConnectorValidationError(f"{what} contains a null byte")
    first_segment = path.replace("\\", "/").split("/", 1)[0]
    if first_segment.startswith("-"):
        raise ConnectorValidationError(
            f"{what} segments must not begin with '-' (option injection)",
            details={"what": what},
        )
    return path


def validate_github_owner(value: str) -> str:
    """Validate a GitHub owner/org login."""
    if not isinstance(value, str) or not _GITHUB_OWNER_RE.match(value):
        raise ConnectorValidationError("github owner login is invalid")
    return value


def validate_github_repo(value: str) -> str:
    """Validate a GitHub repository name."""
    if not isinstance(value, str) or not _GITHUB_REPO_RE.match(value):
        raise ConnectorValidationError("github repository name is invalid")
    return value


def validate_http_path(value: str) -> str:
    """Validate an API path fragment (single leading slash, no '?'/'#' queries,
    no whitespace) before joining onto a base URL."""
    if not isinstance(value, str) or not value.startswith("/"):
        raise ConnectorValidationError("api path must start with '/'")
    if "?" in value or "#" in value or " " in value or "\x00" in value:
        raise ConnectorValidationError("api path contains forbidden characters")
    return value
