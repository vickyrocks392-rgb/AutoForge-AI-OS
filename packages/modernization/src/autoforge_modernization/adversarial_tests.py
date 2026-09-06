"""Adversarial tests for Phase 18-G.3 modernization engine.

This module is runnable as a script:

    python -m autoforge_modernization.adversarial_tests

When invoked that way no sys.path manipulation is needed because the
package is already importable via the installed ``autoforge_modernization``
namespace.  A guard is kept for the case where the file is executed
directly with a non-package interpreter, but it derives the package ``src``
directory from ``__file__`` (no hardcoded developer paths).
"""
from __future__ import annotations
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: int
    error: str | None = None


def run_test(name: str, fn) -> TestResult:
    start = time.time()
    try:
        fn()
        return TestResult(name=name, passed=True, duration_ms=int((time.time() - start) * 1000))
    except Exception as e:
        return TestResult(name=name, passed=False, duration_ms=int((time.time() - start) * 1000), error=str(e))


def _ensure_package_on_path() -> None:
    """Add the package ``src`` directory to ``sys.path`` only when needed.

    Derives the path from ``__file__`` so it works regardless of where the
    repository is checked out.  This is a controlled bootstrap path for the
    script-entry use case, not a hardcoded developer path.
    """
    pkg_src = Path(__file__).resolve().parent
    if str(pkg_src) not in sys.path:
        sys.path.insert(0, str(pkg_src))


def _m():
    _ensure_package_on_path()
    from autoforge_modernization.cobol_ast import COBOLTokenizer
    from autoforge_modernization.cobol_parser import COBOLParser
    from autoforge_modernization.jcl_semantics import JCLParser
    from autoforge_modernization.sql_semantics import SQLParser
    from autoforge_modernization.dependency_graph import DependencyGraph, EdgeKind
    from autoforge_modernization.transformation_engine import TransformationEngine
    from autoforge_modernization.dag_scheduler import DAGScheduler
    from autoforge_modernization.rag_integration import RAGClient
    from autoforge_modernization.ollama_integration import OllamaClient
    from autoforge_modernization.capability_stubs import CapabilityDetector
    from autoforge_modernization.metrics_forensics import MetricsForensics
    return dict(locals())


# Original tests (21)


def test_cobol_empty():
    m = _m()
    p = m["COBOLParser"](m["COBOLTokenizer"]("").tokenize())
    r = p.parse()
    assert r is not None


def test_cobol_minimal():
    m = _m()
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TEST.\n       PROCEDURE DIVISION.\n           GOBACK."
    p = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize())
    r = p.parse()
    assert r.name == "TEST"


def test_cobol_pic_binary():
    m = _m()
    src = "       01 WS-AMT PIC 9(9) BINARY.\n       01 WS-NAME PIC X(20)."
    p = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize())
    p.parse()
    dt = p.summary()["data_types"]
    assert isinstance(dt, dict)


def test_jcl_minimal():
    m = _m()
    p = m["JCLParser"]("//MYJOB JOB (ACCT)\n//STEP1 EXEC PGM=DUMMY\n")
    p.parse()
    assert p.summary()["job_name"] == "MYJOB"


def test_jcl_cycle():
    m = _m()
    g = m["DependencyGraph"]()
    a = g.node("A", "COBOL"); b = g.node("B", "COBOL")
    g.edge(a, b, m["EdgeKind"].CALL); g.edge(b, a, m["EdgeKind"].CALL)
    cycles = g.cycles()
    assert len(cycles) > 0


def test_dependency_graph():
    m = _m()
    g = m["DependencyGraph"]()
    prog = g.node("PROG1", "COBOL"); copy = g.node("CPY1", "COPYBOOK")
    g.edge(prog, copy, m["EdgeKind"].COPY)
    order = g.topological_sort()
    names = [n.name for n in order]
    assert names.index("PROG1") < names.index("CPY1")


def test_sql_minimal():
    m = _m()
    p = m["SQLParser"]("CREATE TABLE TESTTABLE (ID INT);")
    p.parse()
    assert "TESTTABLE" in p.summary()["tables"]


def test_transform_cobol():
    m = _m()
    e = m["TransformationEngine"]()
    r = e.transform_cobol({"program_id": "PGM1", "data_items": ["A", "B"], "paragraphs": ["P1"], "external_calls": [], "gaps": [], "data_types": {"A": {"java_type": "int"}}, "copybooks": [], "performed_targets": []}, "test")
    assert r.status == "OK"


