"""
Context Compaction — 18-L Gate 3.

Deterministic, provider-neutral compaction of *accumulated intra-execution
history*, integrated into Context Engineering as a **pre-selection** stage.

Contract summary (Gate 2 design, implemented here):

* **One integration point** — inside ``EngineeringContextBuilder._build_candidates``,
  *before* ``select_context``. Ranking, budgeting and mandatory admission remain
  exclusively Context Engineering's; compaction never duplicates them.
* **Deterministic by default** — no model, provider or runtime is imported by any
  module in this package. ``CompactionMethod.MODEL_MEDIATED`` exists in the
  contract for forward compatibility only and is **not implemented**.
* **Derived, rebuildable** — a compact record is a cache. Deleting it loses
  nothing, because every reference points at authoritative durable state.
* **Off by default** — ``CompactionPolicy.enabled`` defaults to ``False``. Context
  Engineering remains globally ON; compaction is an independent, reversible
  feature.

Protected and unmodified by this package: 18-J (its idempotency mechanism is
*reused*, never changed), Context Engineering core, 18-K, the Model Router and the
inference lab.
"""

from autoforge_execution.compaction.compaction_policy import (
    DEFAULT_POLICY,
    CompactionPolicy,
    classify_item,
    classify_items,
)
from autoforge_execution.compaction.compaction_schema import (
    COMPACTION_ID_PREFIX,
    CompactedContextRecord,
    CompactionAssemblyRecord,
    CompactionMethod,
    CompactionProvenance,
    CompactionTrigger,
    DurableRef,
    PreservationClass,
    ValidationStatus,
    make_compaction_id,
    make_idempotency_key,
    make_request_fingerprint,
)
from autoforge_execution.compaction.compaction_validation import (
    CompactionPolicyVersionError,
    CompactionReferenceUnresolvableError,
    CompactionValidationError,
    apply_validation,
    validate,
)
from autoforge_execution.compaction.compactor import (
    ITERATION_SOURCE_KIND,
    ContextCompactor,
    DurableReferenceResolver,
    link_iteration_chain,
    project_iteration,
)
from autoforge_execution.compaction.storage import (
    CatalogReferenceResolver,
    CompactionRecordStore,
)

__all__ = [
    "COMPACTION_ID_PREFIX",
    "DEFAULT_POLICY",
    "ITERATION_SOURCE_KIND",
    "CatalogReferenceResolver",
    "CompactedContextRecord",
    "CompactionAssemblyRecord",
    "CompactionMethod",
    "CompactionPolicy",
    "CompactionPolicyVersionError",
    "CompactionProvenance",
    "CompactionRecordStore",
    "CompactionReferenceUnresolvableError",
    "CompactionTrigger",
    "CompactionValidationError",
    "ContextCompactor",
    "DurableRef",
    "DurableReferenceResolver",
    "PreservationClass",
    "ValidationStatus",
    "apply_validation",
    "classify_item",
    "classify_items",
    "link_iteration_chain",
    "make_compaction_id",
    "make_idempotency_key",
    "make_request_fingerprint",
    "project_iteration",
    "validate",
]
