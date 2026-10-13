"""
PolicyDesk Knowledge Assistant — Configuration & Environment Validation Module.
Enforces strict external runtime data root confinement and parameter validation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PolicyDeskConfig(BaseModel):
    """Configuration settings for PolicyDesk Knowledge Assistant."""

    project_name: str = "PolicyDesk Knowledge Assistant"
    project_id: str = "Phase20-B-PolicyDesk"
    
    # Runtime Data Root (Must reside OUTSIDE AutoForge and Customer deliverable repositories)
    data_dir: Path
    vector_db_dir: Path
    ingestion_dir: Path
    runtime_dir: Path
    logs_dir: Path
    tmp_dir: Path
    
    # Model Cache Root
    model_cache_dir: Path

    # Embeddings Configuration
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimensions: int = 384
    vector_collection_name: str = "policydesk_kb"

    # LLM Answer Generation Configuration
    llm_provider: str = "local_runtime"
    llm_base_url: str = "http://127.0.0.1:19801/v1"
    llm_model: str = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
    llm_timeout_seconds: float = 15.0
    llm_temperature: float = 0.0

    # Retrieval Thresholds
    top_k_default: int = 5
    min_similarity_threshold: float = 0.25  # Cosine similarity floor for abstention
    max_chunk_chars: int = 600
    chunk_overlap_chars: int = 80

    # Server Configuration
    host: str = "127.0.0.1"
    port: int = 8080

    model_config = ConfigDict(arbitrary_types_allowed=True)


def resolve_and_validate_paths(
    custom_data_dir: Optional[str | Path] = None,
    allow_test_in_repo: bool = False,
) -> PolicyDeskConfig:
    """
    Resolves data and model directories, validating that production data paths
    are strictly isolated outside the AutoForge repository and Customer Deliverables.
    """
    repo_root = Path(__file__).resolve().parents[3]  # AutoForge root
    customer_src_root = Path(__file__).resolve().parents[1]  # Customer Deliverables/Phase20-B-PolicyDesk

    # Check test override
    env_allow_test = os.environ.get("POLICYDESK_ALLOW_IN_REPO_DATA", "0").lower() in ("1", "true", "yes")
    is_test_override = allow_test_in_repo or env_allow_test

    # Determine data directory
    env_data_dir = os.environ.get("POLICYDESK_DATA_DIR")
    if custom_data_dir:
        resolved_data_dir = Path(custom_data_dir).expanduser().resolve()
    elif env_data_dir:
        resolved_data_dir = Path(env_data_dir).expanduser().resolve()
    else:
        # Canonical external data root on macOS
        resolved_data_dir = (
            Path.home()
            / "Library"
            / "Application Support"
            / "AutoForge"
            / "CustomerProjects"
            / "Phase20-B-PolicyDesk"
        ).resolve()

    # Determine model cache directory
    env_cache_dir = os.environ.get("POLICYDESK_MODEL_CACHE_DIR")
    if env_cache_dir:
        resolved_cache_dir = Path(env_cache_dir).expanduser().resolve()
    else:
        resolved_cache_dir = (Path.home() / "Library" / "Caches" / "AutoForge" / "models").resolve()

    # Enforce strict isolation check
    if not is_test_override:
        # Check against repo root
        try:
            rel_to_repo = resolved_data_dir.relative_to(repo_root)
            raise RuntimeError(
                f"SAFETY ISOLATION VIOLATION: PolicyDesk data directory '{resolved_data_dir}' "
                f"is located inside the Git repository at '{rel_to_repo}'. "
                "Production runtime data, vector stores, and customer uploads MUST reside outside "
                "the source repository to prevent accidental tracking or data leakage."
            )
        except ValueError:
            pass  # Successfully outside repo_root

        # Check against customer deliverable root
        try:
            rel_to_cust = resolved_data_dir.relative_to(customer_src_root)
            raise RuntimeError(
                f"SAFETY ISOLATION VIOLATION: PolicyDesk data directory '{resolved_data_dir}' "
                f"is located inside the customer deliverable source root at '{rel_to_cust}'."
            )
        except ValueError:
            pass  # Successfully outside customer_src_root

    # Prepare subdirectories
    vector_db_dir = resolved_data_dir / "vector_db"
    ingestion_dir = resolved_data_dir / "ingestion"
    runtime_dir = resolved_data_dir / "runtime"
    logs_dir = resolved_data_dir / "logs"
    tmp_dir = resolved_data_dir / "tmp"

    for d in (resolved_data_dir, vector_db_dir, ingestion_dir, runtime_dir, logs_dir, tmp_dir, resolved_cache_dir):
        d.mkdir(parents=True, exist_ok=True)

    llm_url = os.environ.get(
        "POLICYDESK_LLM_URL",
        os.environ.get("AUTOFORGE_LOCAL_RUNTIME_URL", "http://127.0.0.1:19801/v1")
    )
    llm_model = os.environ.get(
        "POLICYDESK_LLM_MODEL",
        "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
    )
    llm_timeout = float(os.environ.get("POLICYDESK_LLM_TIMEOUT", "15.0"))
    port = int(os.environ.get("POLICYDESK_PORT", "8080"))

    return PolicyDeskConfig(
        data_dir=resolved_data_dir,
        vector_db_dir=vector_db_dir,
        ingestion_dir=ingestion_dir,
        runtime_dir=runtime_dir,
        logs_dir=logs_dir,
        tmp_dir=tmp_dir,
        model_cache_dir=resolved_cache_dir,
        llm_base_url=llm_url,
        llm_model=llm_model,
        llm_timeout_seconds=llm_timeout,
        port=port,
    )