def test_transform_cobol_review():
    m = _m()
    e = m["TransformationEngine"]()
    r = e.transform_cobol({"program_id": "PGM1", "data_items": [], "paragraphs": ["MAIN"], "external_calls": ["CICSAPI"], "gaps": ["x"], "data_types": {}, "copybooks": [], "performed_targets": []}, "test")
    assert r.status == "REVIEW_REQUIRED"


def test_rag_off():
    m = _m()
    rc = m["RAGClient"](available=False)
    r = rc.retrieve("test query", scope="cobol")
    assert r["available"] is False


def test_rag_metrics():
    m = _m()
    rc = m["RAGClient"](available=False)
    rc.retrieve("test", scope="cobol")
    m2 = rc.get_metrics()
    assert m2["calls"] == 1


def test_ollama_off():
    m = _m()
    oc = m["OllamaClient"](available=False)
    r = oc.complete("test", file_path="/test.cbl", task="test")
    assert r["available"] is False


def test_ollama_metrics():
    m = _m()
    oc = m["OllamaClient"](available=False)
    oc.complete("test", file_path="/test.cbl", task="test")
    m2 = oc.get_metrics()
    assert m2["calls"] == 1


def test_dag_scheduler():
    m = _m()
    from autoforge_modernization.dependency_graph import DependencyGraph, EdgeKind
    g = DependencyGraph()
    a = g.node("A", "COBOL"); b = g.node("B", "COBOL"); c = g.node("C", "COBOL")
    g.edge(a, b, EdgeKind.CALL); g.edge(b, c, EdgeKind.CALL)
    sched = m["DAGScheduler"](g)
    results = sched.schedule(lambda ctx: ctx)
    assert len(results) == 3


def test_dag_scheduler_cycle():
    m = _m()
    from autoforge_modernization.dependency_graph import DependencyGraph, EdgeKind
    g = DependencyGraph()
    a = g.node("A", "COBOL"); b = g.node("B", "COBOL")
    g.edge(a, b, EdgeKind.CALL); g.edge(b, a, EdgeKind.CALL)
    try:
        m["DAGScheduler"](g).schedule(lambda ctx: ctx)
        assert False, "Expected cycle error"
    except RuntimeError as e:
        assert "cycle" in str(e).lower()


def test_metrics_forensics():
    m = _m()
    mf = m["MetricsForensics"]()
    s = mf.stage("parse"); s.count = 10; s.bytes_in = 1000
    mf.incr("files_total", 5); mf.incr("files_ok", 3)
    mf.set_semantic_loc(500); mf.set_generated_loc(400)
    sm = mf.summary()
    assert sm["counters"]["files_total"] == 5
    assert sm["loc_ratio"] == 0.8


def test_capability_cics():
    m = _m()
    r = m["CapabilityDetector"]().detect_all("EXEC CICS LINK PROGRAM('PGM1')")
    assert len(r) == 1 and r[0].technology == "CICS"


def test_capability_asm():
    m = _m()
    r = m["CapabilityDetector"]().detect_all("  CSECT\n  BALR 12,0\n  USING *,12")
    assert len(r) == 1 and r[0].technology == "ASM"
    assert r[0].mode.value == "BLOCKED"


def test_capability_none():
    assert _m()["CapabilityDetector"]().detect_all("hello world COBOL") == []


def test_provenance_hashes():
    m = _m()
    e = m["TransformationEngine"]()
    r = e.transform_cobol({"program_id": "PGM1", "data_items": [], "paragraphs": [], "external_calls": [], "gaps": [], "data_types": {}, "copybooks": [], "performed_targets": []}, "source code")
    assert len(r.source_hash) == 16 and len(r.target_hash) == 16
    assert r.source_hash != r.target_hash


def test_jcl_proc_resolution():
    m = _m()
    from autoforge_modernization.dependency_graph import build_from_jcl
    g = m["DependencyGraph"]()
    sm = {"job_name": "JOB1", "steps": [{"name": "S1", "program": "PGM1"}, {"name": "S2", "proc": "PROC1"}], "datasets": ["D1"], "proc_libs": []}
    build_from_jcl(sm, g)
    assert g.summary()["edge_count"] >= 3


