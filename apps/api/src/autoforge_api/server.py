"""
Local-First HTTP Server & REST API Router for AutoForge AI OS.
Serves the Product Experience and acts as the application boundary.
"""

from __future__ import annotations
import json
import os
import urllib.parse
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any, Dict, Optional

from autoforge_api.auth import ApiAuthError, ApiAuthenticator, auth_is_disabled
from autoforge_api.models import WorkspaceMode
from autoforge_api.redaction import redact_secrets
from autoforge_api.service import AutoForgeApiService

#: API paths readable without authentication. Deliberately minimal: read-only
#: liveness/metadata only. Every other /api path requires an authenticated caller.
PUBLIC_API_PATHS: frozenset[str] = frozenset({"/api/system/status"})


def _extract_project_id(path: str) -> str | None:
    """Resolve the project identity encoded in an API path, if any.

    Runs BEFORE the resource is fetched or mutated so authorization can be
    evaluated against the real target rather than a caller-supplied claim.
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "projects":
        return urllib.parse.unquote(parts[2])
    return None



class AutoForgeRequestHandler(SimpleHTTPRequestHandler):
    """
    HTTP Request Handler serving both the static web frontend and the REST API boundary.
    """

    service: AutoForgeApiService = None
    web_dir: str = ""
    authenticator: Any = None

    # ── Authentication / Authorization boundary (SHC-02) ───────────────────

    def _authenticate_request(self, path: str):
        """Single canonical authentication + project-authorization gate.

        Called at the top of every /api verb handler. Returns the authenticated
        caller, or ``None`` after having already written an error response.
        """
        if self.authenticator is None:
            self._send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE, "API authentication is not configured."
            )
            return None
        try:
            caller = self.authenticator.authenticate(self.headers)
        except ApiAuthError as exc:
            self._send_error_json(HTTPStatus(exc.status), exc.message)
            return None
        except Exception:
            self._send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication failed.")
            return None

        try:
            self.authenticator.authorize_project(caller, _extract_project_id(path))
        except ApiAuthError as exc:
            self._send_error_json(HTTPStatus(exc.status), exc.message)
            return None
        return caller

    def __init__(self, *args, **kwargs):
        if not self.web_dir:
            # Set default web_dir to apps/web/public
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
            self.web_dir = os.path.join(base, "apps", "web", "public")
        super().__init__(*args, directory=self.web_dir, **kwargs)

    def _send_json(self, status: HTTPStatus, data: Any) -> None:
        sanitized = redact_secrets(data)
        payload = json.dumps(sanitized, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message, "status": status.value})

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query_params = urllib.parse.parse_qs(parsed.query)

        if not path.startswith("/api"):
            # Serve static files from web_dir
            if path == "" or path == "/":
                self.path = "/index.html"
            return super().do_GET()

        # SHC-02: authentication gate. Public allowlist is read-only status only.
        if path not in PUBLIC_API_PATHS and self._authenticate_request(path) is None:
            return

        try:
            if path == "/api/system/status":
                status = self.service.get_system_status()
                self._send_json(HTTPStatus.OK, status.model_dump())

            elif path == "/api/projects":
                import asyncio
                projects = asyncio.run(self.service.list_projects())
                self._send_json(HTTPStatus.OK, [p.model_dump() for p in projects])

            elif path == "/api/projects/output" or (path.startswith("/api/projects/") and path.endswith("/output")):
                parts = path.split("/")
                p_id = parts[3] if len(parts) > 4 else query_params.get("project_id", ["default"])[0]
                output = self.service.get_project_output(project_id=p_id)
                self._send_json(HTTPStatus.OK, output.model_dump())

            elif path == "/api/workforce":
                workers = self.service.list_workforce()
                self._send_json(HTTPStatus.OK, [w.model_dump() for w in workers])

            elif path == "/api/workflows":
                summary = self.service.get_workflows_summary()
                self._send_json(HTTPStatus.OK, summary)

            elif path == "/api/executions":
                summary = self.service.get_executions_summary()
                self._send_json(HTTPStatus.OK, summary)

            elif path == "/api/reviews":
                summary = self.service.get_reviews_summary()
                self._send_json(HTTPStatus.OK, summary)

            elif path == "/api/artifacts":
                summary = self.service.get_artifacts_summary()
                self._send_json(HTTPStatus.OK, summary)

            elif path == "/api/legacy":
                workspace = self.service.get_legacy_workspace()
                self._send_json(HTTPStatus.OK, workspace.model_dump())

            elif path == "/api/infrastructure":
                summary = self.service.get_infrastructure_summary()
                self._send_json(HTTPStatus.OK, summary)

            elif path == "/api/activity":
                limit = int(query_params.get("limit", ["50"])[0])
                worker_id = query_params.get("worker_id", [None])[0]
                workflow_id = query_params.get("workflow_id", [None])[0]
                acts = self.service.get_agent_activity(limit=limit, worker_id=worker_id, workflow_id=workflow_id)
                self._send_json(HTTPStatus.OK, [a.model_dump() for a in acts])

            elif path == "/api/executions/drilldown" or (path.startswith("/api/executions/") and path.endswith("/drilldown")):
                exec_id = path.split("/")[3] if len(path.split("/")) > 4 else query_params.get("execution_id", ["exec-arch-001"])[0]
                drilldown = self.service.get_execution_drilldown(execution_id=exec_id)
                self._send_json(HTTPStatus.OK, drilldown.model_dump())

            elif path == "/api/models":
                models = self.service.list_models()
                self._send_json(HTTPStatus.OK, [m.model_dump() for m in models])

            elif path == "/api/nodes":
                nodes = self.service.list_nodes_detail()
                self._send_json(HTTPStatus.OK, [n.model_dump() for n in nodes])

            elif path == "/api/knowledge/pipeline":
                stages = self.service.get_rag_pipeline()
                self._send_json(HTTPStatus.OK, [s.model_dump() for s in stages])

            elif path == "/api/knowledge/documents":
                docs = self.service.get_knowledge_documents()
                self._send_json(HTTPStatus.OK, [d.model_dump() for d in docs])

            elif path == "/api/knowledge/chunks":
                doc_id = query_params.get("document_id", [None])[0]
                chunks = self.service.get_knowledge_chunks(document_id=doc_id)
                self._send_json(HTTPStatus.OK, [c.model_dump() for c in chunks])

            elif path == "/api/knowledge/telemetry":
                telemetry = self.service.get_knowledge_telemetry()
                self._send_json(HTTPStatus.OK, telemetry.model_dump())

            elif path == "/api/knowledge/traces":
                traces = self.service.get_knowledge_worker_traces()
                self._send_json(HTTPStatus.OK, [t.model_dump() for t in traces])

            elif path == "/api/hitl/approvals":
                import asyncio
                approvals = asyncio.run(self.service.list_pending_approvals())
                self._send_json(HTTPStatus.OK, [a.model_dump() for a in approvals])

            elif path == "/api/observability/dashboards":
                dashboards = self.service.get_observability_dashboards()
                self._send_json(HTTPStatus.OK, dashboards)

            elif path == "/api/observability/current-node":
                cur = self.service.get_current_node()
                self._send_json(HTTPStatus.OK, cur.model_dump())

            elif path == "/api/observability/node":
                node_id = query_params.get("node_id", [None])[0]
                node_obs = self.service.get_node_observability(node_id=node_id)
                self._send_json(HTTPStatus.OK, node_obs.model_dump())

            elif path == "/api/observability/fleet":
                fleet_obs = self.service.get_fleet_observability()
                self._send_json(HTTPStatus.OK, fleet_obs.model_dump())


            elif path == "/api/experience":
                experience = self.service.get_engineering_experience()
                self._send_json(HTTPStatus.OK, experience)

            elif path == "/api/power-engines/deliveries":
                delivs = self.service.list_power_engine_deliveries()
                self._send_json(HTTPStatus.OK, delivs)

            elif path == "/api/self-improvement":
                si = self.service.get_self_improvement_center()
                self._send_json(HTTPStatus.OK, si.model_dump())

            elif path == "/api/settings":
                settings = {
                    "platform": "AutoForge AI OS",
                    "mode": self.service._workspace_mode.value,
                    "default_local_node": "local_m1",
                    "telemetry_sampling_rate": 1.0,
                    "governance_mode": "strict_hitl",
                    "secrets": {"api_key": "sk-autoforge-secret-12345"}, # Will be automatically redacted
                }
                self._send_json(HTTPStatus.OK, settings)

            elif path.startswith("/api/projects/") and path.endswith("/runtime"):
                proj_id = path.split("/")[3]
                rt = self.service.get_project_app_runtime(proj_id)
                self._send_json(HTTPStatus.OK, rt)

            elif path.startswith("/api/projects/") and path.endswith("/export"):
                proj_id = path.split("/")[3]
                exp = self.service.export_project_archive(proj_id)
                self._send_json(HTTPStatus.OK, exp)

            elif path.startswith("/api/projects/") and path.endswith("/download"):
                proj_id = path.split("/")[3]
                exp = self.service.export_project_archive(proj_id)
                arch_path = exp.get("absolute_path")
                if arch_path and os.path.isfile(arch_path):
                    with open(arch_path, "rb") as f:
                        file_bytes = f.read()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/gzip")
                    self.send_header("Content-Length", str(len(file_bytes)))
                    self.send_header("Content-Disposition", f'attachment; filename="{exp["filename"]}"')
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(file_bytes)
                else:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "Archive file not found.")

            elif path.startswith("/api/projects/") and path.endswith("/download-source"):
                proj_id = path.split("/")[3]
                dist_dir = os.path.join(self.service.build_engine.dist_dir, proj_id)
                src_tar = os.path.join(dist_dir, f"autoforge-src-{proj_id}.tar.gz")
                if os.path.isfile(src_tar):
                    with open(src_tar, "rb") as f:
                        file_bytes = f.read()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/gzip")
                    self.send_header("Content-Length", str(len(file_bytes)))
                    self.send_header("Content-Disposition", f'attachment; filename="autoforge-src-{proj_id}.tar.gz"')
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(file_bytes)
                else:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "Source archive not found.")

            elif path == "/api/toolchains":
                toolchains = self.service.build_engine.toolchain_mgr.discover_toolchains()
                self._send_json(HTTPStatus.OK, [t.model_dump() for t in toolchains])

            elif path == "/api/auth/me":
                user = {
                    "user_id": "operator_admin_01",
                    "name": "Platform Operator",
                    "role": "PLATFORM_ADMIN",
                    "permissions": ["system:read", "system:write", "hitl:approve", "projects:create"],
                }
                self._send_json(HTTPStatus.OK, user)

            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"API endpoint '{path}' not found.")

        except Exception as e:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not path.startswith("/api"):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid request.")
            return

        # SHC-02: every mutating endpoint requires an authenticated caller.
        body_project = None
        if self._authenticate_request(path) is None:
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON body.")
            return

        try:
            if path == "/api/system/mode":
                mode_str = data.get("mode", "GREENFIELD")
                try:
                    mode = WorkspaceMode(mode_str)
                    new_mode = self.service.set_workspace_mode(mode)
                    self._send_json(HTTPStatus.OK, {"mode": new_mode.value})
                except ValueError:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, f"Invalid mode '{mode_str}'.")

            elif path == "/api/capabilities/execute":
                from autoforge_api.models import CapabilityExecutionRequest
                req_cap = CapabilityExecutionRequest(**data)
                res = self.service.execute_capability(req_cap)
                self._send_json(HTTPStatus.OK, res.model_dump())

            elif path == "/api/intent/analyze":
                from autoforge_api.models import IntentAnalysisRequest
                req_intent = IntentAnalysisRequest(**data)
                analysis = self.service.analyze_intent(req_intent)
                self._send_json(HTTPStatus.OK, analysis.model_dump())

            elif path == "/api/intent/execute":
                from autoforge_api.models import IntentExecutionRequest
                req_exec = IntentExecutionRequest(**data)
                res = self.service.execute_intent_pipeline(req_exec)
                self._send_json(HTTPStatus.OK, res.model_dump())

            elif path == "/api/intent/approve-stack":
                from autoforge_api.models import TechStackApprovalRequest
                req_app = TechStackApprovalRequest(**data)
                res = self.service.approve_tech_stack(req_app)
                self._send_json(HTTPStatus.OK, res)

            elif path == "/api/projects":
                import asyncio
                name = data.get("name")
                if not name:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "Project name is required.")
                    return
                description = data.get("description", "")
                template = data.get("template", "greenfield")
                proj = asyncio.run(self.service.create_project(name=name, description=description, template=template))
                self._send_json(HTTPStatus.CREATED, proj.model_dump())

            elif path == "/api/projects/upload":
                from autoforge_api.models import ProjectUploadRequest
                req_up = ProjectUploadRequest(**data)
                res = self.service.upload_project(req_up)
                self._send_json(HTTPStatus.CREATED, res.model_dump())

            elif path.startswith("/api/projects/") and (path.endswith("/run") or path.endswith("/launch")):
                proj_id = path.split("/")[3]
                res = self.service.launch_project_app(proj_id)
                self._send_json(HTTPStatus.OK, res)

            elif path.startswith("/api/projects/") and path.endswith("/stop"):
                proj_id = path.split("/")[3]
                res = self.service.stop_project_app(proj_id)
                self._send_json(HTTPStatus.OK, res)

            elif path == "/api/knowledge/query":
                q = data.get("query", "")
                top_k = int(data.get("top_k", 5))
                res = self.service.query_knowledge(q, top_k=top_k)
                self._send_json(HTTPStatus.OK, res)

            elif path == "/api/power-engines/rag/execute":
                res = self.service.execute_rag_power_engine(data)
                self._send_json(HTTPStatus.OK, res)

            elif path == "/api/hitl/approvals":
                import asyncio
                action_type = data.get("action_type")
                resource = data.get("target_resource", "*")
                requester = data.get("requester", "operator")
                evidence = data.get("evidence", "Manual trigger")
                risk = data.get("risk_level", "high")
                if not action_type:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "action_type is required.")
                    return
                app = asyncio.run(
                    self.service.request_consequential_approval(
                        action_type_str=action_type,
                        resource=resource,
                        requester=requester,
                        evidence=evidence,
                        risk_level=risk,
                        metadata=data.get("metadata", {}),
                    )
                )
                self._send_json(HTTPStatus.CREATED, app.model_dump())

            elif path == "/api/hitl/decision":
                import asyncio
                app_id = data.get("approval_id")
                decision = data.get("decision")
                actor_id = data.get("actor_id", "operator_admin_01")
                feedback = data.get("feedback", "")
                if not app_id or not decision:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "approval_id and decision are required.")
                    return
                try:
                    res = asyncio.run(
                        self.service.submit_approval_decision(
                            approval_id=app_id,
                            decision=decision,
                            actor_id=actor_id,
                            feedback=feedback,
                        )
                    )
                    self._send_json(HTTPStatus.OK, res.model_dump())
                except PermissionError as pe:
                    self._send_error_json(HTTPStatus.FORBIDDEN, str(pe))
                except KeyError as ke:
                    self._send_error_json(HTTPStatus.NOT_FOUND, str(ke))
                except ValueError as ve:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, str(ve))

            elif path == "/api/models":
                from autoforge_api.models import ModelCreateOrUpdateRequest
                req_model = ModelCreateOrUpdateRequest(**data)
                created = self.service.create_model(req_model, actor_id=data.get("actor_id", "operator_admin_01"))
                self._send_json(HTTPStatus.CREATED, created.model_dump())

            elif path.startswith("/api/models/") and path.endswith("/status"):
                parts = path.split("/")
                m_id = parts[3]
                status_val = data.get("status", "active")
                updated = self.service.set_model_status(m_id, status_val, actor_id=data.get("actor_id", "operator_admin_01"))
                self._send_json(HTTPStatus.OK, updated.model_dump())

            elif path == "/api/nodes":
                from autoforge_api.models import NodeDetailResponse
                req_node = NodeDetailResponse(**data)
                created_node = self.service.create_node(req_node, actor_id=data.get("actor_id", "operator_admin_01"))
                self._send_json(HTTPStatus.CREATED, created_node.model_dump())

            elif path.startswith("/api/nodes/") and path.endswith("/status"):
                parts = path.split("/")
                n_id = parts[3]
                status_val = data.get("status", "online")
                updated_node = self.service.set_node_status(n_id, status_val, actor_id=data.get("actor_id", "operator_admin_01"))
                self._send_json(HTTPStatus.OK, updated_node.model_dump())

            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"API POST endpoint '{path}' not found.")

        except Exception as e:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not path.startswith("/api"):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid request.")
            return

        # SHC-02: deletions require an authenticated caller.
        if self._authenticate_request(path) is None:
            return

        try:
            if path.startswith("/api/models/"):
                parts = path.split("/")
                m_id = parts[3]
                self.service.delete_model(m_id)
                self._send_json(HTTPStatus.OK, {"status": "deleted", "model_id": m_id})

            elif path.startswith("/api/nodes/"):
                parts = path.split("/")
                n_id = parts[3]
                self.service.delete_node(n_id)
                self._send_json(HTTPStatus.OK, {"status": "deleted", "node_id": n_id})

            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"API DELETE endpoint '{path}' not found.")

        except Exception as e:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))



def create_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    service: Optional[AutoForgeApiService] = None,
    web_dir: Optional[str] = None,
    authenticator: Optional[ApiAuthenticator] = None,
) -> HTTPServer:
    """
    Factory creating a configured HTTPServer instance with AutoForgeRequestHandler.

    SECURITY (SHC-02): an ``ApiAuthenticator`` is now mandatory. When none is
    supplied one is constructed from the certified ``SecurityPlatform``; if that
    also fails (e.g. no API key configured and auth not explicitly disabled) the
    server refuses to start rather than exposing an unauthenticated API.
    """
    svc = service or AutoForgeApiService()
    AutoForgeRequestHandler.service = svc
    if web_dir:
        AutoForgeRequestHandler.web_dir = web_dir

    auth = authenticator
    if auth is None:
        from autoforge_security.engine import SecurityPlatform

        auth = ApiAuthenticator(security_platform=SecurityPlatform())
    AutoForgeRequestHandler.authenticator = auth

    return HTTPServer((host, port), AutoForgeRequestHandler)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AutoForge AI OS Product Experience Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8787, help="Port to bind")
    parser.add_argument("--web-dir", default=None, help="Directory containing web assets")
    parser.add_argument(
        "--allow-insecure-dev-auth",
        action="store_true",
        help="Explicitly disable API authentication (local development only).",
    )
    args = parser.parse_args()

    if args.allow_insecure_dev_auth:
        import os

        os.environ["AUTOFORGE_API_AUTH_DISABLED"] = "1"
        print("WARNING: API authentication DISABLED — local development only.")

    print(f"Starting AutoForge AI OS Product Experience on http://{args.host}:{args.port}")
    server = create_server(host=args.host, port=args.port, web_dir=args.web_dir)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping AutoForge server.")
        server.server_close()

