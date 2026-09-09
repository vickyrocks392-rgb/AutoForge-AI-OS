"""18-G pipe D2: semantics+rag+plan+generate+inference+build."""
import asyncio
import tempfile
import time


def pipe_semantics(sel, mod, pid, stages, workload):
    t0 = time.perf_counter()
    sm = sel.extractor.extract_project(mod["BANKZ"] / "src" / "base",
                                       file_paths=workload.selected_files)
    stages.append({"stage": "semantic_extraction",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "modules_extracted": sm.total_modules,
                   "procedures_extracted": sm.total_procedures,
                   "entities_extracted": len(sm.entities)})
    return sm


def pipe_plan(mod, pid, stages, sm):
    t0 = time.perf_counter()
    plan = mod["Planner"]().plan(sm, mod["TargetSpec"].java_spring_boot())
    stages.append({"stage": "transformation_planning",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "target_components": len(plan.target_components)})
    return plan


def pipe_generate(mod, sm, plan):
    gen = mod["Generator"]()
    spec = mod["TargetSpec"].java_spring_boot()
    arts = gen.generate(sm, plan, spec, include_project_manifests=True)
    assert any(a.relative_path == "pom.xml" for a in arts)
    assert any(a.relative_path == "src/main/resources/application.properties" for a in arts)
    assert any(a.relative_path.endswith("ModernizedApplication.java") for a in arts)
    return arts, spec


async def pipe_inference(mod, pid, stages, routing, llm_sink, prov_sink, arts, sha_fn):
    t0 = time.perf_counter()
    tasks = mod["ai_tasks"]()

    async def one(spec_t, attempt=0):
        comp, role, prompt, machine, endpoint, tag, worker = spec_t
        if attempt == 0:
            routing.append({"component": comp, "role": role, "machine": machine,
                            "endpoint": endpoint, "model": tag, "worker": worker})
        res = await mod["call_llm"](endpoint, tag, role, prompt, "code_generation",
                                    pid, "task-ai-" + comp.lower(),
                                    "design-note/" + comp + ".md",
                                    machine, worker, llm_sink)
        if res["telemetry"]["result"] != "SUCCESS" and attempt < 2:
            print("  retry %s (attempt %d): %s"
                  % (comp, attempt + 1, res["telemetry"]["result"]), flush=True)
            return await one(spec_t, attempt=attempt + 1)
        return res

    ai_res = await asyncio.gather(*[one(t) for t in tasks])
    failed = [r["telemetry"] for r in ai_res if r["telemetry"]["result"] != "SUCCESS"]
    assert not failed, "fleet inference failures: %s" % failed[:3]
    stages.append({"stage": "concurrent_distributed_inference",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "llm_calls": len(ai_res)})
    for a in arts:
        prov_sink.append({"artifact_id": a.artifact_id, "project_id": pid,
                          "component_name": a.component_name,
                          "relative_path": a.relative_path,
                          "target_language": a.target_language,
                          "classification": "DETERMINISTIC_COMPILER_SYNTHESIS",
                          "is_ai_generated": False, "is_deterministic": True,
                          "originating_stage": "GenericTargetArtifactGenerator",
                          "sha256": sha_fn(a.code)})
    for spec_t, res in zip(tasks, ai_res):
        prov_sink.append({"artifact_id": "art-ai-" + spec_t[0].lower() + "-" + pid[:6],
                          "project_id": pid, "component_name": spec_t[0],
                          "relative_path": "design-notes/" + spec_t[0] + ".md",
                          "target_language": "MARKDOWN", "classification": "AI_DESIGN_NOTE",
                          "is_ai_generated": True, "is_deterministic": False,
                          "originating_stage": spec_t[4] + ":" + spec_t[5],
                          "originating_model": spec_t[5], "worker": spec_t[6],
                          "sha256": sha_fn(res["response"])})
    return ai_res


def pipe_build(mod, pid, stages, arts, spec):
    t0 = time.perf_counter()
    verifier = mod["Verifier"]()
    bdir = mod["Path"](tempfile.mkdtemp(prefix="autoforge_18g_build_"))
    mvn = verifier.verify_maven(arts, spec, build_directory=bdir)
    stages.append({"stage": "maven_build_package",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED" if mvn.passed else "FAILED",
                   "toolchain": mvn.toolchain_used, "command": mvn.command_executed,
                   "fat_jar": mvn.fat_jar_path, "fat_jar_bytes": mvn.fat_jar_size_bytes,
                   "classes": mvn.class_count, "build_directory": mvn.build_directory})
    assert mvn.passed, "Maven build failed: " + (mvn.output_snippet or "")[-3000:]
    assert mvn.fat_jar_size_bytes > 10 * 1024 * 1024
    return verifier, mvn
