"""18-G Run 7 entry A: imports + topology + helpers."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

_EVD = Path(__file__).resolve().parent
sys.path.insert(0, str(_EVD))

REPO_ROOT = _EVD.parents[3]
sys.path.extend([
    str(REPO_ROOT / "packages" / "kernel" / "src"),
    str(REPO_ROOT / "packages" / "knowledge_platform" / "src"),
    str(REPO_ROOT / "packages" / "ai_infrastructure" / "src"),
    str(REPO_ROOT / "packages" / "workforce" / "src"),
    str(REPO_ROOT / "packages" / "modernization" / "src"),
])

from run_18g_helpers_b import async_call_ollama, sha256_of
from run_18g_helpers_c import (
    execute_qdrant_rag as _raw_rag,
    get_nomic_embedding,
    http_get,
)

M1_URL = os.environ.get("AUTOFORGE_M1_OLLAMA_URL", "http://127.0.0.1:11434")
HP_URL = os.environ.get("AUTOFORGE_HP_OLLAMA_URL", "http://192.168.1.102:11434")
QD_URL = os.environ.get("AUTOFORGE_QDRANT_URL", "http://192.168.1.102:6333")
CODING = "qwen2.5-coder:7b-instruct-q3_K_M"
REASON = "ornith-9b-iq3m-4k:latest"
EMBED = "nomic-embed-text:latest"
HP_CODING = "qwen2.5-coder:3b"
COMMIT = "e13539daca1846ccf0d363d97af1dcc6b51fae9c"


def _java_bin():
    repo_java = REPO_ROOT / ".autoforge" / "tools" / "java" / "bin" / "java"
    if repo_java.exists():
        return str(repo_java)
    return "/opt/homebrew/Cellar/openjdk/26.0.2.1/libexec/openjdk.jdk/Contents/Home/bin/java"


def _rag(pid, query, sink):
    return _raw_rag(QD_URL, lambda q: get_nomic_embedding(M1_URL, EMBED, q),
                    pid, query, sink)
