"""
Provider adapters for AI Infrastructure Platform (Phase 17).
"""

from autoforge_ai_infrastructure.adapters.anthropic import AnthropicProviderAdapter
from autoforge_ai_infrastructure.adapters.base import (
    UNAVAILABLE,
    BaseProviderAdapter,
    extract_json_payload,
)
from autoforge_ai_infrastructure.adapters.gemini import GeminiProviderAdapter
from autoforge_ai_infrastructure.adapters.local_runtime import (
    DEFAULT_LOCAL_RUNTIME_BASE_URL,
    LocalRuntimeProviderAdapter,
    bind_local_runtime_adapters,
    bind_optional_ollama_adapter,
)
from autoforge_ai_infrastructure.adapters.openai_compatible import (
    OpenAICompatibleProviderAdapter,
)

__all__ = [
    "UNAVAILABLE",
    "BaseProviderAdapter",
    "extract_json_payload",
    "DEFAULT_LOCAL_RUNTIME_BASE_URL",
    "LocalRuntimeProviderAdapter",
    "bind_local_runtime_adapters",
    "bind_optional_ollama_adapter",
    "OpenAICompatibleProviderAdapter",
    "AnthropicProviderAdapter",
    "GeminiProviderAdapter",
]
