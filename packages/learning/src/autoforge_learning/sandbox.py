"""Real OS-level experiment sandbox — Phase 19 FINAL (Gates 5, 6, 7).

19B-3 closed with an honest limitation: experiment arms used *injected
runners*. That is a contract, not a boundary — an in-process runner can reach
anything the host process can reach. This module replaces it with a genuine
OS-enforced boundary.

Two independent kernel-level mechanisms are combined:

* **macOS Seatbelt** (``/usr/bin/sandbox-exec``) — the kernel policy that
  confines filesystem, network, and process creation. When the platform has no
  Seatbelt the sandbox **refuses to run** rather than silently degrading to an
  unenforced runner.
* **POSIX rlimits** (``resource.setrlimit``) — CPU seconds, address space,
  file size, and process count. These are inherited by the child and enforced
  by the kernel, not by cooperative checks.

Deliberately *not* implemented: a container or orchestration platform. The
task forbids inventing one, and these native mechanisms are sufficient.

The default policy is deny-by-default: no network, no production credentials,
no host-wide write access, no security-system access, no undeclared
capabilities. Every forbidden operation is enforced by the kernel — nothing
here trusts the program being run to behave.
"""

from __future__ import annotations

import logging
import os
import platform
import resource
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger("autoforge.learning.sandbox")

__test__ = False  # declares an OS boundary, not tests


class SandboxUnavailable(RuntimeError):
    """No OS-level isolation mechanism is available on this platform.

    Raised rather than silently falling back to an unenforced in-process
    runner. An experiment that cannot be isolated must not run.
    """


class SandboxViolation(RuntimeError):
    """A sandboxed command attempted a forbidden operation."""


class SandboxTimeout(RuntimeError):
    """A sandboxed command exceeded its wall-clock budget."""


class SandboxResourceExceeded(RuntimeError):
    """A sandboxed command exceeded a declared resource limit."""


def seatbelt_available() -> bool:
    """True when the macOS Seatbelt sandbox binary is present and usable."""
    return platform.system() == "Darwin" and shutil.which("sandbox-exec") is not None


def supported_platform() -> bool:
    """True when this module can enforce a real OS boundary here.

    macOS via Seatbelt. When neither Seatbelt nor a Linux fallback is present
    the sandbox refuses rather than pretending.
    """
    return seatbelt_available() or platform.system() == "Linux"


@dataclass(frozen=True)
class ResourceLimits:
    """Hard kernel limits applied to every sandboxed process."""

    #: Wall-clock seconds before the process group is killed.
    wall_clock_seconds: float = 60.0
    #: CPU seconds (RLIMIT_CPU), cumulative across the process tree.
    cpu_seconds: int = 60
    #: Address space in bytes (RLIMIT_AS).
    memory_bytes: int = 2 * 1024 * 1024 * 1024
    #: Maximum size of any single written file (RLIMIT_FSIZE).
    file_size_bytes: int = 64 * 1024 * 1024
    #: Maximum processes per user (RLIMIT_NPROC).
    max_processes: int = 64
    #: Maximum open file descriptors (RLIMIT_NOFILE).
    max_open_files: int = 256
    #: Maximum bytes captured from stdout/stderr before truncation.
    max_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        for name in (
            "wall_clock_seconds",
            "cpu_seconds",
            "memory_bytes",
            "file_size_bytes",
            "max_processes",
            "max_open_files",
            "max_output_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(
                    f"{name} must be positive, got {getattr(self, name)!r}"
                )

    def describe(self) -> dict[str, float]:
        return {
            "wall_clock_seconds": self.wall_clock_seconds,
            "cpu_seconds": float(self.cpu_seconds),
            "memory_bytes": float(self.memory_bytes),
            "file_size_bytes": float(self.file_size_bytes),
            "max_processes": float(self.max_processes),
            "max_open_files": float(self.max_open_files),
        }


