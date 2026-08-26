"""Filesystem connector — sandboxed workspace operations.

Provides a deterministic, security-conscious workspace boundary for future
engineering workers:

- ROOT CONFINEMENT — every path argument is validated relative to a single
  workspace root. Absolute inputs, ``..`` traversal and symlinks resolving
  outside the root are rejected (:class:`ConnectorValidationError`) BEFORE any
  filesystem effect occurs.
- ERROR NORMALISATION — OS errors map to classified :class:`ConnectorError`
  subclasses; no arbitrary exceptions escape.
- DETERMINISM — operations are synchronous and sequentially consistent within
  one process; all outputs are workspace-relative POSIX-style strings.

The connector performs NO shell execution.
"""

from __future__ import annotations

import shutil
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from autoforge_connectors.errors import (
    ConnectorAuthorizationError,
    ConnectorConflictError,
    ConnectorError,
    ConnectorNotFoundError,
    ConnectorOperationFailedError,
    ConnectorUnavailableError,
    ConnectorValidationError,
)
from autoforge_connectors.events import ConnectorEvents
from autoforge_connectors.instrumentation import observe_connector_operation


@dataclass(frozen=True)
class PathInfo:
    """Metadata for one workspace entry (workspace-relative identity)."""

    relative_path: str
    name: str
    is_dir: bool
    is_symlink: bool
    size_bytes: int
    modified_at: datetime | None


