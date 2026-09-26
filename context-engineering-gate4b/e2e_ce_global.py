#!/usr/bin/env python
"""Gate 4B end-to-end runtime verification — Context Engineering globally enabled.

Proves the canonical production path end to end, with a real Model Router, a
real provider adapter, and a real local-runtime HTTP server:

    normal request
      -> orchestration / workflow engine
      -> EngineeringContextBuilder (Context Engineering, ON by default)
      -> MSC selection / dependency expansion / budgeting
      -> canonical prompt assembly
      -> Model Router allocation
      -> provider adapter (OpenAI-compatible)
      -> local runtime (llama.cpp / MLX wire format)
      -> execution
      -> artifact / result

The local runtime is stood up in-process on a real socket and speaks the
OpenAI-compatible ``/v1/chat/completions`` dialect that ``llama-server`` and MLX
expose, so the provider adapter performs a genuine HTTP round trip. That is the
same transport a real local runtime uses; only token generation is stubbed.

Observability emitted is content-free: counts, budget provenance, ids, and the
prompt-assembly path. No prompt text is logged.

Usage:  .venv/bin/python context-engineering-gate4b/e2e_ce_global.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _pkg in (
    "execution/src",
    "composition/src",
    "workflows/src",
    "ai_infrastructure/src",
    "runtime/src",
    "events/src",
    "event_platform/src",
    "kernel/src",
    "artifacts/src",
    "security/src",
    "models/src",
    "connectors/src",
    "memory/src",
    "knowledge_platform/src",
    "observability/src",
):
    _p = REPO / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from autoforge_ai_infrastructure.execution import (  # noqa: E402
    ExecutionRequest,
    ExecutionTarget,
    ExecutorRegistry,
)
from autoforge_ai_infrastructure.adapters.local_runtime import (  # noqa: E402
    LocalRuntimeProviderAdapter,
)
from autoforge_composition.composition_root import build_autoforge_system  # noqa: E402
from autoforge_workflows.models import TaskDefinition, WorkflowDefinition  # noqa: E402

# Captured server-side so we can prove what the model actually received.
CAPTURED_REQUESTS: list[dict] = []


class _LocalRuntimeHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible local runtime (llama-server / MLX dialect)."""

    def log_message(self, *args):  # silence per-request stderr noise
        return

    def do_GET(self):  # noqa: N802 - stdlib naming
        if self.path.rstrip("/").endswith("/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "local-runtime-1", "object": "model"},
                        {"id": "local-runtime-2", "object": "model"},
                    ],
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw.decode("utf-8") or "{}")
        CAPTURED_REQUESTS.append(body)

        # The adapter's _sync_request always uses POST (including for the model
        # listing), so dispatch on the path rather than the verb.
        if self.path.rstrip("/").endswith("/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "local-runtime-1", "object": "model"},
                        {"id": "local-runtime-2", "object": "model"},
                    ],
                },
            )
            return

        text = body.get("messages", [{}])[-1].get("content", "")
        if "file_edits" in text:
            content = json.dumps(
                {
                    "file_edits": [
                        {
                            "path": "output.py",
                            "content": "def add(a, b):\n    return a + b\n\nprint(add(2, 3))\n",
                        }
                    ]
                }
            )
        else:
            content = (
                "1. Add an `add(a, b)` function in output.py.\n"
                "2. Validate inputs are numeric.\n"
                "3. Cover the function with a unit test.\n"
                "4. Document the module.\n"
            )
        self._json(
            200,
            {
                "id": "chatcmpl-ce-gate4b",
                "object": "chat.completion",
                "model": body.get("model", "local-runtime-1"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 128, "completion_tokens": 64, "total_tokens": 192},
            },
        )

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_local_runtime() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), _LocalRuntimeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[0], server.server_address[1]
    return server, f"http://{host}:{port}/v1"


