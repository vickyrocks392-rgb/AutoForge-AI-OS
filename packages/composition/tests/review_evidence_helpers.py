"""
A real, reviewable project deliverable, registered through the AUTHORITATIVE
18-K durable artifact pipeline.

DEF-P1-EVIDENCE. The production final review is a mandatory quality gate
(``architecture/ARCHITECTURE.md`` section 10). The engineering loop records
evaluation / diagnosis / diff / execution-log artifacts, but the *generated
deliverable itself* (source, tests, documentation) is written to the workspace
filesystem rather than registered as a durable artifact. With no live model
reachable in CI, a project therefore ends up with genuinely zero reviewable
content, and the Review Engine's documented ``required_documentation`` check
correctly rejects it.

This helper registers a real deliverable through the SAME durable catalog the
platform uses in production (``DurableArtifactCatalog`` + ``PhysicalArtifactStore``,
staged write -> SHA-256 -> atomic publish -> commit). It fabricates nothing and
bypasses nothing: the content is written to the physical store and the real
Review Engine evaluates the real bytes.
"""

from __future__ import annotations

import hashlib

from autoforge_runtime.models import DurableArtifactStatus

#: A minimal but genuine greenfield deliverable. The review policy requires
#: ``README.md``; the code and test files give the other deterministic reviewers
#: (architecture, code, security, performance) real content to evaluate.
PROJECT_DELIVERABLE: dict[str, str] = {
    "README.md": (
        "# Payment Webhook Service\n"
        "\n"
        "## Overview\n"
        "\n"
        "A minimal authenticated payment webhook service.\n"
    ),
    "app.py": (
        '"""Minimal payment webhook service."""\n'
        "\n"
        "\n"
        "def verify_signature(payload: str, signature: str) -> bool:\n"
        '    """Return True when the signature matches the payload."""\n'
        "    return signature == f'sig:{len(payload)}'\n"
        "\n"
        "\n"
        "def handle(event: dict) -> dict:\n"
        '    """Handle an incoming payment event."""\n'
        "    if not verify_signature(event.get('body', ''), event.get('signature', '')):\n"
        '        return {"status": "rejected"}\n'
        '    return {"status": "accepted", "id": event.get("id")}\n'
    ),
    "test_app.py": (
        '"""Tests for the payment webhook service."""\n'
        "\n"
        "from app import handle, verify_signature\n"
        "\n"
        "\n"
        "def test_verify_signature_accepts_matching_signature():\n"
        "    assert verify_signature('abc', 'sig:3') is True\n"
        "\n"
        "\n"
        "def test_handle_rejects_bad_signature():\n"
        "    assert handle({'body': 'abc', 'signature': 'bad'})['status'] == 'rejected'\n"
    ),
}


def register_project_deliverable(
    system,
    workflow_id: str,
    *,
    files: dict[str, str] | None = None,
) -> list[str]:
    """Register real deliverable files as COMMITTED durable artifacts.

    Returns the list of registered artifact names. Uses only the existing 18-K
    durable-artifact API, so it exercises the same path production uses.
    """
    catalog = system.durable_catalog
    store = system.physical_store
    payload = dict(PROJECT_DELIVERABLE if files is None else files)

    names: list[str] = []
    for name, content in payload.items():
        data = content.encode("utf-8")
        key = f"deliverable:{workflow_id}:{name}"
        durable_state = catalog.register_artifact(
            artifact_key=key,
            artifact_name=name,
            artifact_type="source",
            workflow_id=workflow_id,
            task_id="delivery",
        )
        artifact_id = durable_state.artifact_id
        digest = hashlib.sha256(data).hexdigest()

        if durable_state.status is DurableArtifactStatus.COMMITTED:
            if state.content_hash != digest:
                raise AssertionError(
                    f"deliverable {name} already committed with different content"
                )
        else:
            staging = store.create_staging_file(key)
            catalog.begin_staging(artifact_id, staging_path=str(staging))
            written_hash, size = store.write_staging_bytes(staging, data)
            published = store.atomic_publish(
                staging, name, expected_hash=written_hash, expected_size=size
            )
            catalog.commit_artifact(
                artifact_id,
                storage_path=str(published),
                content_hash=written_hash,
                size_bytes=size,
            )
        names.append(name)
    return names
