"""Hostile-Input Defenses & Subprocess Safety (18-COMMERCIAL-D).

Provides robust security controls:
1. Path traversal & symlink breakout defenses
2. Safe archive extraction (zip/tar decompression bomb limits)
3. Sensitive credentials and secret detection
4. Prompt injection defenses for untrusted customer source
5. Sandboxed subprocess execution with allowlist, clean env, and timeouts
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field


# Allowlisted commands permitted for verification, compilation, and testing
ALLOWLISTED_COMMANDS: Set[str] = {
    "javac",
    "java",
    "python3",
    "python",
    "pytest",
    "git",
    "mvn",
    "gradle",
    "cat",
    "ls",
    "echo",
}

# Dangerous shell metacharacters and patterns
DANGEROUS_PATTERNS = [
    re.compile(r"[;&|`$><]"),
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+777\b", re.IGNORECASE),
    re.compile(r"\bcurl\s+.*\bsh\b", re.IGNORECASE),
    re.compile(r"\bwget\s+.*\bsh\b", re.IGNORECASE),
    re.compile(r"\b(nc|netcat|ncat)\b", re.IGNORECASE),
]

# Sensitive file patterns that must never be processed or included
SENSITIVE_PATTERNS = [
    re.compile(r"(^|/)\.env(\..+)?$", re.IGNORECASE),
    re.compile(r".*id_rsa.*", re.IGNORECASE),
    re.compile(r".*id_ed25519.*", re.IGNORECASE),
    re.compile(r".*\.pem$", re.IGNORECASE),
    re.compile(r".*\.key$", re.IGNORECASE),
    re.compile(r".*\.pkcs12$", re.IGNORECASE),
    re.compile(r".*credentials\.json$", re.IGNORECASE),
    re.compile(r".*secrets?\.(json|yaml|yml)$", re.IGNORECASE),
    re.compile(r".*shadow$", re.IGNORECASE),
    re.compile(r".*passwd$", re.IGNORECASE),
]

# Secrets regex for scanning content
SECRET_CONTENT_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|token|password|auth[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-\.]{16,}['\"]", re.IGNORECASE),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(AKIA[0-9A-Z]{16})"),
]

# Prompt injection markers inside untrusted source code comments/strings
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*override", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a(n)?\s+", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+guidelines", re.IGNORECASE),
    re.compile(r"reveal\s+(internal|system)\s+(prompt|instructions|keys)", re.IGNORECASE),
]


class SecurityViolationError(Exception):
    """Raised when an untrusted input breaches security constraints."""
    pass


def validate_path_confinement(target_path: Path, base_dir: Path) -> Path:
    """
    Validates that target_path resolves strictly within base_dir.
    Prevents path traversal attacks (e.g. ../../etc/passwd) and symlink breakouts.
    """
    resolved_base = base_dir.resolve()
    resolved_target = (base_dir / target_path).resolve() if not target_path.is_absolute() else target_path.resolve()

    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise SecurityViolationError(
            f"Path traversal detected: '{target_path}' escapes base directory '{base_dir}'"
        )

    # Check for symlink escaping base
    if target_path.is_symlink():
        symlink_dest = target_path.resolve()
        try:
            symlink_dest.relative_to(resolved_base)
        except ValueError:
            raise SecurityViolationError(
                f"Symlink breakout detected: '{target_path}' points outside '{base_dir}' to '{symlink_dest}'"
            )

    return resolved_target


def is_sensitive_path(path: str) -> bool:
    """Checks if a file path matches known sensitive patterns (.env, keys, credentials)."""
    norm_path = path.replace("\\", "/")
    return any(p.search(norm_path) for p in SENSITIVE_PATTERNS)


def scan_for_secrets(content: str) -> List[str]:
    """Scans content for potential leaked secrets, API keys, or private keys."""
    findings = []
    for pattern in SECRET_CONTENT_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            findings.append(pattern.pattern)
    return findings


def sanitize_prompt_context(source_code: str) -> Tuple[str, bool]:
    """
    Wraps untrusted source code in explicit boundary fences.
    Flags potential prompt injection attempts in code comments/strings.
    """
    has_injection_risk = any(p.search(source_code) for p in PROMPT_INJECTION_PATTERNS)
    # Neutralize any direct system-level instruction formatting
    sanitized = source_code.replace("```system", "```text")
    return sanitized, has_injection_risk


def safe_extract_archive(
    archive_path: Path,
    dest_dir: Path,
    max_files: int = 1000,
    max_total_bytes: int = 50 * 1024 * 1024,  # 50 MB
    max_file_bytes: int = 10 * 1024 * 1024,   # 10 MB
) -> List[Path]:
    """
    Extracts zip or tar archive safely into dest_dir.
    Protects against:
    - Path traversal (../../)
    - Absolute path extraction
    - Decompression bombs / huge file counts
    - Symlinks pointing outside dest_dir
    """
    archive_path = Path(archive_path).resolve()
    dest_dir = Path(dest_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    extracted_files: List[Path] = []
    total_bytes = 0
    file_count = 0

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                file_count += 1
                if file_count > max_files:
                    raise SecurityViolationError(f"Archive exceeds maximum file count limit ({max_files})")

                # Check compressed size vs uncompressed
                total_bytes += info.file_size
                if total_bytes > max_total_bytes:
                    raise SecurityViolationError(f"Archive exceeds uncompressed size limit ({max_total_bytes} bytes)")
                if info.file_size > max_file_bytes:
                    raise SecurityViolationError(f"File '{info.filename}' exceeds single file size limit ({max_file_bytes} bytes)")

                # Path confinement check
                out_path = dest_dir / info.filename
                validate_path_confinement(out_path, dest_dir)

                if is_sensitive_path(info.filename):
                    continue  # Safely ignore sensitive files in archive

                if info.is_dir():
                    out_path.mkdir(parents=True, exist_ok=True)
                else:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(out_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted_files.append(out_path)

    elif tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as tf:
            for member in tf.getmembers():
                file_count += 1
                if file_count > max_files:
                    raise SecurityViolationError(f"Archive exceeds maximum file count limit ({max_files})")

                total_bytes += member.size
                if total_bytes > max_total_bytes:
                    raise SecurityViolationError(f"Archive exceeds uncompressed size limit ({max_total_bytes} bytes)")
                if member.size > max_file_bytes:
                    raise SecurityViolationError(f"File '{member.name}' exceeds single file size limit ({max_file_bytes} bytes)")

                out_path = dest_dir / member.name
                validate_path_confinement(out_path, dest_dir)

                if member.issym() or member.islnk():
                    link_target = dest_dir / member.linkname
                    validate_path_confinement(link_target, dest_dir)

                if is_sensitive_path(member.name):
                    continue

                tf.extract(member, path=dest_dir)
                if member.isfile():
                    extracted_files.append(out_path)
    else:
        raise ValueError(f"Unsupported archive format: '{archive_path.name}'. Expected .zip, .tar, .tar.gz, .tgz")

    return extracted_files


class SafeExecutionResult(BaseModel):
    """Result of sandboxed subprocess execution."""
    success: bool
    return_code: int
    stdout: str
    stderr: str
    duration_ms: float
    command: List[str]


class SafeExecutionRunner:
    """
    Subprocess execution sandbox.
    Enforces:
    - Allowlisted commands only
    - Working directory jail
    - Cleaned environment (no host secrets or sensitive env vars)
    - Timeout limits
    - Output size capping
    - No shell=True execution
    """

    def __init__(
        self,
        working_dir: Path,
        timeout_seconds: int = 60,
        max_output_bytes: int = 1024 * 1024,  # 1 MB
        custom_env: Optional[Dict[str, str]] = None,
    ):
        self.working_dir = Path(working_dir).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.custom_env = custom_env or {}

    def _sanitize_env(self) -> Dict[str, str]:
        """Builds a sanitized environment excluding sensitive tokens and keys."""
        safe_keys = {
            "PATH",
            "HOME",
            "USER",
            "LANG",
            "LC_ALL",
            "JAVA_HOME",
            "PYTHONPATH",
            "TMPDIR",
            "TERM",
        }
        clean_env = {k: v for k, v in os.environ.items() if k in safe_keys}
        clean_env.update(self.custom_env)
        return clean_env

    def run(self, cmd: List[str]) -> SafeExecutionResult:
        """
        Executes cmd safely without shell=True.
        """
        if not cmd:
            raise ValueError("Command list is empty.")

        binary = Path(cmd[0]).name
        if binary not in ALLOWLISTED_COMMANDS:
            raise SecurityViolationError(f"Command '{binary}' is not in allowlisted commands: {ALLOWLISTED_COMMANDS}")

        for arg in cmd:
            for p in DANGEROUS_PATTERNS:
                if p.search(arg):
                    raise SecurityViolationError(f"Dangerous pattern detected in argument '{arg}': {p.pattern}")

        import time
        start_time = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.working_dir),
                env=self._sanitize_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            stdout = proc.stdout[:self.max_output_bytes]
            stderr = proc.stderr[:self.max_output_bytes]
            return SafeExecutionResult(
                success=(proc.returncode == 0),
                return_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                command=cmd,
            )
        except subprocess.TimeoutExpired as te:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SafeExecutionResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=f"Command timed out after {self.timeout_seconds} seconds: {te}",
                duration_ms=duration_ms,
                command=cmd,
            )
        except Exception as ex:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SafeExecutionResult(
                success=False,
                return_code=-2,
                stdout="",
                stderr=f"Command execution error: {ex}",
                duration_ms=duration_ms,
                command=cmd,
            )
