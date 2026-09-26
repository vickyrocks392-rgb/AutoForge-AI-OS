"""
Local Runtime Provider Adapter for AI Infrastructure (18-L Gate 4).

Canonical local inference path for AutoForge. Binds the **existing**
``OpenAICompatibleProviderAdapter`` transport to local runtime servers —
llama.cpp's ``llama-server`` and MLX's OpenAI-compatible server both speak
``/v1/chat/completions`` — so the canonical path no longer requires an Ollama
daemon.

Why this is not a new inference architecture:
  * the wire protocol, message normalization, token accounting, structured-JSON
    handling, error taxonomy and async execution all come from the existing
    :class:`OpenAICompatibleProviderAdapter`; this module only supplies the
    local endpoint defaults and the model-tag mapping;
  * nothing about llama.cpp or MLX leaks above this layer. The Model Router
    still routes by ``provider_id``; Context Engineering still never sees a
    runtime;
  * :class:`OllamaProviderAdapter` remains available as an *optional* provider
    adapter. It is simply no longer the default, so Ollama is no longer a
    production/runtime dependency of the canonical AutoForge path.

Provider neutrality note: ``provider_id`` stays a free string. A deployment
running an Ollama daemon can still bind it explicitly via
``bind_optional_ollama_adapter``; nothing in AutoForge requires it.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

from autoforge_ai_infrastructure.adapters.openai_compatible import (
    OpenAICompatibleProviderAdapter,
)
from autoforge_ai_infrastructure.execution import ExecutorRegistry

logger = logging.getLogger(__name__)

#: Default llama.cpp ``llama-server`` OpenAI-compatible endpoint (local-only).
DEFAULT_LOCAL_RUNTIME_BASE_URL = "http://127.0.0.1:8080/v1"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


class LocalRuntimeProviderAdapter(OpenAICompatibleProviderAdapter):
    """OpenAI-compatible adapter preconfigured for a local runtime server.

    Works unchanged against llama.cpp ``llama-server`` and MLX's
    OpenAI-compatible server, because both expose ``/v1/chat/completions``.
    The base URL is environment-overridable so a node's endpoint is a
    deployment concern, never a hard-coded assumption in the architecture.
    """

    def __init__(
        self,
        provider_id: str,
        base_url: str | None = None,
        *,
        default_timeout_seconds: float = 300.0,
        model_tag_map: Mapping[str, str] | None = None,
        http_client: Any = None,
    ) -> None:
        resolved = (base_url or _env("AUTOFORGE_LOCAL_RUNTIME_URL", DEFAULT_LOCAL_RUNTIME_BASE_URL)).rstrip("/")
        super().__init__(
            provider_id=provider_id,
            base_url=resolved,
            # Local CPU/GPU prefill on a large context window is slow; a 60s
            # default produces spurious timeouts on exactly the long-context
            # work Context Engineering exists to enable.
            default_timeout_seconds=default_timeout_seconds,
            model_tag_map=dict(model_tag_map or {}),
            http_client=http_client,
        )

    @property
    def runtime_family(self) -> str:
        """Coarse runtime label for observability only; never used for routing."""
        host = self._base_url.split("//", 1)[-1]
        if host.startswith("127.0.0.1") or host.startswith("localhost"):
            return "local"
        return "lan"


def bind_local_runtime_adapters(
    executor_registry: ExecutorRegistry,
    *,
    local_runtime_base_url: str | None = None,
    node_endpoints: dict[str, str] | None = None,
) -> None:
    """Bind the canonical local runtime nodes to the ExecutorRegistry.

    Each local node (``local-m1``, ``local-hp``, and any additional node such as
    ``local-mac-mini-m6``) is bound to an OpenAI-compatible local runtime server.
    Nodes without an explicit endpoint share ``local_runtime_base_url``.
    """
    endpoints = dict(node_endpoints or {})
    default_url = (
        local_runtime_base_url
        or _env("AUTOFORGE_LOCAL_RUNTIME_URL", DEFAULT_LOCAL_RUNTIME_BASE_URL)
    )

    for provider_id in ("local-m1", "local-hp"):
        executor_registry.bind(
            provider_id,
            LocalRuntimeProviderAdapter(
                provider_id=provider_id,
                base_url=endpoints.get(provider_id, default_url),
            ),
        )

    # Additional LAN nodes are created only when explicitly configured; no
    # topology is invented.
    for provider_id in sorted(endpoints):
        if provider_id in ("local-m1", "local-hp"):
            continue
        executor_registry.bind(
            provider_id,
            LocalRuntimeProviderAdapter(
                provider_id=provider_id,
                base_url=endpoints[provider_id],
            ),
        )


def bind_optional_ollama_adapter(
    executor_registry: ExecutorRegistry,
    *,
    provider_id: str = "local-ollama",
    base_url: str | None = None,
) -> None:
    """Opt-in binding for a deployment that *does* run an Ollama daemon.

    This exists so provider neutrality is preserved rather than faked: Ollama
    stays a supported optional provider, it is simply not required, not
    registered by default, and not on the canonical execution path.
    """
    from autoforge_ai_infrastructure.adapters.ollama import OllamaProviderAdapter

    url = base_url or _env("AUTOFORGE_OLLAMA_URL", "http://127.0.0.1:11434")
    executor_registry.bind(
        provider_id,
        OllamaProviderAdapter(provider_id=provider_id, base_url=url),
    )
    logger.info("optional Ollama provider adapter bound as %s -> %s", provider_id, url)


__all__ = [
    "DEFAULT_LOCAL_RUNTIME_BASE_URL",
    "LocalRuntimeProviderAdapter",
    "bind_local_runtime_adapters",
    "bind_optional_ollama_adapter",
]