"""Phase 19 FINAL — real OS sandbox tests (Gates 5, 6, 7, 10).

Every escape attempt must be stopped by the **kernel**, not by a cooperative
check inside the runner. "The runner normally won't do that" is explicitly not
accepted as evidence.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from autoforge_learning.sandbox import (
    AUTOFORGE_SOURCE_ROOT,
    ResourceLimits,
    SandboxPolicy,
    SandboxTimeout,
    SandboxViolation,
    is_credential_env,
    run_sandboxed,
    run_sandboxed_arm,
    seatbelt_available,
    supported_platform,
)

pytestmark = pytest.mark.skipif(
    not supported_platform(),
    reason="no OS isolation mechanism available on this platform",
)

LIMITS = ResourceLimits(wall_clock_seconds=30, cpu_seconds=15)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "arm-workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def policy(workspace: Path) -> SandboxPolicy:
    return SandboxPolicy(workspace=workspace)


def run(argv, policy, limits=LIMITS):
    return run_sandboxed(argv, policy=policy, limits=limits)


# ── Gate 5: the boundary is real and the default is deny ─────────────────────


def test_the_sandbox_actually_engages_a_kernel_boundary(policy):
    result = run(["/bin/echo", "alive"], policy)
    assert result.exit_code == 0
    assert result.stdout.strip() == "alive"
    # The policy summary records which boundary was enforced, not just asserted.
    assert result.policy_summary["boundary"] in ("seatbelt+rlimits", "rlimits")


def test_python_executes_inside_the_sandbox(policy, workspace):
    """A legitimate interpreter must still start — the sandbox is not a brick."""
    python = shutil.which("python3")
    script = workspace / "arm.py"
    script.write_text("import hashlib; print('ran', hashlib.sha256(b'x').hexdigest()[:8])")
    result = run([python, str(script)], policy)
    assert result.exit_code == 0, result.stderr[:400]
    assert "ran " in result.stdout


# ── Gate 6: every escape attempt fails closed ────────────────────────────────


def test_path_traversal_out_of_the_workspace_is_denied(policy):
    """A relative escape cannot address anything outside the sandbox."""
    result = run(["/bin/cat", "../../../../../../etc/passwd"], policy)
    assert not result.stdout.strip()


def test_absolute_host_path_read_is_denied(policy):
    result = run(["/bin/cat", "/etc/passwd"], policy)
    assert result.exit_code != 0
    assert not result.stdout.strip()


def test_autoforge_source_read_is_denied(policy):
    """An arm cannot even read the learning/security implementation."""
    target = (
        AUTOFORGE_SOURCE_ROOT
        / "packages/security/src/autoforge_security/ai_guardrails.py"
    )
    result = run(["/bin/cat", str(target)], policy)
    assert result.exit_code != 0
    assert not result.stdout.strip()


def test_autoforge_source_write_is_denied(policy):
    """An arm cannot modify the AutoForge implementation."""
    target = AUTOFORGE_SOURCE_ROOT / ".sandbox-escape-probe"
    try:
        result = run(["/usr/bin/touch", str(target)], policy)
        assert result.exit_code != 0
        assert not target.exists()
    finally:
        if target.exists():  # pragma: no cover - only if the escape succeeded
            target.unlink()
            pytest.fail("sandbox allowed a write into the AutoForge source tree")


def test_write_outside_the_workspace_is_denied(policy, tmp_path):
    outside = tmp_path / "escaped.txt"
    result = run(["/usr/bin/touch", str(outside)], policy)
    assert result.exit_code != 0
    assert not outside.exists()


def test_parent_directory_enumeration_is_denied(policy):
    result = run(["/bin/ls", "/"], policy)
    assert not result.stdout.strip()


def test_network_access_is_denied(policy):
    result = run(
        ["/usr/bin/curl", "-s", "--max-time", "5", "https://example.com"], policy
    )
    assert result.exit_code != 0
    assert not result.stdout.strip()


def test_loopback_access_is_denied(policy):
    """Loopback is a common SSRF pivot and is denied by default."""
    result = run(
        ["/usr/bin/curl", "-s", "--max-time", "3", "http://127.0.0.1:9/"], policy
    )
    assert result.exit_code != 0
    assert not result.stdout.strip()


def test_cloud_metadata_access_is_denied(policy):
    result = run(
        ["/usr/bin/curl", "-s", "--max-time", "3", "http://169.254.169.254/"],
        policy,
    )
    assert result.exit_code != 0
    assert not result.stdout.strip()


def test_environment_credentials_never_reach_the_child(policy, monkeypatch):
    """Credentials in the host environment are not inherited."""
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "hunter2")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecret")
    monkeypatch.setenv("AUTOFORGE_MASTER_KEY", "master")
    result = run(["/usr/bin/env"], policy)
    assert "hunter2" not in result.stdout
    assert "ghp_supersecret" not in result.stdout
    assert "AWS_SECRET_ACCESS_KEY" not in result.stdout
    assert "GITHUB_TOKEN" not in result.stdout


def test_home_and_tmp_are_redirected_into_the_workspace(policy, workspace):
    result = run(["/usr/bin/env"], policy)
    assert f"HOME={workspace}" in result.stdout
    assert f"TMPDIR={workspace}/.tmp" in result.stdout


@pytest.mark.parametrize(
    "name",
    ["AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "AUTOFORGE_MASTER_KEY", "DB_PASSWORD"],
)
def test_credential_shaped_variables_are_recognised(name):
    assert is_credential_env(name)


def test_ordinary_variables_are_not_treated_as_credentials():
    for benign in ("PATH", "HOME", "LANG", "PYTHONUNBUFFERED"):
        assert not is_credential_env(benign)


def test_a_nonexistent_executable_is_refused(policy):
    with pytest.raises(SandboxViolation):
        run(["/definitely/not/a/real/binary"], policy)


def test_an_empty_argv_is_refused(policy):
    with pytest.raises(SandboxViolation):
        run_sandboxed([], policy=policy, limits=LIMITS)


# ── Gate 7: resource governance terminates safely ────────────────────────────


def test_an_infinite_loop_is_terminated_by_the_wall_clock(policy):
    """An unbounded loop is killed; it never hangs the experiment."""
    python = shutil.which("python3")
    script = policy.workspace / "spin.py"
    script.write_text("while True:\n    pass\n")
    tight = ResourceLimits(wall_clock_seconds=3, cpu_seconds=10)
    with pytest.raises(SandboxTimeout):
        run_sandboxed([python, str(script)], policy=policy, limits=tight)


def test_cpu_limit_is_enforced_by_the_kernel(policy):
    python = shutil.which("python3")
    script = policy.workspace / "burn.py"
    script.write_text("x=0\nwhile True:\n    x+=1\n")
    tiny = ResourceLimits(wall_clock_seconds=20, cpu_seconds=2)
    result = run_sandboxed([python, str(script)], policy=policy, limits=tiny)
    # RLIMIT_CPU terminates the child rather than running forever.
    assert result.exit_code != 0


def test_limits_must_be_positive():
    with pytest.raises(ValueError):
        ResourceLimits(wall_clock_seconds=0)
    with pytest.raises(ValueError):
        ResourceLimits(memory_bytes=-1)


def test_output_is_captured_with_a_declared_bound(policy):
    python = shutil.which("python3")
    script = policy.workspace / "chatty.py"
    script.write_text("print('x' * 200000)\n")
    bounded = ResourceLimits(
        wall_clock_seconds=30, cpu_seconds=15, max_output_bytes=1000
    )
    result = run_sandboxed([python, str(script)], policy=policy, limits=bounded)
    assert result.truncated is True
    assert len(result.stdout) <= 1000


# ── Gate 10: an arm run is fully reproducible ─────────────────────────────────


def test_an_arm_run_records_everything_needed_to_reproduce(workspace):
    python = shutil.which("python3")
    record = run_sandboxed_arm(
        "treatment",
        [python, "arm.py"],
        workspace=workspace / "treatment",
        source_files={
            "arm.py": "import json; print(json.dumps({'latency_ms': 80.0}))"
        },
        config={"strategy": "faster"},
        limits=LIMITS,
    )
    payload = record.to_dict()
    for field in (
        "arm",
        "argv",
        "exit_code",
        "stdout",
        "config_hash",
        "environment_hash",
        "source_hash",
        "interpreter",
        "policy_summary",
        "limits",
        "executed_at",
    ):
        assert field in payload
    assert record.arm == "treatment"
    assert json.loads(record.stdout)["latency_ms"] == 80.0


def test_a_recorded_arm_run_can_be_replayed_independently(workspace):
    """Re-run the recorded argv + source; the result reproduces."""
    python = shutil.which("python3")
    source = {"arm.py": "print('deterministic-output')"}
    first = run_sandboxed_arm(
        "control", [python, "arm.py"], workspace=workspace / "c1",
        source_files=source, config={"strategy": "baseline"}, limits=LIMITS,
    )
    second = run_sandboxed_arm(
        "control", [python, "arm.py"], workspace=workspace / "c2",
        source_files=source, config={"strategy": "baseline"}, limits=LIMITS,
    )
    assert first.stdout == second.stdout == "deterministic-output\n"
    assert first.source_hash == second.source_hash
    assert first.config_hash == second.config_hash
    assert first.exit_code == second.exit_code == 0


def test_different_configurations_hash_differently(workspace):
    python = shutil.which("python3")
    source = {"arm.py": "print('x')"}
    a = run_sandboxed_arm(
        "c", [python, "arm.py"], workspace=workspace / "a",
        source_files=source, config={"strategy": "a"}, limits=LIMITS,
    )
    b = run_sandboxed_arm(
        "c", [python, "arm.py"], workspace=workspace / "b",
        source_files=source, config={"strategy": "b"}, limits=LIMITS,
    )
    assert a.config_hash != b.config_hash
    assert a.source_hash == b.source_hash


def test_control_and_treatment_are_isolated_from_each_other(workspace):
    """Two arms cannot see or overwrite each other's files."""
    python = shutil.which("python3")
    run_sandboxed_arm(
        "control", [python, "arm.py"], workspace=workspace / "control",
        source_files={"arm.py": "open('marker.txt','w').write('control')"},
        config={"arm": "control"}, limits=LIMITS,
    )
    treatment = run_sandboxed_arm(
        "treatment", [python, "arm.py"], workspace=workspace / "treatment",
        source_files={
            "arm.py": (
                "import os\n"
                "open('marker.txt','w').write('treatment')\n"
                "print('sibling_visible', os.path.exists('../control/marker.txt'))\n"
            )
        },
        config={"arm": "treatment"}, limits=LIMITS,
    )
    assert "sibling_visible False" in treatment.stdout
    assert (workspace / "control" / "marker.txt").read_text() == "control"
    assert (workspace / "treatment" / "marker.txt").read_text() == "treatment"
def test_the_declared_limits_are_recorded_in_the_result(policy):
    result = run(["/bin/echo", "x"], policy)
    recorded = result.policy_summary["limits"]
    assert recorded["wall_clock_seconds"] == LIMITS.wall_clock_seconds
    assert recorded["cpu_seconds"] == float(LIMITS.cpu_seconds)
    assert recorded["memory_bytes"] == float(LIMITS.memory_bytes)


def test_output_is_captured_with_a_declared_bound(policy):
    python = shutil.which("python3")
    script = policy.workspace / "chatty.py"
    script.write_text("print('x' * 200000)\n")
    bounded = ResourceLimits(
        wall_clock_seconds=30, cpu_seconds=15, max_output_bytes=1000
    )
    result = run_sandboxed([python, str(script)], policy=policy, limits=bounded)
    assert result.truncated is True
    assert len(result.stdout) <= 1000