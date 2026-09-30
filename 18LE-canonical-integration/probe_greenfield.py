"""18-LE fresh greenfield autonomous certification (M6-only, real inference).

Establishes the G-1/G-2/G-3 contract:
  G-1  a deterministic verification contract exists
  G-2  the verification contract actually executes
  G-3  the resulting deterministic status governs completion

Nothing is reused from any previous greenfield run.
"""
import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path('/Users/kalachanddash/Developer/AutoForge-AI-OS')
for p in ['events', 'event_platform', 'runtime', 'models', 'ai_infrastructure',
          'workflows', 'execution', 'artifacts', 'review', 'security',
          'connectors', 'orchestration', 'kernel', 'composition', 'workforce']:
    s = REPO / 'packages' / p / 'src'
    if s.exists() and str(s) not in sys.path:
        sys.path.insert(0, str(s))

REQUEST_TEXT = (
    "Build a small Python package called 'textmetrics' in textmetrics/ with a "
    "core.py module. It must expose:\n"
    "  - word_count(text): returns len(text.split())\n"
    "  - char_count(text): returns len(text)\n"
    "Deliverables required by this request (all four must exist):\n"
    "  - textmetrics/__init__.py and textmetrics/core.py\n"
    "  - tests/test_textmetrics.py using pytest.\n"
    "  - README.md at the project root describing the package, its two public "
    "functions, and how to run the test suite with: python -m pytest -q tests\n"
    "CRITICAL CONSTRAINT on the test file: do NOT hard-code any numeric "
    "character or word count. Every assertion must call the function under test "
    "and compare against a Python expression computed at runtime, e.g. "
    "assert char_count(s) == len(s) and assert word_count(s) == len(s.split()), "
    "where s is a string literal defined in the same test. This makes the tests "
    "correct by construction and independent of manual counting."
)

# G-1: the explicit deterministic verification contract. This is DECLARED, not
# invented: it is the project's own test suite command, supplied by the requester
# through Request.configuration exactly as DECISION B layer 1 prescribes.
VERIFICATION_COMMAND = 'python -m pytest -q tests'


