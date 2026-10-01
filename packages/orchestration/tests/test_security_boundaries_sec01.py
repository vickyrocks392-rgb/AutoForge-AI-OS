"""
SEC-01 security regression tests.

A shell metacharacter sequence in a sandbox image reference previously reached
``os.system`` through an f-string and executed arbitrary commands.

Invariant: the image reference is data. It must reach the container CLI as an
argv element and never be parsed by a shell.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from autoforge_execution.sandbox.provider import PodmanSandboxProvider

_PROBE = textwrap.dedent(
    """
    import sys
    from autoforge_execution.sandbox.provider import PodmanSandboxProvider
    print(PodmanSandboxProvider(image=sys.argv[1]).is_available())
    """
)


def _probe_is_available(image: str, tmp_path: Path) -> bool:
    """Exercise ``is_available`` against a stub ``podman`` on PATH.

    The stub makes the availability probe genuinely reachable without requiring a
    real container runtime to be installed on the test host.
    """
    stub_dir = tmp_path / "stubbin"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "podman"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, image],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    return proc.stdout.strip() == "True"


@pytest.mark.parametrize(
    "payload",
    [
        "localhost/autoforge-sandbox:latest; touch {marker}",
        "localhost/autoforge-sandbox:latest && touch {marker}",
        "localhost/autoforge-sandbox:latest`touch {marker}`",
        "localhost/autoforge-sandbox:latest$(touch {marker})",
        "localhost/autoforge-sandbox:latest | touch {marker}",
        "localhost/autoforge-sandbox:latest\ntouch {marker}",
    ],
)
def test_sec01_image_reference_cannot_execute_commands(payload, tmp_path):
    """SEC-01: metacharacters in an image reference must not execute anything."""
    marker = tmp_path / "pwned"
    assert not marker.exists()

    _probe_is_available(payload.format(marker=marker), tmp_path)

    assert not marker.exists(), (
        "SEC-01 REGRESSION: sandbox image reference reached a shell and "
        f"executed an injected command (marker={marker})"
    )


def test_sec01_provider_contains_no_shell_probe():
    """SEC-01: the provider must not build a shell string for the image probe."""
    module_file = sys.modules[PodmanSandboxProvider.__module__].__file__
    assert module_file, "cannot locate provider source"
    text = Path(module_file).read_text(encoding="utf-8")

    assert "os.system(" not in text, (
        "SEC-01 REGRESSION: sandbox provider reintroduced os.system()"
    )
    assert '["podman", "image", "exists", self._image]' in text, (
        "SEC-01 REGRESSION: image reference is no longer passed as an argv element"
    )