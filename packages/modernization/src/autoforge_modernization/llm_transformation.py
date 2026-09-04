"""Real LLM transformation engine reusing the AutoForge AI infrastructure.

The engine does NOT create a second model-routing system and does NOT bypass
the existing AI infrastructure.  All inference flows through
``autoforge_ai_infrastructure``:

    CapabilityRegistry (metadata)
        -> ModelRouterService (selection only)
        -> ExecutorRegistry (provider-neutral execution seam)
        -> provider adapter (e.g. OllamaProviderAdapter)

Every transformation is captured in a structured :class:`LLMTransformationContract`
(Section 5 contract).  When no inference worker/model is available the status is
honestly recorded as ``UNAVAILABLE`` / ``NOT_USED`` — no fabricated execution,
no fabricated metrics.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LLMTransformationStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"
    NOT_USED = "not_used"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Section 5 structured transformation contract
# ---------------------------------------------------------------------------


class LLMTransformationContract:
    """Structured transformation result (Section 5 contract).

    Never treated as an opaque blob: every field is meaningful and auditable.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.contract_id: str = kwargs.get("contract_id", str(uuid.uuid4()))
        self.source_artifact_id: str = kwargs.get("source_artifact_id", "")
        self.source_sha256: str = kwargs.get("source_sha256", "")
        self.target_technology: str = kwargs.get("target_technology", "")
        self.target_framework: str = kwargs.get("target_framework", "")
        self.target_version: str = kwargs.get("target_version", "")
        self.transformation_strategy: str = kwargs.get(
            "transformation_strategy", "llm_generated"
        )
        self.model: str = kwargs.get("model", "")
        self.provider: str = kwargs.get("provider", "")
        self.prompt_context_id: str = kwargs.get("prompt_context_id", "")
        self.rag_evidence_ids: list[str] = list(kwargs.get("rag_evidence_ids", []) or [])
        self.generated_code: str = kwargs.get("generated_code", "")
        self.target_sha256: str = kwargs.get("target_sha256", "")
        self.confidence: float = float(kwargs.get("confidence", 0.0))
        self.assumptions: list[str] = list(kwargs.get("assumptions", []) or [])
        self.unresolved_ambiguities: list[str] = list(
            kwargs.get("unresolved_ambiguities", []) or []
        )
        self.review_required_reasons: list[str] = list(
            kwargs.get("review_required_reasons", []) or []
        )
        self.verification_requirements: list[str] = list(
            kwargs.get("verification_requirements", []) or []
        )
        self.token_usage_in: int = int(kwargs.get("token_usage_in", 0))
        self.token_usage_out: int = int(kwargs.get("token_usage_out", 0))
        self.latency_ms: float = float(kwargs.get("latency_ms", 0.0))
        self.retry_count: int = int(kwargs.get("retry_count", 0))
        self.status: str = kwargs.get(
            "status", LLMTransformationStatus.NOT_USED.value
        )
        self.is_fabricated: bool = bool(kwargs.get("is_fabricated", False))
        self.ran_at: datetime = kwargs.get("ran_at", _utc_now())
        self.labels: dict[str, Any] = dict(kwargs.get("labels", {}) or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "source_artifact_id": self.source_artifact_id,
            "source_sha256": self.source_sha256,
            "target_technology": self.target_technology,
            "target_framework": self.target_framework,
            "target_version": self.target_version,
            "transformation_strategy": self.transformation_strategy,
            "model": self.model,
            "provider": self.provider,
            "prompt_context_id": self.prompt_context_id,
            "rag_evidence_ids": self.rag_evidence_ids,
            "target_sha256": self.target_sha256,
            "generated_code_length": len(self.generated_code),
            "confidence": self.confidence,
            "assumptions": self.assumptions,
            "unresolved_ambiguities": self.unresolved_ambiguities,
            "review_required_reasons": self.review_required_reasons,
            "verification_requirements": self.verification_requirements,
            "token_usage_in": self.token_usage_in,
            "token_usage_out": self.token_usage_out,
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "status": self.status,
            "is_fabricated": self.is_fabricated,
            "ran_at": self.ran_at.isoformat(),
            "labels": self.labels,
        }

    def status_is_success(self) -> bool:
        return self.status == LLMTransformationStatus.SUCCESS.value


# ---------------------------------------------------------------------------
# Inference infrastructure (reuses autoforge_ai_infrastructure)
# ---------------------------------------------------------------------------


