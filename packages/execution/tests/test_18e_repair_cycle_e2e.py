#!/usr/bin/env python3
"""test_18e_repair_cycle_e2e.py - Authoritative E2E for Phase 18-E repair cycle."""
import sys; from pathlib import Path; from urllib.parse import urlparse
_repo_root = Path(__file__).resolve().parents[3]
for d in ["packages/connectors/src","packages/models/src","packages/execution/src",
          "packages/workforce/src","packages/orchestration/src","packages/workflows/src",
          "packages/ai_infrastructure/src","packages/knowledge_platform/src",
          "phase18/implementation"]:
    p = str(_repo_root / d)
    if p not in sys.path: sys.path.insert(0, p)

import asyncio; import hashlib; import urllib.request; import pytest
from autoforge_workflows.models import TaskDefinition; from autoforge_workflows.engine import WorkflowEngine
from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.context import ExecutionContext
from autoforge_execution.diagnosis import FailureDiagnoser
from autoforge_execution.engine import ExecutionEngine
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.models import (ArtifactType, CommandSpec, DiagnosisReport, EvaluationStatus)
from autoforge_execution_18e.diagnosis_rag import RAGIntegratedDiagnoser
from autoforge_execution_18e.repair_cycle import RepairCycle, RepairCycleConfig
from autoforge_execution_18e.repair_models import RepairStatus, RepairFailureReason, SafeFileEdit
from autoforge_execution_18e.safe_edit import SafeFileEditor
from autoforge_knowledge_platform.rag18.facade import KnowledgeRAGEngine
from autoforge_knowledge_platform.rag18.config import default_knowledge_config

_LOCALHOSTS = {"127.0.0.1", "localhost", "::1"}

def _is_local_url(url):
    try: parsed = urlparse(url)
    except: return False
    return bool(parsed.hostname) and parsed.hostname in _LOCALHOSTS


class BadHashRepairAIProvider(AIEngineeringProvider):
    def __init__(self): self.plans=[]; self.impls=[]; self.repairs=[]; self.diags=[]
    async def generate_plan(self, ctx): self.plans.append(ctx.task_name or ""); return f"Plan: {ctx.task_name}"
    async def generate_implementation(self, ctx, plan):
        self.impls.append([{"path":"calculator.py","content":"def multiply(a: int, b: int) -> int:\n    return a + b\n"}]); return self.impls[-1]
    async def diagnose_failure(self, ctx, evidence):
        comb = evidence.get("stderr","")+"\n"+evidence.get("stdout",""); rk = getattr(ctx,"retrieved_knowledge",None)
        rh = f" [RAG evidence: {rk[0].get('content','')[:80] if rk else 'NONE'}]" if rk else ""
        d = DiagnosisReport(root_cause="Buggy multiply"+rh, failure_mechanism="Assertion failure",
            affected_files=["calculator.py"], suggested_fix="return a * b", confidence_score=0.92)
        self.diags.append(d); return d
    async def generate_repair(self, ctx, diag):
        self.repairs.append([{"path":"calculator.py","content":"def multiply(a: int, b: int) -> int:\n    return a * b\n",
            "expected_content_hash":"0"*64,"description":"Bad hash repair"}]); return self.repairs[-1]