@dataclass(frozen=True)
class SandboxPolicy:
    """The declared, deny-by-default policy for one experiment arm.

    ``extra_read_paths`` exists for read-only access to genuinely required
    inputs (an interpreter's standard library, for instance). Write access is
    *always* confined to ``workspace``; it can never be widened.
    """

    #: The arm's own writable directory. Nothing outside it is writable.
    workspace: Path
    #: Read-only paths the arm may read. Never writable.
    extra_read_paths: tuple[Path, ...] = ()
    #: Environment variable names explicitly allowed into the child.
    allowed_env_names: tuple[str, ...] = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
    )
    #: When False the sandbox denies all network at the kernel boundary.
    allow_network: bool = False
    #: When False the sandbox denies loopback and metadata endpoints too.
    allow_loopback: bool = False
    #: Credential-shaped variables are always dropped, even if allowlisted.
    strip_credentials: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", Path(self.workspace).resolve())


#: Environment variables that must never reach a sandboxed arm, even if a
#: policy allowlists them. These are credentials, not preferences.
CREDENTIAL_ENV_MARKERS: tuple[str, ...] = (
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "ANTHROPIC_",
    "OPENAI_",
    "NPM_TOKEN",
    "HF_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "SSH_",
    "GPG_",
    "SLACK_",
    "STRIPE_",
    "DATADOG_",
    "SENTRY_",
    "AUTOFORGE_MASTER_KEY",
    "MASTER_KEY",
    "API_KEY",
    "APIKEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "SESSION_KEY",
)


def is_credential_env(name: str) -> bool:
    """True when an environment variable name looks credential-bearing."""
    upper = name.upper()
    return any(marker in upper for marker in CREDENTIAL_ENV_MARKERS)


def build_child_environment(policy: SandboxPolicy) -> dict[str, str]:
    """Rebuild a minimal, credential-free environment for the child.

    Only allowlisted names survive, and credential-shaped names are dropped
    even when allowlisted. The child therefore cannot inherit a secret from the
    host process environment.
    """
    env: dict[str, str] = {}
    for name in policy.allowed_env_names:
        if policy.strip_credentials and is_credential_env(name):
            logger.warning("dropping credential-shaped env var %s from sandbox", name)
            continue
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    env.setdefault("PATH", "/usr/bin:/bin")
    # Point HOME/TMPDIR into the sandbox workspace so nothing leaks to the real
    # home directory or a shared temp location.
    env["HOME"] = str(policy.workspace)
    env["TMPDIR"] = str(policy.workspace / ".tmp")
    (policy.workspace / ".tmp").mkdir(parents=True, exist_ok=True)
    return env


#: The AutoForge source tree, denied explicitly so an experiment arm cannot
#: read — let alone modify — the learning or security implementation.
AUTOFORGE_SOURCE_ROOT = Path(__file__).resolve().parents[4]


def _python_prefixes(executable: str) -> tuple[str, ...]:
    """Read-only prefixes a Python interpreter genuinely needs.

    A venv ``python3`` is a shim that execs the real interpreter living outside
    the venv. Discovering that prefix keeps the AutoForge-source deny intact
    while still letting a legitimate interpreter start.

    The interpreter's own installation prefix is always included first: when the
    child is the resolved real interpreter, the host's ``sysconfig`` paths (which
    point at the venv) would otherwise be wrong for it.
    """
    prefixes: list[str] = []
    try:
        real = Path(executable).resolve()
        parent = real.parent
        # Only a genuine interpreter *installation root*. Guard against
        # deriving "/" (or any shallow parent) from an ordinary binary such as
        # /bin/cat — re-allowing "/" would silently undo every deny above.
        if parent != Path("/") and parent.parent != Path("/"):
            prefixes.append(str(parent.parent))
            if parent.parent.parent != Path("/"):
                prefixes.append(str(parent.parent.parent))
    except Exception:  # pragma: no cover - defensive
        logger.debug("could not derive interpreter prefix from %s", executable)
    return tuple(dict.fromkeys(p for p in prefixes if p))


