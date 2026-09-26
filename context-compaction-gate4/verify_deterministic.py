"""Gate 4 deterministic verification (task §6).

Runs BEFORE any model is consulted, per Gate 4 §6. Verifies identity,
dependency, provenance, requirement, verification, recovery and conflict
invariants, plus the Gate 3 limitations L1–L4 and storage/idempotency
round-trips (§15–§18).

Read-only with respect to production code.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

from autoforge_execution.compaction import (
    CompactionPolicy,
    ContextCompactor,
    apply_validation,
    classify_item,
)
from autoforge_execution.compaction.compaction_schema import DurableRef
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
)

sys.path.insert(0, str(Path(__file__).parent))
from corpus import build_corpus  # noqa: E402

ENABLED = CompactionPolicy(enabled=True)


def section_identity(case, builder, ctx, record) -> dict:
    """§6 Identity: iteration ids, context ids, source refs, artifact ids."""
    iteration_items = [i for i in (record.items if record else [])
                       if i.source.kind == "iteration"]
    return {
        "iteration_refs_preserved": sorted(i.source.ref for i in iteration_items),
        "iteration_refs_count": len(iteration_items),
        "context_ids_unique": len({i.context_id for i in iteration_items})
        == len(iteration_items),
        "context_ids_content_derived": all(
            i.context_id.startswith("ctx_") for i in iteration_items
        ),
        "source_refs_preserved": all(
            i.source.ref.startswith("iter-") for i in iteration_items
        ),
    }


def section_dependencies(record) -> dict:
    """§6 Dependencies: chain intact, no orphans."""
    items = [i for i in record.items if i.source.kind == "iteration"]
    ids = {i.context_id for i in record.items}
    orphans = [
        d for i in record.items for d in i.depends_on if d not in ids
    ]
    chained = sum(1 for i in items if i.depends_on)
    return {
        "dependency_chain_edges": chained,
        "orphaned_dependency_refs": orphans,
        "no_orphans": not orphans,
        "ordered_chain_intact": all(
            previous.context_id in current.depends_on
            for previous, current in zip(items, items[1:])
        ),
    }


def section_provenance(record) -> dict:
    """§6 Provenance: source, type, version, authoritative-vs-inferred."""
    items = [i for i in record.items if i.source.kind == "iteration"]
    return {
        "all_have_provenance": all(i.provenance is not None for i in items),
        "all_attributed": all(
            i.provenance and i.provenance.acquired_from for i in items
        ),
        "none_inferred": all(
            i.provenance and i.provenance.inferred is False for i in items
        ),
        "acquired_from_values": sorted(
            {i.provenance.acquired_from for i in items if i.provenance}
        ),
        "provenance_is_content_free": all(
            set(vars(i.provenance)) <= {
                "acquired_from", "source_ref", "provider", "acquired_at",
                "inferred",
            }
            for i in items if i.provenance
        ),
    }


def section_requirements(case, record) -> dict:
    """§6 Requirements: constraints, approvals, rejected decisions."""
    body = "\n".join(i.content for i in record.items)
    preserved = [f for f in case.required_facts if f.lower() in body.lower()]
    forbidden_present = [f for f in case.forbidden_facts if f.lower() in body.lower()]
    approvals = [i for i in record.items if i.source.kind == "approval"]
    return {
        "required_facts_expected": len(case.required_facts),
        "required_facts_preserved": len(preserved),
        "required_facts_missing": [
            f for f in case.required_facts if f not in preserved
        ],
        "all_required_preserved": len(preserved) == len(case.required_facts),
        "forbidden_facts_present_as_available": forbidden_present,
        "approval_items_carried": len(approvals),
        "approvals_irreplaceable": all(
            classify_item(i).value == "irreplaceable" for i in approvals
        ),
        "rejection_never_becomes_absence": all(
            "REJECTED" in i.content for i in approvals
        ),
    }


def section_verification(record) -> dict:
    """§6 Verification: results preserved, deterministic evidence authoritative."""
    body = "\n".join(i.content for i in record.items)
    return {
        "observed_failures_present": "observed_failures:" in body,
        "authority_markers_present": "authority: observed" in body,
        "deterministic_evidence_marked": "observed_by_deterministic_checks"
        in body,
        "model_claims_never_marked_verified": "verified_root_cause" not in body,
        "proposals_marked_proposed": "proposed_root_cause:" in body,
    }


def section_recovery(record) -> dict:
    """§6 Recovery: unresolved work and failure history preserved."""
    body = "\n".join(i.content for i in record.items)
    return {
        "supersession_status_present": "status: superseded" in body,
        "current_status_present": "status: current" in body,
        "corrections_present": "proposed_correction:" in body,
        "failure_history_present": "result: failed" in body,
    }


def section_conflicts(record) -> dict:
    """§6 Conflicts: contradictions detectable, authority not corrupted."""
    items = [i for i in record.items if i.source.kind == "iteration"]
    bodies = [i.content for i in items]
    return {
        "iterations_not_collapsed": len(bodies) == len(set(bodies)),
        "each_iteration_distinct_ref": len({i.source.ref for i in items}) == len(items),
        "authority_markers_consistent": all(
            ("authority: observed" in i.content) for i in items
        ),
    }


def _durable_stack(root_name: str):
    """Build a real (catalog, physical_store) pair over a fresh SQLite file."""
    from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
    from autoforge_runtime.persistence import PersistenceLayer
    from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

    root = Path(tempfile.mkdtemp(prefix=root_name))
    art_root = root / "artifacts"
    store = PhysicalArtifactStore(
        artifact_root=art_root,
        staging_root=art_root / ".staging",
        quarantine_root=art_root / ".quarantine",
    )
    catalog = DurableArtifactCatalog(
        persistence=PersistenceLayer(db_path=root / "state.db"),
        physical_store=store,
    )
    return root, art_root, store, catalog


async def verify_storage_roundtrip(case) -> dict:
    """L3 / §16: create -> persist -> RESTART -> reload -> resolve -> validate."""
    from autoforge_execution.compaction import CompactionRecordStore
    from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
    from autoforge_runtime.persistence import PersistenceLayer
    from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

    root, art_root, store, catalog = _durable_stack("af_g4_store_")
    db = root / "state.db"
    record = ContextCompactor(ENABLED).compact(
        task_id=case.task.task_id, prior_iterations=case.history
    )
    assert apply_validation(record, policy=ENABLED)

    compactor_store = CompactionRecordStore(catalog, store)
    artifact_id_1 = compactor_store.save(record)

    # --- simulated process restart: brand new catalog + store handles -----
    store2 = PhysicalArtifactStore(
        artifact_root=art_root,
        staging_root=art_root / ".staging",
        quarantine_root=art_root / ".quarantine",
    )
    catalog2 = DurableArtifactCatalog(
        persistence=PersistenceLayer(db_path=db), physical_store=store2
    )
    compactor_store2 = CompactionRecordStore(catalog2, store2)
    reloaded = compactor_store2.load(record.compaction_id)
    artifact_id_2 = compactor_store2.save(record)  # idempotency across restart

    return {
        "case": case.name,
        "reloaded_ok": reloaded is not None,
        "artifact_id_stable_across_restart": artifact_id_1 == artifact_id_2,
        "identity_preserved": bool(reloaded)
        and reloaded.compaction_id == record.compaction_id,
        "fingerprint_preserved": bool(reloaded)
        and reloaded.request_fingerprint == record.request_fingerprint,
        "content_digest_preserved": bool(reloaded)
        and reloaded.content_digest() == record.content_digest(),
        "items_preserved": bool(reloaded) and len(reloaded.items) == len(record.items),
        "provenance_preserved": bool(reloaded)
        and reloaded.provenance is not None
        and reloaded.provenance.source_context_ids
        == record.provenance.source_context_ids,
        "schema_version": reloaded.compaction_schema_version if reloaded else None,
        "no_duplicate_artifact": artifact_id_1 == artifact_id_2,
    }


async def verify_reference_resolution(case) -> dict:
    """L1 / §15: reference creation, persistence, resolution, hash/version, failures."""
    from autoforge_execution.compaction import CatalogReferenceResolver
    from autoforge_runtime.artifact_catalog import derive_artifact_key

    _root, _art, store, catalog = _durable_stack("af_g4_refs_")

    key = derive_artifact_key(artifact_name="iter-1")
    st = catalog.register_artifact(artifact_key=key, artifact_name="iter-1")
    staging = store.create_staging_file(key)
    catalog.begin_staging(st.artifact_id, staging_path=str(staging))
    h, _ = store.write_staging_text(staging, "iteration one content")
    published = store.atomic_publish(staging, "iter-1")
    committed = catalog.commit_artifact(
        st.artifact_id, storage_path=str(published), content_hash=h
    )

    resolver = CatalogReferenceResolver(catalog)
    resolved = resolver.resolve("iter-1")
    missing = resolver.resolve("iter-999")

    bad_record = ContextCompactor(ENABLED).compact(
        task_id=case.task.task_id, prior_iterations=case.history
    )
    bad_record.durable_refs = [
        DurableRef(artifact_id=str(committed.artifact_id), content_hash="")
    ]
    bad_valid = apply_validation(bad_record, policy=ENABLED)

    return {
        "case": case.name,
        "reference_created": resolved is not None,
        "reference_has_artifact_id": bool(resolved and resolved.artifact_id),
        "reference_has_content_hash": bool(resolved and resolved.content_hash),
        "reference_has_version": bool(resolved and resolved.logical_version >= 1),
        "reference_matches_committed_hash": bool(
            resolved and resolved.content_hash == committed.content_hash
        ),
        "reference_has_no_content_field": resolved is not None
        and not hasattr(resolved, "content"),
        "missing_source_returns_none": missing is None,
        "invalid_reference_rejected_by_validation": bad_valid is False,
        "invalid_reference_reasons": list(bad_record.validation_reasons),
    }


async def verify_idempotency(case) -> dict:
    """§17: same request, different source, changed policy, repeated execution."""
    same_a = ContextCompactor(ENABLED).compact(
        task_id=case.task.task_id, prior_iterations=case.history
    )
    same_b = ContextCompactor(ENABLED).compact(
        task_id=case.task.task_id, prior_iterations=case.history
    )
    # A genuinely different source: a DIFFERENT TASK with a different history
    # length. Using history[:2] alone would be a no-op probe whenever the case
    # has <= 2 iterations, because those all sit inside the retention window.
    other = ContextCompactor(ENABLED).compact(
        task_id=case.task.task_id + "-other", prior_iterations=case.history
    )
    longer = ContextCompactor(ENABLED).compact(
        task_id=case.task.task_id, prior_iterations=case.history + case.history
    )
    v2 = ContextCompactor(CompactionPolicy(enabled=True, policy_version=2)).compact(
        task_id=case.task.task_id, prior_iterations=case.history
    )
    return {
        "case": case.name,
        "iterations": len(case.history),
        "same_source_same_policy_same_id": same_a.compaction_id == same_b.compaction_id,
        "same_source_same_policy_same_digest": (
            same_a.content_digest() == same_b.content_digest()
        ),
        "no_duplicate_items_on_retry": len({i.context_id for i in same_b.items})
        == len(same_b.items),
        "different_task_distinct_id": same_a.compaction_id != other.compaction_id,
        "longer_history_distinct_id": same_a.compaction_id != longer.compaction_id,
        "changed_policy_distinct_id": same_a.compaction_id != v2.compaction_id,
        "changed_policy_distinct_fingerprint": (
            same_a.request_fingerprint != v2.request_fingerprint
        ),
    }


async def build_context(case, *, compaction: bool, workspace: Path):
    """Build the canonical context for one arm.

    SAME inputs for both arms; the only difference is whether a compactor is
    injected (Gate 4 §7/§31). The compactor itself decides the difference.
    """
    builder = EngineeringContextBuilder(
        compactor=ContextCompactor(ENABLED) if compaction else None
    )
    ctx = await builder.assemble_context(
        task_def=case.task,
        workspace_root=workspace,
        prior_iterations=case.history,
        last_evaluation=case.history[-1].evaluation,
        last_diagnosis=case.history[-1].diagnosis,
        context_window_tokens=32768,
    )
    return builder, ctx


async def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="af_g4_det_"))
    (workspace / "service.py").write_text("X = 1\n", encoding="utf-8")

    results: dict = {"cases": {}, "storage": [], "references": [],
                    "idempotency": []}

    for case in build_corpus():
        entry: dict = {"iterations": len(case.history)}

        # --- Arm B (compacted) is what the deterministic sections inspect ----
        builder, ctx = await build_context(case, compaction=True, workspace=workspace)
        record = builder.last_compaction_record

        entry["arm_b"] = {
            "compaction_ran": record is not None,
            "validation_status": record.validation_status if record else None,
            "trigger": record.trigger if record else None,
            "source_estimated_tokens": record.source_estimated_tokens if record else None,
            "estimated_tokens": record.estimated_tokens if record else None,
            "reduction_ratio": record.reduction_ratio if record else None,
        }

        # Gate 4 §31: record candidate/selected/excluded counts per experiment.
        asm = ctx.context_assembly_record
        entry["counts"] = {
            "candidates_considered": asm.considered_count,
            "candidates_selected": asm.selected_count,
            "excluded": len(asm.excluded),
        }

        # --- deterministic sections (§6) ---------------------------------
        if record is not None:
            entry["identity"] = section_identity(case, builder, ctx, record)
            entry["dependencies"] = section_dependencies(record)
            entry["provenance"] = section_provenance(record)
            entry["requirements"] = section_requirements(case, record)
            entry["verification"] = section_verification(record)
            entry["recovery"] = section_recovery(record)
            entry["conflicts"] = section_conflicts(record)
        else:
            entry["note"] = "compaction did not trigger for this case (short history)"

        results["cases"][case.name] = entry
        results["storage"].append(await verify_storage_roundtrip(case))
        results["references"].append(await verify_reference_resolution(case))
        results["idempotency"].append(await verify_idempotency(case))

    # --- aggregate pass/fail ------------------------------------------------
    def _all_true(rows, *keys) -> bool:
        return all(all(r.get(k) is True for k in keys) for r in rows)

    results["summary"] = {
        "storage_roundtrip_all_pass": _all_true(
            results["storage"],
            "reloaded_ok", "identity_preserved", "content_digest_preserved",
            "provenance_preserved", "no_duplicate_artifact",
        ),
        "reference_resolution_all_pass": _all_true(
            results["references"],
            "reference_created", "reference_has_content_hash",
            "reference_matches_committed_hash", "missing_source_returns_none",
            "invalid_reference_rejected_by_validation",
        ),
        "idempotency_all_pass": _all_true(
            results["idempotency"],
            "same_source_same_policy_same_id", "no_duplicate_items_on_retry",
            "different_task_distinct_id", "longer_history_distinct_id",
            "changed_policy_distinct_id",
        ),
        "requirements_all_preserved": all(
            e.get("requirements", {}).get("all_required_preserved", True)
            for e in results["cases"].values()
        ),
        "no_forbidden_resurrection": all(
            not e.get("requirements", {}).get("forbidden_facts_present_as_available")
            for e in results["cases"].values()
        ),
        "no_orphaned_dependencies": all(
            e.get("dependencies", {}).get("no_orphans", True)
            for e in results["cases"].values()
        ),
        "model_claims_never_verified": all(
            e.get("verification", {}).get("model_claims_never_marked_verified", True)
            for e in results["cases"].values()
        ),
    }

    dest = Path(__file__).parent / "preservation_results.json"
    dest.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps(results["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