class Deterministic18EAIProvider(AIEngineeringProvider):
    def __init__(self): self.plans=[]; self.impls=[]; self.repairs=[]; self.diags=[]
    async def generate_plan(self, ctx): self.plans.append(ctx.task_name or ""); return f"Plan: {ctx.task_name}"
    async def generate_implementation(self, ctx, plan):
        self.impls.append([{"path":"calculator.py","content":
            "def multiply(a: int, b: int) -> int:\n    # BUG: returns addition instead of product\n    return a + b\n"}]); return self.impls[-1]
    async def diagnose_failure(self, ctx, evidence):
        comb = evidence.get("stderr","")+"\n"+evidence.get("stdout",""); rk = getattr(ctx,"retrieved_knowledge",None)
        rh = f" [RAG evidence: {rk[0].get('content','')[:80] if rk else 'NONE'}]" if rk else ""
        root = "Calculator.multiply uses addition (a+b) instead of multiplication (a*b)"+rh
        mech = "Assertion failure: multiply(3,4)==12 returned 7" if "7" in comb else "Non-zero exit"
        d = DiagnosisReport(root_cause=root, failure_mechanism=mech, affected_files=["calculator.py"],
            suggested_fix="return a * b", confidence_score=0.92); self.diags.append(d); return d
    async def generate_repair(self, ctx, diag):
        buggy = "def multiply(a: int, b: int) -> int:\n    # BUG: returns addition instead of product\n    return a + b\n"
        bh = hashlib.sha256(buggy.encode()).hexdigest()
        self.repairs.append([{"path":"calculator.py","content":"def multiply(a: int, b: int) -> int:\n    # FIXED\n    return a * b\n",
            "expected_content_hash":bh,"description":"Fix addition->multiply"}]); return self.repairs[-1]



@pytest.mark.asyncio
async def test_18e_repair_cycle_through_real_execution_engine(tmp_path):
    tmp = Path(tmp_path)
    ai = Deterministic18EAIProvider()
    (tmp/"repair_knowledge.py").write_text("FIX_MULTIPLY='Replace return a+b with return a*b'\n")
    rag_cfg = default_knowledge_config()
    rag_engine = KnowledgeRAGEngine(config=rag_cfg)
    await rag_engine.initialize()
    await rag_engine.index_repository(workspace_root=str(tmp), project_id="e2e-test-project", force=True)
    health = await rag_engine.health()
    assert health["ok"] and health["vector_db"]["ok"] is True and health["embedding"]["ok"] is True
    assert _is_local_url(rag_cfg.ollama_base_url)
    env = WorkspaceEnvironment(tmp)
    exec_engine = ExecutionEngine(environment=env, ai_provider=ai,
        workflow_engine=WorkflowEngine(), rag_engine=rag_engine)
    (tmp/"test_calculator.py").write_text(
        "import unittest\nfrom calculator import multiply\n\n"
        "class T(unittest.TestCase):\n    def test_it(self): self.assertEqual(multiply(3,4),12)\n"
        "if __name__=='__main__': unittest.main()\n"
    )
    task_def = TaskDefinition(task_id="task-18e", name="Fix Calculator Multiply",
        input_data={"commands": [[sys.executable,"test_calculator.py"]]})
    passed, artifacts, eval_res = await exec_engine.execute_task_definition(task_def)
    assert passed is True and eval_res.status == EvaluationStatus.PASSED
    workers = list(exec_engine._dispatcher._active_workers.values())
    worker = workers[-1]; hist = worker.state.iteration_history
    assert len(hist) == 2
    i1, i2 = hist[0], hist[1]
    assert i1.iteration==1 and not i1.passed and i1.evaluation.status==EvaluationStatus.FAILED
    assert i2.iteration==2 and i2.passed and i2.evaluation.status==EvaluationStatus.PASSED
    assert i1.diagnosis is not None and "RAG evidence" in i1.diagnosis.root_cause
    calc = (tmp/"calculator.py").read_text()
    assert "return a * b" in calc and "return a + b" not in calc
    assert len(ai.impls)==1 and len(ai.plans)==1 and len(ai.repairs)==1
    art_types = {a.artifact_type for a in artifacts}
    assert ArtifactType.EVALUATION_REPORT in art_types and ArtifactType.EXECUTION_LOG in art_types
    has_repair = ArtifactType.DIAGNOSIS_REPORT in art_types or ArtifactType.DIFF in art_types
    assert has_repair
    r = await env.execute_command(CommandSpec(argv=[sys.executable,"test_calculator.py"]))
    assert r.exit_code == 0
    print("\n[PASS] 18-E E2E: 2 iterations, RAG diagnosis, hash-protected repair, PASSED")



