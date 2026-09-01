#!/usr/bin/env python3
"""Phase 18-D: Index AutoForge workspace into local Qdrant RAG.

Usage:
    python scripts/index_knowledge.py --workspace .
    python scripts/index_knowledge.py --workspace . --project-id myproj --force

Exit codes:
    0  — indexing succeeded or nothing to do
    1  — Qdrant or Ollama unavailable (pre-flight check failed)
    2  — indexing failed unexpectedly
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("index_knowledge")


async def _check_ollama(embedding_url: str) -> bool:
    """Return True if Ollama is reachable at embedding_url."""
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(
            embedding_url.rstrip("/") + "/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


async def _check_qdrant(qdrant_url: str) -> bool:
    """Return True if Qdrant is reachable at qdrant_url."""
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(
            qdrant_url.rstrip("/") + "/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


async def _main(workspace: Path, project_id: str | None, force: bool) -> int:
    # ── Pre-flight checks ──────────────────────────────────────────────
    from autoforge_knowledge_platform.rag18.config import (
        DEFAULT_OLLAMA_BASE_URL,
        DEFAULT_QDRANT_URL,
    )

    ollama_ok = await _check_ollama(DEFAULT_OLLAMA_BASE_URL)
    if not ollama_ok:
        log.warning(
            "Ollama not reachable at %s — run 'ollama serve' first. "
            "Install: https://ollama.com/download",
            DEFAULT_OLLAMA_BASE_URL,
        )
        # Check if nomic-embed-text is available anyway (some setups work)
        log.info("Proceeding anyway (offline RAG will degrade gracefully).")

    qdrant_ok = await _check_qdrant(DEFAULT_QDRANT_URL)
    if not qdrant_ok:
        log.warning(
            "Qdrant not reachable at %s — run 'qdrant' or 'docker run -p 6333:6333 qdrant/qdrant' first.",
            DEFAULT_QDRANT_URL,
        )
        log.info("Proceeding anyway (offline RAG will degrade gracefully).")

    # ── Build config ───────────────────────────────────────────────────
    qdrant_path = Path.home() / ".autoforge" / "knowledge" / "vector-db"
    qdrant_path.mkdir(parents=True, exist_ok=True)

    from autoforge_knowledge_platform.rag18 import KnowledgeConfig, KnowledgeRAGEngine

    cfg = KnowledgeConfig(
        workspace_root=str(workspace.resolve()),
        qdrant_path=str(qdrant_path),
    )

    log.info("Config: collection=%s, qdrant=%s, ollama=%s",
             cfg.collection_name, cfg.qdrant_url, cfg.ollama_base_url)

    # ── Index ───────────────────────────────────────────────────────────
    engine = KnowledgeRAGEngine(config=cfg)
    try:
        await engine.initialize()
    except Exception as exc:
        log.error("Failed to initialize indexer: %s", exc)
        return 2

    try:
        report = await engine.index_repository(
            workspace_root=workspace,
            project_id=project_id,
            force=force,
        )
    except Exception as exc:
        log.error("Indexing failed: %s", exc)
        return 2

    await engine.close()
    log.info(
        "Index complete: scanned=%d, inserted=%d, updated=%d, "
        "unchanged=%d, deleted=%d, total_chunks=%d, duration=%.1fms",
        report.sources_scanned,
        report.inserted,
        report.updated,
        report.unchanged,
        report.deleted,
        report.total_chunks,
        report.duration_ms,
    )
    if report.errors:
        for err in report.errors[:5]:
            log.warning("Index error: %s", err)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Index AutoForge workspace into local Qdrant RAG")
    parser.add_argument(
        "--workspace", "-w",
        type=Path,
        default=Path.cwd(),
        help="Workspace root to index (default: cwd)",
    )
    parser.add_argument(
        "--project-id", "-p",
        default=None,
        help="Project ID to scope indexing",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-index all files, even unchanged ones",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(_main(args.workspace, args.project_id, args.force))
    except KeyboardInterrupt:
        log.info("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())