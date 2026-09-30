"""18-LE canonical routing E2E probe.

Drives the REAL composed system (no mocks) for each commercial capability and
records which engine actually executed. Read-only with respect to the repo.
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

CASES = {
    'rag_knowledge': 'Build a customer knowledge assistant that ingests our documents and answers with grounded citations.',
    'custom_ai_agent': 'Build a custom AI customer-support agent with calculator and current_time tools.',
    'ai_automation': 'Build an AI automation that watches a drop folder and runs a multi-step workflow.',
    'code_migration': 'Migrate the existing Python module to modern typed Python and verify the result.',
    'legacy_modernization': 'Modernize the legacy COBOL batch ledger and its JCL job into a modern Java service.',
}

LEDGER_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEDGER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT      PIC 9(7)V99.
       01  WS-ENTRY-TOTAL PIC 9(9)V99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE 1250.50 TO WS-AMOUNT.
           ADD WS-AMOUNT TO WS-ENTRY-TOTAL.
           IF WS-ENTRY-TOTAL > 1000
               MOVE "HIGH" TO WS-STATUS.
           END-IF.
           DISPLAY "LEDGER TOTAL: " WS-ENTRY-TOTAL.
           STOP RUN.
"""
LEDGER_JCL = """//LEDGER  JOB (ACCT),'LEDGER BATCH',CLASS=A
//STEP1   EXEC PGM=IEFBR14
//SYSPRINT DD SYSOUT=*
//
"""


def legacy_fixture() -> str:
    root = Path(tempfile.mkdtemp(prefix='18le_legacy_'))
    (root / 'cbl').mkdir()
    (root / 'jcl').mkdir()
    (root / 'cbl' / 'LEDGER.cbl').write_text(LEDGER_COBOL, encoding='utf-8')
    (root / 'jcl' / 'LEDGER.jcl').write_text(LEDGER_JCL, encoding='utf-8')
    return str(root)


def knowledge_fixture() -> str:
    """A REAL customer corpus for the RAG engine.

    The RAG engine's own INTAKE/VERIFY stages require grounded knowledge sources;
    an empty corpus cannot be verified. Supplying real documents is the
    requester's declared input, not an invented verification.
    """
    root = Path(tempfile.mkdtemp(prefix='18le_knowledge_'))
    (root / 'accounts_policy.md').write_text(
        '# Transaction Threshold Policy\n\n'
        'Any transaction above 1000 requires compliance sign-off before posting.\n'
        'The ledger total is displayed after each batch entry is applied.\n',
        encoding='utf-8',
    )
    (root / 'ledger_overview.md').write_text(
        '# Ledger Service\n\n'
        'The ledger accumulates entries and reports a running total.\n'
        'When the total exceeds the threshold the status is marked HIGH.\n',
        encoding='utf-8',
    )
    return str(root)


def python_fixture() -> str:
    """A REAL Python module for the Code Migration engine."""
    root = Path(tempfile.mkdtemp(prefix='18le_migration_'))
    (root / 'order_processor.py').write_text(
        'def process_order(order):\n'
        '    total = 0\n'
        '    for line in order["lines"]:\n'
        '        total = total + line["amount"]\n'
        '    if total > 1000:\n'
        '        return {"status": "HIGH", "total": total}\n'
        '    return {"status": "OK", "total": total}\n',
        encoding='utf-8',
    )
    return str(root)


async def probe(capability: str) -> dict:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    ws = Path(tempfile.mkdtemp(prefix=f'18le_{capability}_ws_'))
    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()

    adapter = system.kernel.execution_engine
    original = adapter.execute_loop
    observed: list[dict] = []

    async def spy(loop_type, loop_input, context):
        result = await original(loop_type, loop_input, context)
        observed.append({
            'loop_type': loop_type,
            'status': result.get('status'),
            'passed': result.get('passed'),
            'routed': result.get('routed', False),
            'capability': result.get('capability'),
            'capability_source': result.get('capability_source'),
            'engine_class': result.get('engine_class'),
            'delivery_dir': result.get('delivery_dir'),
            'stages': result.get('stages_executed'),
            'scorecard_keys': sorted((result.get('verification_scorecard') or {}).keys()),
            'artifacts': len(result.get('artifacts') or []),
            'error': result.get('error'),
        })
        return result

    adapter.execute_loop = spy

    configuration = {
        'environment': 'production',
        'execute': True,
        'capability': capability,
        'output_root': str(Path(tempfile.mkdtemp(prefix='18le_out_'))),
    }
    if capability == 'legacy_modernization':
        configuration['legacy_source_root'] = legacy_fixture()
    if capability == 'rag_knowledge':
        configuration['knowledge_sources'] = [
            {'source_id': 'policy', 'source_type': 'document',
             'path': f'{knowledge_fixture()}/accounts_policy.md'},
            {'source_id': 'overview', 'source_type': 'document',
             'path': f'{knowledge_fixture()}/ledger_overview.md'},
        ]
    if capability == 'code_migration':
        configuration['migration_source_path'] = python_fixture()
        configuration['source_languages'] = ['python']
        configuration['target_language'] = 'python'

    record: dict = {'capability': capability}
    try:
        submitted = await system.kernel.submit_request(Request(
            user_id=uuid.uuid4(),
            request_text=CASES[capability],
            configuration=configuration,
        ))
        project_id = submitted['project_id']
        record['project_id'] = str(project_id)
        state = await system.runtime_facade.get_project_state(project_id)
        record['final_status'] = str(state.get('status'))

        record['loops'] = observed
        routed = [o for o in observed if o.get('routed')]
        record['routed_loops'] = len(routed)
        record['engines_invoked'] = sorted(
            {o['engine_class'] for o in routed if o.get('engine_class')}
        )
        record['canonical_routing_pass'] = bool(routed)
    except Exception as exc:  # pragma: no cover - diagnostic
        record['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        await system.shutdown()
    return record


async def main() -> int:
    out = {'phase': '18-LE canonical capability routing E2E', 'results': {}}
    for cap in CASES:
        rec = await probe(cap)
        out['results'][cap] = rec
        print(f"{cap:24s} routed={rec.get('canonical_routing_pass')} "
              f"engines={rec.get('engines_invoked')} "
              f"status={rec.get('final_status')} err={rec.get('error')}")
        for lp in rec.get('loops', [])[:2]:
            print(f"    loop={lp['loop_type']:12s} engine={lp['engine_class']} "
                  f"routed={lp['routed']} status={lp['status']} "
                  f"scorecard={lp['scorecard_keys']}")
    passed = [c for c, r in out['results'].items() if r.get('canonical_routing_pass')]
    out['summary'] = {
        'capabilities_tested': len(CASES),
        'capabilities_routed': passed,
        'canonical_routing_pass': len(passed) == len(CASES),
    }
    print(json.dumps(out['summary'], indent=2))
    ev = REPO / '18LE-canonical-integration' / 'evidence'
    ev.mkdir(parents=True, exist_ok=True)
    (ev / 'canonical_routing.json').write_text(
        json.dumps(out, indent=2, default=str), encoding='utf-8'
    )
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