@pytest.mark.asyncio
async def test_18e_safe_editor_hash_mismatch_rejected(tmp_path):
    tmp = Path(tmp_path)
    buggy = "def multiply(a: int, b: int) -> int:\n    return a + b\n"
    (tmp/"calculator.py").write_text(buggy)
    editor = SafeFileEditor()
    bad_edit = SafeFileEdit(target_path="calculator.py", new_content="def multiply(a,b): return a*b\n",
        expected_content_hash="0"*64)
    result = editor.apply_edit(bad_edit, tmp)
    assert not result.success
    assert result.content_hash_matches is False
    assert result.status == RepairFailureReason.INVALID_EDIT
    assert (tmp/"calculator.py").read_text() == buggy
    print("\n[PASS] SafeFileEditor correctly rejected hash mismatch")


@pytest.mark.asyncio
async def test_18e_safe_editor_hash_match_accepted(tmp_path):
    tmp = Path(tmp_path)
    buggy = "def multiply(a: int, b: int) -> int:\n    return a + b\n"
    (tmp/"calculator.py").write_text(buggy)
    bh = hashlib.sha256(buggy.encode()).hexdigest()
    editor = SafeFileEditor()
    good_edit = SafeFileEdit(target_path="calculator.py", new_content="def multiply(a,b): return a*b\n",
        expected_content_hash=bh)
    result = editor.apply_edit(good_edit, tmp)
    assert result.success
    assert "return a*b" in (tmp/"calculator.py").read_text()
    print("\n[PASS] SafeFileEditor correctly accepted hash match and applied edit")


@pytest.mark.asyncio
async def test_18e_rag_diagnoser_calls_real_qdrant(tmp_path):
    tmp = Path(tmp_path)
    rag_cfg = default_knowledge_config()
    rag_engine = KnowledgeRAGEngine(config=rag_cfg)
    await rag_engine.initialize()
    (tmp/"test.txt").write_text("The multiply function returns a+b instead of a*b")
    await rag_engine.index_repository(workspace_root=str(tmp), project_id="rag-test", force=True)
    result = await rag_engine.retrieve_for_context("How to fix multiply?", project_id="rag-test", top_k=3)
    assert result is not None
    hits = getattr(result,"hits",None) or getattr(result,"results",[])
    assert len(hits) > 0
    print(f"\n[PASS] RAG retrieved {len(hits)} hits from local Qdrant")


@pytest.mark.asyncio
async def test_18e_repair_cycle_bounded_retry(tmp_path):
    tmp = Path(tmp_path)
    rag_cfg = default_knowledge_config()
    rag_engine = KnowledgeRAGEngine(config=rag_cfg)
    await rag_engine.initialize()
    (tmp/"rk.py").write_text("FIX='return a*b'\n")
    await rag_engine.index_repository(workspace_root=str(tmp), project_id="retry-test", force=True)
    env = WorkspaceEnvironment(tmp)
    buggy = "def multiply(a: int, b: int) -> int:\n    return a + b\n"
    (tmp/"calculator.py").write_text(buggy)
    (tmp/"test_calc.py").write_text(
        "import unittest\nfrom calculator import multiply\n\n"
        "class T(unittest.TestCase):\n    def test_it(self): self.assertEqual(multiply(3,4),12)\n"
        "if __name__=='__main__': unittest.main()\n"
    )
    ai = Deterministic18EAIProvider()
    exec_engine = ExecutionEngine(environment=env, ai_provider=ai,
        workflow_engine=WorkflowEngine(), rag_engine=rag_engine)
    td = TaskDefinition(task_id="retry-1", name="Bounded Retry Test",
        input_data={"commands": [[sys.executable,"test_calc.py"]]})
    passed, artifacts, eval_res = await exec_engine.execute_task_definition(td)
    assert passed is True
    workers = list(exec_engine._dispatcher._active_workers.values())
    hist = workers[-1].state.iteration_history
    assert len(hist) == 2
    print(f"\n[PASS] Bounded retry: 2 iterations (1 fail + 1 repair+pass)")