@dataclass
class InferenceStack:
    """A composed AI-infrastructure stack: registry + router + executors."""

    registry: Any = None
    router: Any = None
    executors: Any = None
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model: str = DEFAULT_MODEL
    provider_id: str = "local-m1"
    available: bool = False
    health: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    def is_available(self) -> bool:
        return bool(
            self.available
            and self.router is not None
            and self.executors is not None
        )


def check_ollama(base_url: str = DEFAULT_OLLAMA_BASE_URL, timeout: float = 5.0) -> dict:
    """Honest liveness probe of the local Ollama daemon."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{base_url}/api/tags",
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        models = [m.get("name", "") for m in data.get("models", [])]
        return {"available": True, "models": models, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "models": [], "error": str(exc)}


def build_ollama_inference_stack(
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = 5.0,
) -> InferenceStack:
    """Build a real AI-infrastructure stack bound to the local Ollama daemon.

    When Ollama is unreachable the returned stack is honest: ``available=False``,
    and the registry contains no eligible model, so any request records
    ``UNAVAILABLE`` rather than fabricated output.
    """
    health = check_ollama(base_url, timeout=timeout)
    stack = InferenceStack(
        base_url=base_url,
        model=model,
        health=health,
        available=bool(health["available"]),
    )
    try:
        from autoforge_ai_infrastructure.execution import ExecutorRegistry
        from autoforge_ai_infrastructure.metadata import (
            CapabilityIds,
            CapabilityMetadata,
            DeploymentMetadata,
            DeploymentMode,
            LatencyProfile,
            ModelMetadata,
            ModelStatus,
            Modality,
            ProviderMetadata,
            ProviderStatus,
            ProviderType,
        )
        from autoforge_ai_infrastructure.policies import LocalFirstRoutingPolicy
        from autoforge_ai_infrastructure.registry import InMemoryCapabilityRegistry
        from autoforge_ai_infrastructure.router import ModelRouterService

        registry = InMemoryCapabilityRegistry()
        for capability_id, display, description in (
            (CapabilityIds.CODE_GENERATION, "Code Generation", "Produces source code."),
            (CapabilityIds.STRUCTURED_OUTPUT, "Structured Output", "Emits schema-conforming JSON."),
            (CapabilityIds.TEXT_GENERATION, "Text Generation", "Produces natural-language output."),
            (CapabilityIds.REASONING, "Reasoning", "Multi-step analytical reasoning."),
        ):
            registry.register_capability(
                CapabilityMetadata(
                    capability_id=capability_id,
                    display_name=display,
                    description=description,
                )
            )
        stack.registry = registry

        provider_available = bool(health["available"])
        from autoforge_ai_infrastructure.adapters.ollama import OllamaProviderAdapter

        executors = ExecutorRegistry()
        executors.bind(
            stack.provider_id,
            OllamaProviderAdapter(
                provider_id=stack.provider_id,
                base_url=base_url,
                default_timeout_seconds=120.0,
            ),
        )
        stack.executors = executors

        from autoforge_ai_infrastructure.adapters.ollama import OllamaProviderAdapter  # noqa: F811
        from autoforge_ai_infrastructure.metadata import ProviderMetadata  # noqa: F811

        _ = OllamaProviderAdapter
        registry.register_provider(
            ProviderMetadata(
                provider_id=stack.provider_id,
                display_name="Local M-series inference worker",
                provider_type=ProviderType.LOCAL_RUNTIME,
                endpoint=base_url,
                supported_capabilities=frozenset(
                    {
                        CapabilityIds.CODE_GENERATION,
                        CapabilityIds.STRUCTURED_OUTPUT,
                        CapabilityIds.TEXT_GENERATION,
                        CapabilityIds.REASONING,
                    }
                ),
                deployment_modes=frozenset({DeploymentMode.LOCAL}),
            )
        )
        _set_provider_availability(
            registry, stack.provider_id, provider_available
        )

        if provider_available:
            registry.register_model(
                ModelMetadata(
                    model_id=model,
                    display_name=model,
                    provider_id=stack.provider_id,
                    family=model.split(":")[0],
                    version=model.split(":")[1] if ":" in model else "latest",
                    status=ModelStatus.ACTIVE,
                    context_window_tokens=32768,
                    max_output_tokens=8192,
                    capabilities=frozenset(
                        {
                            CapabilityIds.CODE_GENERATION,
                            CapabilityIds.STRUCTURED_OUTPUT,
                            CapabilityIds.TEXT_GENERATION,
                            CapabilityIds.REASONING,
                        }
                    ),
                    input_modalities=frozenset({Modality.TEXT}),
                    output_modalities=frozenset({Modality.TEXT}),
                    latency=LatencyProfile(typical_latency_ms=1000),
                    quality_tier=3,
                    reliability=0.9,
                    deployment_modes=frozenset({DeploymentMode.LOCAL}),
                )
            )
            registry.register_deployment(
                DeploymentMetadata(
                    model_id=model,
                    mode=DeploymentMode.LOCAL,
                    environment="local-m1-inference-worker",
                    runtime_hints={"quantization": "q3_k_m", "backend": "ollama"},
                )
            )

        router = ModelRouterService(registry, default_policy=LocalFirstRoutingPolicy())
        stack.router = router
        stack.available = bool(provider_available and health["available"])
        if not provider_available:
            logger.warning(
                "build_ollama_inference_stack: Ollama unreachable at %s - "
                "LLM transformations will record UNAVAILABLE", base_url
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("build_ollama_inference_stack failed: %s", exc)
        stack.health["error"] = str(exc)
        stack.available = False
    return stack


def _set_provider_availability(
    registry: Any, provider_id: str, available: bool
) -> None:
    """Set provider availability after registration."""
    try:
        from autoforge_ai_infrastructure.metadata import ProviderStatus
        registry.set_provider_status(
            provider_id,
            ProviderStatus.AVAILABLE if available else ProviderStatus.UNAVAILABLE,
            reason="ollama-health-probe",
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Inference frontend: small typed facade over the AI infrastructure router
# ---------------------------------------------------------------------------


class LLMInferenceFrontend:
    """Route + execute requests through the existing AI infrastructure only."""

    def __init__(self, stack: InferenceStack | None = None) -> None:
        self.stack = stack or build_ollama_inference_stack()
        self._calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return self.stack.is_available()

    def health(self) -> dict:
        return dict(self.stack.health)

    @property
    def routing_decision_records(self) -> list[dict[str, Any]]:
        try:
            return [d.model_dump() for d in self.stack.router.decision_log()]
        except Exception:  # noqa: BLE001
            return []

    async def generate(
        self,
        prompt_text: str,
        *,
        task: str = "transformation_generation",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout_seconds: float = 180.0,
        routing_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """One routed inference call.  Returns a dict with honest status."""
        started = time.perf_counter()
        if not self.is_available():
            return {
                "status": LLMTransformationStatus.UNAVAILABLE.value,
                "model": self.stack.model,
                "provider": self.stack.provider_id,
                "content": "",
                "latency_ms": (time.perf_counter() - started) * 1000.0,
                "tokens": {"input_tokens": 0, "output_tokens": 0},
                "error": "inference worker unavailable (Ollama unreachable)",
                "is_fabricated": False,
            }
        try:
            from autoforge_ai_infrastructure.execution import (
                ExecutionRequest,
                ExecutionTarget,
                execute_attempt,
            )
            from autoforge_ai_infrastructure.metadata import (
                CapabilityIds,
                DeploymentMode,
                RoutingRequest,
            )

            capabilities = frozenset(
                routing_capabilities
                or [
                    CapabilityIds.CODE_GENERATION,
                    CapabilityIds.STRUCTURED_OUTPUT,
                ]
            )
            routing_request = RoutingRequest(
                required_capabilities=capabilities,
                allowed_deployment_modes=frozenset({DeploymentMode.LOCAL}),
                min_context_window_tokens=8192,
            )
            decision = self.stack.router.route(routing_request)
            candidate = decision.selected
            target = ExecutionTarget(
                model_id=candidate.model.model_id,
                provider_id=candidate.model.provider_id,
            )
            request = ExecutionRequest(
                payload={
                    "messages": [
                        {"role": "system", "content": "AutoForge modernization worker."},
                        {"role": "user", "content": prompt_text},
                    ]
                },
                parameters={"temperature": temperature, "num_predict": max_tokens},
                timeout_seconds=timeout_seconds,
            )
            result = await execute_attempt(self.stack.executors, request, target)
            output = dict(result.output or {})
            latency_ms = float(result.latency_ms or 0.0)
            tokens = output.get("tokens") or {}
            record = {
                "status": LLMTransformationStatus.SUCCESS.value,
                "model": result.model_id,
                "provider": result.provider_id,
                "content": output.get("content", ""),
                "structured_output": output.get("structured_output"),
                "latency_ms": latency_ms,
                "tokens": {
                    "input_tokens": int(tokens.get("input_tokens", 0)),
                    "output_tokens": int(tokens.get("output_tokens", 0)),
                },
                "routing_policy": decision.policy_name,
                "routing_decision_id": str(decision.decision_id),
                "error": None,
                "is_fabricated": False,
                "attempts": result.attempts,
                "failovers": result.failovers,
            }
            self._calls.append(record)
            return record
        except Exception as exc:  # noqa: BLE001
            record = {
                "status": LLMTransformationStatus.UNAVAILABLE.value,
                "model": self.stack.model,
                "provider": self.stack.provider_id,
                "content": "",
                "latency_ms": (time.perf_counter() - started) * 1000.0,
                "tokens": {"input_tokens": 0, "output_tokens": 0},
                "error": str(exc),
                "is_fabricated": False,
            }
            logger.warning("LLMInferenceFrontend.generate failed: %s", exc)
            self._calls.append(record)
            return record

    def metrics(self) -> dict[str, Any]:
        calls = self._calls
        return {
            "calls": len(calls),
            "real_calls": sum(1 for c in calls if c["status"] == "success"),
            "unavailable_calls": sum(
                1 for c in calls if c["status"] == "unavailable"
            ),
            "tokens_in": sum(c["tokens"]["input_tokens"] for c in calls),
            "tokens_out": sum(c["tokens"]["output_tokens"] for c in calls),
            "total_latency_ms": sum(float(c["latency_ms"]) for c in calls),
        }


# ---------------------------------------------------------------------------
# Structured output parsing helpers
# ---------------------------------------------------------------------------


def extract_fenced_code(text: str) -> str:
    """Extract the first fenced code block from LLM output (deterministic)."""
    if not text:
        return ""
    match = re.search(r"```[a-zA-Z0-9_\-+]*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).rstrip()
    return text.rstrip()


def parse_llm_json(text: str) -> dict[str, Any]:
    """Best-effort strict JSON parse of structured LLM output.  Never invents."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:  # noqa: BLE001
                return {}
        return {}


