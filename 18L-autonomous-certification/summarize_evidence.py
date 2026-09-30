"""Print a compact summary of every 18-L evidence artifact."""
import json
from pathlib import Path

_E = Path(__file__).resolve().parent / "evidence"

g = json.load(open(_E / "greenfield_run.json"))
print("GREENFIELD : review=%s evidence=%d artifacts=%d/%d source=%d state=%s "
      "recovery_hashes=%s" % (
          g["final_review"]["approved"], g["final_review"]["evidence_files"],
          g["durable_artifact_counts"]["committed"],
          g["durable_artifact_counts"]["total"],
          len(g["durable_artifact_counts"]["source_code"]),
          g["final_state"]["status"], g["recovery"]["all_hash_verified"]))

f = json.load(open(_E / "failure_paths.json"))
print("FAILURE    : %d/%d fail-closed verified" % (f["passed"], f["total"]))

v = json.load(open(_E / "vacuous_approval_probe.json"))
print("B-1        : %s" % v["verdict"][:100])

l = json.load(open(_E / "legacy_modernization.json"))
print("B-2        : pipeline=%s transformed=%s placeholder_content=%s" % (
    l["pipeline_status"], l["transformation_records"],
    l.get("pipeline_uses_placeholder_content")))

a = json.load(open(_E / "architectural_audit.json"))
print("ARCHITECTURE: %d/%d integrity checks passed" % (a["passed"], a["total"]))
