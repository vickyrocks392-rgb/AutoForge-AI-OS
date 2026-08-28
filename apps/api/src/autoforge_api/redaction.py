"""
Secrets Redaction Utility for AutoForge API.
Ensures no raw tokens, private keys, or credentials are leaked in API payloads.
"""

from __future__ import annotations
from typing import Any, Dict, List


SENSITIVE_KEY_SUBSTRINGS = (
    "secret",
    "password",
    "private_key",
    "api_key",
    "auth_token",
    "api_token",
    "jwt_token",
    "bearer_token",
    "session_token",
    "refresh_token",
    "access_token",
    "credential",
    "access_key",
)

# Keys that contain 'token' in the NLP / LLM context window sense and must NOT be redacted
NON_SENSITIVE_LLM_TOKEN_KEYS = (
    "context_window_tokens",
    "max_output_tokens",
    "input_tokens",
    "output_tokens",
    "throughput_tokens_per_second",
    "context_tokens",
    "average_chunk_size_tokens",
    "average_context_size_tokens",
    "total_tokens",
)



def redact_secrets(data: Any) -> Any:
    """
    Recursively sanitize dictionaries and lists to mask sensitive credential fields.
    """
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            k_lower = str(key).lower()
            if k_lower in NON_SENSITIVE_LLM_TOKEN_KEYS:
                sanitized[key] = redact_secrets(value)
            elif any(s in k_lower for s in SENSITIVE_KEY_SUBSTRINGS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = redact_secrets(value)
        return sanitized
    elif isinstance(data, list):
        return [redact_secrets(item) for item in data]
    return data
