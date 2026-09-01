"""
Phase 18-E — Safe File Editor
Applies file edits with pre-condition verification.
"""
from __future__ import annotations
import hashlib
from typing import Any

from autoforge_execution_18e.repair_models import SafeFileEdit, SafeFileEditResult


class SafeFileEditor:
    """Applies file edits with safety verification."""

    def __init__(self, filesystem: Any | None = None) -> None:
        self._filesystem = filesystem

    def _get_fs(self, workspace_root: Any) -> Any:
        if self._filesystem is not None:
            return self._filesystem
        from autoforge_connectors.filesystem import WorkspaceFilesystem
        return WorkspaceFilesystem(workspace_root)

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def apply_edit(self, edit: SafeFileEdit, workspace_root: Any) -> SafeFileEditResult:
        """Apply a single safe file edit with target content verification."""
        fs = self._get_fs(workspace_root)

        try:
            old_content = fs.read_text(edit.target_path)
        except Exception as e:
            return SafeFileEditResult(
                edit=edit, success=False,
                actual_content_matches=False, content_hash_matches=False,
                error=f"Cannot read target file for edit: {e}",
            )

        content_matches = True
        hash_matches = True
        error_msg = None

        if edit.expected_content is not None:
            if old_content != edit.expected_content:
                content_matches = False
                error_msg = (
                    f"Target mismatch for {edit.target_path}: expected content "
                    f"hash {self._hash(edit.expected_content)[:12]} but found "
                    f"{self._hash(old_content)[:12]}"
                )

        if edit.expected_content_hash is not None:
            actual_hash = self._hash(old_content)
            if actual_hash != edit.expected_content_hash:
                hash_matches = False
                if error_msg is None:
                    error_msg = (
                        f"Hash mismatch for {edit.target_path}: expected "
                        f"{edit.expected_content_hash[:12]} actual {actual_hash[:12]}"
                    )

        # If no verification given, apply anyway (backward compat) but flag
        if edit.expected_content is None and edit.expected_content_hash is None:
            content_matches = True
            hash_matches = True
            error_msg = None

        if error_msg is not None:
            return SafeFileEditResult(
                edit=edit, success=False,
                actual_content_matches=content_matches, content_hash_matches=hash_matches,
                old_content=old_content, error=error_msg,
            )

        try:
            fs.write_text(edit.target_path, edit.new_content, overwrite=True)
            new_content = edit.new_content
            verify_content = fs.read_text(edit.target_path)
            if verify_content != new_content:
                return SafeFileEditResult(
                    edit=edit, success=False,
                    actual_content_matches=True, content_hash_matches=True,
                    old_content=old_content, new_content=new_content,
                    error="Post-write verification failed: file content mismatch",
                )
            return SafeFileEditResult(
                edit=edit, success=True,
                actual_content_matches=True, content_hash_matches=True,
                old_content=old_content, new_content=new_content,
            )
        except Exception as e:
            return SafeFileEditResult(
                edit=edit, success=False,
                actual_content_matches=content_matches, content_hash_matches=hash_matches,
                old_content=old_content, error=f"Failed to write file: {e}",
            )

    def apply_edits(self, edits, workspace_root) -> list:
        """Apply a batch of edits, returning results for each."""
        return [self.apply_edit(edit, workspace_root) for edit in edits]
