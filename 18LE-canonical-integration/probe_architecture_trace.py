"""18-LE full canonical architecture trace (§13).

Proves, for at least one successful run, the complete production path with the
ACTUAL engine invoked at every boundary:

  Request -> Kernel.submit_request -> Intent -> Strategic Engine
  -> Executable Workflow -> O-2 DefaultOrchestrationEngine -> capability routing
  -> Commercial Power Engine -> execution -> ArtifactPipeline
  -> DurableArtifactCatalog -> PhysicalArtifactStore -> deterministic validation
  -> Review -> Completion

No simulated routing and no mocks: the real composed system is driven and each
boundary is observed.
"""
import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path('/Users/kalachanddash/Developer/AutoForge-AI-OS')
for p in ['events', 'event_platform', 'runtime', 'models', 'ai_infrastructure',
          'workflows', 'execution', 'artifacts', 'review', 'security',
          'connectors', 'orchestration', 'kernel', 'composition', 'workforce',
          'power_engines', 'modernization']:
    s = REPO / 'packages' / p / 'src'
    if s.exists() and str(s) not in sys.path:
        sys.path.insert(0, str(s))

CAPABILITY = 'custom_ai_agent'
REQUEST = ('Build a custom AI customer-support agent that can read order files, '
           'use the calculator and current_time tools, and answer within a '
           'bounded loop.')


async def main() -> int:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    trace: dict = {'phase': '18-LE canonical architecture trace',
                   'capability': CAPABILITY}

    workspace = Path(tempfile.mkdtemp(prefix='18LE_trace_ws_'))
    system = build_autoforge_system(workspace_root=str(workspace))
    await system.initialize()
    trace['kernel'] = type(system.kernel).__name__
    trace['orchestration_engine'] = type(system.kernel.orchestration_engine).__name__
    trace['strategic_engine'] = type(system.strategic_engine).__name__
    trace['execution_engine'] = type(system.execution_engine).__name__
    trace['durable_catalog'] = type(system.durable_catalog).__name__
    trace['physical_store'] = type(system.physical_store).__name__
    trace['review_engine'] = type(system.review_engine).__name__
    trace['capability_router'] = type(system.capability_router).__name__
    trace['router_capabilities'] = system.capability_router.capabilities

    # observe the routing seam
    adapter = system.kernel.execution_engine
    original = adapter.execute_loop
    seen: list = []

    async def spy(loop_type, loop_input, context):
        result = await original(loop_type, loop_input, context)
        seen.append({
            'loop_type': loop_type,
            'routed': result.get('routed', False),
            'capability': result.get('capability'),
            'capability_source': result.get('capability_source'),
            'engine_class': result.get('engine_class'),
            'status': result.get('status'),
            'stages_executed': result.get('stages_executed'),
            'scorecard': result.get('verification_scorecard'),
            'delivery_dir': result.get('delivery_dir'),
            'artifacts': len(result.get('artifacts') or []),
        })
        return result

    adapter.execute_loop = spy

    submitted = await system.kernel.submit_request(Request(
        user_id=uuid.uuid4(),
        request_text=REQUEST,
        configuration={
            'environment': 'production',
            'execute': True,
            'capability': CAPABILITY,
            'output_root': str(Path(tempfile.mkdtemp(prefix='18LE_trace_out_'))),
        },
    ))
    project_id = submitted['project_id']
    trace['project_id'] = str(project_id)

    active = system.kernel.active_projects[project_id]
    plan = active.get('strategic_plan')
    workflow = active.get('executable_workflow')
    trace['strategic_plan'] = {
        'present': plan is not None,
        'requirements': len(getattr(plan, 'requirements', []) or []),
        'acceptance_criteria': len(getattr(plan, 'acceptance_criteria', []) or []),
    }
    trace['executable_workflow'] = {
        'present': workflow is not None,
        'loop_count': len(getattr(workflow, 'loops', []) or []),
    }

    routed = [s for s in seen if s['routed']]
    trace['loops_observed'] = len(seen)
    trace['loops_routed'] = len(routed)
    trace['engine_actually_invoked'] = sorted(
        {s['engine_class'] for s in routed if s.get('engine_class')}
    )
    trace['capability_resolution'] = [
        {'loop': s['loop_type'], 'capability': s['capability'],
         'source': s['capability_source']} for s in routed
    ][:1]
    trace['engine_stages'] = routed[0]['stages_executed'] if routed else []
    trace['engine_verification_scorecard'] = routed[0]['scorecard'] if routed else {}
    trace['delivery_dir'] = routed[0]['delivery_dir'] if routed else None
    trace['delivery_exists'] = bool(
        routed and routed[0].get('delivery_dir')
        and Path(routed[0]['delivery_dir']).exists()
    )

    state = await system.runtime_facade.get_project_state(project_id)
    trace['final_state'] = str(state.get('status'))
    wf_id = system.kernel.completion_module._project_workflow_id(state)
    records = system.durable_catalog.find_by_workflow(wf_id) or []
    trace['durable_artifacts'] = len(records)
    trace['durable_all_committed'] = all(
        str(getattr(getattr(r, 'status', ''), 'value', getattr(r, 'status', '')))
        == 'committed' for r in records
    ) if records else False

    evidence = await system.kernel.completion_module._collect_final_review_evidence(
        project_id)
    trace['review_evidence_files'] = len(evidence)
    trace['review_evidence_names'] = sorted(evidence)[:20]

    print(json.dumps(trace, indent=2, default=str))

    ev = REPO / '18LE-canonical-integration' / 'evidence'
    ev.mkdir(parents=True, exist_ok=True)
    (ev / 'canonical_architecture_trace.json').write_text(
        json.dumps(trace, indent=2, default=str), encoding='utf-8')
    await system.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))

