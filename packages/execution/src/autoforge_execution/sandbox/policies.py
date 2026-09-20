"""
Security policy evaluation and validation engine for Workload Sandboxing (Phase 18-I).

Enforces filesystem confinement, process boundaries, network isolation,
secret sanitization, and prompt-injection resistance.
"""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from autoforge_execution.errors import SecurityViolationError
from autoforge_execution.sandbox.models import (
    FilesystemPolicy,
    NetworkMode,
    NetworkPolicy,
    ProcessPolicy,
    ResourceLimits,
    SecretPolicy,
    WorkloadSpec,
)


class PolicyViolationError(SecurityViolationError):
    """Raised when a workload specification violates sandbox security policy."""

    def __init__(self, message: str, violation_type: str = "POLICY_VIOLATION", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details or {})
        self.violation_type = violation_type


# Prompt injection regex patterns attempting to override security controls
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"\bdisable[\s_-]*sandbox\b", re.IGNORECASE),
    re.compile(r"\brun[\s_-]*as[\s_-]*root\b", re.IGNORECASE),
    re.compile(r"\bmount[\s_-]+/\b", re.IGNORECASE),
    re.compile(r"\bsend[\s_-]+credentials\b", re.IGNORECASE),
    re.compile(r"\bconnect[\s_-]+to[\s_-]+localhost\b", re.IGNORECASE),
    re.compile(r"\bignore[\s_-]+security[\s_-]+policy\b", re.IGNORECASE),
    re.compile(r"\bbypass[\s_-]+isolation\b", re.IGNORECASE),
]