def structure_get_code(structured: dict[str, Any], raw_content: str) -> str:
    """Resolve generated code from structured output or the raw content."""
    if not structured:
        return extract_fenced_code(raw_content)
    for key in ("generated_code", "code", "target_code", "artifact"):
        value = structured.get(key)
        if isinstance(value, str) and value.strip():
            return value.rstrip()
        if isinstance(value, dict):
            inner = value.get("content") or value.get("code")
            if isinstance(inner, str) and inner.strip():
                return inner.rstrip()
    return extract_fenced_code(raw_content)


# ---------------------------------------------------------------------------
# LLM transformation engine
# ---------------------------------------------------------------------------


class LLMTransformationEngine:
    """Runs one LLM transformation request and produces a Section-5 contract.

    Uses :class:`LLMInferenceFrontend` for routing/execution and the
    ``TransformationContextAssembler`` prompt passed in by the caller.
    """

    def __init__(
        self,
        frontend: LLMInferenceFrontend | None = None,
        *,
        max_retries: int = 1,
        max_output_tokens: int = 4096,
    ) -> None:
        self.frontend = frontend or LLMInferenceFrontend()
        self.max_retries = int(max_retries)
        self.max_output_tokens = int(max_output_tokens)
        self._contracts: list[LLMTransformationContract] = []

    def is_available(self) -> bool:
        return self.frontend.is_available()

    def contracts(self) -> list[LLMTransformationContract]:
        return list(self._contracts)

    async def transform(
        self,
        prompt: Any,
        *,
        source_artifact_id: str,
        source_sha256: str,
        target_technology: str,
        target_framework: str = "",
        target_version: str = "",
        strategy: str = "llm_generated",
        rag_evidence_ids: list[str] | None = None,
    ) -> LLMTransformationContract:
        """Generate code via a real routed inference call when available."""
        started = time.perf_counter()
        retries = 0
        last_error: str | None = None
        record: dict[str, Any] | None = None

        if not self.is_available():
            contract = LLMTransformationContract(
                source_artifact_id=source_artifact_id,
                source_sha256=source_sha256,
                target_technology=target_technology,
                target_framework=target_framework,
                target_version=target_version,
                transformation_strategy=strategy,
                model=self.frontend.stack.model,
                provider=self.frontend.stack.provider_id,
                prompt_context_id=getattr(prompt, "prompt_context_id", ""),
                rag_evidence_ids=rag_evidence_ids or [],
                status=LLMTransformationStatus.UNAVAILABLE.value,
                is_fabricated=False,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                labels={
                    "llm_worker": "not_configured",
                    "error": "inference worker unavailable",
                },
            )
            self._contracts.append(contract)
            return contract

        for attempt in range(self.max_retries + 1):
            retries = attempt
            record = await self.frontend.generate(
                prompt.to_text(),
                task="transformation_generation",
                max_tokens=self.max_output_tokens,
            )
            if record["status"] == LLMTransformationStatus.SUCCESS.value:
                break
            last_error = record.get("error")
        if record is None:
            record = {}

        if record.get("status") != LLMTransformationStatus.SUCCESS.value:
            contract = LLMTransformationContract(
                source_artifact_id=source_artifact_id,
                source_sha256=source_sha256,
                target_technology=target_technology,
                target_framework=target_framework,
                target_version=target_version,
                transformation_strategy=strategy,
                model=record.get("model", self.frontend.stack.model),
                provider=record.get("provider", self.frontend.stack.provider_id),
                prompt_context_id=getattr(prompt, "prompt_context_id", ""),
                rag_evidence_ids=rag_evidence_ids or [],
                status=record.get(
                    "status", LLMTransformationStatus.UNAVAILABLE.value
                ),
                is_fabricated=False,
                latency_ms=float(record.get("latency_ms", 0.0)),
                retry_count=retries,
                labels={
                    "llm_worker": "not_used",
                    "error": last_error or record.get("error", "inference failed"),
                },
            )
            self._contracts.append(contract)
            return contract

        content = record.get("content", "")
        tokens = record.get("tokens") or {}
        structured = parse_llm_json(content)
        generated_code = structure_get_code(structured, content)
        confidence = float(structured.get("confidence", 0.5 if structured else 0.0))
        assumptions = [str(a) for a in (structured.get("assumptions") or [])]
        ambiguities = [
            str(a)
            for a in (
                structured.get("unresolved_ambiguities")
                or structured.get("ambiguities")
                or []
            )
        ]
        review_reasons = [
            str(r)
            for r in (
                structured.get("review_required_reasons")
                or structured.get("review_required")
                or []
            )
        ]
        verification_requirements = [
            str(v)
            for v in (
                structured.get("verification_requirements")
                or structured.get("verification")
                or []
            )
        ]
        status = LLMTransformationStatus.SUCCESS.value
        if not generated_code:
            status = LLMTransformationStatus.REVIEW_REQUIRED.value
            review_reasons.append("LLM returned no code block")

        contract = LLMTransformationContract(
            source_artifact_id=source_artifact_id,
            source_sha256=source_sha256,
            target_technology=target_technology,
            target_framework=target_framework,
            target_version=target_version,
            transformation_strategy=strategy,
            model=record.get("model", ""),
            provider=record.get("provider", ""),
            prompt_context_id=getattr(prompt, "prompt_context_id", ""),
            rag_evidence_ids=rag_evidence_ids or [],
            generated_code=generated_code,
            target_sha256=_sha256(generated_code),
            confidence=confidence,
            assumptions=assumptions,
            unresolved_ambiguities=ambiguities,
            review_required_reasons=review_reasons,
            verification_requirements=verification_requirements,
            token_usage_in=int(tokens.get("input_tokens", 0)),
            token_usage_out=int(tokens.get("output_tokens", 0)),
            latency_ms=float(record.get("latency_ms", 0.0)),
            retry_count=retries,
            status=status,
            is_fabricated=False,
            labels={
                "llm_worker": "real",
                "routing_policy": record.get("routing_policy", ""),
                "routing_decision_id": record.get("routing_decision_id", ""),
            },
        )
        self._contracts.append(contract)
        return contract


__all__ = [
    "LLMTransformationStatus",
    "LLMTransformationContract",
    "InferenceStack",
    "check_ollama",
    "build_ollama_inference_stack",
    "LLMInferenceFrontend",
    "LLMTransformationEngine",
    "extract_fenced_code",
    "parse_llm_json",
]