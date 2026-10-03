"""Safe source-code self-improvement — Phase 19B-3 (Gates 11, 12, 26).

Gate 11 permits the learning system to propose, and where authorized to
execute, source-code modifications — but never as a model writing straight over
production. The lifecycle is:

    OBSERVATION → HYPOTHESIS → CODE CHANGE PROPOSAL → ISOLATED WORKSPACE
    → BUILD → TEST → STATIC ANALYSIS → SECURITY CHECK → REVIEW
    → REGRESSION EVALUATION → HITL APPROVAL → ROLLBACK HANDLE → PROMOTION

Gate 12 lists ten mandatory gates and says: *if any mandatory gate fails, NO
PROMOTION*. :data:`MANDATORY_GATES` is that list as data, and
:class:`CodeChangeGatekeeper` evaluates all ten in order and refuses to produce
a promotable verdict unless every one passed — there is no partial credit and
no "mostly passed".

Gate 26 is the hard boundary. :data:`PROTECTED_PATHS` names the components that
require explicit human-controlled engineering changes. A proposal touching any
of them is denied at the *proposal* stage, long before any workspace exists, so
the denial costs nothing and leaves no residue.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional

from pydantic import Field

from autoforge_learning.models import LearningBase, LearningScope

logger = logging.getLogger("autoforge.learning.codemod")

__test__ = False  # declares a gatekeeper, not tests


class CodeChangeRefused(RuntimeError):
    """A source-code change was refused. It is never partially applied."""


class GateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


#: The ten mandatory gates of Gate 12, in the order they must be evaluated.
MANDATORY_GATES: tuple[str, ...] = (
    "syntax_parse",
    "compilation",
    "unit_tests",
    "integration_tests",
    "deterministic_validation",
    "security_tests",
    "regression_tests",
    "protected_system_tests",
    "review",
    "promotion_authorization",
)

#: Gate 26: paths that autonomous code modification may never touch. A proposal
#: naming any of these is denied outright — this is not a warning threshold that
#: a sufficiently good evaluation could overcome.
PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        "packages/security/",
        "packages/security/src/autoforge_security/",
        "autoforge_security",
        "ai_guardrails",
        "trust_boundary",
        "authorization",
        "credentials",
        "permissions",
        "governance",
        "hitl",
        "audit",
        "rollback",
        "learning authority model",
        "packages/learning/src/autoforge_learning/gateway.py",
        "packages/learning/src/autoforge_learning/promotion.py",
        "packages/learning/src/autoforge_learning/approval.py",
        "packages/learning/src/autoforge_learning/invariants.py",
        "packages/kernel/src/autoforge_kernel/completion.py",
        "packages/review/src/autoforge_review/engine.py",
    }
)

#: Path fragments whose presence in a change is an immediate refusal. Checked
#: against the *proposed* paths before any workspace is created.
PROTECTED_PATH_FRAGMENTS: tuple[str, ...] = (
    "security",
    "guardrail",
    "authorization",
    "credential",
    "permission",
    "trust_boundary",
    "hitl",
    "governance",
    "audit",
    "rollback",
)

class CodeChangeProposal(LearningBase):
    """A proposed source change, isolated, diffable, attributable, reversible.

    The proposal carries the *unified diff* rather than the new file contents,
    so a reviewer sees exactly what would change without the system holding a
    writable handle to the production tree. ``base_content_hash`` pins the tree
    it was written against, which is what makes the change reversible: the
    prior state is identified by a hash, not remembered by the system.
    """

    proposal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: LearningScope
    summary: str
    #: Unified diff. Recorded verbatim so promotion is auditable.
    diff: str
    touched_paths: tuple[str, ...] = ()
    base_content_hash: str = Field(..., min_length=8)
    proposed_content_hash: str = Field(..., min_length=8)
    isolated_workspace: str = ""
    proposed_by: str = "autoforge.learning"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hypothesis_id: Optional[uuid.UUID] = None
    correlation_id: Optional[str] = None

    @property
    def touches_protected_path(self) -> bool:
        """True when any touched path is a protected component.

        Matching is by prefix as well as equality, so a *directory* entry such as
        ``packages/security/`` protects every file beneath it — otherwise a
        whole subsystem could be edited simply by naming a file inside it.
        """
        return any(self._is_protected(path) for path in self.touched_paths)

    @classmethod
    def _is_protected(cls, path: str) -> bool:
        if not path:
            return False
        normalized = path.replace("\\", "/").rstrip("/")
        for protected in PROTECTED_PATHS:
            candidate = protected.replace("\\", "/").rstrip("/")
            if normalized == candidate or normalized.startswith(candidate + "/"):
                return True
        return any(fragment in normalized for fragment in PROTECTED_PATH_FRAGMENTS)


@dataclass
class GateResult:
    """One mandatory gate's outcome."""

    gate: str
    status: GateStatus
    detail: str = ""


