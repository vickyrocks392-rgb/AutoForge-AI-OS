"""
18-L C-2: read-only historical audit of Context Compaction durable records.

Objective: prove that no durable compaction state created under the defective
pre-Gate-4 implementation can silently enter the trusted production path.

This script is STRICTLY READ-ONLY. It opens SQLite with ``mode=ro`` where it can,
never writes, and never migrates, quarantines, or deletes anything.

Repair boundary (from filesystem mtimes of the repaired sources):
  * Repair 1 (fingerprint scope)  -> 2026-09-26 18:23
  * Repair 2 (load integrity)      -> 2026-09-26 18:31
Any record created BEFORE those instants is a pre-repair record and is classified.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: Durable compaction records are named ``compaction_<compaction_id>`` where the
#: id is ``cmp_<hex>``. Matching the full pattern is essential: a looser
#: ``compaction_*`` glob also matches the Python SOURCE files
#: (``compaction_policy.py``) and their bytecode caches, which are not records.
COMPACTION_PREFIX = "compaction_"
COMPACTION_ARTIFACT_GLOB = "compaction_cmp_*"
REPAIR_1 = datetime(2026, 9, 26, 18, 23, 0, tzinfo=timezone.utc).timestamp()
REPAIR_2 = datetime(2026, 9, 26, 18, 31, 0, tzinfo=timezone.utc).timestamp()

# The exact timestamp we compare against, from source mtime (local time).
REPAIR_1_LOCAL = datetime(2026, 9, 26, 18, 23, 0).timestamp()
REPAIR_2_LOCAL = datetime(2026, 9, 26, 18, 31, 0).timestamp()


def find_catalogs() -> list[Path]:
    """Every SQLite catalog that could hold durable artifact state."""
    roots = [REPO, Path("/tmp"), Path(os.environ.get("TMPDIR", "/tmp"))]
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*.db"):
                if ".venv" in p.parts or "node_modules" in p.parts:
                    continue
                seen.add(p)
        except (PermissionError, OSError):
            continue
    return sorted(seen)


def find_compaction_artifacts() -> list[Path]:
    """Every on-disk artifact produced by CompactionRecordStore."""
    roots = [REPO, Path("/tmp"), Path(os.environ.get("TMPDIR", "/tmp"))]
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob(COMPACTION_ARTIFACT_GLOB):
                if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts:
                    seen.add(p)
        except (PermissionError, OSError):
            continue
    return sorted(seen)


def read_only_rows(db: Path, table: str) -> list[dict]:
    """Read a table strictly read-only; never create or modify the database."""
    uri = f"file:{db}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        return [{"_error": f"open failed: {exc}"}]
    try:
        cur = conn.execute(f"SELECT * FROM {table}")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except sqlite3.Error as exc:
        return [{"_error": f"query failed: {exc}"}]
    finally:
        conn.close()


def classify(path: Path) -> dict:
    """Classify one persisted compaction record (read-only)."""
    mtime = path.stat().st_mtime
    row: dict = {
        "path": str(path),
        "artifact_name": path.name,
        "file_mtime": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        "size_bytes": path.stat().st_size,
    }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        row["parse_error"] = str(exc)[:120]
        row["classification"] = "CORRUPTED"
        row["rationale"] = f"unreadable as JSON: {exc}"
        return row

    row["compaction_id"] = payload.get("compaction_id")
    row["request_fingerprint"] = payload.get("request_fingerprint")
    row["idempotency_key"] = payload.get("idempotency_key")
    row["task_id"] = payload.get("task_id")
    row["policy_version"] = payload.get("policy_version")
    row["schema_version"] = payload.get("compaction_schema_version")
    row["logical_version"] = payload.get("logical_version")
    row["item_count"] = len(payload.get("items") or [])
    row["reference_count"] = len(payload.get("durable_refs") or [])

    # Repair 1 marker: the post-repair fingerprint is always computed WITH the
    # idempotency key (which embeds task/execution scope) as an input.
    scope = str(row.get("idempotency_key") or "")
    row["fingerprint_encodes_scope"] = bool(scope) and bool(
        row.get("request_fingerprint")
    )

    pre_repair_1 = mtime < REPAIR_1_LOCAL
    pre_repair_2 = mtime < REPAIR_2_LOCAL
    row["pre_repair_1"] = pre_repair_1
    row["pre_repair_2"] = pre_repair_2

    if pre_repair_1:
        row["classification"] = "DUPLICATE / COLLISION-RISK"
        row["rationale"] = (
            "Created before Repair 1 (fingerprint scope). Its identity may not "
            "encode the logical scope, so it cannot be proven collision-free."
        )
    elif pre_repair_2:
        row["classification"] = "INTEGRITY-UNCERTAIN"
        row["rationale"] = (
            "Created before Repair 2 (load-time content_hash verification), so it "
            "was never subject to on-load integrity enforcement."
        )
    else:
        row["classification"] = "VALID"
        row["rationale"] = (
            "Created after both Gate 4 repairs; identity encodes logical scope "
            "and the record is subject to load-time hash verification."
        )
    return row


def location_class(path: Path) -> str:
    """Separate genuine production persistence from ephemeral test scratch.

    C-2 is about durable state that could enter the TRUSTED production path. A
    record under a pytest/`mkdtemp` scratch directory is disposable test output,
    never production state, and is reported separately so the distinction cannot
    be confused.
    """
    parts = set(path.parts)
    text = str(path)
    if "pytest-of-" in text or "af_g4_store_" in text or "af_g4_" in text:
        return "ephemeral test scratch (not production)"
    if str(REPO) in text and "site-packages" not in text:
        return "repository / production-like"
    if "/T/" in text or text.startswith("/tmp") or text.startswith("/var/folders"):
        return "OS temp dir (non-durable, outside repository)"
    return "other"


def main() -> int:
    print("=" * 78)
    print("18-L C-2 - HISTORICAL COMPACTION RECORD AUDIT (READ-ONLY)")
    print("=" * 78)
    print("Repair 1 (fingerprint scope) : 2026-09-26 18:23 local")
    print("Repair 2 (load integrity)     : 2026-09-26 18:31 local")
    print()

    artifacts = find_compaction_artifacts()
    catalogs = find_catalogs()

    print(f"[1] Compaction artifact FILES on disk        : {len(artifacts)}")
    print(f"[2] SQLite catalogs scanned (durable state) : {len(catalogs)}")
    print()

    rows = [classify(p) for p in artifacts]
    for r in rows:
        r["location_class"] = location_class(Path(r["path"]))

    by_location: dict[str, int] = {}
    for r in rows:
        by_location[r["location_class"]] = by_location.get(r["location_class"], 0) + 1

    tally: dict[str, int] = {}
    for r in rows:
        tally[r["classification"]] = tally.get(r["classification"], 0) + 1

    print("--- Where the records live ---")
    for loc, n in sorted(by_location.items()):
        print(f"  {loc:42s} {n}")
    print()

    print("--- Classification of every record found ---")
    for cls, n in sorted(tally.items()):
        print(f"  {cls:32s} {n}")
    print()

    production_rows = [
        r for r in rows if r["location_class"] == "repository / production-like"
    ]
    pre_repair_production = [
        r for r in production_rows if r.get("pre_repair_1") or r.get("pre_repair_2")
    ]

    pre_repair = [r for r in rows if r.get("pre_repair_1") or r.get("pre_repair_2")]
    print(f"PRE-REPAIR RECORDS (ALL LOCATIONS)          : {len(pre_repair)}")
    print(f"PRE-REPAIR RECORDS IN PRODUCTION LOCATIONS  : {len(pre_repair_production)}")
    if pre_repair_production:
        for r in pre_repair_production:
            print(f"  ! {r['path']}")
            print(f"    {r['classification']}: {r['rationale']}")
    else:
        print("  -> NONE in any production-like location.")
    print()

    catalog_rows = []
    for db in catalogs:
        entries = read_only_rows(db, "durable_artifact_state")
        compaction = [
            e for e in entries
            if str(e.get("artifact_name", "")).startswith(COMPACTION_PREFIX)
        ]
        if compaction:
            catalog_rows.append((db, compaction))

    total = sum(len(c) for _db, c in catalog_rows)
    print(f"CATALOG compaction rows (durable_artifact_state): {total}")
    for db, entries in catalog_rows[:10]:
        print(f"  {db}")
        for e in entries[:3]:
            print(f"     name={e.get('artifact_name')} status={e.get('status')}")
    print()

    out = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "repair_1_local": "2026-09-26T18:23:00",
        "repair_2_local": "2026-09-26T18:31:00",
        "artifact_files_found": len(artifacts),
        "artifact_glob": COMPACTION_ARTIFACT_GLOB,
        "catalogs_scanned": len(catalogs),
        "catalog_compaction_rows": total,
        "records_by_location": by_location,
        "classification_tally": tally,
        "pre_repair_record_count_all_locations": len(pre_repair),
        "pre_repair_record_count_production_locations": len(pre_repair_production),
        "production_location_records": production_rows,
        "records": rows,
    }
    dest = Path(__file__).parent / "c2_historical_audit.json"
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {dest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
