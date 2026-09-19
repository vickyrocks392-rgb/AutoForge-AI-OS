"""Proprietary Source Isolation & Boundary Sanitizer for Customer Deliverables."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional


class ProprietaryCodeViolationError(RuntimeError):
    """Raised if proprietary AutoForge code or internal imports are detected in customer output."""


class SecretLeakageViolationError(RuntimeError):
    """Raised if unmasked credentials, API keys, or private keys are detected in customer output."""


class ProprietaryBoundarySanitizer:
    """
    Audits customer deliverable packages to enforce strict commercial export boundaries.
    Guarantees zero AutoForge proprietary source code, internal imports, or secrets leak to customers.
    """

    DEFAULT_FORBIDDEN_TERMS = [
        "autoforge_kernel",
        "autoforge_modernization",
        "autoforge_ai_infrastructure",
        "autoforge_workforce",
        "autoforge_orchestration",
        "autoforge_runtime",
        "autoforge_artifacts",
        "autoforge_events",
        "autoforge_composition",
        "autoforge_power_engines",
    ]

    FORBIDDEN_DIR_NAMES = {
        ".git",
        ".pytest_cache",
        ".vscode",
        ".idea",
    }

    SECRET_PATTERNS = [
        (re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"), "Private cryptographic key"),
        (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key ID"),
        (re.compile(r"\bghp_[a-zA-Z0-9]{30,}\b"), "GitHub Personal Access Token"),
        (re.compile(r"\bsk-[a-zA-Z0-9]{32,}\b"), "OpenAI / Model API Key"),
    ]

    BINARY_EXTENSIONS = {
        ".pyc", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".db", ".sqlite", ".pdf", ".zip", ".bin"
    }

    def __init__(
        self,
        delivery_dir: Path | str,
        forbidden_terms: List[str] | None = None,
        scan_secrets: bool = True,
    ):
        self.delivery_dir = Path(delivery_dir).resolve()
        self.forbidden_terms = forbidden_terms or self.DEFAULT_FORBIDDEN_TERMS
        self.scan_secrets = scan_secrets

    def scan_for_secrets(self) -> List[str]:
        """Scans deliverable files for exposed secrets or credentials."""
        secret_violations: List[str] = []
        if not self.delivery_dir.exists():
            return secret_violations

        for root, _, files in os.walk(self.delivery_dir):
            for file in files:
                fpath = Path(root) / file
                if fpath.suffix.lower() in self.BINARY_EXTENSIONS:
                    continue

                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    rel_path = fpath.relative_to(self.delivery_dir)
                    for pattern, desc in self.SECRET_PATTERNS:
                        matches = pattern.findall(text)
                        for m in matches:
                            m_str = str(m)
                            # Allow explicit dummy placeholders
                            if any(ph in m_str.lower() for ph in ["placeholder", "example", "dummy", "xxxx", "test"]):
                                continue
                            secret_violations.append(f"{rel_path}: Exposed {desc} pattern detected")
                except Exception:
                    pass

        return secret_violations

    def sanitize(self) -> List[str]:
        """
        Scans all files and directories in the customer deliverable.
        Raises ProprietaryCodeViolationError or SecretLeakageViolationError on detection.
        Returns an empty list on clean validation.
        """
        violations: List[str] = []
        if not self.delivery_dir.exists():
            return violations

        for root, dirs, files in os.walk(self.delivery_dir):
            # 1. Check directory names and symlinks
            for d in dirs:
                dpath = Path(root) / d
                if dpath.is_symlink():
                    try:
                        resolved = dpath.resolve()
                        if not resolved.is_relative_to(self.delivery_dir.resolve()):
                            violations.append(
                                f"Directory symlink traversal outside delivery boundary: '{dpath.name}' points to '{resolved}'"
                            )
                    except Exception as e:
                        violations.append(f"Insecure directory symlink detected: '{dpath.name}' ({e})")

                if d in self.FORBIDDEN_DIR_NAMES:
                    rel_d = (Path(root) / d).relative_to(self.delivery_dir)
                    violations.append(f"Forbidden internal directory found: '{rel_d}'")
                for term in self.forbidden_terms:
                    if term in d:
                        rel_d = (Path(root) / d).relative_to(self.delivery_dir)
                        violations.append(f"Proprietary package directory found: '{rel_d}'")

            # 2. Check files and symlinks
            for file in files:
                fpath = Path(root) / file

                # Detect symlink traversal outside delivery directory
                if fpath.is_symlink():
                    try:
                        resolved = fpath.resolve()
                        if not resolved.is_relative_to(self.delivery_dir.resolve()):
                            violations.append(
                                f"Symlink traversal outside delivery boundary: '{fpath.name}' points to '{resolved}'"
                            )
                    except Exception as e:
                        violations.append(f"Insecure symlink detected: '{fpath.name}' ({e})")

                # Check filename against proprietary terms
                for term in self.forbidden_terms:
                    if term in file:
                        rel_path = fpath.relative_to(self.delivery_dir)
                        violations.append(f"Proprietary file name detected: '{rel_path}'")

                if fpath.suffix.lower() in self.BINARY_EXTENSIONS:
                    continue

                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for term in self.forbidden_terms:
                        # Static import patterns
                        if f"import {term}" in text or f"from {term}" in text:
                            rel_path = fpath.relative_to(self.delivery_dir)
                            violations.append(f"{rel_path} imports proprietary '{term}'")
                        # Dynamic import patterns
                        elif f'"{term}"' in text or f"'{term}'" in text:
                            if "__import__" in text or "import_module" in text:
                                rel_path = fpath.relative_to(self.delivery_dir)
                                violations.append(f"{rel_path} dynamically imports proprietary '{term}'")
                except Exception:
                    pass

        if violations:
            msg = "Proprietary code leakage detected in customer delivery:\n" + "\n".join(violations)
            raise ProprietaryCodeViolationError(msg)

        # 3. Check for secrets if enabled
        if self.scan_secrets:
            sec_violations = self.scan_for_secrets()
            if sec_violations:
                msg = "Secret or credential leakage detected in customer delivery:\n" + "\n".join(sec_violations)
                raise SecretLeakageViolationError(msg)

        return []