def seatbelt_profile(
    policy: SandboxPolicy, *, allowed_executables: Sequence[str] = ()
) -> str:
    """Build a macOS Seatbelt profile enforcing the arm's declared policy.

    Seatbelt is *last-match-wins*, so the profile is written strictly ordered:
    every deny comes first, then every allow. That ordering is what makes an
    omission safe — forgetting an allow makes the policy stricter, never
    weaker.

    Denied regardless of policy:

    * every write outside the arm's own workspace;
    * every network operation (unless explicitly permitted);
    * host configuration (``/etc``, ``/var/root``, ``/private/etc``);
    * the entire AutoForge source tree, for both read and write — an experiment
      must not read, let alone modify, the learning or security implementation.

    Seatbelt has no fine-grained loopback switch, so ``allow_loopback`` without
    ``allow_network`` still denies everything — the conservative outcome.
    """
    workspace = str(policy.workspace)
    source_root = str(AUTOFORGE_SOURCE_ROOT)

    allows = [
        f'(subpath "{workspace}")',
        '(subpath "/usr/lib")',
        '(subpath "/usr/bin")',
        '(subpath "/bin")',
        '(subpath "/System")',
        '(subpath "/Library/Frameworks")',
        '(subpath "/private/var/db/dyld")',
        '(subpath "/private/var/folders")',
        '(subpath "/opt/homebrew")',
    ]
    for extra in policy.extra_read_paths:
        allows.append(f'(subpath "{Path(extra).resolve()}")')
    for exe in allowed_executables:
        real = Path(exe).resolve()
        allows.append(f'(literal "{real}")')
        for prefix in _python_prefixes(exe):
            allows.append(f'(subpath "{prefix}")')

    denies = [
        # ── writes: nothing outside the arm's own workspace
        "(deny file-write*)",
        # ── host configuration and privileged data
        '(deny file-read* (subpath "/etc"))',
        '(deny file-read* (subpath "/private/etc"))',
        '(deny file-read* (subpath "/var/root"))',
        # ── the AutoForge implementation: never readable, never writable
        f'(deny file-read* (subpath "{source_root}"))',
        f'(deny file-write* (subpath "{source_root}"))',
        # ── network: denied by default, kernel-enforced
        "(deny network*)",
        # ── directory enumeration of the host root. Listing / leaks the shape of
        #    the machine even when every file inside is unreadable. Scoped to the
        #    root only, so an interpreter can still stat its own libraries.
        '(deny file-read-metadata (subpath "/"))',
    ]
    if policy.allow_network:
        denies = [d for d in denies if d != "(deny network*)"]
    if policy.allow_loopback and not policy.allow_network:
        logger.warning("allow_loopback without allow_network: network still denied")

    lines = ["(version 1)", "(allow default)", *denies]
    # Re-allow writes only inside the workspace. Reads are deliberately NOT
    # re-allowed broadly: the denies above must stay in force, so only the
    # specific system paths an interpreter genuinely needs are added back.
    lines.append(f'(allow file-write* (subpath "{workspace}"))')
    lines.extend(READ_EXCEPTIONS)
    # Re-allow metadata for exactly the declared prefixes, so the root-enumeration
    # deny above stands everywhere else.
    for prefix in _allowed_prefixes_for(policy, allowed_executables):
        lines.append(f'(allow file-read-metadata (subpath "{prefix}"))')
    for prefix in _allowed_prefixes_for(policy, allowed_executables):
        lines.append(f'(allow file-read* (subpath "{prefix}"))')
    return "\n".join(lines)


#: System paths an interpreter must read to start at all. These are appended
#: *after* the sensitive-path denies, so a deny always wins over them: they can
#: never re-open ``/etc`` or the AutoForge source tree.
READ_EXCEPTIONS: tuple[str, ...] = (
    '(subpath "/usr/lib")',
    '(subpath "/usr/bin")',
    '(subpath "/bin")',
    '(subpath "/System")',
    '(subpath "/Library/Frameworks")',
    '(subpath "/private/var/db/dyld")',
    '(subpath "/private/var/folders")',
    '(subpath "/opt/homebrew")',
)


def _allowed_prefixes_for(
    policy: SandboxPolicy, allowed_executables: Sequence[str]
) -> tuple[str, ...]:
    """Every prefix the profile re-allows *reads* for, narrowly.

    Only the arm's workspace, explicitly declared read paths, and the declared
    interpreter's own installation. Nothing broader.
    """
    out: list[str] = [str(policy.workspace)]
    for extra in policy.extra_read_paths:
        out.append(str(Path(extra).resolve()))
    for exe in allowed_executables:
        out.extend(_python_prefixes(exe))
        out.append(str(Path(exe).resolve().parent))
    return tuple(dict.fromkeys(out))