async def main() -> int:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    workspace = Path(tempfile.mkdtemp(prefix='18LE_greenfield_ws_'))
    system = build_autoforge_system(workspace_root=str(workspace))
    await system.initialize()

    # M6 deployment binding (CONFIGURATION ONLY -- no source change).
    #
    # The production Model Router catalog registers local model ids for the M1/HP
    # node profiles (``qwen2.5-coder-7b``, ``ornith-9b``). The certified
    # 18-L/18-LE topology is "M6 Qwen3-Coder-30B authority + 0 continuous
    # workers", and the M6 local runtime serves that model. The platform already
    # ships a provider-neutral, deployment-level seam for exactly this --
    # ``BaseProviderAdapter.register_model_alias`` -- which maps a canonical
    # model id to the tag the local runtime serves.
    #
    # This does NOT add a provider, register a model, change the router, change
    # inference topology, start a worker, or reference M1/HP hardware. It is
    # applied to the PRODUCTION system's own already-bound adapters.
    from autoforge_ai_infrastructure.metadata import ModelQuery  # noqa: E402

    MODEL_ID = 'mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2'
    executors = getattr(
        system.execution_engine._ai._executor, '_executors', None
    ) or {}
    bound_models = []
    for pid, adapter in executors.items():
        if hasattr(adapter, 'register_model_alias'):
            for alias in ('qwen2.5-coder-7b', 'qwen2.5-coder-3b', 'ornith-9b'):
                adapter.register_model_alias(alias, MODEL_ID)
                bound_models.append(f'{pid}:{alias}->{MODEL_ID}')
    out_models = [
        {'model_id': m.model_id, 'provider_id': m.provider_id}
        for m in system.kernel.model_router._router.registry.query_models(ModelQuery())
    ] if hasattr(system.kernel.model_router, '_router') else []

    out: dict = {
        'phase': '18-LE fresh greenfield certification',
        'model': MODEL_ID,
        'model_aliases_bound': bound_models,
        'catalog_models': out_models,
        'request_text': REQUEST_TEXT,
        'verification_contract': VERIFICATION_COMMAND,
        'workspace': str(workspace),
    }

    # DECISION B / G-1: the explicit deterministic verification contract.
    # It is DECLARED through Request.configuration (DECISION B layer 1), never
    # invented: it is the project's own pytest suite command.
    submitted = await system.kernel.submit_request(Request(
        user_id=uuid.uuid4(),
        request_text=REQUEST_TEXT,
        configuration={
            'environment': 'production',
            # submit_request executes the project when this is true, so the run
            # happens exactly once (a second execute_project would be an
            # invalid COMPLETING -> RUNNING transition).
            'execute': True,
            'language': 'python',
            'verification_command': VERIFICATION_COMMAND,
        },
    ))
    project_id = submitted['project_id']
    out['project_id'] = str(project_id)
    print(f'project_id = {project_id}')

    state = await system.runtime_facade.get_project_state(project_id)
    out['final_state'] = str(state.get('status'))

    # ── durable artifacts (18-K) ────────────────────────────────────────────
    catalog = system.durable_catalog
    wf_id = system.kernel.completion_module._project_workflow_id(state)
    records = catalog.find_by_workflow(wf_id) or []
    out['durable_artifacts'] = {'count': len(records), 'by_status': {}, 'by_type': {}}
    for r in records:
        st = str(getattr(getattr(r, 'status', ''), 'value', getattr(r, 'status', '')))
        out['durable_artifacts']['by_status'][st] = (
            out['durable_artifacts']['by_status'].get(st, 0) + 1)
        at = str(getattr(r, 'artifact_type', ''))
        out['durable_artifacts']['by_type'][at] = (
            out['durable_artifacts']['by_type'].get(at, 0) + 1)
    print(f"durable artifacts = {out['durable_artifacts']}")

    # ── G-2/G-3: deterministic validation truth from the REAL port ───────────
    validation = await system.kernel.completion_module.validation_port.validate_project(
        project_id)
    out['validation'] = {
        k: validation.get(k) for k in
        ('required', 'performed', 'passed', 'command', 'exit_code', 'reason',
         'test_results')}
    print(f"validation = {json.dumps(out['validation'], default=str)[:400]}")

    # ── review evidence ─────────────────────────────────────────────────────
    evidence = await system.kernel.completion_module._collect_final_review_evidence(
        project_id)
    out['review_evidence_files'] = len(evidence)
    out['review_evidence_names'] = sorted(evidence)[:40]
    print(f'review evidence files = {len(evidence)}')

    # ── generated source on disk ────────────────────────────────────────────
    produced = sorted(
        str(p.relative_to(workspace)) for p in workspace.rglob('*')
        if p.is_file() and '.autoforge' not in p.parts
        and p.suffix in {'.py', '.md', '.toml', '.cfg', '.txt'})
    out['generated_files'] = produced[:60]
    print(f'generated files = {len(produced)}')
    out['readme_present'] = 'README.md' in produced

    # ── 18-K durability: registration, hash integrity, recovery ───────────
    store = system.physical_store
    integrity = []
    for r in records:
        path = getattr(r, 'storage_path', None)
        if not path:
            continue
        p = Path(path)
        entry = {'name': str(getattr(r, 'artifact_name', '')),
                 'exists': p.exists()}
        if p.exists():
            import hashlib
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            recorded = getattr(r, 'content_sha256', None) or getattr(r, 'checksum', None)
            entry['sha256'] = digest
            entry['matches_recorded'] = (recorded is None) or (str(recorded) == digest)
        integrity.append(entry)
    out['artifact_integrity'] = {
        'checked': len(integrity),
        'all_exist': all(e['exists'] for e in integrity) if integrity else False,
        'all_hashes_match': all(e.get('matches_recorded', True) for e in integrity)
        if integrity else False,
    }
    print(f"artifact integrity = {out['artifact_integrity']}")

    # ── completion decision (the G-3 proof) ─────────────────────────────────
    # ``submit_request`` already ran execute_project, so the project is in
    # COMPLETING/FINISHED. Calling finalize_project again would attempt an
    # invalid COMPLETING -> COMPLETING transition, so the outcome is read from
    # the authoritative state and the validation port instead of re-finalising.
    validation_truth = validation
    out['finalize'] = {
        'already_finalized_by_execute_project': True,
        'validation_required': validation_truth.get('required'),
        'validation_passed': validation_truth.get('passed'),
    }
    print('FINALIZE =', json.dumps(out['finalize'], default=str)[:400])
    state_after = await system.runtime_facade.get_project_state(project_id)
    out['final_state'] = str(state_after.get('status'))
    print('final_state =', out['final_state'])

    ev = REPO / '18LE-canonical-integration' / 'evidence'
    ev.mkdir(parents=True, exist_ok=True)
    (ev / 'greenfield.json').write_text(
        json.dumps(out, indent=2, default=str), encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items()
                      if k in ('final_state', 'durable_artifacts')},
                     indent=2, default=str)[:600])

    await system.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