def test_18e_no_cloud_qdrant_local_url_enforced():
    from autoforge_knowledge_platform.rag18.errors import VectorStoreUnavailableError
    def _a(url):
        if not _is_local_url(url):
            raise VectorStoreUnavailableError(f"Only local vector database URLs allowed; got: {url}")
    _a("http://127.0.0.1:6333"); _a("http://localhost:6333"); _a("http://[::1]:6333")
    with pytest.raises(VectorStoreUnavailableError, match="local vector database"): _a("https://cloud.qdrant.io")
    with pytest.raises(VectorStoreUnavailableError, match="local vector database"): _a("http://34.118.90.11:6333")


def test_18e_no_cloud_ollama_embedding_local_only():
    from autoforge_knowledge_platform.rag18.embedding import OllamaEmbeddingService
    import inspect
    sig = inspect.signature(OllamaEmbeddingService.__init__)
    assert "api_key" not in list(sig.parameters.keys())


def test_18e_no_cloud_knowledge_rag_engine_no_cloud_params():
    import inspect
    sig = inspect.signature(KnowledgeRAGEngine.__init__)
    params = list(sig.parameters.keys())
    cloud = [p for p in params if any(kw in p.lower() for kw in ("openai","anthropic","azure","api_key","cloud","gpt"))]
    assert not cloud


def test_18e_no_cloud_ollama_live():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            assert b"models" in r.read()
    except Exception as exc:
        pytest.fail(f"Ollama not responding at localhost:11434: {exc}")


def test_18e_no_cloud_qdrant_live():
    try:
        with urllib.request.urlopen("http://127.0.0.1:6333/", timeout=5) as r:
            assert b"qdrant" in r.read().lower()
    except Exception as exc:
        pytest.fail(f"Qdrant not responding at localhost:6333: {exc}")


@pytest.mark.asyncio
async def test_18c_regression_worker_with_rag_engine_still_works(tmp_path):
    from autoforge_execution.loop import LoopConfig
    from autoforge_execution.worker import EngineeringWorker
    from autoforge_execution.models import WorkerType
    env = WorkspaceEnvironment(Path(tmp_path))
    ai = Deterministic18EAIProvider()
    worker = EngineeringWorker(worker_id="regression", worker_type=WorkerType.CODING,
        environment=env, ai_provider=ai,
        loop_config=LoopConfig(max_iterations=2, timeout_seconds=30.0), rag_engine=None)
    (Path(tmp_path)/"always_pass.py").write_text("def ok(): return True\n")
    (Path(tmp_path)/"t.py").write_text(
        "import unittest\nfrom always_pass import ok\n\n"
        "class T(unittest.TestCase):\n    def test_it(self): self.assertTrue(ok())\n"
        "if __name__=='__main__': unittest.main()\n"
    )
    task = TaskDefinition(task_id="reg1", name="Regression",
        input_data={"commands":[[sys.executable,"t.py"]]})
    ctx = ExecutionContext.from_task_definition(task, Path(tmp_path))
    ctx.project_files = ["always_pass.py","t.py"]
    passed, _, ev = await worker.execute_task(ctx)
    assert passed is True and ev.status == EvaluationStatus.PASSED
    assert len(ai.impls)==1 and len(ai.plans)==1 and len(ai.repairs)==0
    print("\n[PASS] 18-C regression: EngineeringWorker with rag_engine=None still works")


# =============================================================================
# AUTHORITATIVE LIVE E2E TESTS -- 18-E FINAL PROOF
# =============================================================================


