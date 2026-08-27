"""AI-assisted review seam — routed through Phase 7 AI Infrastructure.

ALL AI-assisted review goes through the AutoForge AI abstraction (section 22):
    Review → AutoForge AI abstraction → Capability Registry / Model Router
            → provider.

We NEVER instantiate OpenAI/Anthropic/Gemini/Ollama directly.  This adapter
follows the same pattern as Phase 10's ``AIInfrastructureAdapter``: route via
``ModelRouterService`` and execute via ``RoutedModelExecutor``.

Deterministic-first (sections 7, 11): AI proposals are advisory.  They can
recommend severity, but the Policy clamps/finalises it and an AI proposal can
never flip a deterministic block to a PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from autoforge_ai_infrastructure.execution import (
    ExecutionRequest,
    ExecutionResult,
    RoutedModelExecutor,
)
from autoforge_ai_infrastructure.metadata import CapabilityIds, RoutingRequest
from autoforge_ai_infrastructure.router import ModelRouterService

from autoforge_review.models import AISourceMetadata, FindingKind, ReviewCategory, Severity


@dataclass
class ProposedFinding:
    """An AI-proposed finding (not yet policy-finalised by the engine)."""

    title: str
    severity: Severity
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    kind: FindingKind = FindingKind.DEFECT
    confidence: float = 0.5
    file: str | None = None
    remediation: str = ""


@dataclass
class AIReviewTask:
    """Unit of AI-assisted review work for one category."""

    category: ReviewCategory
    scope: dict[str, str] = field(default_factory=dict)
    evidence_digest: str = ""
    policy_context: str = ""


@dataclass
class AIReviewResult:
    """Outcome of one AI-assisted review task."""

    findings: list[ProposedFinding] = field(default_factory=list)
    ai_source: AISourceMetadata = field(default_factory=AISourceMetadata)


@runtime_checkable
class ReviewAIProvider(Protocol):
    """Protocol satisfied by any AI reasoning service used for review."""

    async def review(self, task: AIReviewTask) -> AIReviewResult:
        """Return AI proposals + source metadata for ``task``."""
        ...


class AIInfrastructureReviewAdapter:
    """Standard ReviewAIProvider routing through Phase 7 AI Infrastructure."""

    REVIEW_CAPABILITY = CapabilityIds.STRUCTURED_OUTPUT
    PROMPT_VERSION = "review.v1"

    def __init__(
        self,
        router: ModelRouterService | None = None,
        model_executor: RoutedModelExecutor | None = None,
    ) -> None:
        self._router = router
        self._executor = model_executor

    async def review(self, task: AIReviewTask) -> AIReviewResult:
        if self._router is None or self._executor is None:
            return AIReviewResult(
                ai_source=AISourceMetadata(executed=False, prompt_version=self.PROMPT_VERSION)
            )

        payload = {
            "task": "ai_review",
            "category": task.category.value,
            "prompt_version": self.PROMPT_VERSION,
            "policy_context": task.policy_context or "",
            "evidence_digest": task.evidence_digest or _digest(task.scope),
            "scope": _sample(task.scope),
            "output_schema": {
                "findings": [
                    {
                        "title": "str",
                        "description": "str",
                        "evidence": ["str"],
                        "severity": "info|low|medium|high|critical",
                        "kind": "defect|policy_violation|security_exception|...",
                        "confidence": "float",
                        "file": "str?",
                        "remediation": "str",
                    }
                ]
            },
        }
        request = ExecutionRequest(payload=payload)
        routing = RoutingRequest(
            required_capabilities=frozenset({self.REVIEW_CAPABILITY})
        )
        try:
            result: ExecutionResult = await self._executor.execute(request, routing)
        except Exception as exc:  # noqa: BLE001 - provider failures degrade safely
            return AIReviewResult(
                ai_source=AISourceMetadata(
                    executed=False,
                    prompt_version=self.PROMPT_VERSION,
                    error_message=str(exc),
                )
            )

        policy_name = getattr(self._router, "default_policy_name", None)
        ai_source = AISourceMetadata(
            capability_id=self.REVIEW_CAPABILITY,
            provider_id=result.provider_id,
            model_id=result.model_id,
            routing_policy=policy_name,
            prompt_version=self.PROMPT_VERSION,
            executed=True,
        )

        proposals: list[ProposedFinding] = []
        for raw in (result.output or {}).get("findings", []):
            if not isinstance(raw, dict) or not raw.get("title"):
                continue
            proposals.append(
                ProposedFinding(
                    title=str(raw["title"])[:500],
                    description=str(raw.get("description", ""))[:2000],
                    evidence=[str(e)[:500] for e in raw.get("evidence", [])],
                    severity=_coerce_severity(raw.get("severity")),
                    kind=_coerce_kind(raw.get("kind")),
                    confidence=_coerce_confidence(raw.get("confidence")),
                    file=raw.get("file"),
                    remediation=str(raw.get("remediation", ""))[:1000],
                )
            )
        return AIReviewResult(findings=proposals, ai_source=ai_source)


def _digest(scope: dict[str, str]) -> str:
    """Compact, deterministic digest of a source scope for the prompt."""
    if not scope:
        return "(no source provided)"
    total_chars = sum(len(v) for v in scope.values())
    return f"{len(scope)} file(s), {total_chars} chars; subjects: {', '.join(sorted(scope))}"


def _sample(scope: dict[str, str], limit: int = 3) -> dict[str, str]:
    """Return a bounded sample of source files as review context."""
    out: dict[str, str] = {}
    for key in list(scope.keys())[:limit]:
        out[key] = scope[key][:4000]
    return out


def _coerce_severity(value: Any) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError:
        return Severity.MEDIUM


def _coerce_kind(value: Any) -> FindingKind:
    try:
        return FindingKind(str(value).lower())
    except ValueError:
        return FindingKind.DEFECT


def _coerce_confidence(value: Any) -> float:
    try:
        f = float(value)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return 0.5
