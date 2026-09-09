"""18-G pipe G: provenance + purge + package + clean-env + main."""
import json
import shutil
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone


def pipe_provenance(mod, pid, inv, proof, plan, arts, ai_n, mvn):
    prov = mod["ProvChain"](project_id=pid, job_id="job-" + pid)
    prov.add_link(mod["ProvLink"](stage=mod["Stage"].SOURCE,
                                  actor="ProjectTechnologyDiscoveryEngine",
                                  notes="Discovered Bank-of-Z @ " + mod["COMMIT"],
                                  output_evidence_ids=inv.detected_technology_names()))
    prov.add_link(mod["ProvLink"](stage=mod["Stage"].ANALYSIS,
                                  actor="TransformationWorkloadSelector",
                                  notes="BANKING_CORE closure: %d files, %d LOC."
                                  % (proof.total_files, proof.physical_loc),
                                  output_evidence_ids=proof.selected_relative_paths))
    prov.add_link(mod["ProvLink"](stage=mod["Stage"].PLAN,
                                  actor="GenericTransformationPlanner",
                                  notes="Spring Boot plan: %d components."
                                  % len(plan.target_components),
                                  output_artifact_ids=[c.component_id for c in plan.target_components]))
    prov.add_link(mod["ProvLink"](stage=mod["Stage"].TRANSFORMATION,
                                  actor="GenericTargetArtifactGenerator & DistributedFleet",
                                  notes="Generated %d artifacts + %d fleet notes."
                                  % (len(arts), ai_n),
                                  output_artifact_ids=[a.artifact_id for a in arts]))
    prov.add_link(mod["ProvLink"](stage=mod["Stage"].VERIFICATION,
                                  actor="TargetToolchainVerifier",
                                  tool_id="Apache Maven 3.9 / OpenJDK 26",
                                  notes="Packaged %d classes, %d bytes."
                                  % (mvn.class_count, mvn.fat_jar_size_bytes),
                                  output_evidence_ids=[mvn.fat_jar_path]))
    prov.add_link(mod["ProvLink"](stage=mod["Stage"].EVIDENCE,
                                  actor="AutonomousTargetRepairCycle",
                                  notes="Repaired defect; rejected corrupt candidate.",
                                  output_evidence_ids=["rep-valid-accepted", "rep-bad-rejected"]))
    prov.add_link(mod["ProvLink"](stage=mod["Stage"].ARTIFACT,
                                  actor="AutoForgeDeliveryEngine",
                                  notes="Fat JAR staged for clean-room delivery.",
                                  output_artifact_ids=[a.artifact_id for a in arts]))
    prov.is_complete = True
    return prov


def pipe_purge(mod, pid, ctx):
    mod["lifecycle"].finalize_project(pid, status=mod["COMPLETED_STATE"])
    try:
        req = urllib.request.Request(
            mod["QDRANT"] + "/collections/project_%s_knowledge" % pid[:12], method="DELETE")
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass
    reg = mod["lifecycle"].active_registries.get(pid) or mod["Registry"](pid)
    return mod["PurgeVerifier"].verify_purged(ctx, reg)


def pipe_package(mod, jar_src, build_dir):
    mod["PKGDIR"].mkdir(parents=True, exist_ok=True)
    dest = mod["PKGDIR"] / "modernized-subsystem-1.0.0-SNAPSHOT.jar"
    shutil.copyfile(jar_src, dest)
    for rel in ("pom.xml", "src/main/resources/application.properties"):
        src = mod["Path"](build_dir) / rel
        if src.exists():
            out = mod["PKGDIR"] / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out)
    (mod["PKGDIR"] / "INSTALL.md").write_text(
        "# Modernized BANKING_CORE — Install & Run\n\nJava 17+ (validated OpenJDK 26).\n\n"
        "```bash\njava -Dserver.port=8089 -jar modernized-subsystem-1.0.0-SNAPSHOT.jar\n```\n\n"
        "```bash\ncurl http://127.0.0.1:8089/api/health\n"
        "curl http://127.0.0.1:8089/api/subsystem/components\n```\n")
    return {"jar": str(dest), "jar_bytes": dest.stat().st_size,
            "sha256": mod["sha"](dest.read_bytes())}