def test_transform_cobol_blocked():
    m = _m()
    e = m["TransformationEngine"]()
    r = e.transform_cobol({"program_id": "", "data_items": [], "paragraphs": [], "external_calls": ["CICSAPI"], "gaps": ["x"], "data_types": {}, "copybooks": [], "performed_targets": []}, "test")
    assert r.status == "BLOCKED"


def test_transform_jcl():
    m = _m()
    e = m["TransformationEngine"]()
    r = e.transform_jcl({"job_name": "MYJOB", "steps": [{"name": "S1", "program": "PGM1"}], "datasets": ["D1"], "proc_libs": []}, "test")
    assert r.status == "OK"


def test_transform_jcl_blocked():
    m = _m()
    e = m["TransformationEngine"]()
    r = e.transform_jcl({"job_name": "MYJOB", "steps": [], "datasets": []}, "test")
    assert r.status == "BLOCKED"


def test_transform_sql():
    m = _m()
    e = m["TransformationEngine"]()
    r = e.transform_sql({"tables": ["T1"], "views": ["V1"], "indexes": []}, "test")
    assert r.status == "OK"
    assert "@Entity" in r.target_code


# New G.3 tests (32)


def test_cobol_semantic_move():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MOVETST.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 A PIC 9(5) VALUE 100.\n       01 B PIC 9(5).\n       PROCEDURE DIVISION.\n       MAIN.\n           MOVE A TO B.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert prov["program_id"] == "MOVETST"
    assert "private int" in java


def test_cobol_semantic_move_literal():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. LITEST.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 X PIC X(10).\n       PROCEDURE DIVISION.\n       MAIN.\n           MOVE 'HELLO' TO X.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "'HELLO'" in java


def test_cobol_semantic_perform():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PERTEST.\n       PROCEDURE DIVISION.\n       MAIN.\n           PERFORM DOIT.\n       DOIT.\n           CONTINUE.\n       GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "doit();" in java


def test_cobol_semantic_function_uppercase():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. FUNTEST.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 NAME PIC X(20).\n       01 UPPER-NAME PIC X(20).\n       PROCEDURE DIVISION.\n       MAIN.\n           MOVE FUNCTION UPPER-CASE(NAME) TO UPPER-NAME.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "toUpperCase()" in java

    p = m["SQLParser"]("CREATE TABLE TESTTABLE (ID INT);")



def test_cobol_semantic_set():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SETTEST.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 FLG PIC X VALUE 'N'.\n       PROCEDURE DIVISION.\n       MAIN.\n           SET FLG TO TRUE.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "true" in java


def test_cobol_semantic_arithmetic():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. ARITEST.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 A PIC 9(5) VALUE 10.\n       01 B PIC 9(5) VALUE 3.\n       PROCEDURE DIVISION.\n       MAIN.\n           ADD B TO A.\n           SUBTRACT B FROM A.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "this.a = this.a +" in java
    assert "this.a = this.a -" in java


def test_cobol_semantic_cics_detected():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CICSTST.\n       PROCEDURE DIVISION.\n       MAIN.\n           EXEC CICS RECEIVE MAP('MAP1') END-EXEC.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert prov["cics_detected"] is True


def test_cobol_semantic_call_review():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CALLTST.\n       PROCEDURE DIVISION.\n       MAIN.\n           CALL 'SUBPROG'.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "REVIEW_REQUIRED" in java
    assert "external_call" in str(gaps)





def test_cobol_semantic_evaluate():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. EVATEST.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 X PIC 9 VALUE 1.\n       PROCEDURE DIVISION.\n       MAIN.\n           EVALUATE X WHEN 1 CONTINUE END-EVALUATE.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "switch" in java


def test_cobol_semantic_pic_types():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PICTYPE.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01 A PIC 9(5) COMP.\n       01 B PIC 9(5) COMP-3.\n       01 C PIC X(10).\n       01 D PIC S9(9) BINARY.\n       PROCEDURE DIVISION.\n       MAIN.\n           GOBACK.\n"
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert "private int a;" in java
    assert "private int b;" in java
    assert "private String c;" in java
    assert "private long d;" in java


def test_jcl_step_ordering():
    m = _m()
    src = "//MYJOB JOB (ACCT)\n//STEP1 EXEC PGM=PGM1\n//STEP2 EXEC PGM=PGM2\n//STEP3 EXEC PGM=PGM3\n"
    p = m["JCLParser"](src)
    p.parse()
    s = p.summary()
    assert len(s["steps"]) == 3
    assert s["steps"][0]["name"] == "STEP1"
    assert s["steps"][2]["name"] == "STEP3"