def _relative(relative_path: str) -> PurePosixPath:
    """Normalise user input into a safe workspace-relative POSIX path."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ConnectorValidationError("path must be a non-empty string")
    candidate = PurePosixPath(relative_path.replace("\\", "/"))
    if candidate.is_absolute():
        raise ConnectorValidationError(
            "absolute paths are not accepted inside a workspace",
            details={"path": relative_path},
        )
    cleaned_parts: list[str] = []
    for part in candidate.parts:
        if part == ".":
            continue
        if part == "..":
            raise ConnectorValidationError(
                "'..' segments are forbidden (traversal protection)",
                details={"path": relative_path},
            )
        if "\x00" in part:
            raise ConnectorValidationError("path contains a null byte")
        cleaned_parts.append(part)
    if not cleaned_parts:
        raise ConnectorValidationError(
            "path resolves to the workspace root; expected an entry path"
        )
    return PurePosixPath(*cleaned_parts)


class WorkspaceFilesystem:
    """Confined read/write surface over one workspace directory tree."""

    def __init__(
        self,
        root: Path | str,
        *,
        events: ConnectorEvents | None = None,
    ) -> None:
        root_path = Path(root).expanduser()
        if not root_path.exists():
            raise ConnectorNotFoundError(
                f"workspace root does not exist: {root_path}",
                details={"root": str(root_path)},
            )
        if not root_path.is_dir():
            raise ConnectorValidationError(
                f"workspace root is not a directory: {root_path}"
            )
        try:
            self._root = root_path.resolve(strict=True)
        except OSError as exc:  # pragma: no cover - exotic filesystem failure
            raise ConnectorOperationFailedError(
                "workspace root could not be resolved",
                details={"os_error": exc.strerror},
            ) from exc
        self._events = events
        #: Most recent OperationObservation on this connector.
        self.last_operation: Any = None

    @property
    def connector_name(self) -> str:
        return "filesystem"

    @property
    def root(self) -> Path:
        """Resolved absolute workspace root."""
        return self._root

    def _contained(self, relative_path: str) -> Path:
        """Resolve under the root, enforcing containment.

        Symlinks are followed by ``resolve()`` so a link pointing outside
        the workspace escapes containment detection — hence rejection.
        """
        clean = _relative(relative_path)
        target = (self._root / clean).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise ConnectorValidationError(
                "path escapes the workspace boundary (symlink or traversal)",
                details={"path": relative_path},
            ) from exc
        return target

    def _rel_str(self, target: Path) -> str:
        return target.relative_to(self._root).as_posix()

    def _info_for(self, absolute: Path) -> PathInfo:
        st = absolute.lstat()
        mode = st.st_mode
        return PathInfo(
            relative_path=self._rel_str(absolute),
            name=absolute.name,
            is_dir=stat.S_ISDIR(mode),
            is_symlink=stat.S_ISLNK(mode),
            size_bytes=st.st_size,
            modified_at=datetime.fromtimestamp(st.st_mtime),
        )

    def exists(self, path: str) -> bool:
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="exists",
        ):
            return self._contained(path).exists()

    def metadata(self, path: str) -> PathInfo:
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="metadata",
        ):
            target = self._contained(path)
            if not target.exists():
                raise ConnectorNotFoundError(
                    "path does not exist in workspace", details={"path": path}
                )
            return self._info_for(target)

    def list_dir(self, path: str) -> list[PathInfo]:
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="list_dir",
        ):
            target = self._contained(path)
            if not target.exists():
                raise ConnectorNotFoundError(
                    "directory does not exist in workspace", details={"path": path}
                )
            if not target.is_dir():
                raise ConnectorValidationError(
                    "path is not a directory", details={"path": path}
                )
            return [self._info_for(child) for child in sorted(target.iterdir())]

    def read_text(self, path: str, *, encoding: str = "utf-8") -> str:
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="read_text",
        ):
            target = self._contained(path)
            try:
                return target.read_text(encoding=encoding)
            except IsADirectoryError as exc:
                raise ConnectorValidationError(
                    "path is a directory, not a file", details={"path": path}
                ) from exc
            except FileNotFoundError as exc:
                raise ConnectorNotFoundError(
                    "file does not exist in workspace", details={"path": path}
                ) from exc
            except UnicodeDecodeError as exc:
                raise ConnectorValidationError(
                    "file is not decodable with the requested encoding",
                    details={"path": path, "encoding": encoding},
                ) from exc
            except OSError as exc:
                raise self._os_error(exc, path=path)

    def read_bytes(self, path: str) -> bytes:
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="read_bytes",
        ):
            target = self._contained(path)
            try:
                return target.read_bytes()
            except IsADirectoryError as exc:
                raise ConnectorValidationError(
                    "path is a directory, not a file", details={"path": path}
                ) from exc
            except FileNotFoundError as exc:
                raise ConnectorNotFoundError(
                    "file does not exist in workspace", details={"path": path}
                ) from exc
            except OSError as exc:
                raise self._os_error(exc, path=path)

    # ------------------------------------------------------------------
    # Write / mutate operations
    # ------------------------------------------------------------------

    def write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = False,
        parents: bool = True,
        encoding: str = "utf-8",
    ) -> str:
        """Create (or replace when ``overwrite``) a text file.

        Returns the workspace-relative path written.
        """
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="write_text",
            detail={"bytes": len(content.encode(encoding))},
        ):
            target = self._parented_target(path, parents=parents)
            self._assert_writable_target(target, overwrite=overwrite)
            try:
                target.write_text(content, encoding=encoding)
            except OSError as exc:
                raise self._os_error(exc, path=path)
            return self._rel_str(target)

    def write_bytes(
        self,
        path: str,
        content: bytes,
        *,
        overwrite: bool = False,
        parents: bool = True,
    ) -> str:
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="write_bytes",
            detail={"bytes": len(content)},
        ):
            target = self._parented_target(path, parents=parents)
            self._assert_writable_target(target, overwrite=overwrite)
            try:
                target.write_bytes(content)
            except OSError as exc:
                raise self._os_error(exc, path=path)
            return self._rel_str(target)

    def mkdir(self, path: str, *, parents: bool = True, exist_ok: bool = True) -> str:
        """Create a directory inside the workspace."""
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="mkdir",
        ):
            target = self._contained_raw(path)
            if target.exists() and not exist_ok:
                raise ConnectorConflictError(
                    "directory already exists", details={"path": path}
                )
            if target.exists() and not target.is_dir():
                raise ConnectorConflictError(
                    "a non-directory occupies the path", details={"path": path}
                )
            try:
                target.mkdir(parents=parents, exist_ok=True)
            except OSError as exc:
                raise self._os_error(exc, path=path)
            return self._rel_str(target)

    def move(self, source: str, destination: str, *, overwrite: bool = False) -> str:
        """Move/rename an entry within the workspace boundary."""
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="move",
            detail={"source": source, "destination": destination},
        ):
            src = self._contained(source)
            dst = self._contained(destination)
            if not src.exists():
                raise ConnectorNotFoundError(
                    "source does not exist in workspace", details={"path": source}
                )
            if dst.exists():
                if not overwrite:
                    raise ConnectorConflictError(
                        "destination already exists", details={"path": destination}
                    )
                if dst.is_dir() and not dst.is_symlink():
                    shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dst))
            except OSError as exc:
                raise self._os_error(exc, path=f"{source} -> {destination}")
            return self._rel_str(dst)

    def delete(self, path: str, *, recursive: bool = False) -> None:
        """Delete a file or directory (non-empty dirs need ``recursive``)."""
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="delete",
            detail={"recursive": recursive},
        ):
            target = self._contained(path)
            if not target.exists():
                raise ConnectorNotFoundError(
                    "path does not exist in workspace", details={"path": path}
                )
            try:
                if target.is_dir() and not target.is_symlink():
                    if recursive:
                        shutil.rmtree(target)
                    else:
                        target.rmdir()
                else:
                    target.unlink()
            except OSError as exc:
                raise self._os_error(exc, path=path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _contained_raw(self, path: str) -> Path:
        """Containment check WITHOUT requiring existence of intermediates."""
        clean = _relative(path)
        lexical_target = self._root / clean
        if lexical_target.exists():
            resolved = lexical_target.resolve()
            try:
                resolved.relative_to(self._root)
            except ValueError as exc:
                raise ConnectorValidationError(
                    "path escapes the workspace boundary (symlink or traversal)",
                    details={"path": path},
                ) from exc
            return resolved
        # Not-yet-existing targets: verify the deepest existing ancestor so
        # a symlinked ancestor cannot smuggle paths outside the root.
        anchor = lexical_target.parent
        while not anchor.exists():
            anchor = anchor.parent
        resolved_anchor = anchor.resolve()
        try:
            resolved_anchor.relative_to(self._root)
        except ValueError as exc:
            raise ConnectorValidationError(
                "path escapes the workspace boundary (symlinked ancestor)",
                details={"path": path},
            ) from exc
        return lexical_target

    def _parented_target(self, path: str, *, parents: bool) -> Path:
        target = self._contained_raw(path)
        parent = target.parent
        if not parent.exists():
            if not parents:
                raise ConnectorNotFoundError(
                    "parent directory does not exist", details={"path": path}
                )
            # Containment was already verified against the deepest existing
            # ancestor inside _contained_raw; materialise the rest safely.
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise self._os_error(exc, path=path)
        return target

    @staticmethod
    def _assert_writable_target(target: Path, *, overwrite: bool) -> None:
        if target.is_dir():
            raise ConnectorConflictError(
                "a directory occupies the target path",
                details={"path": str(target)},
            )
        if target.exists() and not overwrite:
            raise ConnectorConflictError(
                "target already exists (pass overwrite=True to replace)"
            )

    @staticmethod
    def _os_error(exc: OSError, *, path: str) -> ConnectorError:
        err = exc.errno
        if err == 13:  # EACCES
            raise ConnectorAuthorizationError(
                "permission denied by the operating system",
                details={"path": path},
            ) from exc
        if err == 28:  # ENOSPC
            raise ConnectorUnavailableError(
                "no space left on device", details={"path": path}
            ) from exc
        if err == 36:  # ENAMETOOLONG
            raise ConnectorValidationError(
                "file name too long", details={"path": path}
            ) from exc
        raise ConnectorOperationFailedError(
            "filesystem operation failed",
            details={"path": path, "os_error": exc.strerror},
        ) from exc


__all__ = ["PathInfo", "WorkspaceFilesystem"]