@dataclass
class GatekeeperVerdict:
    """The aggregate verdict across all ten mandatory gates."""

    proposal_id: uuid.UUID
    results: tuple[GateResult, ...] = ()
    promotable: bool = False
    blocking_gates: tuple[str, ...] = ()
    denied_reason: str = ""

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(r.gate for r in self.results if r.status is GateStatus.FAILED)


class CodeChangeGatekeeper:
    """Evaluates the ten mandatory gates and refuses partial passes."""

    def assert_permitted(self, proposal: CodeChangeProposal) -> None:
        """Deny a protected-path change before anything is created (Gate 26)."""
        if proposal.touches_protected_path:
            offending = sorted(
                p for p in proposal.touched_paths if self._is_protected(p)
            )
            raise CodeChangeRefused(
                "AUTOMATIC LEARNING PROMOTION = DENIED: the proposal touches "
                f"protected component(s) {offending}. Security, authorization, "
                "guardrails, trust boundary, HITL, governance, audit, rollback "
                "and the learning authority model require explicit "
                "human-controlled engineering changes."
            )
        if not proposal.isolated_workspace:
            raise CodeChangeRefused(
                "a source change must be prepared in an isolated workspace; "
                "there is no direct-write path to production source"
            )

    _is_protected = CodeChangeProposal._is_protected

    def evaluate(
        self,
        proposal: CodeChangeProposal,
        *,
        gate_results: Mapping[str, GateStatus],
        review_approved: bool = False,
        promotion_authorized: bool = False,
    ) -> GatekeeperVerdict:
        """Run every mandatory gate; refuse promotion unless all ten passed.

        A gate the caller did not supply is ``NOT_RUN``, which blocks — absence
        of evidence is never a pass (Gate 12's whole point).
        """
        self.assert_permitted(proposal)

        results: list[GateResult] = []
        for gate in MANDATORY_GATES:
            status = gate_results.get(gate, GateStatus.NOT_RUN)
            if gate == "review" and status is GateStatus.NOT_RUN and review_approved:
                status = GateStatus.PASSED
            if (
                gate == "promotion_authorization"
                and status is GateStatus.NOT_RUN
                and promotion_authorized
            ):
                status = GateStatus.PASSED
            results.append(GateResult(gate=gate, status=status))

        blocking = tuple(r.gate for r in results if r.status is not GateStatus.PASSED)
        return GatekeeperVerdict(
            proposal_id=proposal.proposal_id,
            results=tuple(results),
            promotable=not blocking,
            blocking_gates=blocking,
            denied_reason=(
                "" if not blocking else f"mandatory gate(s) not passed: {list(blocking)}"
            ),
        )


def verify_diff_is_reversible(proposal: CodeChangeProposal, base_content: str) -> bool:
    """True when the recorded base hash still matches the tree being changed.

    Reversibility is asserted against content, not memory: if the working tree
    has moved since the diff was computed, applying the change could destroy
    work the system never saw, so the proposal is stale and refused.
    """
    digest = hashlib.sha256(base_content.encode("utf-8")).hexdigest()
    return digest == proposal.base_content_hash


def parses_as_python(source: str) -> bool:
    """Gate 1 (``syntax_parse``): the proposed content must actually parse."""
    try:
        ast.parse(source)
    except SyntaxError:
        return False
    return True


__all__ = [
    "MANDATORY_GATES",
    "PROTECTED_PATHS",
    "PROTECTED_PATH_FRAGMENTS",
    "CodeChangeGatekeeper",
    "CodeChangeProposal",
    "CodeChangeRefused",
    "GateResult",
    "GateStatus",
    "GatekeeperVerdict",
    "parses_as_python",
    "verify_diff_is_reversible",
]