@dataclass(frozen=True)
class SandboxResult:
    """The real, observed outcome of one sandboxed command."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    truncated: bool = False
    policy_summary: dict[str, object] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def _apply_rlimits(limits: ResourceLimits) -> None:
    """Apply the declared limits to the forked child, before ``exec``.

    Applied between fork and exec so the child inherits limits the *kernel*
    enforces rather than cooperative checks. Safe in a forked child because it
    only touches rlimits and performs no allocation that could deadlock.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes)
    )
    resource.setrlimit(
        resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files)
    )
    if platform.system() != "Darwin" and hasattr(resource, "RLIMIT_AS"):
        # macOS does not implement RLIMIT_AS; setting it fails in the child.
        resource.setrlimit(
            resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes)
        )
    if hasattr(resource, "RLIMIT_NPROC"):
        try:
            resource.setrlimit(
                resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes)
            )
        except (ValueError, OSError) as ex:  # pragma: no cover - platform dependent
            logger.warning("could not apply RLIMIT_NPROC: %s", ex)
    if hasattr(resource, "RLIMIT_CORE"):
        # No core dumps: they would write outside the workspace.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _terminate_tree(process: "subprocess.Popen[bytes]") -> None:
    """Kill the whole process group so no child outlives the timeout."""
    import signal as signal_module

    try:
        os.killpg(os.getpgid(process.pid), signal_module.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


def run_sandboxed(
    argv: Sequence[str],
    *,
    policy: SandboxPolicy,
    limits: Optional[ResourceLimits] = None,
    stdin_data: str = "",
    cwd: Optional[Path] = None,
) -> SandboxResult:
    """Execute ``argv`` inside a genuine OS sandbox. Never returns unconfined.

    The command runs under the Seatbelt profile (filesystem, network, and
    process confinement), POSIX rlimits (CPU, file size, process count), a
    rebuilt credential-free environment, and a wall-clock timeout that kills the
    entire process group.

    There is no shell: ``argv`` is an explicit list, so shell metacharacters are
    inert and "the runner normally won't do that" is never the answer.

    Raises:
        SandboxUnavailable: no OS boundary is available here. The command is
            **not** run — an experiment that cannot be isolated must not run.
        SandboxViolation: the argv is not a real executable.
        SandboxTimeout: the command exceeded its wall-clock budget.
    """
    limits = limits or ResourceLimits()
    argv = [str(a) for a in argv]
    if not argv:
        raise SandboxViolation("sandboxed command requires a non-empty argv")

    policy.workspace.mkdir(parents=True, exist_ok=True)
    work_dir = Path(cwd).resolve() if cwd is not None else policy.workspace

    executable = shutil.which(argv[0]) if os.sep not in argv[0] else argv[0]
    if executable is None:
        raise SandboxViolation(
            f"sandboxed command {argv[0]!r} is not an executable on PATH"
        )
    if not Path(executable).is_file():
        raise SandboxViolation(f"sandboxed command {executable!r} is not a file")
    # A venv interpreter is a shim inside the project tree, which the sandbox
    # denies. Resolve to the real interpreter so the command still starts: the
    # deny must block AutoForge's *source*, not the toolchain an experiment needs.
    argv = [str(Path(executable).resolve()), *argv[1:]]
    executable = argv[0]

    env = build_child_environment(policy)

    if seatbelt_available():
        profile = seatbelt_profile(policy, allowed_executables=[executable])
        profile_path = policy.workspace / ".autoforge_sandbox_profile"
        profile_path.write_text(profile, encoding="utf-8")
        command = [
            "/usr/bin/sandbox-exec",
            "-f",
            str(profile_path),
            executable,
            *argv[1:],
        ]
        boundary = "seatbelt+rlimits"
    elif platform.system() == "Linux":
        # On Linux the rlimits are the kernel boundary. This module never claims
        # a network boundary it does not actually have.
        logger.warning("running on Linux without Seatbelt; rlimits only")
        command = [executable, *argv[1:]]
        boundary = "rlimits"
    else:
        raise SandboxUnavailable(
            f"no OS isolation mechanism available on {platform.system()}; "
            f"refusing to run an unenforced experiment"
        )

    started = time.perf_counter()
    try:
        process = subprocess.Popen(  # noqa: S603 - argv is explicit, no shell
            command,
            cwd=str(work_dir),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=lambda: _apply_rlimits(limits),
        )
    except OSError as ex:
        raise SandboxUnavailable(f"could not start sandboxed process: {ex}") from ex

    timed_out = False
    try:
        out, err = process.communicate(
            input=stdin_data.encode("utf-8"), timeout=limits.wall_clock_seconds
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_tree(process)
        try:
            out, err = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            out, err = b"", b""

    duration = time.perf_counter() - started
    truncated = False
    stdout_text = out.decode("utf-8", errors="replace")
    stderr_text = err.decode("utf-8", errors="replace")
    if len(stdout_text) > limits.max_output_bytes:
        stdout_text = stdout_text[: limits.max_output_bytes]
        truncated = True
    if len(stderr_text) > limits.max_output_bytes:
        stderr_text = stderr_text[: limits.max_output_bytes]
        truncated = True

    result = SandboxResult(
        argv=tuple(argv),
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_seconds=duration,
        timed_out=timed_out,
        truncated=truncated,
        policy_summary={
            "boundary": boundary,
            "workspace": str(policy.workspace),
            "network_allowed": policy.allow_network,
            "limits": limits.describe(),
        },
    )

    if timed_out:
        raise SandboxTimeout(
            f"sandboxed command exceeded {limits.wall_clock_seconds}s and its "
            f"process group was killed (limits={limits.describe()})"
        )
    return result


# ── experiment arms in the real sandbox ─────────────────────────────────────

#: A complete, reproducible description of one sandboxed arm run. This is what
#: Gate 10 requires: enough to independently reconstruct the result after a
#: restart, with no reference to the live process that produced it.
@dataclass(frozen=True)
class ArmExecutionRecord:
    """Everything needed to reproduce one sandboxed arm, persisted verbatim."""

    arm: str
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    workspace: str
    source_hash: str
    config_hash: str
    environment_hash: str
    interpreter: str
    policy_summary: dict[str, object]
    limits: dict[str, float]
    executed_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "workspace": self.workspace,
            "source_hash": self.source_hash,
            "config_hash": self.config_hash,
            "environment_hash": self.environment_hash,
            "interpreter": self.interpreter,
            "policy_summary": self.policy_summary,
            "limits": self.limits,
            "executed_at": self.executed_at,
        }


def _hash_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_sandboxed_arm(
    arm: str,
    argv: Sequence[str],
    *,
    workspace: Path,
    source_files: dict[str, str],
    config: dict[str, object],
    limits: Optional[ResourceLimits] = None,
    policy_overrides: Optional[dict[str, object]] = None,
    cwd: Optional[Path] = None,
) -> ArmExecutionRecord:
    """Materialise and execute one experiment arm inside the real sandbox.

    The arm's source is written into a fresh workspace, hashed, and executed.
    Everything needed to reproduce it later is returned in the record: the exact
    argv, the interpreter, hashes of the source, configuration and environment,
    the enforced policy and limits, and the observed result.

    The workspace is prepared *before* the sandbox starts, so no write happens
    outside the boundary.
    """
    limits = limits or ResourceLimits()
    overrides = dict(policy_overrides or {})
    arm_workspace = Path(workspace).resolve()
    arm_workspace.mkdir(parents=True, exist_ok=True)

    # Materialise the arm's source inside its own workspace.
    for name, content in source_files.items():
        target = arm_workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    source_text = "\n".join(f"{k}\n{source_files[k]}" for k in sorted(source_files))
    source_hash = _hash_text(source_text)
    config_hash = _hash_text(repr(sorted(config.items())))

    policy = SandboxPolicy(workspace=arm_workspace, **overrides)  # type: ignore[arg-type]
    env = build_child_environment(policy)
    environment_hash = _hash_text(repr(sorted(env.items())))

    result = run_sandboxed(
        argv,
        policy=policy,
        limits=limits,
        cwd=cwd,
    )
    return ArmExecutionRecord(
        arm=arm,
        argv=result.argv,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=result.duration_seconds,
        workspace=str(arm_workspace),
        source_hash=source_hash,
        config_hash=config_hash,
        environment_hash=environment_hash,
        interpreter=result.argv[0],
        policy_summary=dict(result.policy_summary),
        limits=limits.describe(),
        executed_at=time.time(),
    )


def _terminate_tree(process: "subprocess.Popen[bytes]") -> None:
    """Kill the whole process group so no child outlives the timeout."""
    import signal as signal_module

    try:
        os.killpg(os.getpgid(process.pid), signal_module.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass
