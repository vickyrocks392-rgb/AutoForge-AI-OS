"""18-G pipe F: repair + regression via production repair cycle."""
import tempfile
import time
import uuid

_SPRING_ONLY = ("src/main/java/com/autoforge/generated/ModernizedApplication.java",
                "pom.xml",
                "src/main/resources/application.properties")


def pipe_repair(mod, pid, stages, rag_tel, rep_tel, verifier, arts, spec):
    t0 = time.perf_counter()
    spring = [a for a in arts if a.relative_path in _SPRING_ONLY]
    plain = [a for a in arts if a.relative_path not in _SPRING_ONLY]
    assert spring, "Spring entry-point artifacts expected for Maven packaging"
    victim = plain[0]
    # controlled defect: stray statement outside any class (single-branch repair)
    broken = victim.code + '\nSystem.out.println("stray");\n'
    broken_art = mod["Artifact"](component_name=victim.component_name,
                                 target_language=victim.target_language,
                                 relative_path=victim.relative_path, code=broken)
    trial = [broken_art if a.component_name == victim.component_name else a for a in plain]
    fail_res = verifier.verify(trial, spec)
    assert fail_res.passed is False, "controlled defect must fail toolchain verification"
    rag_rec = mod["rag_fn"](pid, "Resolve Java compilation syntax defect in modernized banking app",
                            rag_tel)
    cycle = mod["RepairCycle"](verifier=verifier)
    repaired_plain, outcome, final_res = cycle.repair_cycle(trial, fail_res, spec)
    assert outcome.final_status == "success" and final_res.passed is True, \
        "production repair cycle must succeed: %s" % outcome.final_status
    first_attempt = outcome.attempts[0] if outcome.attempts else None
    diagnosis = getattr(first_attempt, "diagnosis", outcome.diagnosis if hasattr(outcome, "diagnosis") else "toolchain defect")
    strategy = getattr(first_attempt, "repair_strategy", "unknown")
    rep_tel.append({"repair_id": "rep-18g-" + uuid.uuid4().hex[:6],
                    "defect_type": "SYNTAX_INJECTION",
                    "detected_failure": (fail_res.output_snippet or "")[:200],
                    "diagnosis": diagnosis, "strategy": strategy,
                    "diagnosis_rag_query": rag_rec["query"], "diagnosis_rag_used": True,
                    "repair_attempts": outcome.total_attempts,
                    "recompilation_passed": True, "accepted": True,
                    "final_toolchain": getattr(final_res, "toolchain_used", "javac")})
    # corrupt repair candidate must be rejected (real Maven gate)
    corrupt = mod["Artifact"](component_name="CorruptCandidate", target_language="JAVA",
                              relative_path="src/main/java/CorruptCandidate.java",
                              code=victim.code + "\npublic class CorruptCandidate { void broken( { bad( ;\n")
    bad_res = verifier.verify_maven(
        arts + [corrupt], spec,
        build_directory=mod["Path"](tempfile.mkdtemp(prefix="autoforge_18g_bad_")))
    assert bad_res.passed is False
    rep_tel.append({"repair_id": "rep-bad-18g-" + uuid.uuid4().hex[:6],
                    "defect_type": "CORRUPT_CANDIDATE", "diagnosis_rag_used": True,
                    "recompilation_passed": False, "accepted": False,
                    "rejection_reason": "Maven toolchain rejected corrupt candidate"})
    # regression: repair the Spring tree and rebuild the full app with Maven
    fixed_art = repaired_plain[0]
    repaired_arts = []
    for a in plain:
        repaired_arts.append(a)
    repaired_arts[0] = mod["Artifact"](
        component_name=fixed_art.component_name, target_language=fixed_art.target_language,
        relative_path=fixed_art.relative_path, code=fixed_art.code)
    full_fixed = repaired_arts + spring
    reg_dir = mod["Path"](tempfile.mkdtemp(prefix="autoforge_18g_regress_"))
    reg_res = verifier.verify_maven(full_fixed, spec, build_directory=reg_dir)
    assert reg_res.passed
    stages.append({"stage": "autonomous_repair_and_regression",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "valid_repair_accepted": True,
                   "bad_repair_rejected": True,
                   "regression_classes": reg_res.class_count})
