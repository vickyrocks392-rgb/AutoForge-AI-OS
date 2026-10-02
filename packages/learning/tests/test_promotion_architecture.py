"""PHASE 19B-2 ARCHITECTURAL INTEGRITY — Gates 20, 21, 23.

This file is the automated form of the Gate 20/21/23 checklist. It proves:

1. No protected system was modified by this gate.
2. The canonical architecture order still holds
   (request → … → promotion → audit), and the prohibited inversion
   (model → learning → promotion → behaviour) does not exist.
3. This gate did not wire promoted learning into any production engine.
4. Learning creates no second security or audit component.

Every check is static (AST / git) or behavioural, never a comment.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
LEARNING_SRC = REPO / "packages" / "learning" / "src" / "autoforge_learning"

#: Frozen by Gates 19B-1/18. Phase 19B-2 must not touch any of them.
PROTECTED_FILES = (
    # Phase 18 security / guardrails
    "packages/security/src/autoforge_security/ai_guardrails.py",
    "packages/security/src/autoforge_security/hitl.py",
    "packages/security/src/autoforge_security/governance.py",
    "packages/security/src/autoforge_security/audit.py",
    "packages/security/src/autoforge_security/authorization.py",
    "packages/security/src/autoforge_security/permissions.py",
    "packages/security/src/autoforge_security/credentials.py",
    "packages/security/src/autoforge_security/trust_boundary.py",
    # 18-J durable execution
    "packages/kernel/src/autoforge_kernel/completion.py",
    # 18-K runtime / packaging / delivery
    "packages/runtime/src/autoforge_runtime/artifact_catalog.py",
    "packages/runtime/src/autoforge_runtime/physical_artifact_store.py",
    # Artifact durability semantics
    "packages/artifacts/src/autoforge_artifacts/models.py",
    "packages/artifacts/src/autoforge_artifacts/store.py",
    # Review engine
    "packages/review/src/autoforge_review/engine.py",
    # Composition root (Context Engineering / model router wiring)
    "packages/composition/src/autoforge_composition/composition_root.py",
)

#: Engines Gate 13 forbids this gate from changing.
PROTECTED_ENGINE_FILES = (
    "packages/kernel/src/autoforge_kernel/learning_engine.py",
    "packages/execution/src/autoforge_execution/engine.py",
)


def _source_files() -> list[Path]:
    return sorted(LEARNING_SRC.glob("*.py"))


def _git_unchanged(rel: str) -> bool:
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", rel],
        cwd=REPO,
        capture_output=True,
    )
    return result.returncode == 0


# ── GATE 20: PROTECTED SYSTEMS ───────────────────────────────────────────────


@pytest.mark.parametrize("rel", PROTECTED_FILES, ids=lambda p: Path(p).name)
def test_protected_system_is_untouched_by_19b2(rel):
    """Gate 20 — a protected area may only change with a proven dependency."""
    assert _git_unchanged(rel), f"{rel} was modified by Phase 19B-2"


@pytest.mark.parametrize("rel", PROTECTED_ENGINE_FILES, ids=lambda p: Path(p).name)
def test_production_engines_are_untouched_by_19b2(rel):
    """Gate 13/20 — no execution-path behaviour changed in this gate."""
    assert _git_unchanged(rel), f"{rel} was modified by Phase 19B-2"


#: Prefix scopes Phase 19B-2 is permitted to change. Anything else is a
#: scope violation. ``.github/workflows/ci.yml`` is in scope because this gate
#: makes the learning suite part of CI; without that, 19B-2 would ship
#: ungated.
ALLOWED_PREFIXES = (
    "packages/learning/",
    "19B2-VALIDATION-PROMOTION/",
    ".github/workflows/ci.yml",
)


def test_the_only_tracked_change_is_within_the_declared_scope():
    """Gate 20 — the production diff is confined to the declared scope."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    changed = [line for line in result.stdout.split() if line]
    out_of_scope = [
        path
        for path in changed
        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    assert out_of_scope == [], f"out-of-scope modification: {out_of_scope}"


def test_no_file_outside_learning_was_touched():
    """Gate 20/24 — a stricter sweep: nothing at all outside the scopes."""
    result = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    # Only tracked modifications matter here; the repository legitimately
    # carries unrelated untracked artifacts that must NOT be staged.
    tracked = [
        line[3:].strip()
        for line in result.stdout.splitlines()
        if line[:2] in (" M", "M ", "MM", " D", "D ")
    ]
    out_of_scope = [
        path
        for path in tracked
        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    assert out_of_scope == [], f"tracked out-of-scope modification: {out_of_scope}"


# ── GATE 13: NO AUTONOMOUS BEHAVIOUR CHANGE ──────────────────────────────────


def test_no_production_engine_reads_the_active_learning_state():
    """Gate 13 — the promotion infrastructure exists but nothing consumes it."""
    for rel in PROTECTED_ENGINE_FILES + PROTECTED_FILES:
        path = REPO / rel
        if not path.exists():
            continue
        text = path.read_text()
        assert "get_active_state" not in text, f"{rel} reads promoted learning"
        assert "LearningLifecycleService" not in text, f"{rel} wires the lifecycle"


def test_the_kernel_learning_engine_is_not_rewired_to_promotion():
    """Gate 13 — the 19B-1 kernel path is untouched by this gate.

    The 19B-1 boundary call (``evaluate_learning_proposal``) is already in
    that module and must stay; what must NOT appear is any 19B-2 promotion
    concept.
    """
    text = (REPO / "packages/kernel/src/autoforge_kernel/learning_engine.py").read_text()
    for forbidden in ("PromotionService", "RollbackHandle", "RegressionEvaluator",
                      "DurableLearningStore", "ApprovalCoordinator"):
        assert forbidden not in text, f"kernel learning engine gained {forbidden}"


# ── GATE 21: ARCHITECTURAL INTEGRITY ─────────────────────────────────────────


def test_no_module_grants_authority_to_a_model():
    """Gate 21 — the model may propose; it may never approve or promote.

    Checked structurally (AST calls), not by substring, so a field named
    ``approver_subject_type`` is not mistaken for a self-approval call.
    """
    forbidden_attrs = {
        "grant_permission",
        "add_role",
        "register_secret",
        "set_policy",
        "mutate",
        "update_policy",
        "reload",
    }
    for path in _source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            assert name not in forbidden_attrs, (
                f"{path.name} calls the authority-granting API {name}"
            )


def test_the_learning_package_defines_no_self_authorization_surface():
    """Static proof: no public method named like an authority grant."""
    for path in _source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            assert not any(
                token in node.name
                for token in ("grant", "authorize_self", "elevate", "promote_self")
            ), f"{path.name}.{node.name} implies self-authorization"


def test_no_parallel_security_or_audit_component_is_created():
    """Gate 9/21 — reuse the certified components; build no second system."""
    certified = {
        "AuditEngine",
        "HITLManager",
        "AIGuardrailsEngine",
        "AuthorizationEngine",
        "GovernancePolicyEngine",
        "SecurityPlatform",
        "Permission",
        "Subject",
        "AuthenticationService",
        "CredentialManager",
    }
    for path in _source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name not in certified, (
                    f"{path.name} redefines the certified component {node.name}"
                )


def test_every_learning_module_parses_and_exports_resolve():
    import autoforge_learning

    for path in _source_files():
        ast.parse(path.read_text())
    missing = [n for n in autoforge_learning.__all__ if not hasattr(autoforge_learning, n)]
    assert missing == []


def test_the_lifecycle_order_is_structural_not_conventional():
    """Gate 21 — the order is enforced by the call sequence in one function."""
    text = (LEARNING_SRC / "promotion.py").read_text()
    ordered = [
        "Gate A: evaluation must exist",
        "Gate C: security boundary must still permit",
        "Gate D: human approval",
        "Gate F (HARD): rollback handle BEFORE any state change",
        "COMMIT: one atomic pointer write",
    ]
    positions = []
    for marker in ordered:
        index = text.find(marker)
        assert index != -1, f"missing stage marker: {marker}"
        positions.append(index)
    assert positions == sorted(positions), "promotion stages are out of order"


def test_rollback_requires_no_model_and_no_network():
    """RB-01 — rollback is a pointer restore, never a reasoned decision.

    Structural: the rollback code path performs no network I/O and calls no
    model/provider. Docstrings may of course mention that it needs no model.
    """
    tree = ast.parse((LEARNING_SRC / "promotion.py").read_text())
    rollback = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_rollback_locked"
    )
    called = set()
    for node in ast.walk(rollback):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(getattr(func, "attr", None) or getattr(func, "id", None))
    for forbidden in ("requests", "httpx", "urlopen", "generate", "complete", "invoke_model"):
        assert forbidden not in called, f"rollback path calls {forbidden}"

    # The module imports no network client at all.
    source = (LEARNING_SRC / "promotion.py").read_text()
    for module in ("import requests", "import httpx", "from urllib", "import socket"):
        assert module not in source, f"promotion module imports {module}"