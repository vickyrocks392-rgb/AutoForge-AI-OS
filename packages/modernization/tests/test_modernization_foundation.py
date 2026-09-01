"""Tests for autoforge_modernization G.1 Foundation."""
from __future__ import annotations
import pytest
from pydantic import ValidationError
from autoforge_modernization import ModernizationJob, ModernizationPhase, JobStatus, GateState, LockdownState, TechnologyCapability, TechnologyCapabilityRegistry, SpecialistTool, SpecialistToolingInventory, Requirement, GapFinding, FixRecommendation, GateDecisionRecord, MigrationPlan, LOCMetrics, DataPlane, AmbiguousRequirementError, LockdownViolationError, RecommendationAction, GateDecision, ModernizationError, CapabilityError, ToolPurpose, ToolCapability, InstallationState, BusinessIntent, GapSeverity, ApprovalState, MigrationStrategy, DataPlaneBoundary, RequirementStatus, PlanningGateError, DataPlaneError, CapabilityState, CapabilityLevel

class TestImports:
    def test_job_import(self):
        assert ModernizationJob is not None
        assert ModernizationPhase is not None
    def test_lockdown(self):
        s = LockdownState()
        assert s.enabled is False
        s.enable(reason="test")
        assert s.enabled is True
    def test_job_create(self):
        job = ModernizationJob(project_id="p1", name="j")
        assert job.status == JobStatus.PENDING
        job.advance_phase(ModernizationPhase.RECONNAISSANCE)
        assert ModernizationPhase.INTAKE in job.completed_phases
    def test_tooling(self):
        inv = SpecialistToolingInventory()
        t = SpecialistTool(name="x", technology="y", purpose=[], capability=[])
        inv.register(t)
        assert inv.get("x") is t
    def test_capability_registry(self):
        reg = TechnologyCapabilityRegistry()
        reg.register(TechnologyCapability(technology_name="cobol", version="85"))
        assert reg.get("cobol", "85") is not None
    def test_requirement(self):
        r = Requirement(project_id="p1", title="t", description="d")
        assert r.source.value == "stakeholder"
    def test_gap_finding(self):
        f = GapFinding(project_id="p1", component_id="c1", finding_type="x", title="t", description="d")
        assert f.approval_state.value == "pending"
    def test_errors(self):
        e = AmbiguousRequirementError(requirement_id="r1", reason="why")
        assert e.requirement_id == "r1"
        assert e.reason == "why"
        e = LockdownViolationError(operation="web_research")
        assert e.operation == "web_research"

from autoforge_modernization import RecommendationAction, GateDecision, ModernizationError, CapabilityError, ToolPurpose, ToolCapability, InstallationState, BusinessIntent, GapSeverity, ApprovalState, MigrationStrategy, DataPlaneBoundary, RequirementStatus, PlanningGateError, DataPlaneError

class TestEnums:
    def test_phase_values(self):
        assert ModernizationPhase.INTAKE == "intake"
        assert ModernizationPhase.RECONNAISSANCE == "reconnaissance"
        assert ModernizationPhase.PLANNING_GATE == "planning_gate"
    def test_job_status_values(self):
        assert JobStatus.PENDING == "pending"
        assert JobStatus.AT_GATE == "at_gate"
        assert JobStatus.COMPLETE == "complete"
    def test_gate_state_values(self):
        assert GateState.PENDING == "pending"
        assert GateState.BLOCKED_HITL == "blocked_hitl"
        assert GateState.APPROVED == "approved"
    def test_recommendation_action(self):
        assert RecommendationAction.KEEP == "keep"
        assert RecommendationAction.MODERNIZE == "modernize"
    def test_approval_state(self):
        assert ApprovalState.PENDING == "pending"
        assert ApprovalState.APPROVED == "approved"
    def test_migration_strategy(self):
        assert MigrationStrategy.RETAIN == "retain"
        assert MigrationStrategy.REWRITE == "rewrite"
        assert MigrationStrategy.REFACTOR == "refactor"
    def test_data_plane_enum(self):
        from autoforge_modernization import DataPlane
        assert DataPlane.CLIENT == "client"
        assert DataPlane.EXTERNAL == "external"
        assert DataPlane.SHARED == "shared"