def test_jcl_include_members():
    m = _m()
    src = "//MYJOB JOB (ACCT)\n//STEP1 EXEC PGM=IKJEFT01\n//   INCLUDE MEMBER=PROC001\n//   SET VAR=VAL\n"
    p = m["JCLParser"](src)
    p.parse()
    s = p.summary()
    assert "PROC001" in s["proc_libs"]



def test_jcl_workflow_yaml():
    m = _m()
    src = "//MYJOB JOB (ACCT)\n//STEP1 EXEC PGM=PGM1\n//DD1 DD DSN=DATA.FILE,DISP=SHR\n"
    p = m["JCLParser"](src)
    p.parse()
    yaml = p.to_workflow_yaml()
    assert "MYJOB" in yaml
    assert "STEP1" in yaml
    assert "DATA.FILE" in yaml


def test_jcl_dataset_extraction():
    m = _m()
    src = "//MYJOB JOB (ACCT)\n//STEP1 EXEC PGM=PGM1\n//INDD DD DSN=PROD.INPUT,DISP=SHR\n//OUTDD DD DSN=PROD.OUTPUT,DISP=(NEW,CATLG,DELETE)\n"
    p = m["JCLParser"](src)
    p.parse()
    s = p.summary()
    assert len(s["datasets"]) >= 2


def test_sql_multiple_tables():
    m = _m()
    src = "CREATE TABLE T1 (A INT); CREATE TABLE T2 (B INT);"
    p = m["SQLParser"](src)
    p.parse()
    s = p.summary()
    assert len(s["tables"]) >= 2


def test_sql_join_tables():
    m = _m()
    src = "SELECT A.COL1, B.COL2 FROM TABLE1 A JOIN TABLE2 B ON A.ID = B.ID"
    p = m["SQLParser"](src)
    p.parse()
    s = p.summary()
    assert "TABLE1" in s["referenced_tables"]
    assert "TABLE2" in s["referenced_tables"]



def test_ollama_health_check():
    m = _m()
    oc = m["OllamaClient"](available=False)
    health = oc.check_health()
    assert "available" in health
    assert health["available"] is False


def test_ollama_fallback_records_metrics():
    m = _m()
    oc = m["OllamaClient"](available=False)
    result = oc.complete("test prompt", file_path="/test.cbl", task="test")
    assert result["available"] is False
    assert "error" in result
    metrics = oc.get_metrics()
    assert metrics["fallbacks"] == 1
    assert metrics["calls"] == 1


def test_rag_miss_records():
    m = _m()
    rc = m["RAGClient"](available=False)
    result = rc.retrieve("COBOL modernization patterns", scope="cobol")
    assert result["available"] is False
    assert result["hits"] == []
    metrics = rc.get_metrics()
    assert metrics["calls"] == 1


def test_bms_detection():
    m = _m()
    from autoforge_modernization.capability_stubs import BMSCapability
    src = "COBIL00 DFHMSD CTRL=(ALARM,FREEKB)\nCOBIL0A DFHMDI COLUMN=1,LINE=1\n"
    cap = BMSCapability()
    assert cap.detect(src) is True



def test_ims_detection():
    m = _m()
    from autoforge_modernization.capability_stubs import IMSCapability
    src = "PSBGEN LANG=COBOL,PSBNAME=PSBGEN1\nPCB TYPE=TP,LABEL=PCB01"
    cap = IMSCapability()
    assert cap.detect(src) is True


def test_vsam_detection():
    m = _m()
    from autoforge_modernization.capability_stubs import VSAMCapability
    src = "DEFINE CLUSTER (NAME(VSAM.FILE) CYLINDERS(10 5) KEYS(12 0))"
    cap = VSAMCapability()
    assert cap.detect(src) is True


def test_pli_detection():
    m = _m()
    from autoforge_modernization.capability_stubs import PLICapability
    src = "DCL NAME CHAR(50); OPTIONS(MAIN); PROC();"
    cap = PLICapability()
    assert cap.detect(src) is True


def test_depgraph_build_from_cobol():
    m = _m()
    from autoforge_modernization.dependency_graph import build_from_cobol
    g = m["DependencyGraph"]()
    summary = {"program_id": "PROG1", "copybooks": ["COPY1", "COPY2"], "external_calls": ["SUB1", "SUB2"], "performed_targets": ["P1", "P2"], "data_items": [], "data_types": {}, "paragraphs": ["P1", "P2"], "gaps": []}
    build_from_cobol("PROG1", summary, g)
    s = g.summary()
    assert s["node_count"] >= 4