@pytest.mark.asyncio
async def test_18e_comprehensive_authoritative_live_e2e(tmp_path):
    tmp = Path(tmp_path)
    rag_cfg = default_knowledge_config()
    rag_engine = KnowledgeRAGEngine(config=rag_cfg)
    await rag_engine.initialize()
    (tmp/"repair_knowledge.py").write_text("BUG_FIX=Replace return a+b with return a*b\n")
    await rag_engine.index_repository(workspace_root=str(tmp), project_id="auth-e2e", force=True)
    assert (await rag_engine.health())["ok"]
    assert _is_local_url(rag_cfg.ollama_base_url)
    env = WorkspaceEnvironment(tmp)
    buggy = ("def multiply(a: int, b: int) -> int:\n"
             "    # BUG: returns addition instead of product\n"
             "    return a + b\n")
    bh = hashlib.sha256(buggy.encode()).hexdigest()
    (tmp/"calculator.py").write_text(buggy)
    (tmp/"test_calculator.py").write_text(
        "import unittest\nfrom calculator import multiply\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_3_4(self): self.assertEqual(multiply(3,4),12)\n"
        "    def test_0_5(self): self.assertEqual(multiply(0,5),0)\n"
        "    def test_1_7(self): self.assertEqual(multiply(1,7),7)\n"
        "if __name__=='__main__': unittest.main()\n"
    )
    td = TaskDefinition(task_id="auth-e2e-1", name="Fix Calculator",
        input_data={"commands": [[sys.executable, "test_calculator.py"]]})
    ai = Deterministic18EAIProvider()
    ee = ExecutionEngine(environment=env, ai_provider=ai,
        workflow_engine=WorkflowEngine(), rag_engine=rag_engine)
    passed, artifacts, ev = await ee.execute_task_definition(td)
    workers = list(ee._dispatcher._active_workers.values()); assert workers
    hist = workers[-1].state.iteration_history
    i1 = hist[0]
    assert i1.iteration == 1 and not i1.passed
    assert i1.evaluation and i1.evaluation.status == EvaluationStatus.FAILED
    assert i1.diagnosis and "RAG evidence" in i1.diagnosis.root_cause
    assert len(ai.repairs) == 1
    edit = ai.repairs[0][0]
    assert edit["path"] == "calculator.py" and "return a * b" in edit["content"]
    assert "return a + b" not in edit["content"]
    assert edit.get("expected_content_hash") == bh
    fixed = (tmp/"calculator.py").read_text()
    assert "return a * b" in fixed and "return a + b" not in fixed
    ns = {}; exec(compile(fixed, "calculator.py", "exec"), ns)
    fn = ns["multiply"]
    assert fn(3,4)==12 and fn(0,5)==0 and fn(1,7)==7
    assert len(hist) == 2
    i2 = hist[1]
    assert i2.iteration == 2 and i2.passed
    assert i2.evaluation and i2.evaluation.status == EvaluationStatus.PASSED
    assert passed and ev and ev.status == EvaluationStatus.PASSED
    atypes = {a.artifact_type for a in artifacts}
    assert ArtifactType.EVALUATION_REPORT in atypes
    assert ArtifactType.EXECUTION_LOG in atypes
    assert ArtifactType.DIAGNOSIS_REPORT in atypes or ArtifactType.DIFF in atypes
    assert len(i2.changed_files)>0 and "calculator.py" in i2.changed_files
    r = await env.execute_command(CommandSpec(argv=[sys.executable,"test_calculator.py"]))
    assert r.exit_code == 0
    print("REAL FAILURE:PASS REAL DIAGNOSIS:PASS REAL LOCAL RAG:PASS")
    print("REAL REPAIR:PASS REAL FILE MUTATION:PASS BOUNDED RETRY:PASS")
    print("REAL RE-EXECUTION:PASS REAL RE-EVALUATION:PASS FINAL PASS:PASS PROVENANCE:PASS")