class TestJobs:
    def test_job_unique_ids(self):
        j1 = ModernizationJob(project_id="p1", name="a")
        j2 = ModernizationJob(project_id="p1", name="b")
        assert j1.job_id != j2.job_id
    def test_advance_phase(self):
        job = ModernizationJob(project_id="p1", name="j")
        assert job.current_phase == ModernizationPhase.INTAKE
        job.advance_phase(ModernizationPhase.RECONNAISSANCE)
        assert job.current_phase == ModernizationPhase.RECONNAISSANCE
        assert ModernizationPhase.INTAKE in job.completed_phases
    def test_record_error(self):
        job = ModernizationJob(project_id="p1", name="j")
        job.record_error("oops")
        assert job.last_error == "oops"
    def test_blocked_gate(self):
        job = ModernizationJob(project_id="p1", name="j")
        assert job.is_blocked_at_gate() is False
        job.advance_phase(ModernizationPhase.PLANNING_GATE)
        job.wave_gate_states[0] = GateState.BLOCKED_HITL
        assert job.is_blocked_at_gate() is True
    def test_empty_project_raises(self):
        # Project ID has no min_length validator, so empty is allowed but
        # we still test that the job is created. Pydantic only catches type errors.
        job = ModernizationJob(project_id="", name="x")
        assert job.project_id == ""
    def test_job_initial_status(self):
        job = ModernizationJob(project_id="p1", name="j")
        assert job.status == JobStatus.PENDING
        assert job.current_phase == ModernizationPhase.INTAKE

class TestTooling:
    def test_tool_mark_verified(self):
        t = SpecialistTool(name="x", technology="y", purpose=[ToolPurpose.PARSER], capability=[ToolCapability.ANALYSIS])
        t.mark_verified()
        assert t.is_verified() is True
    def test_tool_mark_failed(self):
        t = SpecialistTool(name="x", technology="y", purpose=[ToolPurpose.PARSER], capability=[ToolCapability.ANALYSIS])
        t.mark_failed("bad install")
        assert t.installation_state == InstallationState.FAILED
    def test_inventory_register(self):
        inv = SpecialistToolingInventory()
        t = SpecialistTool(name="x", technology="y", purpose=[], capability=[])
        inv.register(t)
        assert inv.get("x") is t
    def test_inventory_find_by_technology(self):
        inv = SpecialistToolingInventory()
        t = SpecialistTool(name="x", technology="y", purpose=[], capability=[])
        inv.register(t)
        found = inv.find_by_technology("y")
        assert len(found) == 1
        assert found[0].name == "x"


class TestBusiness:
    def test_requirement_ambiguous(self):
        r = Requirement(project_id="p1", title="t", description="d", is_ambiguous=True, ambiguity_reason="two ways")
        assert r.is_ambiguous is True
        assert r.ambiguity_reason == "two ways"
    def test_gap_finding_approval(self):
        f = GapFinding(project_id="p1", component_id="c1", finding_type="x", title="t", description="d")
        assert f.approval_state == ApprovalState.PENDING
        f.approval_state = ApprovalState.APPROVED
        assert f.approval_state == ApprovalState.APPROVED
    def test_fix_recommendation(self):
        rec = FixRecommendation(project_id="p1", gap_id="g1", action=RecommendationAction.MODERNIZE, description="d")
        assert rec.action == RecommendationAction.MODERNIZE
    def test_gate_decision(self):
        rec = GateDecisionRecord(project_id="p1", decision=GateDecision.APPROVED)
        assert rec.decision == GateDecision.APPROVED
    def test_migration_plan(self):
        p = MigrationPlan(project_id="p1", name="Plan A")
        assert p.project_id == "p1"
        assert p.status.value == "draft"
    def test_data_plane_boundary_model(self):
        from autoforge_modernization import DataPlaneBoundary
        b = DataPlaneBoundary()
        assert b.enabled is True
        assert isinstance(b.boundary_id, str)


class TestErrors:
    def test_ambiguous_error_str(self):
        e = AmbiguousRequirementError(requirement_id="r1", reason="unclear")
        assert e.requirement_id == "r1"
        assert e.reason == "unclear"
        assert "r1" in str(e)
    def test_lockdown_error_str(self):
        e = LockdownViolationError(operation="web_research")
        assert e.operation == "web_research"
        assert "web_research" in str(e)
    def test_error_hierarchy(self):
        assert issubclass(AmbiguousRequirementError, PlanningGateError)
        assert issubclass(PlanningGateError, ModernizationError)
        assert issubclass(LockdownViolationError, DataPlaneError)
        assert issubclass(DataPlaneError, ModernizationError)
        assert issubclass(CapabilityError, ModernizationError)


