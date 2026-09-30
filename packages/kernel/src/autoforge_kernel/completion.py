"""
Completion Module

Responsible for validating completion and finalizing projects.
This module implements the Completion component of the Kernel.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from autoforge_events.event_types import EventCategory, EventType

from autoforge_kernel.interfaces import (
    CompletionModule,
    EventBus,
    RuntimeStateManager,
    ReviewEngine,
)
from autoforge_kernel.event_utils import publish_event, make_timestamp


#: The final review is a MANDATORY completion gate. Per
#: ``architecture/ARCHITECTURE.md`` §10 the Review Engine "is the quality gate
#: of the platform", and per ``docs/subsystems/kernel/KERNEL_SPECIFICATION.md``
#: §24.1 completion requires "All reviews approved". Only an explicit approval
#: may satisfy it; absence of a verdict is never an approval.
#:
#: The accepted affirmative decision is the ``approved`` value of
#: ``autoforge_review.models.ReviewDecision``. It is referenced here as a
#: literal string because this module must not import ``autoforge_review``:
#: the Kernel's dependency direction is defined by ADR-002 and the Kernel
#: legitimately knows nothing about the review package's types.
_APPROVED_DECISION = "approved"

#: Decisions that are explicitly non-approving. Each one must block successful
#: completion and is reported verbatim so the operator sees why. These are the
#: other three ``ReviewDecision`` values: ``rejected``, ``changes_requested``
#: and ``requires_hitl``.
_NON_APPROVING_DECISIONS = frozenset({"rejected", "changes_requested", "requires_hitl"})


def evaluate_final_review_result(result: Any) -> tuple[bool, str]:
    """Normalise a final-review result to ``(approved, reason)``.

    The production review contract is
    ``KernelReviewEngineAdapter.review_project``, which returns a ``dict``
    carrying ``approved`` plus the ``ReviewDecision`` value under ``decision``
    and ``status``. An object exposing an equivalent ``approved`` attribute is
    also accepted so the Kernel is not coupled to one concrete return shape.

    FAIL CLOSED. Every outcome other than an explicit, unambiguous approval is
    non-approving:

    * ``None`` — the review produced no result at all.
    * a non-boolean, absent or unrecognised ``approved`` flag — malformed.
    * an explicit ``False`` — rejected or changes requested.
    * an affirmative flag contradicted by a non-approving decision.

    Rationale: an unreadable verdict carries no approval. Treating it as one
    would reinstate exactly the fail-open behaviour this gate exists to close.
    """
    if result is None:
        return False, "Final review produced no result."

    # Accept the documented dict contract or any object exposing the same field.
    if isinstance(result, dict):
        approved_flag = result.get("approved")
        decision = result.get("decision", result.get("status"))
    else:
        approved_flag = getattr(result, "approved", None)
        decision = getattr(result, "decision", None)
        if decision is None:
            decision = getattr(result, "status", None)

    # Normalise the decision to a lowercase string when one is present. Enum
    # members are reduced via ``value``; anything else falls back to ``str``.
    if decision is not None:
        decision_value = getattr(decision, "value", decision)
        try:
            decision_value = str(decision_value).strip().lower()
        except Exception:  # pragma: no cover - defensive only
            decision_value = None
    else:
        decision_value = None

    if approved_flag is not True:
        if approved_flag is None:
            return False, (
                "Final review returned no interpretable approval evidence "
                "(missing 'approved' field)."
            )
        if isinstance(approved_flag, bool):
            # An explicit False is a real verdict, not a malformed one.
            if decision_value in _NON_APPROVING_DECISIONS:
                return False, f"Final review decision: {decision_value}."
            return False, (
                "Final review did not approve"
                + (f" (decision: {decision_value})" if decision_value else ".")
            )
        return False, (
            "Final review returned a malformed approval flag of type "
            f"{type(approved_flag).__name__}; expected a boolean."
        )

    # The flag says approved — confirm nothing contradicts it.
    if decision_value in _NON_APPROVING_DECISIONS:
        return False, (
            f"Final review is contradictory: approved=True but decision is "
            f"{decision_value}."
        )
    if decision_value is not None and decision_value != _APPROVED_DECISION:
        return False, (
            f"Final review decision {decision_value!r} is not the explicit "
            f"approval decision ({_APPROVED_DECISION!r})."
        )

    return True, "Final review explicitly approved the project."


def _validation_review_context(validation: dict[str, Any] | None) -> dict[str, Any]:
    """Project deterministic validation truth into the review request.

    DEF-18LR-D8. ``KernelReviewEngineAdapter.review_project`` already understands
    ``has_test_failures`` / ``test_error``; this function renders whatever the
    deterministic validation port decided into that existing contract, so no new
    review-evidence shape is invented.

    Returns an empty mapping when no deterministic validation applies, which
    preserves the pre-existing review evidence exactly.
    """
    if not validation:
        return {}

    test_results = validation.get("test_results")
    failed = bool(validation.get("has_test_failures"))
    errored = bool(validation.get("has_errors"))
    context: dict[str, Any] = {
        "has_test_failures": failed or errored,
        "test_error": str(validation.get("reason") or validation.get("output") or ""),
        "validation_performed": bool(validation.get("performed", True)),
        "validation_passed": bool(validation.get("passed", False)),
    }
    if isinstance(test_results, dict):
        context["test_results"] = test_results
    return context


class FinalReviewEvidenceCollector:
    """Collects a project's real, durable artifacts as final-review evidence.

    DEF-P1-EVIDENCE. The production final review previously received no evidence
    at all, so ``KernelReviewEngineAdapter._execute_review`` fell back to a
    synthetic ``{"manifest.json": "{}"}`` placeholder. That placeholder defeated
    the Review Engine's own explicitly-empty-evidence branch (``review/engine.py``)
    and instead produced a real ``high / Required Files`` documentation finding,
    so every project was rejected regardless of quality.

    This collector reads the **existing, authoritative** durable artifact
    representation — ``DurableArtifactCatalog`` (18-K) — and hands the final
    review the project's actual deliverables. It introduces no new persistence
    model, no second artifact system, and no new review pipeline.

    Artifacts are correlated to a project by ``workflow_id``: the Kernel records
    the project's ``workflow_id`` at planning time (``kernel.py:264``) and every
    execution artifact records the same ``workflow_id`` in its provenance
    (``ArtifactProvenance.workflow_id``). This is the existing linkage; no index
    is invented here.
    """

    #: Artifact types that carry no reviewable project content. These are the
    #: platform's own bookkeeping records about a run, not deliverables a human
    #: would review, and are excluded so the review evaluates the project rather
    #: than the platform's telemetry of itself.
    NON_REVIEWABLE_ARTIFACT_TYPES = frozenset(
        {
            "compaction_record",
            "compaction_assembly_record",
        }
    )

    def __init__(self, durable_catalog: Any | None = None) -> None:
        self._catalog = durable_catalog

    @property
    def has_catalog(self) -> bool:
        return self._catalog is not None

    def _is_reviewable(self, artifact_type: str) -> bool:
        return artifact_type not in self.NON_REVIEWABLE_ARTIFACT_TYPES

    def _status_committed(self) -> Any:
        """Resolve the COMMITTED durable-artifact status without a hard import.

        The Kernel must not import ``autoforge_runtime`` types (ADR-002), so the
        status is resolved through the catalog's own model module at call time
        and degrades to string comparison if the module is unavailable.
        """
        try:
            from autoforge_runtime.models import DurableArtifactStatus

            return DurableArtifactStatus.COMMITTED
        except Exception:  # pragma: no cover - defensive only
            return "committed"

    def collect(self, project_id: uuid.UUID, workflow_id: Any) -> dict[str, str]:
        """Return ``{artifact_name: content}`` for the project's durable artifacts.

        Returns an empty mapping when the project genuinely produced no
        reviewable artifacts. An empty mapping is NOT an approval: it causes the
        Review Engine's own explicitly-empty-evidence branch to run, which
        returns a real, inspectable ``no_target`` verdict that the completion
        gate then evaluates normally.
        """
        if self._catalog is None or workflow_id is None:
            return {}

        states = self._catalog.find_by_workflow(workflow_id)
        committed = self._status_committed()
        committed_value = str(getattr(committed, "value", committed))

        files: dict[str, str] = {}
        for state in states or []:
            raw_status = getattr(state, "status", None)
            status_value = str(getattr(raw_status, "value", raw_status) or "")
            if status_value != committed_value:
                # Only committed artifacts are the project's real output. A
                # staged or failed artifact is not a deliverable and must not be
                # presented to the review as if it were.
                continue
            artifact_type = str(getattr(state, "artifact_type", "") or "")
            if not self._is_reviewable(artifact_type):
                continue
            name = getattr(state, "artifact_name", None) or state.artifact_id
            path = getattr(state, "storage_path", None)
            if not path:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    files[str(name)] = fh.read()
            except OSError:
                # An unreadable durable artifact must not be silently presented
                # as reviewed content. Skipping it means the review sees less
                # evidence and is therefore strictly more likely to fail closed.
                continue
        return files


class DefaultCompletionModule(CompletionModule):
    """
    Default implementation of completion validation and finalization.

    Validates completion and finalizes projects per Kernel Specification v1.0 Section 24.
    """

    def __init__(
        self,
        review_engine: ReviewEngine | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
        evidence_collector: "FinalReviewEvidenceCollector | None" = None,
        validation_port: Any | None = None,
    ):
        """
        Initialize the completion module.

        Args:
            review_engine: Review Engine for final review.
            event_bus: Event bus for publishing events.
            runtime_state_manager: Runtime state manager.
            evidence_collector: Collects the project's real durable artifacts for
                the final review. Optional so the Kernel stays constructible
                without a durable catalog, but the production composition root
                always supplies one.
            validation_port: DEF-18LR-D8. A DETERMINISTIC validation system that
                executes the project's own declared verification command and
                reports its real result. The Kernel defines the port only; the
                concrete runner is wired by the composition root, because the
                Kernel's dependency direction (ADR-002) forbids it importing the
                execution package. It is never an LLM judgement.
        """
        self.review_engine = review_engine
        self.event_bus = event_bus
        self.runtime_state_manager = runtime_state_manager
        self.evidence_collector = evidence_collector
        self.validation_port = validation_port

    async def validate_completion(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Validate that a project is complete.

        Evaluates actual project state against acceptance criteria, quality gates,
        artifact completeness, dependency completion, execution success, and approval status.

        Args:
            project_id: The project to validate.

        Returns:
            Validation result with detailed per-criteria status.
        """
        validation_result = {
            "valid": True,
            "acceptance_criteria_met": True,
            "quality_gates_passed": True,
            # True when no explicit quality gates are recorded. The generic gate
            # list is NOT the platform quality gate: per architecture/ARCHITECTURE.md
            # section 10 that role belongs to the Review Engine, which is enforced
            # as a mandatory gate in ``finalize_project``. Recording vacuity
            # explicitly prevents an empty list from reading as real gate evidence.
            "quality_gates_vacuous": True,
            # The mandatory final-review gate is enforced in ``finalize_project``;
            # it is reported here so callers can see that completion additionally
            # requires an explicit review approval.
            "final_review_required": True,
            "artifacts_complete": True,
            "dependencies_satisfied": True,
            "execution_success": True,
            "approval_status_ok": True,
            "errors": [],
            "warnings": [],
        }

        if not self.runtime_state_manager:
            validation_result["valid"] = False
            validation_result["errors"].append("Runtime state manager not configured")
            return validation_result

        # Get project state from Runtime State Manager
        try:
            project = await self.runtime_state_manager.get_project(project_id)
            if not project:
                validation_result["valid"] = False
                validation_result["errors"].append(f"Project {project_id} not found")
                return validation_result

            state = await self.runtime_state_manager.get_project_state(project_id)
        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Failed to read project state: {str(e)}")
            return validation_result

        # Validate acceptance criteria
        acceptance_criteria = state.get("acceptance_criteria", [])
        if not acceptance_criteria:
            validation_result["warnings"].append("No acceptance criteria defined")
        else:
            # Check if all acceptance criteria are marked as met
            all_met = all(
                criterion.get("met", False) for criterion in acceptance_criteria
            )
            if not all_met:
                validation_result["acceptance_criteria_met"] = False
                validation_result["valid"] = False
                unmet = [
                    c.get("description", "Unknown")
                    for c in acceptance_criteria
                    if not c.get("met", False)
                ]
                validation_result["errors"].append(
                    f"Acceptance criteria not met: {', '.join(unmet)}"
                )

        # Validate quality gates
        quality_gates = state.get("quality_gates", [])
        if not quality_gates:
            validation_result["warnings"].append(
                "No quality gates defined; completion still requires an explicit "
                "final review approval"
            )
        else:
            # Real gate evidence is present, so the generic gate list is no longer
            # vacuous. The platform quality gate remains the mandatory final review.
            validation_result["quality_gates_vacuous"] = False
            all_passed = all(
                gate.get("passed", False) for gate in quality_gates
            )
            if not all_passed:
                validation_result["quality_gates_passed"] = False
                validation_result["valid"] = False
                failed_gates = [
                    gate.get("name", "Unknown")
                    for gate in quality_gates
                    if not gate.get("passed", False)
                ]
                validation_result["errors"].append(
                    f"Quality gates not passed: {', '.join(failed_gates)}"
                )

        # Validate artifact completeness
        artifacts = state.get("artifacts", [])
        required_artifact_count = state.get("required_artifact_count", 0)
        if required_artifact_count > 0 and len(artifacts) < required_artifact_count:
            validation_result["artifacts_complete"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Artifacts incomplete: {len(artifacts)} of {required_artifact_count} produced"
            )

        # Validate dependency satisfaction
        task_count = state.get("task_count", 0)
        completed_count = state.get("completed_count", 0)
        failed_count = state.get("failed_count", 0)
        if task_count > 0 and completed_count < task_count:
            validation_result["dependencies_satisfied"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Dependencies not satisfied: {completed_count} of {task_count} tasks completed"
            )

        # Validate execution success
        if failed_count and failed_count > 0:
            validation_result["execution_success"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Execution had {failed_count} failed tasks"
            )

        # Validate approval status
        approval_history = state.get("approval_history", [])
        pending_approvals = [
            a for a in approval_history if a.get("status") == "pending"
        ]
        if pending_approvals:
            validation_result["approval_status_ok"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Pending approvals: {len(pending_approvals)} approval(s) not yet decided"
            )

        # Validate metrics thresholds
        actual_cost = state.get("actual_cost", 0.0)
        estimated_cost = state.get("estimated_cost", 0.0)
        if estimated_cost > 0 and actual_cost > estimated_cost * 1.5:
            validation_result["warnings"].append(
                f"Cost ({actual_cost}) exceeds 150% of estimate ({estimated_cost})"
            )

        return validation_result

    def _project_workflow_id(self, state: dict[str, Any] | None) -> Any:
        """Resolve the project's ``workflow_id`` from its Runtime state.

        ``Kernel.submit_request`` persists the planned workflow identity through
        the existing ``RuntimeStateManager.update_project`` API, which projects
        ``project.metadata`` into ``ProjectState.configuration``. The other
        locations are checked as a fallback for state written by other callers.
        """
        if not state:
            return None
        for container_key in ("configuration", "executable_workflow", "metadata"):
            container = state.get(container_key)
            if isinstance(container, dict) and container.get("workflow_id"):
                return container["workflow_id"]
        return state.get("workflow_id")

    def _has_evidence_authority(self) -> bool:
        """True when an authoritative evidence collector is wired.

        A collector backed by the durable artifact catalog is the platform's own
        record of what the project produced, so its verdict on "empty" is
        trustworthy. Without one, the module has no evidence authority and
        evaluates the review verdict alone (see :meth:`_run_final_review`).
        """
        collector = self.evidence_collector
        return collector is not None and bool(
            getattr(collector, "has_catalog", False)
        )

    def _has_validation_authority(self) -> bool:
        """True when a deterministic validation port is wired."""
        return self.validation_port is not None

    async def _collect_validation_evidence(
        self, project_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Run the project's deterministic validation and return its truth.

        DEF-18LR-D8. The canonical evidence model must reach the final review
        with the relevant validation truth -- not just the source artifacts.

        The port is a *deterministic* system (it executes the project's own
        declared verification command and parses the runner's real output). It
        is never an LLM judgement: the model is explicitly NOT authoritative
        for whether tests passed.

        Returns ``None`` when no deterministic validation applies, so callers can
        distinguish "not applicable" from "failed".
        """
        if not self._has_validation_authority():
            return None
        try:
            return await self.validation_port.validate_project(project_id)
        except Exception as exc:  # pragma: no cover - defensive only
            # A validation port that cannot answer is a validation failure, not
            # an absence of validation. Fail closed rather than pass silently.
            return {
                "required": True,
                "passed": False,
                "reason": (
                    f"Deterministic validation raised {type(exc).__name__}: {exc}"
                ),
                "test_results": None,
            }

    async def _collect_final_review_evidence(self, project_id: uuid.UUID) -> dict[str, str]:
        """Collect the project's real durable artifacts for the final review.

        An exception here is a genuine evidence-collection failure and is
        propagated so the caller can fail closed. Missing evidence is NOT
        converted into an approval: it flows to the Review Engine, whose own
        explicitly-empty-evidence branch produces an inspectable ``no_target``
        verdict that this module evaluates normally.
        """
        if self.evidence_collector is None or not getattr(
            self.evidence_collector, "has_catalog", False
        ):
            return {}

        state: dict[str, Any] | None = None
        if self.runtime_state_manager is not None:
            state = await self.runtime_state_manager.get_project_state(project_id)

        return self.evidence_collector.collect(
            project_id, self._project_workflow_id(state)
        )

    async def _run_final_review(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Run the mandatory final review and normalise its outcome.

        Per KERNEL_SPECIFICATION.md Section 24 the Completion Module "Invokes
        Review Engine for final review", and Section 24.1 requires "All reviews
        approved" before completion. This method never raises: a review that
        cannot be completed, or that does not explicitly approve, is reported
        as ``approved=False`` together with the reason.

        The review is given the project's real durable artifacts. No synthetic
        or placeholder evidence is manufactured here (DEF-P1-EVIDENCE).

        SAFETY: a review failure is NOT an approval. An exception raised by the
        review engine is captured as the reason rather than swallowed, so it
        participates in the ordinary completion-failure path instead of silently
        permitting finalization.
        """
        if self.review_engine is None:
            # The final review is a mandatory gate and its mandatory evidence is
            # absent, so this fails closed rather than falling back to the
            # pre-review behaviour. The production composition root always wires
            # a review engine (composition_root.py), so this branch indicates a
            # misconfigured system rather than a legitimately review-free one.
            return {
                "approved": False,
                "reason": (
                    "No review engine is configured; the mandatory final review "
                    "gate cannot be satisfied."
                ),
                "review_result": None,
                "evidence_files": 0,
            }

        try:
            evidence_files = await self._collect_final_review_evidence(project_id)
        except Exception as exc:
            # SAFETY: fail closed. Evidence that cannot be collected must not be
            # turned into an approval.
            return {
                "approved": False,
                "reason": (
                    f"Final review evidence collection raised "
                    f"{type(exc).__name__}: {exc}"
                ),
                "review_result": None,
                "evidence_files": 0,
            }

        # DEF-18LR-B1: MANDATORY review + ZERO reviewable evidence = NOT APPROVED.
        #
        # The Review Engine's ``no_target`` branch is legitimate where "nothing
        # to review" is a valid answer (an ad-hoc, artifact-scoped review). It is
        # NOT legitimate for the mandatory project-completion gate, where
        # "nothing to review" means the project produced nothing at all. The
        # Review Engine cannot distinguish the two -- it is handed the evidence
        # and answers about it -- so the requirement belongs HERE, at the one
        # boundary that knows the review is mandatory and that the empty set
        # means "no deliverable", not "no scope".
        #
        # The Review Engine's own semantics are deliberately left untouched.
        #
        # The check applies whenever an evidence collector is wired, because
        # that collector IS the authoritative answer to "what did this project
        # produce". With no collector configured the module has no evidence
        # authority at all and falls back to evaluating the verdict alone, which
        # is already fail-closed for every non-approval, exception and
        # malformed result.
        if self._has_evidence_authority() and not evidence_files:
            return {
                "approved": False,
                "reason": (
                    "The mandatory final review received no reviewable evidence: "
                    "the project produced no committed deliverable. An empty "
                    "evidence set is never an approval for project completion."
                ),
                "review_result": None,
                "evidence_files": 0,
            }

        validation = await self._collect_validation_evidence(project_id)
        review_context = _validation_review_context(validation)

        try:
            review_result = await self.review_engine.review_project(
                project_id, evidence=evidence_files, context=review_context
            )
        except Exception as exc:
            # SAFETY: fail closed. The previous behaviour ("except Exception:
            # pass") let finalization continue, converting a failed review into a
            # successful completion.
            return {
                "approved": False,
                "reason": f"Final review raised {type(exc).__name__}: {exc}",
                "review_result": None,
                "evidence_files": len(evidence_files),
                "validation": validation,
            }

        approved, reason = evaluate_final_review_result(review_result)
        return {
            "approved": approved,
            "reason": reason,
            "review_result": review_result,
            "evidence_files": len(evidence_files),
            "validation": validation,
        }


    async def finalize_project(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Finalize a completed project.

        Args:
            project_id: The project to finalize.

        Returns:
            Finalization result.
        """
        # Validate completion first
        validation_result = await self.validate_completion(project_id)

        if not validation_result["valid"]:
            return {
                "success": False,
                "error": "Project validation failed",
                "validation_result": validation_result,
            }

        # Update project state to Completing
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="Completing",
            )

        # Mandatory final review gate (KERNEL_SPECIFICATION.md Section 24).
        # SAFETY: fail closed. Only an explicit approval may allow the project to
        # reach "Finished". A review that was not configured, raised, returned
        # nothing, or returned an uninterpretable or non-approving result must
        # block completion instead of being discarded.
        review_gate = await self._run_final_review(project_id)

        if not review_gate["approved"]:
            return {
                "success": False,
                "error": "Final review did not approve the project",
                "project_id": str(project_id),
                "review_gate": {
                    "approved": False,
                    "reason": review_gate["reason"],
                    "evidence_files": review_gate.get("evidence_files", 0),
                },
                "validation_result": validation_result,
            }

        # DEF-18LR-D8: DETERMINISTIC VALIDATION IS AUTHORITATIVE.
        #
        # The Review Engine *evaluates* evidence; it does not *produce* it, and
        # it is not allowed to overrule a deterministic result. A mandatory
        # validation that failed must therefore block completion even when the
        # review returned an explicit APPROVED -- otherwise "the LLM says it
        # looks good" would silently override "the tests fail".
        #
        # The review result is preserved verbatim above so this is auditable:
        # the block names both the review verdict and the validation truth.
        validation_truth = review_gate.get("validation")
        if isinstance(validation_truth, dict) and validation_truth.get("required"):
            if not validation_truth.get("passed"):
                return {
                    "success": False,
                    "error": "Deterministic validation failed",
                    "project_id": str(project_id),
                    "review_gate": {
                        "approved": True,
                        "reason": review_gate["reason"],
                        "evidence_files": review_gate.get("evidence_files", 0),
                        "overridden_by": "deterministic_validation_gate",
                    },
                    "validation": validation_truth,
                    "validation_result": validation_result,
                }

        # Update project state to Finished with proper timestamp
        finished_at = make_timestamp()
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="Finished",
                metadata={"finished_at": finished_at, "acceptance_criteria_met": True},
            )

        # Publish project.finished event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.PROJECT_FINISHED,
            event_category=EventCategory.PROJECT,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={
                "validation_result": validation_result,
                "final_review": {
                    "approved": True,
                    "reason": review_gate["reason"],
                    "evidence_files": review_gate.get("evidence_files", 0),
                },
                "finished_at": finished_at,
            },
        )

        return {
            "success": True,
            "project_id": str(project_id),
            "validation_result": validation_result,
            "final_review": {
                "approved": True,
                "reason": review_gate["reason"],
                "evidence_files": review_gate.get("evidence_files", 0),
            },
            "finished_at": finished_at,
        }


class CompletionModuleWrapper:
    """
    Completion Module Wrapper.

    Validates completion and finalizes projects.
    """

    def __init__(
        self,
        completion_module: CompletionModule | None = None,
        review_engine: ReviewEngine | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
    ):
        """
        Initialize the completion module wrapper.

        Args:
            completion_module: Completion module.
            review_engine: Review Engine.
            event_bus: Event bus.
            runtime_state_manager: Runtime state manager.
        """
        self.completion_module = completion_module or DefaultCompletionModule(
            review_engine=review_engine,
            event_bus=event_bus,
            runtime_state_manager=runtime_state_manager,
        )

    async def validate_completion(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Validate completion.

        Args:
            project_id: The project.

        Returns:
            Validation result.
        """
        return await self.completion_module.validate_completion(project_id)

    async def finalize_project(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Finalize project.

        Args:
            project_id: The project.

        Returns:
            Finalization result.
        """
        return await self.completion_module.finalize_project(project_id)