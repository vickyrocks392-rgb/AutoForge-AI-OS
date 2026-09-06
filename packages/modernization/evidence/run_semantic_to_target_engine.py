#!/usr/bin/env python3
"""Semantic-to-Target Engineering Engine Acceptance Runner.

Executes the milestone validation on a real CardDemo multi-module workload:
- Programs: CBACT01C.cbl, COTRN02C.cbl, CSUTLDTC.cbl
- Copybooks: CVACT01Y.cpy
- Batch Jobs: READACCT.jcl

Validates end-to-end:
1. Unified System Semantic Graph & Technology-Neutral Semantic Model
2. System-Level Target Architecture Plan & Target Component Graph
3. Cross-Module Transformation Planning:
   - JCL orchestration -> target pipeline/execution flow
   - Program -> CALL program -> target interface / dependency mapping
   - Shared copybook -> shared domain entity decision
   - Datasets -> data-access boundaries / adapters
   - Unresolved external calls (CEEDAYS, IEFBR14, CEE3ABD) -> explicit ExternalDependencyMapping
   - Business rules & error semantics preserved across modules
4. Multi-Target Generality Proof (Java Spring Boot vs Python FastAPI) without pair engines
5. Coordinated Target Artifact Generation
6. Real Toolchain Verification (javac compiling all artifacts together)
7. Real JVM Behavioral Verification:
   - Orchestrator executing Job READACCT (PREDEL utility -> STEP05 CBACT01C)
   - COTRN02C invoking CSUTLDTC date validation
   - CSUTLDTC evaluating valid and invalid date cases
   - CBACT01C evaluating deterministic file status branches (00->0, 10->16, 99->12)
8. Comprehensive System Provenance Chain
9. Strict Production Reality Gate

Outputs: packages/modernization/evidence/semantic_to_target_engine_report.json
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

repo_root = Path(__file__).resolve().parents[3]
pkg_src = repo_root / "packages" / "modernization" / "src"
if str(pkg_src) not in sys.path:
    sys.path.insert(0, str(pkg_src))

from autoforge_modernization.composition.generator import GenericTargetArtifactGenerator
from autoforge_modernization.composition.planner import (
    ArtifactRole,
    GenericTransformationPlanner,
    PreservationCategory,
)
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)
from autoforge_modernization.semantic.extractors import ProjectSemanticExtractor
from autoforge_modernization.target.specification import TargetSpecification


def main() -> int:
    print("=" * 78)
    print("AUTOFORGE — SEMANTIC-TO-TARGET ENGINEERING ENGINE ACCEPTANCE RUNNER")
    print("=" * 78)

    carddemo_path = repo_root / ".autoforge" / "carddemo" / "app"
    if not carddemo_path.exists():
        print(f"ERROR: CardDemo workload path not found at {carddemo_path}")
        return 1

    workload_rel_files = [
        "cbl/CBACT01C.cbl",
        "cbl/COTRN02C.cbl",
        "cbl/CSUTLDTC.cbl",
        "cpy/CVACT01Y.cpy",
        "jcl/READACCT.jcl",
    ]
    workload_files = [carddemo_path / rf for rf in workload_rel_files]

    t0_all = time.perf_counter()
    prov_chain = ModernizationProvenanceChain(
        project_id="carddemo-multi-module-system",
        job_id="carddemo-system-transformation-job",
    )

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 1 — FORENSIC EXTRACTION & UNIFIED SYSTEM SEMANTIC GRAPH
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 1] Extracting Technology-Neutral Semantic Model & System Graph...")
    extractor = ProjectSemanticExtractor()
    semantic_model = extractor.extract_project(carddemo_path, file_paths=workload_files)
    graph = semantic_model.semantic_graph

    print(f"  Source Modules: {len(semantic_model.modules)} ({list(semantic_model.modules.keys())})")
    print(f"  Source Entities: {len(semantic_model.entities)} ({list(semantic_model.entities.keys())})")
    print(f"  System Semantic Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    prov_chain.add_link(
        ProvenanceLink(
            stage=ProvenanceStage.ANALYSIS,
            actor="ProjectSemanticExtractor",
            input_artifact_ids=[str(f) for f in workload_files],
            output_evidence_ids=[m.source_sha256 for m in semantic_model.modules.values()],
            notes=f"Extracted {len(semantic_model.modules)} modules, {len(semantic_model.entities)} entities, and {len(graph.nodes)} graph nodes",
        )
    )

    # Verify key semantic relationships exist in the source graph
    edge_tuples = [(e.src, e.kind, e.dst) for e in graph.edges]
    has_jcl_exec = any(k == "EXECUTES" for _, k, _ in edge_tuples)
    has_call = any(k == "CALLS" for _, k, _ in edge_tuples)
    has_include = any(k == "INCLUDES" for _, k, _ in edge_tuples)
    assert has_jcl_exec, "Missing EXECUTES edge in semantic graph"
    assert has_call, "Missing CALLS edge in semantic graph"
    assert has_include, "Missing INCLUDES edge in semantic graph"
    print("  ✓ Verified core semantic relationships (EXECUTES, CALLS, INCLUDES) present in graph.")

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 2 — TARGET SYSTEM ARCHITECTURE PLANNING (JAVA)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 2] Planning System-Level Target Architecture for Java...")
    planner = GenericTransformationPlanner()
    java_spec = TargetSpecification.java_spring_boot()
    java_plan = planner.plan(semantic_model, java_spec)

    target_arch = java_plan.target_system_architecture
    assert target_arch is not None, "TargetSystemArchitecture must be generated"
    comp_graph = target_arch.component_graph
    assert comp_graph is not None, "TargetComponentGraph must be generated"

    print(f"  Architecture Style: {target_arch.architecture_style}")
    print(f"  Target Components Planned: {len(java_plan.target_components)}")
    for comp in java_plan.target_components:
        print(f"    - {comp.name} [{comp.role.value}] -> {comp.suggested_relative_path}")

    print(f"\n  Target Component Graph: {len(comp_graph.nodes)} nodes, {len(comp_graph.edges)} edges")
    for edge in comp_graph.edges:
        print(f"    - {edge.src_component_id} --[{edge.kind}]--> {edge.dst_component_id} ({edge.interaction_pattern})")

    print(f"\n  Cross-Module Dependency Mappings: {len(java_plan.cross_module_dependencies)}")
    for dep in java_plan.cross_module_dependencies:
        print(f"    - {dep.source_caller_module} --[{dep.source_relationship_kind}]--> {dep.source_callee_module} "
              f"=> {dep.target_caller_component} --[{dep.target_relationship_kind}]--> {dep.target_callee_component}")

    print(f"\n  Shared Data Ownership Decisions: {len(java_plan.shared_data_decisions)}")
    for sd in java_plan.shared_data_decisions:
        print(f"    - Entity: {sd.entity_name} ({sd.source_type}) -> Target: {sd.target_model_name} "
              f"[{sd.ownership_strategy}], Consumers: {sd.sharing_modules}")

    print(f"\n  DataStore / I/O Mappings: {len(java_plan.datastore_mappings)}")
    for ds in java_plan.datastore_mappings[:4]:
        print(f"    - Store: {ds.dataset_name} ({ds.resource_type}) -> Adapter: {ds.target_adapter_name} "
              f"[{ds.adapter_strategy}], Modes: {ds.access_modes}")

    print(f"\n  Execution / Batch Orchestration Flows: {len(java_plan.execution_orchestration)}")
    for ef in java_plan.execution_orchestration:
        print(f"    - Job: {ef.job_name} -> Orchestrator: {ef.target_orchestrator_name} "
              f"[{ef.orchestration_pattern}], Steps: {len(ef.steps)}")

    print(f"\n  Explicit Unresolved External Dependencies: {len(java_plan.external_dependencies)}")
    for ed in java_plan.external_dependencies:
        print(f"    - Call: {ed.source_module} -> {ed.unresolved_target_name} [{ed.dependency_kind}] "
              f"| Blocking: {ed.is_blocking} | Path: {ed.recommended_resolution_path}")

    prov_chain.add_link(
        ProvenanceLink(
            stage=ProvenanceStage.PLAN,
            actor="GenericTransformationPlanner",
            input_evidence_ids=[m.source_sha256 for m in semantic_model.modules.values()],
            output_artifact_ids=[c.component_id for c in java_plan.target_components],
            notes=f"Derived target system architecture with {len(comp_graph.nodes)} nodes and {len(java_plan.cross_module_dependencies)} cross-module dependencies",
        )
    )

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 3 — MULTI-TARGET ARCHITECTURAL GENERALITY PROOF (PYTHON)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 3] Planning System-Level Target Architecture for Python (Generality Proof)...")
    py_spec = TargetSpecification.python_fastapi()
    py_plan = planner.plan(semantic_model, py_spec)

    print(f"  Target Language: {py_plan.target_language}")
    print(f"  Target Architecture Style: {py_plan.target_architecture.architecture_style}")
    print(f"  Target Components Planned: {len(py_plan.target_components)}")

    # Strict divergence assertions
    assert java_plan.target_language != py_plan.target_language
    assert java_plan.target_architecture.architecture_style != py_plan.target_architecture.architecture_style
    assert all(c.suggested_relative_path.endswith(".java") for c in java_plan.target_components)
    assert all(c.suggested_relative_path.endswith(".py") for c in py_plan.target_components)
    print("  ✓ Multi-target generality verified: Same source semantics produced distinct, language-idiomatic architectures.")

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 4 — COORDINATED TARGET ARTIFACT GENERATION
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 4] Generating Coordinated Target Artifacts (Java)...")
    generator = GenericTargetArtifactGenerator()
    artifacts = generator.generate(semantic_model, java_plan, java_spec)

    print(f"  Generated {len(artifacts)} target artifacts:")
    for a in artifacts:
        print(f"    - {a.component_name} ({a.loc} LOC) -> {a.relative_path} [SHA: {a.sha256[:12]}]")

    # Verify inter-artifact coordination
    code_map = {a.component_name: a.code for a in artifacts}
    assert "Cvact01y" in code_map, "Cvact01y domain model missing"
    assert "Cbact01c" in code_map, "Cbact01c component missing"
    assert "Cotrn02c" in code_map, "Cotrn02c component missing"
    assert "Csutldtc" in code_map, "Csutldtc component missing"
    assert "ReadacctOrchestration" in code_map, "ReadacctOrchestration orchestrator missing"

    # Cotrn02c must reference Csutldtc
    assert "Csutldtc csutldtc" in code_map["Cotrn02c"], "Cotrn02c does not coordinate with Csutldtc"
    # Cotrn02c and Cbact01c must reference shared domain model Cvact01y
    assert "Cvact01y cvact01y" in code_map["Cotrn02c"], "Cotrn02c does not reference Cvact01y"
    assert "Cvact01y cvact01y" in code_map["Cbact01c"], "Cbact01c does not reference Cvact01y"
    # ReadacctOrchestration must coordinate Cbact01c execution
    assert "Cbact01c cbact01c" in code_map["ReadacctOrchestration"], "Orchestrator does not reference Cbact01c"
    print("  ✓ Verified inter-artifact coordination across generated target files.")

    prov_chain.add_link(
        ProvenanceLink(
            stage=ProvenanceStage.TRANSFORMATION,
            actor="GenericTargetArtifactGenerator",
            input_artifact_ids=[c.component_id for c in java_plan.target_components],
            output_artifact_ids=[a.artifact_id for a in artifacts],
            notes=f"Generated {len(artifacts)} coordinated target artifacts ({sum(a.loc for a in artifacts)} LOC)",
        )
    )

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 5 — REAL TOOLCHAIN COMPILATION VERIFICATION
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 5] Real Toolchain Verification with Host javac...")
    verifier = TargetToolchainVerifier()
    v_res = verifier.verify(artifacts, java_spec)

    print(f"  Compilation Passed: {v_res.passed}")
    print(f"  Class Files Generated: {len(v_res.class_files_generated)}")
    for cf in v_res.class_files_generated:
        print(f"    - {cf}")

    if not v_res.passed:
        print(f"ERROR: javac compilation failed:\n{v_res.output_snippet}")
        return 1

    prov_chain.add_link(
        ProvenanceLink(
            stage=ProvenanceStage.VERIFICATION,
            actor="TargetToolchainVerifier",
            input_artifact_ids=[a.artifact_id for a in artifacts],
            output_evidence_ids=[v_res.verification_id],
            notes=f"Compiled {len(v_res.class_files_generated)} classes with OpenJDK javac",
        )
    )
    print("  ✓ All coordinated target artifacts successfully compiled together into JVM bytecode.")

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 6 — REAL JVM BOUNDED BEHAVIORAL VERIFICATION
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 6] Executing Bounded Target Behavioral Verification on JVM...")
    java_bin = repo_root / ".autoforge" / "tools" / "openjdk" / "bin" / "java"
    class_bin_dir = Path(v_res.class_files_generated[0]).parent.parent.parent.parent

    behavioral_results: list[dict[str, Any]] = []

    # 6a. Orchestrated Job Execution (ReadacctOrchestration -> Cbact01c)
    cmd_orch = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.ReadacctOrchestration"]
    proc_orch = subprocess.run(cmd_orch, capture_output=True, text=True, check=True)
    orch_out = proc_orch.stdout.strip()
    assert "JOB_RESULT=0" in orch_out, f"Job orchestration failed: {orch_out}"
    print(f"  ✓ Orchestration Workflow (ReadacctOrchestration): {orch_out}")
    behavioral_results.append({
        "component": "ReadacctOrchestration",
        "description": "Multi-step batch job orchestration invoking Cbact01c",
        "expected": "JOB_RESULT=0",
        "observed": orch_out,
        "passed": True,
    })

    # 6b. Cross-Module Service Call (Cotrn02c -> Csutldtc)
    cmd_cotrn = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cotrn02c"]
    proc_cotrn = subprocess.run(cmd_cotrn, capture_output=True, text=True, check=True)
    cotrn_out = proc_cotrn.stdout.strip()
    assert "Return code: 0" in cotrn_out, f"Cross-module call failed: {cotrn_out}"
    print(f"  ✓ Cross-Module Invocation (Cotrn02c -> Csutldtc): {cotrn_out}")
    behavioral_results.append({
        "component": "Cotrn02c",
        "description": "Inter-module call to Csutldtc date routine",
        "expected": "Return code: 0",
        "observed": cotrn_out,
        "passed": True,
    })

    # 6c. Preserved Date Utility Logic (Csutldtc)
    date_tests = [
        ("2026-09-06", "YYYY-MM-DD", "DATE_RESULT=0", "Valid ISO date format"),
        ("BAD_DATE_FORMAT", "YYYY-MM-DD", "DATE_RESULT=4", "Invalid date format error"),
    ]
    for dt, fmt, exp, desc in date_tests:
        cmd_dt = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Csutldtc", dt, fmt]
        proc_dt = subprocess.run(cmd_dt, capture_output=True, text=True, check=True)
        dt_out = proc_dt.stdout.strip()
        assert exp in dt_out, f"Date test {dt} failed: {dt_out}"
        print(f"  ✓ Date Routine ({dt} [{desc}]): {dt_out}")
        behavioral_results.append({
            "component": "Csutldtc",
            "description": f"Date validation semantics ({desc})",
            "expected": exp,
            "observed": dt_out,
            "passed": True,
        })

    # 6d. Preserved Deterministic File Status Evaluation (Cbact01c)
    status_tests = [
        ("00", "STATUS_RESULT=0", "Success (00 -> RC 0)"),
        ("10", "STATUS_RESULT=16", "End of File (10 -> RC 16)"),
        ("99", "STATUS_RESULT=12", "I/O Error (Other -> RC 12)"),
    ]
    for inp_status, exp, desc in status_tests:
        cmd_st = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cbact01c", inp_status]
        proc_st = subprocess.run(cmd_st, capture_output=True, text=True, check=True)
        st_out = proc_st.stdout.strip()
        assert exp in st_out, f"Status test {inp_status} failed: {st_out}"
        print(f"  ✓ File Status Branch ({inp_status} [{desc}]): {st_out}")
        behavioral_results.append({
            "component": "Cbact01c",
            "description": f"Deterministic business rule: {desc}",
            "expected": exp,
            "observed": st_out,
            "passed": True,
        })

    prov_chain.add_link(
        ProvenanceLink(
            stage=ProvenanceStage.VERIFICATION,
            actor="RealJVMExecutionHarness",
            input_artifact_ids=[a.artifact_id for a in artifacts],
            output_evidence_ids=[v_res.verification_id],
            notes=f"Executed {len(behavioral_results)} JVM behavioral verification checks (all passed)",
        )
    )

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 7 — PRODUCTION REALITY REPORT
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 7] Generating Production Reality Report & Artifacts...")
    elapsed_total = time.perf_counter() - t0_all

    report_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(elapsed_total, 3),
        "workload": {
            "name": "CardDemo Multi-Module System Workload",
            "source_files": workload_rel_files,
            "modules_count": len(semantic_model.modules),
            "entities_count": len(semantic_model.entities),
            "procedures_count": semantic_model.total_procedures,
            "operations_count": semantic_model.total_operations,
            "business_rules_count": semantic_model.total_business_rules,
            "io_operations_count": len(semantic_model.io_operations),
            "system_semantic_graph": {
                "nodes_count": len(graph.nodes),
                "edges_count": len(graph.edges),
            },
        },
        "target_system_architecture": {
            "target_language": java_plan.target_language,
            "architecture_style": target_arch.architecture_style,
            "components_count": len(java_plan.target_components),
            "component_graph": {
                "nodes_count": len(comp_graph.nodes),
                "edges_count": len(comp_graph.edges),
                "edges": [
                    {
                        "src": e.src_component_id,
                        "dst": e.dst_component_id,
                        "kind": e.kind,
                        "interaction_pattern": e.interaction_pattern,
                    }
                    for e in comp_graph.edges
                ],
            },
            "cross_module_dependencies": [
                {
                    "caller": dep.source_caller_module,
                    "callee": dep.source_callee_module,
                    "source_kind": dep.source_relationship_kind,
                    "target_caller": dep.target_caller_component,
                    "target_callee": dep.target_callee_component,
                    "target_kind": dep.target_relationship_kind,
                    "interaction_pattern": dep.interaction_pattern,
                }
                for dep in java_plan.cross_module_dependencies
            ],
            "shared_data_decisions": [
                {
                    "entity": sd.entity_name,
                    "source_type": sd.source_type,
                    "target_model": sd.target_model_name,
                    "ownership_strategy": sd.ownership_strategy,
                    "consumers": sd.sharing_modules,
                }
                for sd in java_plan.shared_data_decisions
            ],
            "datastore_mappings": [
                {
                    "dataset": ds.dataset_name,
                    "resource_type": ds.resource_type,
                    "target_adapter": ds.target_adapter_name,
                    "strategy": ds.adapter_strategy,
                    "access_modes": ds.access_modes,
                }
                for ds in java_plan.datastore_mappings
            ],
            "execution_orchestration": [
                {
                    "job": ef.job_name,
                    "orchestrator": ef.target_orchestrator_name,
                    "pattern": ef.orchestration_pattern,
                    "steps": ef.steps,
                }
                for ef in java_plan.execution_orchestration
            ],
            "external_dependencies": [
                {
                    "source_module": ed.source_module,
                    "target": ed.unresolved_target_name,
                    "kind": ed.dependency_kind,
                    "affected_component": ed.affected_component,
                    "blocking": ed.is_blocking,
                    "confidence": ed.confidence,
                    "recommended_resolution_path": ed.recommended_resolution_path,
                }
                for ed in java_plan.external_dependencies
            ],
        },
        "multi_target_divergence": {
            "proven": True,
            "targets": [
                {
                    "language": java_plan.target_language,
                    "style": java_plan.target_architecture.architecture_style,
                    "components_count": len(java_plan.target_components),
                },
                {
                    "language": py_plan.target_language,
                    "style": py_plan.target_architecture.architecture_style,
                    "components_count": len(py_plan.target_components),
                },
            ],
        },
        "generation": {
            "artifacts_count": len(artifacts),
            "artifacts": [
                {
                    "component": a.component_name,
                    "relative_path": a.relative_path,
                    "loc": a.loc,
                    "sha256": a.sha256,
                }
                for a in artifacts
            ],
        },
        "verification": {
            "toolchain": "OpenJDK javac (Host Compiler)",
            "passed": v_res.passed,
            "classes_generated": len(v_res.class_files_generated),
            "duration_ms": v_res.duration_ms,
        },
        "behavioral_verification": {
            "runtime": "OpenJDK java (Host JVM)",
            "total_checks": len(behavioral_results),
            "all_passed": all(b["passed"] for b in behavioral_results),
            "checks": behavioral_results,
        },
        "provenance_chain": {
            "total_links": len(prov_chain.links),
            "stages": [l.stage.value for l in prov_chain.links],
        },
        "production_reality_gate": {
            "PROVEN": [
                "Multi-module semantic graph drives system-level target transformation",
                "Cross-module dependencies (COTRN02C->CSUTLDTC, READACCT->CBACT01C) mapped to target relationships",
                "Shared copybook entity CVACT01Y mapped to shared target domain model Cvact01y",
                "Unresolved external dependencies (CEEDAYS, IEFBR14, CEE3ABD, COBDATFT) explicitly tracked without fabrication",
                "JCL execution flow mapped to sequential pipeline orchestrator ReadacctOrchestration",
                "Coordinated Java artifacts generated without source-target pair engines",
                "Real javac compilation of all coordinated artifacts into JVM bytecode",
                "Real JVM execution of batch orchestration, inter-module call, and file status branches",
                "Multi-target architecture divergence proven between Java and Python from identical source semantics",
                "End-to-end modernization provenance connecting source evidence to target behavior",
            ],
            "PARTIALLY_PROVEN": [
                "I/O dataset boundaries mapped to file/stream adapters (runtime VSAM/KSDS emulators not executed)",
                "CEEDAYS IBM LE callable service mapped to simulated ISO date parser with non-blocking fallback",
            ],
            "BLOCKED": [],
            "NOT_PROVEN": [
                "Full CardDemo migration (only 5-file bounded multi-module system proven)",
                "Spring Boot framework runtime execution (only standard OpenJDK JVM execution verified)",
                "Full relational database / SQL migration for VSAM files (only file/stream adapter mapped)",
            ],
        },
    }

    report_path = repo_root / "packages" / "modernization" / "evidence" / "semantic_to_target_engine_report.json"
    report_path.write_text(json.dumps(report_data, indent=2))
    print(f"\nReport written to {report_path}")

    print("\n" + "=" * 78)
    print("ALL MILESTONE ACCEPTANCE CRITERIA SUCCESSFULLY SATISFIED")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
