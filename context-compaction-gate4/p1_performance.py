"""18-L P1 §20: performance of the repaired persistence path."""

import json
import statistics
import tempfile
import time
from pathlib import Path

from autoforge_execution.compaction import (
    CompactionPolicy,
    CompactionRecordStore,
    ContextCompactor,
)
from autoforge_execution.models import (
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)

HERE = Path(__file__).parent


def hist(n: int = 12):
    return [
        LoopIterationRecord(
            iteration=i,
            action_plan=f"iteration {i}: investigate the connection pool timeout",
            changed_files=[f"src/pool_{i}.py"],
            passed=False,
            evaluation=EvaluationResult(
                status=EvaluationStatus.FAILED,
                failures=[f"test_pool_timeout::FAILED at iteration {i}"],
            ),
        )
        for i in range(1, n + 1)
    ]


def stack(root: Path):
    from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
    from autoforge_runtime.persistence import PersistenceLayer
    from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

    art = root / "artifacts"
    store = PhysicalArtifactStore(
        artifact_root=art,
        staging_root=art / ".staging",
        quarantine_root=art / ".quarantine",
    )
    catalog = DurableArtifactCatalog(
        persistence=PersistenceLayer(db_path=root / "state.db"),
        physical_store=store,
    )
    return CompactionRecordStore(catalog, store)


def timed(fn, n: int = 25):
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return {
        "mean_ms": round(statistics.mean(samples), 4),
        "median_ms": round(statistics.median(samples), 4),
        "max_ms": round(max(samples), 4),
    }


def main() -> int:
    compactor = ContextCompactor(CompactionPolicy(enabled=True))
    record = compactor.compact(task_id="perf", prior_iterations=hist())

    # Logical identity computation (in-memory, no I/O).
    identity = timed(lambda: record.logical_identity(), 200)
    # Existing content digest, for comparison.
    content = timed(lambda: record.content_digest(), 200)
    # Serialization.
    serial = timed(lambda: record.as_dict(), 200)

    # First save (full write path) then replay saves (identity comparison path).
    first_root = Path(tempfile.mkdtemp(prefix="p1_perf_first_"))
    cstore = stack(first_root)
    first = timed(lambda: cstore.save(record), 15)

    replay_root = Path(tempfile.mkdtemp(prefix="p1_perf_replay_"))
    rstore = stack(replay_root)
    rstore.save(record)  # commit once
    replay = timed(lambda: rstore.save(record), 15)

    # Reload incl. byte-hash integrity verification.
    load = timed(lambda: rstore.load(record.compaction_id), 15)

    out = {
        "logical_identity_computation": identity,
        "content_digest_computation": content,
        "serialization": serial,
        "first_save_full_write": first,
        "replay_save_identity_comparison": replay,
        "load_with_integrity_verification": load,
        "notes": {
            "logical_identity": (
                "Covers every serialized field except the two declared "
                "runtime-only ones; cost is one canonical JSON dump plus SHA-256."
            ),
            "replay_save": (
                "Now reads the committed artifact and RECOMPUTES its logical "
                "identity, instead of hashing the incoming payload. One small "
                "file read plus one parse per replay."
            ),
            "load": (
                "Unchanged from the Gate 4 repair: SHA-256 over the stored bytes "
                "against the catalog hash, plus the new logical-identity check."
            ),
        },
    }
    (HERE / "p1_performance.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print("=== §20 PERFORMANCE (repaired persistence path) ===")
    for key in (
        "logical_identity_computation",
        "content_digest_computation",
        "serialization",
        "first_save_full_write",
        "replay_save_identity_comparison",
        "load_with_integrity_verification",
    ):
        m = out[key]
        print(f"  {key:38s} mean={m['mean_ms']:8.4f}ms  max={m['max_ms']:8.4f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