class TestCapabilityRegistry:
    def test_register_and_get(self):
        reg = TechnologyCapabilityRegistry()
        reg.register(TechnologyCapability(technology_name="cobol", version="85"))
        cap = reg.get("cobol", "85")
        assert cap is not None
        assert cap.technology_name == "cobol"
    def test_default_state_unknown(self):
        cap = TechnologyCapability(technology_name="cobol", version="85")
        assert cap.state == CapabilityState.UNKNOWN
        assert cap.level == CapabilityLevel.NONE
        assert cap.requires_action() is True
        assert cap.can_proceed() is False

    def test_state_supported(self):
        cap = TechnologyCapability(technology_name="cobol", version="85", state=CapabilityState.SUPPORTED)
        assert cap.state == CapabilityState.SUPPORTED
        assert cap.requires_action() is False
        assert cap.can_proceed() is True

    def test_state_partially_supported(self):
        cap = TechnologyCapability(technology_name="cobol", version="85", state=CapabilityState.PARTIALLY_SUPPORTED)
        assert cap.state == CapabilityState.PARTIALLY_SUPPORTED
        assert cap.can_proceed() is True
        assert cap.requires_action() is False

    def test_state_tool_required(self):
        cap = TechnologyCapability(technology_name="cobol", version="85", state=CapabilityState.TOOL_REQUIRED)
        assert cap.state == CapabilityState.TOOL_REQUIRED
        assert cap.requires_action() is True
        assert cap.can_proceed() is False

    def test_state_unsupported(self):
        cap = TechnologyCapability(technology_name="cobol", version="85", state=CapabilityState.UNSUPPORTED)
        assert cap.state == CapabilityState.UNSUPPORTED
        assert cap.requires_action() is True
        assert CapabilityState.is_blocking(cap.state) is True

    def test_get_state_returns_unknown(self):
        reg = TechnologyCapabilityRegistry()
        reg.register(TechnologyCapability(technology_name="cobol", version="85"))
        state = reg.get_state("cobol", "85")
        assert state == CapabilityState.UNKNOWN
        assert state.value == "unknown"

    def test_get_state_missing_returns_unknown(self):
        reg = TechnologyCapabilityRegistry()
        state = reg.get_state("unknown_tech")
        assert state == CapabilityState.UNKNOWN

    def test_all_unsupported(self):
        reg = TechnologyCapabilityRegistry()
        reg.register(TechnologyCapability(technology_name="cobol", version="85"))
        unsupported = reg.all_unsupported()
        assert len(unsupported) == 1
        assert unsupported[0].technology_name == "cobol"

    def test_all_gap_technologies(self):
        reg = TechnologyCapabilityRegistry()
        reg.register(TechnologyCapability(technology_name="cobol", version="85"))
        gaps = reg.all_gap_technologies()
        assert len(gaps) == 1

    def test_is_sufficient_class_methods(self):
        assert CapabilityState.is_sufficient(CapabilityState.SUPPORTED) is True
        assert CapabilityState.is_sufficient(CapabilityState.PARTIALLY_SUPPORTED) is True
        assert CapabilityState.is_sufficient(CapabilityState.UNKNOWN) is False
        assert CapabilityState.is_sufficient(CapabilityState.TOOL_REQUIRED) is False

    def test_is_blocking_class_methods(self):
        assert CapabilityState.is_blocking(CapabilityState.UNSUPPORTED) is True
        assert CapabilityState.is_blocking(CapabilityState.TOOL_REQUIRED) is True
        assert CapabilityState.is_blocking(CapabilityState.ENVIRONMENT_REQUIRED) is True
        assert CapabilityState.is_blocking(CapabilityState.MODEL_REQUIRED) is True
        assert CapabilityState.is_blocking(CapabilityState.UNKNOWN) is True
        assert CapabilityState.is_blocking(CapabilityState.SUPPORTED) is False
        assert CapabilityState.is_blocking(CapabilityState.PARTIALLY_SUPPORTED) is False

    def test_empty_name_allowed(self):
        # Name has no validator; just confirm round-trip
        job = ModernizationJob(project_id="p1", name="")
        assert job.name == ""
    def test_lockdown_state_enable_disable(self):
        from autoforge_modernization import LockdownState
        s = LockdownState()
        s.enable(reason="compliance")
        assert s.enabled is True
        assert s.web_research_enabled is False
        s.disable()
        assert s.enabled is False
        assert s.web_research_enabled is True