async def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    server, base_url = start_local_runtime()
    evidence: dict = {"local_runtime": base_url}
    try:
        workspace = Path(tempfile.mkdtemp(prefix="af_gate4b_e2e_"))
        (workspace / "service.py").write_text(
            "def add(a, b):\n    return a - b\n", encoding="utf-8"
        )

        # ---- 1. Canonical production system, DEFAULT configuration ---------
        system = build_autoforge_system(workspace_root=str(workspace))
        await system.initialize()

        evidence["context_engineering_enabled"] = (
            system.context_builder.enable_context_engineering
        )
        evidence["model_allocator_wired"] = type(
            system.context_builder.model_allocator
        ).__name__
        evidence["dispatcher_shares_canonical_builder"] = (
            system.execution_engine._dispatcher._context_builder is system.context_builder
        )

        # ---- 2. Bind the real local runtime as the default provider -------
        executor_registry = ExecutorRegistry()
        adapter = LocalRuntimeProviderAdapter(provider_id="local-m1", base_url=base_url)
        executor_registry.bind("local-m1", adapter)
        evidence["provider_adapter"] = type(adapter).__name__
        evidence["local_runtime_reachable"] = await adapter.check_health()

        ai_adapter = system.execution_engine._ai
        ai_adapter._executor = executor_registry
        ai_adapter._router = system.kernel.model_router.router_service
        evidence["model_allocation"] = "ModelRouterService"

        # ---- 3. Direct provider round trip through canonical messages ------
        direct = await adapter.execute(
            ExecutionRequest(
                payload={
                    "messages": [
                        {"role": "system", "content": "You are an AutoForge worker."},
                        {"role": "user", "content": "ping"},
                    ]
                }
            ),
            ExecutionTarget(model_id="local-runtime-1", provider_id="local-m1"),
        )
        evidence["direct_provider_round_trip_ok"] = bool(direct.get("content"))

        # ---- 4. Real engineering execution through the canonical path ------
        task_def = TaskDefinition(
            task_id="t-gate4b-e2e",
            name="Implement calculator add function",
            task_type="coding",
            description="Add a correct add(a, b) function and verify it.",
            input_data={
                "files": [{"path": "output.py", "content": "print(1)\n"}],
                "commands": [[sys.executable, "output.py"]],
                "fallback_policy": "allow_fallback",
            },
        )
        workflow = WorkflowDefinition(name="Gate 4B E2E", tasks=[task_def])
        handle = system.workflow_engine.submit(workflow)
        completed = await system.execution_engine.run_workflow_to_completion(handle)

        evidence["workflow_status"] = str(
            getattr(completed.status, "value", completed.status)
        )

        # ---- 5. Content-free Context Engineering observability -------------
        obs = ai_adapter.last_prompt_observability
        evidence["prompt_observability"] = obs
        evidence["ce_selected_context_count"] = obs.get("selected_context_count")
        evidence["ce_budget_source"] = obs.get("budget_source")
        evidence["ce_context_window_tokens"] = obs.get("context_window_tokens")
        evidence["prompt_assembly_path"] = obs.get("prompt_assembly_path")

        execution_results = ai_adapter.execution_history
        evidence["model_executions"] = len(execution_results)
        if execution_results:
            last = execution_results[-1]
            evidence["last_allocation"] = {
                "model_id": last.model_id,
                "provider_id": last.provider_id,
                "attempts": last.attempts,
                "failovers": last.failovers,
                "latency_ms": round(last.latency_ms or 0.0, 2),
            }

        # ---- 6. What the local runtime actually received ------------------
        # Ignore the direct round-trip probe (call 0) and the /models listing;
        # examine the calls made by the real engineering execution.
        chat_calls = [
            r for r in CAPTURED_REQUESTS if "messages" in r and r.get("messages")
        ]
        evidence["local_runtime_chat_calls"] = len(chat_calls)
        if len(chat_calls) > 1:
            msgs = chat_calls[1].get("messages", [])
            evidence["runtime_received_turns"] = len(msgs)
            evidence["runtime_received_roles"] = [m.get("role") for m in msgs]
            # Prove the canonical CE sections actually reached the wire.
            body = "\n".join(str(m.get("content", "")) for m in msgs)
            evidence["runtime_saw_canonical_sections"] = sorted(
                marker
                for marker in (
                    "## Project Context",
                    "## Task",
                    "# Task:",
                    "## Verification Context",
                )
                if marker in body
            )
            evidence["canonical_context_reached_runtime"] = (
                "## Task" in body or "## Project Context" in body
            )

        # ---- 7. Artifacts / durable result --------------------------------
        evidence["artifact_root_exists"] = (workspace / "artifacts").exists()
        try:
            evidence["durable_artifacts_registered"] = len(
                list(system.durable_catalog.find_by_task(task_def.task_id))
            )
        except Exception as exc:  # noqa: BLE001 - evidence is best-effort
            evidence["durable_artifacts_error"] = str(exc)

        await system.shutdown()
    finally:
        server.shutdown()

    out = REPO / "context-engineering-gate4b" / "e2e_runtime_evidence.json"
    out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps(evidence, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
