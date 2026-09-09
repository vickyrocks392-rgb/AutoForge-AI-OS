#!/usr/bin/env python3
"""
AutoForge AI — Repository & Qdrant Purification Engine
Safely purges non-core accumulated project data, vector stores, and orphaned collections,
and generates auditable before/after storage reports.
"""

import os
import sys
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = REPO_ROOT / "packages" / "modernization" / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

HP_QDRANT_URL = "http://192.168.1.102:6333"


def get_dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            if not fp.is_symlink() and fp.exists():
                try:
                    total += fp.stat().st_size
                except Exception:
                    pass
    return total


def measure_storage() -> dict:
    all_files = []
    category_map = {
        "PRODUCTION SOURCE": 0,
        "TEST SOURCE": 0,
        "TEST FIXTURE": 0,
        "EXTERNAL WORKLOAD": 0,
        "GENERATED OUTPUT": 0,
        "CERTIFICATION EVIDENCE": 0,
        "BUILD ARTIFACT": 0,
        "CACHE": 0,
        "TOOLCHAIN": 0,
        "TEMPORARY": 0,
        "GIT OBJECTS": 0,
    }
    
    for root, dirs, files in os.walk(REPO_ROOT):
        for f in files:
            fp = Path(root) / f
            if not fp.is_symlink() and fp.exists():
                try:
                    sz = fp.stat().st_size
                    rel = str(fp.relative_to(REPO_ROOT))
                    all_files.append((sz, rel))
                    
                    if rel.startswith(".git/"):
                        category_map["GIT OBJECTS"] += sz
                    elif rel.startswith("packages/modernization/src/") or rel.startswith("apps/") or rel.startswith("packages/kernel/"):
                        category_map["PRODUCTION SOURCE"] += sz
                    elif "tests/" in rel and not "fixtures" in rel:
                        category_map["TEST SOURCE"] += sz
                    elif "fixtures" in rel or "workloads/settle_subsystem" in rel:
                        category_map["TEST FIXTURE"] += sz
                    elif rel.startswith(".autoforge/external_workloads") or rel.startswith(".autoforge/carddemo"):
                        category_map["EXTERNAL WORKLOAD"] += sz
                    elif rel.startswith("builds/") or rel.startswith("dist/") or rel.startswith("phase18/"):
                        category_map["GENERATED OUTPUT"] += sz
                    elif "evidence/" in rel or (rel.endswith(".md") and ("REPORT" in rel or "CERTIFICATION" in rel or "BASELINE" in rel)):
                        category_map["CERTIFICATION EVIDENCE"] += sz
                    elif "__pycache__" in rel or rel.endswith(".pyc") or rel.startswith(".pytest_cache"):
                        category_map["BUILD ARTIFACT"] += sz
                    elif rel.startswith("storage/") or rel.startswith(".autoforge/knowledge/vector-db"):
                        category_map["CACHE"] += sz
                    elif rel.startswith(".autoforge/qdrant") or rel.startswith(".autoforge/tools"):
                        category_map["TOOLCHAIN"] += sz
                    elif rel.startswith(".autoforge/logs") or rel.endswith(".log") or rel.endswith(".tmp"):
                        category_map["TEMPORARY"] += sz
                    else:
                        category_map["PRODUCTION SOURCE"] += sz
                except Exception:
                    pass

    total_sz = sum(sz for sz, _ in all_files)
    return {
        "total_mb": round(total_sz / (1024 * 1024), 2),
        "categories_mb": {k: round(v / (1024 * 1024), 2) for k, v in category_map.items()},
    }


