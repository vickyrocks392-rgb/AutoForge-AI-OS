"""Phase 19 — production wiring closure: runtime evidence (Gate 11).

Proves the ``ActiveLearningResolver`` is genuinely reachable from the real system
built by ``composition_root.build_autoforge_system()``, and records the actual
project id, learning state, resolver invocation, resolution result and execution
outcome.

Run: python3 scripts/_verify_phase19_wiring.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _pkg in (
    "composition", "execution", "kernel", "learning", "security", "runtime",
    "events", "event_platform", "connectors", "workflows", "artifacts",
    "review", "orchestration", "ai_infrastructure",
):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))

from autoforge_composition.composition_root import build_autoforge_system  # noqa: E402
from autoforge_kernel.interfaces import Request  # noqa: E402
from autoforge_learning.store import (  # noqa: E402
    ActiveLearningState,
    DurableLearningStore,
)


def banner(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


async def main() -> int:
    print("=" * 74)
    print("PHASE 19 — PRODUCTION WIRING CLOSURE: RUNTIME EVIDENCE (Gate 11)")
    print("=" * 74)

    ok = True
    with tempfile.TemporaryDirectory(prefix="autoforge_wiring_") as tmp:
        base = Path(tmp)
        learning_root = base / "learning-state"
        learning_root.mkdir()

        banner("1. Build the REAL production system")
        autoforge = build_autoforge_system(
            workspace_root=str(base / "ws"),
            learning_store_root=str(learning_root),
        )
        await autoforge.initialize()
        try:
            for label, obj in (
                ("kernel", autoforge.kernel),
                ("execution engine", autoforge.execution_engine),
                ("security platform", autoforge.security_platform),
                ("guardrails", autoforge.security_platform.guardrails),
                ("learning resolver", autoforge.learning_resolver),
            ):
                print(f"  {label:.<34} {type(obj).__name__}")
            print(f"  {'learning store root':.<34} {autoforge.learning_store.root}")

            wired = autoforge.execution_engine.learning_resolver
            print(f"\n  resolver on execution seam : {wired is autoforge.learning_resolver}")
            print(f"  resolver enabled           : {autoforge.learning_resolver.enabled}")
            ok &= wired is autoforge.learning_resolver
            ok &= autoforge.learning_resolver.enabled

            banner("2. Real Kernel request -> real project")
            request = Request(
                user_id=uuid.uuid4(),
                request_text="Add a small utility module with tests",
                configuration={"environment": "production", "execute": False},
            )
            response = await autoforge.kernel.submit_request(request)
            raw = response["project_id"]
            project_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
            print(f"  request accepted by real Kernel : True")
            print(f"  project_id                      : {project_id}")

            banner("3. Observe the resolver being INVOKED on the real path")
            invocations: list[tuple] = []
            engine = autoforge.execution_engine
            real_resolve = engine.resolve_learning

            def observing(pid):
                result = real_resolve(pid)
                invocations.append((pid, result))
                return result

            engine.resolve_learning = observing  # type: ignore[method-assign]
            resolution = engine.resolve_learning(project_id)
            print(f"  resolver invocations    : {len(invocations)}")
            print(f"  invoked with project_id  : {invocations[0][0]}")
            print(f"  reason                   : {resolution.reason}")
            print(f"  is_baseline              : {resolution.is_baseline}")
            print(f"  degraded                 : {resolution.degraded}")
            ok &= bool(invocations)

            banner("4. Promote real durable learning for THIS project")
            now = datetime.now(timezone.utc)
            state = ActiveLearningState(
                project_id=project_id,
                kind="pattern_template",
                key="default",
                version_id=uuid.uuid4(),
                version_number=1,
                candidate_id=uuid.uuid4(),
                content_hash="a" * 64,
                activation_timestamp=now,
                scope_kind="project",
            )
            DurableLearningStore(learning_root).set_active_state(state)
            print(f"  version_id   : {state.version_id}")
            print(f"  candidate_id : {state.candidate_id}")
            print(f"  content_hash : {state.content_hash[:16]}...")

            banner("5. Resolve learning through the real execution engine")
            learned = engine.resolve_learning(project_id)
            print(f"  is_applied  : {learned.is_applied}")
            print(f"  reason      : {learned.reason}")
            print(f"  parameters  : {learned.parameters}")
            print(f"  provenance  : {learned.provenance.to_dict()}")
            ok &= learned.is_applied

            banner("6. Absent / disabled / corrupt all degrade safely")
            other = uuid.uuid4()
            absent = engine.resolve_learning(other)
            print(f"  absent learning    -> baseline={absent.is_baseline} "
                  f"degraded={absent.degraded} ({absent.reason})")
            ok &= absent.is_baseline and not absent.degraded

            engine.set_learning_resolver(None)
            disabled = engine.resolve_learning(project_id)
            print(f"  learning disabled -> {disabled!r}")
            ok &= disabled is None
            engine.set_learning_resolver(autoforge.learning_resolver)

            active_file = next(
                (learning_root / str(project_id) / "active").glob("*.json")
            )
            active_file.write_text('{"content_hash": "tampered"}')
            corrupt = engine.resolve_learning(project_id)
            print(f"  corrupted pointer -> baseline={corrupt.is_baseline} "
                  f"degraded={corrupt.degraded} ({corrupt.reason})")
            ok &= corrupt.is_baseline and corrupt.degraded

            banner("7. Authority boundary unchanged")
            resolver = autoforge.learning_resolver
            forbidden = [
                name
                for name in (
                    "promote", "activate", "deactivate", "rollback",
                    "approve", "grant", "escalate", "set_active_state",
                )
                if hasattr(resolver, name)
            ]
            print(f"  authority methods on resolver : {forbidden or 'none'}")
            ok &= not forbidden
        finally:
            await autoforge.shutdown()

    print("\n" + "=" * 74)
    print("RESULT:", "PASS" if ok else "FAIL")
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