class PolicyValidator:
    """
    Evaluates workload specifications and operational commands against
    defense-in-depth security policies.
    """

    @classmethod
    def validate_spec(cls, spec: WorkloadSpec) -> list[str]:
        """
        Perform complete validation of a WorkloadSpec.
        Returns a list of detected violations, or raises PolicyViolationError
        if policy rejection is strict.
        """
        violations: list[str] = []

        # 1. Process and command validation
        try:
            cls.validate_command(spec.command, spec.process_policy)
        except PolicyViolationError as err:
            violations.append(str(err))

        # 2. Filesystem path validation
        if spec.cwd:
            try:
                cls.check_relative_path_safety(spec.cwd, spec.filesystem_policy)
            except PolicyViolationError as err:
                violations.append(str(err))

        for artifact in spec.artifact_paths:
            try:
                cls.check_relative_path_safety(artifact, spec.filesystem_policy)
            except PolicyViolationError as err:
                violations.append(str(err))

        # 3. Environment validation & secret scanning
        try:
            cls.validate_env_variables(spec.env, spec.secret_policy)
        except PolicyViolationError as err:
            violations.append(str(err))

        # 4. Resource limits validation
        try:
            cls.validate_resource_limits(spec.resource_limits)
        except PolicyViolationError as err:
            violations.append(str(err))

        # 5. Prompt injection checks on command strings
        for arg in spec.command:
            injection_matches = cls.detect_prompt_injections(arg)
            if injection_matches:
                # Prompt injection strings inside arguments are treated strictly as DATA,
                # but if they appear in commands attempting to bypass security, flag it.
                if any(inj in arg.lower() for inj in ("--privileged", "sudo", "--cap-add")):
                    violations.append(f"Prompt injection authority escalation attempt: {injection_matches}")

        if violations:
            raise PolicyViolationError(
                f"Workload {spec.workload_id} rejected due to security policy violations: {'; '.join(violations)}",
                violation_type="POLICY_REJECTED",
                details={"violations": violations, "workload_id": spec.workload_id},
            )

        return violations

    @classmethod
    def validate_command(cls, argv: list[str], policy: ProcessPolicy) -> None:
        """Validate an argv list against process security policies."""
        if not argv or not isinstance(argv, list):
            raise PolicyViolationError("Command argv must be a non-empty list of strings.", "INVALID_ARGV")

        for idx, arg in enumerate(argv):
            if not isinstance(arg, str):
                raise PolicyViolationError(
                    f"Command element at index {idx} must be a string, got {type(arg).__name__}",
                    "INVALID_ARGV_TYPE",
                )
            if "\x00" in arg:
                raise PolicyViolationError(f"Null byte detected in command argument {idx}.", "NULL_BYTE")

        executable = Path(argv[0]).name.lower()

        # Disallowed binaries
        if executable in policy.disallowed_binaries:
            raise PolicyViolationError(
                f"Executable '{executable}' is strictly prohibited by process policy.",
                "FORBIDDEN_BINARY",
                details={"binary": executable},
            )

        # Prohibited command combinations
        cmd_str = " ".join(argv).lower()
        for forbidden in policy.disallowed_commands:
            if forbidden.lower() in cmd_str:
                raise PolicyViolationError(
                    f"Command contains prohibited sequence: '{forbidden}'",
                    "FORBIDDEN_COMMAND",
                    details={"sequence": forbidden, "command": cmd_str},
                )

        # Privilege escalation attempts
        if any(flag in cmd_str for flag in ("--privileged", "--cap-add", "setuid", "setgid")):
            raise PolicyViolationError(
                "Privilege escalation parameters are strictly prohibited.",
                "PRIVILEGE_ESCALATION",
            )

    @classmethod
    def check_relative_path_safety(cls, path_str: str, policy: FilesystemPolicy) -> None:
        """Ensure a relative path does not attempt traversal or point to sensitive system roots."""
        if not path_str or not path_str.strip():
            raise PolicyViolationError("Path must not be empty.", "EMPTY_PATH")

        clean = path_str.replace("\\", "/")

        # Check for traversal
        if ".." in clean.split("/") or clean.startswith("../") or "/../" in clean or clean.endswith("/.."):
            raise PolicyViolationError(
                f"Path traversal sequence '..' in '{path_str}' is strictly forbidden.",
                "PATH_TRAVERSAL",
                details={"path": path_str},
            )

        # Check for absolute path escapes
        posix = PurePosixPath(clean)
        if posix.is_absolute():
            raise PolicyViolationError(
                f"Absolute path '{path_str}' is forbidden; paths must be relative to sandbox workspace.",
                "ABSOLUTE_PATH",
                details={"path": path_str},
            )

        # Check for disallowed path targets
        for disallowed in policy.disallowed_paths:
            disallowed_clean = disallowed.strip("/").lower()
            if clean.lower() == disallowed_clean or clean.lower().startswith(f"{disallowed_clean}/"):
                raise PolicyViolationError(
                    f"Access to prohibited system path '{path_str}' is blocked.",
                    "FORBIDDEN_PATH",
                    details={"path": path_str, "disallowed": disallowed},
                )

    @classmethod
    def validate_workspace_confinement(cls, workspace_root: Path, target_path: Path, policy: FilesystemPolicy) -> Path:
        """
        Verify that a resolved target path lies strictly inside workspace_root.
        Checks for escaping symlinks.
        """
        root = workspace_root.resolve()
        resolved = target_path.resolve()

        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise PolicyViolationError(
                f"Path '{target_path}' resolves to '{resolved}', which escapes workspace root '{root}'.",
                "WORKSPACE_ESCAPE",
                details={"workspace_root": str(root), "resolved": str(resolved)},
            ) from exc

        # Check symlink breakout if target is a symlink
        if target_path.is_symlink() and not policy.allow_symlinks_outside_root:
            link_dest = target_path.readlink()
            dest_resolved = (target_path.parent / link_dest).resolve()
            try:
                dest_resolved.relative_to(root)
            except ValueError as exc:
                raise PolicyViolationError(
                    f"Symlink '{target_path}' points to '{dest_resolved}' outside workspace root.",
                    "SYMLINK_ESCAPE",
                    details={"link": str(target_path), "dest": str(dest_resolved)},
                ) from exc

        return resolved

    @classmethod
    def validate_network_target(cls, host_or_ip: str, policy: NetworkPolicy) -> None:
        """
        Validate destination network target against NetworkPolicy.
        Default DENY blocks all connections.
        """
        if policy.mode == NetworkMode.DENY:
            raise PolicyViolationError(
                f"Outbound network access to '{host_or_ip}' is blocked by default DENY policy.",
                "NETWORK_BLOCKED",
                details={"target": host_or_ip, "mode": policy.mode},
            )

        host_lower = host_or_ip.strip().lower()

        # Block localhost / loopback
        if policy.block_localhost and host_lower in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            raise PolicyViolationError(
                f"Access to loopback target '{host_or_ip}' is strictly prohibited.",
                "LOOPBACK_BLOCKED",
                details={"target": host_or_ip},
            )

        # Check IP subnets
        try:
            ip_obj = ipaddress.ip_address(host_lower)
            for subnet_str in policy.blocked_subnets:
                subnet = ipaddress.ip_network(subnet_str)
                if ip_obj in subnet:
                    raise PolicyViolationError(
                        f"Access to restricted subnet '{subnet_str}' ({host_or_ip}) is strictly blocked.",
                        "SUBNET_BLOCKED",
                        details={"target": host_or_ip, "subnet": subnet_str},
                    )
        except ValueError:
            # It's a hostname, check allowed hosts
            pass

        if policy.mode == NetworkMode.ALLOWLIST:
            if host_lower not in policy.allowed_hosts:
                raise PolicyViolationError(
                    f"Host '{host_or_ip}' is not in network allowlist.",
                    "HOST_NOT_ALLOWLISTED",
                    details={"target": host_or_ip, "allowed": list(policy.allowed_hosts)},
                )

    @classmethod
    def validate_env_variables(cls, env: dict[str, str], policy: SecretPolicy) -> None:
        """Scan custom environment variables for forbidden keys or prefixes."""
        for key in env:
            # Check disallowed keys
            if key in policy.disallowed_env_keys:
                raise PolicyViolationError(
                    f"Environment variable '{key}' is prohibited by secret policy.",
                    "FORBIDDEN_ENV_KEY",
                    details={"key": key},
                )
            # Check disallowed prefixes
            for prefix in policy.disallowed_env_prefixes:
                if key.upper().startswith(prefix):
                    raise PolicyViolationError(
                        f"Environment variable '{key}' matches prohibited secret prefix '{prefix}'.",
                        "FORBIDDEN_ENV_PREFIX",
                        details={"key": key, "prefix": prefix},
                    )

    @classmethod
    def sanitize_environment(
        cls,
        env: dict[str, str],
        policy: SecretPolicy,
        allowlist: tuple[str, ...] | None = None,
    ) -> dict[str, str]:
        """
        Build a sanitized environment dictionary.
        Strips all host secrets and credentials.
        Only variables matching allowlist are retained.
        """
        effective_allowlist = set(policy.default_env_allowlist)
        if allowlist:
            effective_allowlist.update(allowlist)

        sanitized: dict[str, str] = {}

        for k, v in env.items():
            # Check disallowed prefixes & keys
            if any(k.upper().startswith(p) for p in policy.disallowed_env_prefixes):
                continue
            if k in policy.disallowed_env_keys:
                continue

            # Only retain if in allowlist
            if k in effective_allowlist:
                sanitized[k] = v

        # Set safe baseline defaults
        sanitized["PYTHONUNBUFFERED"] = "1"
        sanitized["GIT_TERMINAL_PROMPT"] = "0"
        return sanitized

    @classmethod
    def validate_resource_limits(cls, limits: ResourceLimits) -> None:
        """Validate resource limits are within sane operational bounds."""
        if limits.timeout_seconds <= 0 or limits.timeout_seconds > 3600:
            raise PolicyViolationError(
                f"Timeout {limits.timeout_seconds}s is out of allowed range (1-3600s).",
                "INVALID_TIMEOUT",
            )
        if limits.max_memory_bytes < 1024 * 1024:  # At least 1 MB
            raise PolicyViolationError(
                f"Memory limit {limits.max_memory_bytes} bytes is too small.",
                "INVALID_MEMORY_LIMIT",
            )

    @classmethod
    def detect_prompt_injections(cls, text: str) -> list[str]:
        """Scan text for common prompt injection sequences trying to hijack security controls."""
        detected = []
        for pattern in PROMPT_INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                detected.append(match.group(0))
        return detected
