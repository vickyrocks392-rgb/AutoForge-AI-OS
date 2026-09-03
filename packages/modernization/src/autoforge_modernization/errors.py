"""
Typed exceptions for the Modernization Engine.

All exceptions inherit from ModernizationError so callers can catch the
entire subsystem with a single handler.
"""

from __future__ import annotations


class ModernizationError(Exception):
    """Base exception for all modernization subsystem errors."""

    pass


# ── Capability Errors ────────────────────────────────────────────────────────


class CapabilityError(ModernizationError):
    """Base for capability-related errors."""

    pass


class UnknownTechnologyError(CapabilityError):
    """A technology was detected that AutoForge cannot identify."""

    def __init__(self, technology: str, context: str = "") -> None:
        self.technology = technology
        self.context = context
        super().__init__(
            f"Unknown technology: {technology!r}. {context}".strip()
        )


class UnsupportedTechnologyError(CapabilityError):
    """A technology is known but not supported for modernization."""

    def __init__(
        self,
        technology: str,
        reason: str,
        required_tools: list[str] | None = None,
    ) -> None:
        self.technology = technology
        self.reason = reason
        self.required_tools = required_tools or []
        super().__init__(
            f"Unsupported technology: {technology!r}. Reason: {reason}. "
            f"Required tools: {', '.join(required_tools) if required_tools else 'none'}."
        )



# ── Capability Gap Errors ─────────────────────────────────────────────────────


class CapabilityGapError(ModernizationError):
    """Base for capability gap errors."""

    pass


class UnverifiedToolError(CapabilityGapError):
    """A tool was registered but its installation has not been verified."""

    def __init__(self, tool_name: str, technology: str) -> None:
        self.tool_name = tool_name
        self.technology = technology
        super().__init__(
            f"Tool {tool_name!r} for {technology!r} is registered but not verified. "
            "Call SpecialistToolingInventory.verify_tool() before use."
        )


class UnresolvedCapabilityGapError(CapabilityGapError):
    """A project has an unresolved capability gap that blocks transformation."""

    def __init__(self, gap_description: str, project_id: str) -> None:
        self.gap_description = gap_description
        self.project_id = project_id
        super().__init__(
            f"Unresolved capability gap in project {project_id!r}: {gap_description}"
        )


# ── Business / Planning Gate Errors ──────────────────────────────────────────


class PlanningGateError(ModernizationError):
    """Base for planning gate errors."""

    pass


class AmbiguousRequirementError(PlanningGateError):
    """A requirement is ambiguous and cannot be resolved automatically."""

    def __init__(self, requirement_id: str, reason: str) -> None:
        self.requirement_id = requirement_id
        self.reason = reason
        super().__init__(
            f"Requirement {requirement_id!r} is ambiguous: {reason}"
        )


# ── Checkpoint Errors ────────────────────────────────────────────────────────


class CheckpointError(ModernizationError):
    """Base for checkpoint-related errors."""

    pass


class CorruptedCheckpointError(CheckpointError):
    """A checkpoint failed its integrity check."""

    def __init__(
        self,
        checkpoint_id: str,
        expected_checksum: str,
        actual_checksum: str,
    ) -> None:
        self.checkpoint_id = checkpoint_id
        self.expected_checksum = expected_checksum
        self.actual_checksum = actual_checksum
        super().__init__(
            f"Checkpoint {checkpoint_id!r} failed integrity check. "
            f"Expected {expected_checksum}, got {actual_checksum}. "
            "Manual recovery is required."
        )


class InvalidCheckpointError(CheckpointError):
    """A checkpoint is structurally invalid or incompatible."""

    def __init__(self, checkpoint_id: str, reason: str) -> None:
        self.checkpoint_id = checkpoint_id
        self.reason = reason
        super().__init__(
            f"Checkpoint {checkpoint_id!r} is invalid: {reason}"
        )


# ── LOC / Sizing Errors ──────────────────────────────────────────────────────


class SizingError(ModernizationError):
    """Base for project sizing errors."""

    pass


class LOCAccountingError(SizingError):
    """LOC accounting failed or produced inconsistent results."""

    def __init__(
        self,
        method_1: str,
        count_1: int,
        method_2: str,
        count_2: int,
    ) -> None:
        self.method_1 = method_1
        self.count_1 = count_1
        self.method_2 = method_2
        self.count_2 = count_2
        super().__init__(
            f"LOC accounting mismatch: {method_1}={count_1}, {method_2}={count_2}. "
            f"Difference: {abs(count_1 - count_2)} lines. "
            "Cross-validate with multiple counting methods."
        )


# ── Data Plane Errors ────────────────────────────────────────────────────────


class DataPlaneError(ModernizationError):
    """Base for data-plane boundary errors."""

    pass


class ClientDataLeakError(DataPlaneError):
    """Client data was inadvertently routed to an external data plane."""

    def __init__(self, data_type: str, attempted_plane: str) -> None:
        self.data_type = data_type
        self.attempted_plane = attempted_plane
        super().__init__(
            f"Client data of type {data_type!r} was routed to "
            f"external plane {attempted_plane!r}. Boundary violation blocked."
        )


class LockdownViolationError(DataPlaneError):
    """An operation was attempted that violates lockdown mode."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(
            f"Operation {operation!r} is blocked in lockdown mode. "
            "Internet access is disabled."
        )


# ── Transformation Errors (Foundation — structural only) ────────────────────────


class TransformationError(ModernizationError):
    """Base for transformation errors.

    Specific transformation failures (syntax, compilation, test, behavioral)
    belong to G.3's BoundedTransformationEngine.
    """

    pass


class TransformationBlockedError(TransformationError):
    """A transformation was blocked by the planning gate."""

    def __init__(self, unit_id: str, reason: str) -> None:
        self.unit_id = unit_id
        self.reason = reason
        super().__init__(
            f"Transformation unit {unit_id!r} is blocked: {reason}"
        )


class UnresolvedBusinessIntentError(PlanningGateError):
    """Business intent for a component is unresolved; transformation is deferred."""

    def __init__(self, component_id: str, gap: str) -> None:
        self.component_id = component_id
        self.gap = gap
        super().__init__(
            f"Business intent for component {component_id!r} is unresolved: {gap}. "
            "Transformation is blocked. Human review required."
        )


class ContradictoryBusinessRuleError(PlanningGateError):
    """Two business rules contradict each other and cannot both be satisfied."""

    def __init__(
        self,
        rule_id_1: str,
        rule_id_2: str,
        conflict: str,
    ) -> None:
        self.rule_id_1 = rule_id_1
        self.rule_id_2 = rule_id_2
        self.conflict = conflict
        super().__init__(
            f"Contradictory business rules: {rule_id_1!r} and {rule_id_2!r}. "
            f"Conflict: {conflict}"
        )


class UnapprovedFindingError(PlanningGateError):
    """A finding requires approval before transformation can proceed."""

    def __init__(self, finding_id: str, finding_type: str) -> None:
        self.finding_id = finding_id
        self.finding_type = finding_type
        super().__init__(
            f"Finding {finding_id!r} ({finding_type}) is not approved. "
            "Human review required before transformation."
        )

class ToolRequiredError(CapabilityError):
    """A required specialist tool is not installed or not verified."""

    def __init__(
        self,
        tool_name: str,
        technology: str,
        verification_error: str = "",
    ) -> None:
        self.tool_name = tool_name
        self.technology = technology
        self.verification_error = verification_error
        super().__init__(
            f"Required tool {tool_name!r} for {technology!r} is not available. "
            f"{verification_error}".strip()
        )