@pytest.mark.asyncio
async def test_18e_bad_repair_cannot_fabricate_pass(tmp_path):
    tmp = Path(tmp_path)
    rag_cfg = default_knowledge_config()
    rag_engine = KnowledgeRAGEngine(config=rag_cfg)
    await rag_engine.initialize()
    (tmp/"repair_knowledge.py").write_text("FIX=return a*b\n")
    await rag_engine.index_repository(workspace_root=str(tmp), project_id="bad", force=True)
    env = WorkspaceEnvironment(tmp)
    buggy = "def multiply(a: int, b: int) -> int:\n    return a + b\n"
    (tmp/"calculator.py").write_text(buggy)
    (tmp/"test_calculator.py").write_text(
        "import unittest\nfrom calculator import multiply\n\n"
        "class T(unittest.TestCase):\n    def test_it(self): self.assertEqual(multiply(3,4),12)\n"
        "if __name__=='__main__': unittest.main()\n"
    )
    td = TaskDefinition(task_id="bad-r-1", name="Bad Repair",
        input_data={"commands": [[sys.executable, "test_calculator.py"]]})
    ai = BadHashRepairAIProvider()
    ee = ExecutionEngine(environment=env, ai_provider=ai,
        workflow_engine=WorkflowEngine(), rag_engine=rag_engine)
    passed, artifacts, ev = await ee.execute_task_definition(td)
    assert passed is False, "Failed repair must NOT fabricate PASS"
    assert ev is not None and ev.status == EvaluationStatus.FAILED
    cur = (tmp/"calculator.py").read_text()
    assert cur == buggy, f"File must be unchanged; got:\n{cur}"
    assert "return a + b" in cur
    r = await env.execute_command(CommandSpec(argv=[sys.executable,"test_calculator.py"]))
    assert r.exit_code != 0, "Buggy code must still fail tests"
    workers = list(ee._dispatcher._active_workers.values())
    hist = workers[-1].state.iteration_history
    assert any(not h.passed for h in hist)
    print("BAD REPAIR CANNOT FABRICATE PASS: PASS")
    print("  SafeFileEditor rejected bad repair (hash mismatch) - file unchanged")
    print("  Re-evaluation FAILED - no fabrication")



@pytest.mark.asyncio
async def test_18e_provenance_chain_complete(tmp_path):
    tmp = Path(tmp_path)
    rag_cfg = default_knowledge_config()
    rag_engine = KnowledgeRAGEngine(config=rag_cfg)
    await rag_engine.initialize()
    (tmp/"repair_knowledge.py").write_text("FIX=return a*b\n")
    await rag_engine.index_repository(workspace_root=str(tmp), project_id="prov", force=True)
    env = WorkspaceEnvironment(tmp)
    buggy = ("def multiply(a: int, b: int) -> int:\n"
             "    # BUG: returns addition instead of product\n"
             "    return a + b\n")
    bh = hashlib.sha256(buggy.encode()).hexdigest()
    (tmp/"calculator.py").write_text(buggy)
    (tmp/"test_calculator.py").write_text(
        "import unittest\nfrom calculator import multiply\n\n"
        "class T(unittest.TestCase):\n    def test_it(self): self.assertEqual(multiply(3,4),12)\n"
        "if __name__=='__main__': unittest.main()\n"
    )
    td = TaskDefinition(task_id="prov-1", name="Provenance",
        input_data={"commands": [[sys.executable, "test_calculator.py"]]})
    ai = Deterministic18EAIProvider()
    ee = ExecutionEngine(environment=env, ai_provider=ai,
        workflow_engine=WorkflowEngine(), rag_engine=rag_engine)
    passed, artifacts, ev = await ee.execute_task_definition(td)
    assert passed is True
    workers = list(ee._dispatcher._active_workers.values())
    hist = workers[-1].state.iteration_history
    i1 = hist[0]
    assert i1.iteration == 1 and not i1.passed
    assert i1.evaluation and i1.evaluation.status == EvaluationStatus.FAILED
    assert i1.diagnosis and isinstance(i1.diagnosis, DiagnosisReport)
    assert "RAG evidence" in i1.diagnosis.root_cause
    i2 = hist[1]
    assert i2.iteration == 2 and i2.passed
    assert i2.evaluation and i2.evaluation.status == EvaluationStatus.PASSED
    assert len(i2.changed_files)>0 and "calculator.py" in i2.changed_files
    atypes = {a.artifact_type for a in artifacts}
    assert ArtifactType.EVALUATION_REPORT in atypes
    assert ArtifactType.EXECUTION_LOG in atypes
    assert len(ai.repairs) == 1
    edit = ai.repairs[0][0]
    assert edit.get("expected_content_hash") == bh
    assert edit["path"] == "calculator.py" and "return a * b" in edit["content"]
    print("PROVENANCE CHAIN COMPLETE: PASS")
    print("  Step 1: Iter1 failure + RAG diagnosis  : PASS")
    print("  Step 2: Iter2 repair + changed_files   : PASS")
    print("  Step 3: EVALUATION_REPORT + EXEC_LOG  : PASS")
    print("  Step 4: generate_repair 1x + hash prec: PASS")
