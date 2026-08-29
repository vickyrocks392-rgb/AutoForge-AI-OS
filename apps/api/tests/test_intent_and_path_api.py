from autoforge_api.service import AutoForgeApiService
from autoforge_api.models import (
    IntentAnalysisRequest,
    IntentExecutionRequest,
    StageExecutionStatus,
)


def test_intent_analysis_full_build():
    service = AutoForgeApiService()
    req = IntentAnalysisRequest(prompt="Build me a desktop inventory management application for Windows.")
    res = service.analyze_intent(req)
    
    assert res.intent_type == "application_build"
    assert len(res.shortest_path_stages) == 7
    planning_stage = next(s for s in res.shortest_path_stages if s.stage_id == "planning")
    assert planning_stage.status == StageExecutionStatus.PENDING


def test_intent_analysis_skip_planning_when_plan_supplied():
    service = AutoForgeApiService()
    req = IntentAnalysisRequest(
        prompt="Here is the technical plan: Decompose into SQLite DB, FastAPI backend, and React UI. Implement and test."
    )
    res = service.analyze_intent(req)
    
    assert res.detected_inputs["plan_detected"] is True
    planning_stage = next(s for s in res.shortest_path_stages if s.stage_id == "planning")
    assert planning_stage.status == StageExecutionStatus.SKIPPED
    assert "Planning" in res.skipped_stages_summary[0]


def test_intent_pipeline_execution_and_output():
    service = AutoForgeApiService()
    req = IntentExecutionRequest(
        prompt="Build me an event-driven payment webhook microservice."
    )
    res = service.execute_intent_pipeline(req)
    
    assert res.status == "COMPLETED"
    assert res.execution_id.startswith("exec-int-")
    assert len(res.artifacts) >= 3
    assert len(res.activities) >= 4
    
    # Verify project output retrieval
    output = service.get_project_output(res.project_id)
    assert output.status == "READY"
    assert output.test_results["passed"] >= 4
    assert output.test_results["status"] == "GREEN"
    assert len(output.files_generated) >= 3
    assert any(f["path"].endswith(".py") for f in output.files_generated)
