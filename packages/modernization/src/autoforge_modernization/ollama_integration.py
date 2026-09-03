"""Ollama integration for modernization (Phase 18-G.3).

Wires modernization into real local Ollama for semantic reasoning.
- Real HTTP call to local Ollama daemon (127.0.0.1:11434) when available
- Records: model, task, tokens_in, tokens_out, latency_ms, error
- Never fabricates a response; always records actual vs simulated
"""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


@dataclass
class OllamaCallRecord:
    file_path: str
    model: str
    task: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    error: str | None = None
    fallback_used: bool = False


class OllamaClient:
    def __init__(
        self,
        model_router=None,
        primary_model: str = "llama3.1:8b",
        available: bool = True,
        base_url: str = DEFAULT_OLLAMA_URL,
    ):
        self.router = model_router
        if "/" in primary_model:
            primary_model = primary_model.split("/")[-1]
        self.primary = primary_model
        self.available = available
        self.base_url = base_url
        self.calls = []
        self.metrics = {
            "calls": 0,
            "real_calls": 0,
            "fallbacks": 0,
            "errors": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "total_latency_ms": 0,
            "files_processed": 0,
        }

    def complete(
        self,
        prompt: str,
        file_path: str = "",
        max_tokens: int = 800,
        task: str = "semantic_reasoning",
    ) -> dict:
        """Make a real Ollama call when available, record all metrics."""
        start = time.time()
        record = OllamaCallRecord(
            file_path=file_path,
            model=self.primary,
            task=task,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        )
        if not self.available:
            record.error = "Ollama unavailable (graceful degradation)"
            record.fallback_used = True
            record.latency_ms = int((time.time() - start) * 1000)
            self.calls.append(record)
            self.metrics["calls"] += 1
            self.metrics["fallbacks"] += 1
            self.metrics["files_processed"] += 1
            self.metrics["total_latency_ms"] += record.latency_ms
            return {
                "response": "",
                "available": False,
                "error": record.error,
                "model": self.primary,
                "latency_ms": record.latency_ms,
                "task": task,
            }
        try:
            response_text = self._call_ollama(prompt, self.primary, max_tokens)
            record.tokens_in = max(1, len(prompt) // 4)
            record.tokens_out = max(1, len(response_text) // 4)
            record.latency_ms = int((time.time() - start) * 1000)
            self.calls.append(record)
            self.metrics["calls"] += 1
            self.metrics["real_calls"] += 1
            self.metrics["files_processed"] += 1
            self.metrics["tokens_in"] += record.tokens_in
            self.metrics["tokens_out"] += record.tokens_out
            self.metrics["total_latency_ms"] += record.latency_ms
            return {
                "response": response_text,
                "available": True,
                "model": self.primary,
                "latency_ms": record.latency_ms,
                "tokens_in": record.tokens_in,
                "tokens_out": record.tokens_out,
                "task": task,
            }
        except Exception as e:
            err_str = str(e)
            record.error = f"Ollama call failed: {err_str}"
            record.fallback_used = True
            record.latency_ms = int((time.time() - start) * 1000)
            self.calls.append(record)
            self.metrics["calls"] += 1
            self.metrics["fallbacks"] += 1
            self.metrics["errors"] += 1
            self.metrics["total_latency_ms"] += record.latency_ms
            return {
                "response": "",
                "available": False,
                "error": record.error,
                "model": self.primary,
                "latency_ms": record.latency_ms,
                "task": task,
            }

    def _call_ollama(self, prompt: str, model: str, max_tokens: int) -> str:
        """Direct HTTP call to local Ollama /api/generate."""
        payload = {
            "model": model,
            "prompt": prompt[:16000],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.1},
        }
        url = f"{self.base_url}/api/generate"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
        result = json.loads(body)
        if isinstance(result, dict):
            return result.get("response", "")
        return str(result)

    def check_health(self) -> dict:
        """Check if Ollama daemon is reachable at base_url."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                headers={"Content-Type": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            models = [m.get("name", "") for m in data.get("models", [])]
            return {"available": True, "models": models}
        except Exception as e:
            return {"available": False, "error": str(e)}

    def get_metrics(self) -> dict:
        m = dict(self.metrics)
        if m["calls"]:
            m["avg_latency_ms"] = round(m["total_latency_ms"] / m["calls"], 1)
            m["real_call_rate"] = round(m["real_calls"] / m["calls"], 3)
        return m


__all__ = ["OllamaClient", "OllamaCallRecord"]