def test_depgraph_build_from_jcl():
    m = _m()
    from autoforge_modernization.dependency_graph import build_from_jcl
    g = m["DependencyGraph"]()
    sm = {"job_name": "JOB1", "steps": [{"name": "S1", "program": "PGM1"}], "datasets": ["D1"], "proc_libs": []}
    build_from_jcl(sm, g)
    assert g.summary()["node_count"] >= 2


def test_dag_scheduler_topo_order():
    m = _m()
    from autoforge_modernization.dependency_graph import DependencyGraph, EdgeKind
    g = DependencyGraph()
    a = g.node("A", "COBOL"); b = g.node("B", "COBOL")
    c = g.node("C", "COBOL"); d = g.node("D", "COBOL")
    g.edge(a, b, EdgeKind.CALL); g.edge(b, c, EdgeKind.CALL); g.edge(c, d, EdgeKind.CALL)
    sched = m["DAGScheduler"](g)
    results = sched.schedule(lambda ctx: ctx)
    names = [t.node_name for t in results]
    assert names.index("A") < names.index("B") < names.index("C") < names.index("D")


def test_dag_scheduler_cycle_fails():
    m = _m()
    from autoforge_modernization.dependency_graph import DependencyGraph, EdgeKind
    g = DependencyGraph()
    a = g.node("A", "COBOL"); b = g.node("B", "COBOL")
    g.edge(a, b, EdgeKind.CALL); g.edge(b, a, EdgeKind.CALL)
    try:
        m["DAGScheduler"](g).schedule(lambda ctx: ctx)
        assert False, "Expected RuntimeError for cycle"
    except RuntimeError as e:
        assert "cycle" in str(e).lower()






def test_carddemo_cobol_emission():
    m = _m()
    from autoforge_modernization.cobol_semantic_emitter import COBOLSemanticEmitter
    src = open("/Users/kalachanddash/Documents/AutoForge AI/.autoforge/carddemo/app/cbl/COSGN00C.cbl", errors="replace").read()
    tree = m["COBOLParser"](m["COBOLTokenizer"](src).tokenize()).parse()
    emitter = COBOLSemanticEmitter(tree, src)
    java, gaps, prov = emitter.emit()
    assert len(prov["paragraphs"]) >= 4, f"Expected >=4 paragraphs, got {len(prov['paragraphs'])}"
    assert prov["cics_detected"] is True
    assert len(prov["fields"]) >= 8



def test_carddemo_jcl_extraction():
    m = _m()
    src = open("/Users/kalachanddash/Documents/AutoForge AI/.autoforge/carddemo/app/jcl/CARDFILE.jcl", errors="replace").read()
    p = m["JCLParser"](src)
    p.parse()
    s = p.summary()
    assert s["job_name"] == "CARDFILE"
    assert len(s["steps"]) >= 2
    assert len(s["datasets"]) >= 1


def test_carddemo_sql_extraction():
    m = _m()
    src = open("/Users/kalachanddash/Documents/AutoForge AI/.autoforge/carddemo/app/app-transaction-type-db2/ddl/TRNTYPE.ddl", errors="replace").read()
    p = m["SQLParser"](src)
    p.parse()
    s = p.summary()
    assert "TRANSACTION_TYPE" in str(s["tables"])


def run_all_tests():
    test_fns = [v for v in globals().values() if callable(v) and v.__name__.startswith("test_")]
    return [run_test(fn.__name__, fn) for fn in test_fns]


if __name__ == "__main__":
    results = run_all_tests()
    passed = sum(1 for r in results if r.passed)
    failed = [r for r in results if not r.passed]
    print(f"\n{'='*60}\nPhase 18-G.3 Adversarial Tests\n{'='*60}")
    for r in results:
        tag = "PASS" if r.passed else "FAIL"
        print(f"  [{tag}] {r.name} ({r.duration_ms}ms)")
        if not r.passed: print(f"         ERROR: {r.error}")
    print(f"\n{'='*60}\nResults: {passed}/{len(results)} passed")
    if failed: print(f"FAILED: {[r.name for r in failed]}")
    print(f"{'='*60}")
    sys.exit(0 if not failed else 1)


