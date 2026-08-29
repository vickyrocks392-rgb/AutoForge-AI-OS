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
from autoforge_ai_infrastructure.adapters.ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL_TAGS,
    OllamaProviderAdapter,
)
from autoforge_ai_infrastructure.adapters.openai_compatible import (
    OpenAICompatibleProviderAdapter,
)

__all__ = [
    "UNAVAILABLE",
    "BaseProviderAdapter",
    "extract_json_payload",
    "OllamaProviderAdapter",
    "DEFAULT_OLLAMA_BASE_URL",
    "DEFAULT_OLLAMA_MODEL_TAGS",
    "OpenAICompatibleProviderAdapter",
    "AnthropicProviderAdapter",
    "GeminiProviderAdapter",
]
