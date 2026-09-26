"""
Context Compaction — deterministic validation (18-L Gate 3, implementing Gate 2
§17 V-1…V-13).

Validation is **deterministic** and runs *before* promotion: a record failing any
check is never authoritative, and the previous valid record stays current
(Gate 2 §8 step 10, §18).

Failure is fail-safe by construction. ``validate`` never raises and never repairs;
it reports reasons and the caller keeps the uncompacted context (Gate 3 §23).

New errors extend the existing ``ContextEngineeringError`` family rather than
introducing a parallel taxonomy (Gate 2 E-28).
"""

from __future__ import annotations

from autoforge_execution.compaction.compaction_policy import (
    CompactionPolicy,
    classify_item,
)
from autoforge_execution.compaction.compaction_schema import (
    CompactedContextRecord,
    CompactionMethod,
    ValidationStatus,
)
from autoforge_execution.errors import ContextEngineeringError


class CompactionValidationError(ContextEngineeringError):
    """A compact record failed deterministic validation (Gate 2 §17)."""


class CompactionReferenceUnresolvableError(ContextEngineeringError):
    """A durable reference in a compact record cannot be resolved (Gate 2 V-3)."""


class CompactionPolicyVersionError(ContextEngineeringError):
    """The compaction record or policy version is not supported (Gate 2 V-9)."""


#: Highest compaction schema version this build can read (Gate 2 §20). Records
#: with a higher version are ignored and re-derived, never migrated.
SUPPORTED_SCHEMA_VERSION = 1

_KNOWN_METHODS = {
    CompactionMethod.DETERMINISTIC.value,
    CompactionMethod.HYBRID.value,
    CompactionMethod.MODEL_MEDIATED.value,
}


def validate(
    record: CompactedContextRecord,
    *,
    policy: CompactionPolicy | None = None,
    known_ids: set[str] | None = None,
) -> list[str]:
    """Run V-1…V-13 and return the reasons the record is invalid (empty = valid).

    Pure function: no I/O, no clock, no model, no mutation beyond stamping
    ``completeness``, which is a reportable property.
    """
    reasons: list[str] = []
    item_ids = {i.context_id for i in record.items}

    # V-1 schema: identity and scope must be populated.
    if not record.compaction_id or not record.request_fingerprint:
        reasons.append("v1_schema_missing_identity")
    if not record.task_id:
        reasons.append("v1_schema_missing_task_scope")

    # V-2 required provenance on mandatory items (mirrors MissingProvenanceError).
    for item in record.items:
        if item.required and (
            item.provenance is None or not item.provenance.acquired_from
        ):
            reasons.append(f"v2_missing_provenance:{item.context_id}")

    # V-3 reference integrity: a reference must carry a verifiable hash.
    for ref in record.durable_refs:
        if not ref.artifact_id or not ref.content_hash:
            reasons.append(
                f"v3_unresolvable_reference:{ref.source_ref or ref.artifact_id}"
            )

    # V-4 dependency integrity: every depends_on target must exist in the record.
    pool = item_ids | (known_ids or set())
    for item in record.items:
        for dep in item.depends_on:
            if dep not in pool:
                reasons.append(f"v4_unresolvable_dependency:{item.context_id}->{dep}")

    # V-5 Irreplaceable material must be present and non-empty.
    for item in record.items:
        if classify_item(item).value == "irreplaceable" and not item.content.strip():
            reasons.append(f"v5_irreplaceable_emptied:{item.context_id}")

    # V-7 bounded output.
    if policy is not None and record.estimated_tokens > policy.max_record_tokens:
        reasons.append("v7_record_exceeds_bound")

    # V-9 version integrity.
    if record.compaction_schema_version > SUPPORTED_SCHEMA_VERSION:
        reasons.append("v9_unsupported_schema_version")
    if record.supersedes == record.compaction_id:
        reasons.append("v9_self_supersession")
    if record.logical_version < 1:
        reasons.append("v9_invalid_logical_version")

    # V-10 no untraceable model claims. Gate 3 implements no model stage, so a
    # record claiming one is unbacked by design (Gate 3 §17).
    if record.compaction_method not in _KNOWN_METHODS:
        reasons.append("v10_unknown_compaction_method")
    if record.compaction_method == CompactionMethod.MODEL_MEDIATED.value:
        reasons.append("v10_model_mediated_not_implemented")

    # V-12 no cross-scope leakage.
    for ref in record.durable_refs:
        if not ref.artifact_id:
            reasons.append("v12_reference_outside_scope")

    # V-13 content-free provenance: ids must be strings, never payloads.
    prov = record.provenance
    if prov is not None:
        if not prov.acquired_from:
            reasons.append("v13_provenance_missing_source")
        if any(not isinstance(cid, str) for cid in prov.source_context_ids):
            reasons.append("v13_provenance_carries_payload")

    record.completeness = (
        "partial_unresolvable"
        if any(r.startswith("v3_") for r in reasons)
        else "complete"
    )
    return reasons


def apply_validation(
    record: CompactedContextRecord,
    *,
    policy: CompactionPolicy | None = None,
    known_ids: set[str] | None = None,
) -> bool:
    """Validate and stamp the record's status. Returns True when valid.

    This is the *only* promotion gate: an invalid record is marked REJECTED and
    the caller keeps the previous state (Gate 2 §8 step 10, §18).
    """
    reasons = validate(record, policy=policy, known_ids=known_ids)
    record.validation_reasons = reasons
    record.validation_status = (
        ValidationStatus.REJECTED.value
        if reasons
        else ValidationStatus.VALID.value
    )
    return not reasons


__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "CompactionPolicyVersionError",
    "CompactionReferenceUnresolvableError",
    "CompactionValidationError",
    "apply_validation",
    "validate",
]