def inventory_and_clean_qdrant() -> dict:
    print("\n[HP QDRANT] Auditing & Purging Orphaned Collections on 192.168.1.102:6333...")
    before_cols = []
    deleted_cols = []
    retained_cols = []
    
    try:
        req = urllib.request.urlopen(f"{HP_QDRANT_URL}/collections", timeout=4)
        data = json.loads(req.read().decode("utf-8"))
        collections = data.get("result", {}).get("collections", [])
        
        for c in collections:
            cname = c["name"]
            before_cols.append(cname)
            
            # Orphaned test/subsystem collections
            if cname.startswith("g5_subsystem_knowledge_") or cname.startswith("test_subsystem_qdrant_") or cname == "autoforge_unseen_payroll_rag":
                del_req = urllib.request.Request(f"{HP_QDRANT_URL}/collections/{cname}", method="DELETE")
                try:
                    with urllib.request.urlopen(del_req, timeout=4) as resp:
                        deleted_cols.append(cname)
                        print(f"  ✓ Purged orphaned collection: {cname}")
                except Exception as e:
                    print(f"  ✕ Failed to delete {cname}: {e}")
            else:
                retained_cols.append(cname)
                
    except Exception as e:
        print(f"  ✕ Warning: Could not connect to HP Qdrant: {e}")

    inventory = {
        "endpoint": HP_QDRANT_URL,
        "collections_before_count": len(before_cols),
        "collections_deleted_count": len(deleted_cols),
        "collections_retained_count": len(retained_cols),
        "deleted_collections": deleted_cols,
        "retained_collections": retained_cols,
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    
    with open(EVIDENCE_DIR / "qdrant_inventory.json", "w") as f:
        json.dump(inventory, f, indent=2)
        
    return inventory


def purge_non_core_files():
    print("\n[FILESYSTEM] Purging Non-Core Accumulated Directories...")
    targets = [
        ("storage", REPO_ROOT / "storage", "Stale local Qdrant WAL and segment caches"),
        ("vector_db", REPO_ROOT / ".autoforge" / "knowledge" / "vector-db", "Duplicate local Qdrant database directory"),
        ("external_workloads", REPO_ROOT / ".autoforge" / "external_workloads", "Cloned course workloads"),
        ("carddemo_clone", REPO_ROOT / ".autoforge" / "carddemo", "Cloned CardDemo repository"),
        ("baseline_builds_a", REPO_ROOT / "builds" / "baseline_m1_only_run_a", "Temporary benchmark target code"),
        ("baseline_builds_b", REPO_ROOT / "builds" / "baseline_m1_only_run_b", "Temporary benchmark target code"),
        ("baseline_builds_dist_a", REPO_ROOT / "builds" / "baseline_m1_hp_distributed_run_a", "Temporary benchmark target code"),
        ("baseline_builds_dist_b", REPO_ROOT / "builds" / "baseline_m1_hp_distributed_run_b", "Temporary benchmark target code"),
        ("qdrant_log", REPO_ROOT / ".autoforge" / "logs" / "qdrant.log", "Runtime daemon log"),
    ]
    
    purged_records = []
    
    for name, p, reason in targets:
        if p.exists():
            sz = get_dir_size(p) if p.is_dir() else p.stat().st_size
            sz_mb = round(sz / (1024 * 1024), 2)
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                purged_records.append({"target": name, "path": str(p.relative_to(REPO_ROOT)), "size_mb": sz_mb, "reason": reason, "status": "PURGED"})
                print(f"  ✓ Purged [{sz_mb} MB]: {p.relative_to(REPO_ROOT)}")
            except Exception as e:
                print(f"  ✕ Error purging {p}: {e}")
                purged_records.append({"target": name, "path": str(p), "size_mb": sz_mb, "reason": reason, "status": f"ERROR: {e}"})

    return purged_records


def main():
    print("===================================================================")
    print("AUTFORGE AI — REPOSITORY PURIFICATION & HYGIENE EXECUTION")
    print("===================================================================")
    
    # 1. Storage Before
    before_storage = measure_storage()
    print(f"Repository Size Before Purification: {before_storage['total_mb']} MB")
    
    # 2. Clean HP Qdrant Collections
    qdrant_inv = inventory_and_clean_qdrant()
    
    # 3. Purge Local Filesystem Targets
    purged_files = purge_non_core_files()
    
    # 4. Storage After
    after_storage = measure_storage()
    print(f"\nRepository Size After Purification:  {after_storage['total_mb']} MB")
    delta_mb = round(before_storage['total_mb'] - after_storage['total_mb'], 2)
    print(f"Total Disk Space Recovered:         {delta_mb} MB")

    audit_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "storage_before": before_storage,
        "storage_after": after_storage,
        "delta_recovered_mb": delta_mb,
        "purged_records": purged_files,
        "qdrant_inventory": qdrant_inv,
    }
    
    with open(EVIDENCE_DIR / "repository_storage_audit.json", "w") as f:
        json.dump(audit_report, f, indent=2)
        
    print("\n[SUCCESS] Storage Audit written to repository_storage_audit.json")


if __name__ == "__main__":
    main()
