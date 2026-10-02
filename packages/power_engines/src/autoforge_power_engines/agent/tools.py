"""Customer-owned Declarative Tool System and Built-in Security Sandbox (Phase 18-COMMERCIAL-B)."""

from __future__ import annotations

import ast
import ipaddress
import json
import logging
import math
import operator
import re
import socket
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests
from pydantic import BaseModel, Field

from autoforge_power_engines.agent.spec import AgentToolConfig, ToolRiskLevel

logger = logging.getLogger("autoforge.power_engines.agent.tools")


# ── Path Confinement & Workspace Jail ──────────────────────────────────────────

class WorkspaceSecurityError(PermissionError):
    """Raised when an operation breaches customer workspace isolation."""
    pass


class SSRFSecurityError(PermissionError):
    """Raised when an HTTP request attempts to scan or access private networks."""
    pass


def validate_workspace_path(file_path: str, workspace_root: Path) -> Path:
    """
    Confines all file operations strictly to the customer workspace directory.
    Rejects directory traversal (../), absolute root escapes, symlink escapes,
    and sensitive system directories (.ssh, .git, .env, credentials).
    """
    cleaned_input = file_path.strip()
    if not cleaned_input:
        raise WorkspaceSecurityError("Empty file path is invalid.")

    # Disallow suspicious markers immediately
    forbidden_tokens = ["..", ".ssh", ".git", ".env", "/etc/", "/var/", "/usr/", "~"]
    for token in forbidden_tokens:
        if token in cleaned_input.split("/"):
            raise WorkspaceSecurityError(f"Access denied: path contains forbidden token '{token}'.")

    ws_root = workspace_root.resolve()
    target_path = (ws_root / cleaned_input).resolve()

    # Verify target stays inside workspace root
    try:
        target_path.relative_to(ws_root)
    except ValueError:
        raise WorkspaceSecurityError(f"Directory traversal detected: '{file_path}' escapes workspace '{ws_root}'.")

    # Sensitive filenames check
    if target_path.name.startswith(".env") or target_path.name in ("id_rsa", "id_ed25519", "credentials"):
        raise WorkspaceSecurityError(f"Access denied to sensitive file '{target_path.name}'.")

    return target_path


def validate_outbound_url(url: str, allowed_domains: Optional[List[str]] = None, allow_private: bool = False) -> str:
    """
    Validates outbound HTTP URLs to block SSRF and local network scanning.
    Blocks 127.0.0.1, localhost, 169.254.169.254, RFC1918 private subnets,
    and resolves domain names to prevent DNS rebinding or private host resolution.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFSecurityError(f"Invalid scheme '{parsed.scheme}': only HTTP/HTTPS are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("URL missing valid hostname.")

    # Check against localhost and loopback names
    lowered_host = hostname.lower()
    if lowered_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "local"):
        if not allow_private:
            raise SSRFSecurityError(f"Access to localhost/loopback address '{hostname}' is prohibited.")

    # Check IP addresses
    try:
        ip = ipaddress.ip_address(hostname)
        if not allow_private:
            if ip.is_loopback:
                raise SSRFSecurityError(f"Loopback IP '{ip}' is prohibited.")
            if ip.is_private:
                raise SSRFSecurityError(f"Private network IP '{ip}' is prohibited.")
            if ip.is_link_local:
                raise SSRFSecurityError(f"Link-local IP '{ip}' is prohibited.")
            if ip.is_reserved:
                raise SSRFSecurityError(f"Reserved IP '{ip}' is prohibited.")
            if ip.is_unspecified:
                raise SSRFSecurityError(f"Unspecified IP '{ip}' is prohibited.")
    except ValueError:
        # Not a raw IP, domain name: check DNS resolution to prevent private IP targets
        if not allow_private:
            try:
                addr_info = socket.getaddrinfo(hostname, None)
                for item in addr_info:
                    resolved_ip_str = item[4][0]
                    try:
                        resolved_ip = ipaddress.ip_address(resolved_ip_str)
                        if (
                            resolved_ip.is_loopback
                            or resolved_ip.is_private
                            or resolved_ip.is_link_local
                            or resolved_ip.is_reserved
                            or resolved_ip.is_unspecified
                        ):
                            raise SSRFSecurityError(
                                f"Domain '{hostname}' resolved to prohibited IP '{resolved_ip}'."
                            )
                    except ValueError:
                        pass
            except socket.gaierror:
                pass  # Resolution failure will be handled on connection

    # Optional domain whitelist
    if allowed_domains:
        if not any(lowered_host == d.lower() or lowered_host.endswith("." + d.lower()) for d in allowed_domains):
            raise SSRFSecurityError(f"Domain '{hostname}' is not in allowed domains whitelist.")

    return url


# ── AST Safe Math Evaluator ───────────────────────────────────────────────────

_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "pi": math.pi,
    "e": math.e,
}


def safe_eval_expression(expr: str) -> float | int:
    """
    Evaluates mathematical expressions safely using Python's AST.
    Strictly forbids dangerous eval, builtins, variable assignment, and code execution.
    """
    clean_expr = expr.strip()
    if not clean_expr:
        raise ValueError("Expression cannot be empty.")
    if len(clean_expr) > 200:
        raise ValueError("Expression length exceeds 200 characters.")

    try:
        node = ast.parse(clean_expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid math syntax: {e.msg}")

    def _eval_node(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return _eval_node(n.body)
        elif isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float)):
                return n.value
            raise ValueError(f"Unsupported constant type: {type(n.value)}")
        elif isinstance(n, ast.BinOp):
            op_type = type(n.op)
            if op_type not in _SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            left = _eval_node(n.left)
            right = _eval_node(n.right)
            # Guard against giant powers causing DOS
            if op_type is ast.Pow:
                if isinstance(right, (int, float)) and (right > 100 or right < -100):
                    raise ValueError("Exponent too large (must be between -100 and 100).")
            return _SAFE_OPERATORS[op_type](left, right)
        elif isinstance(n, ast.UnaryOp):
            op_type = type(n.op)
            if op_type not in _SAFE_OPERATORS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            operand = _eval_node(n.operand)
            return _SAFE_OPERATORS[op_type](operand)
        elif isinstance(n, ast.Name):
            if n.id in _SAFE_FUNCTIONS:
                return _SAFE_FUNCTIONS[n.id]
            raise ValueError(f"Undefined math variable or function: '{n.id}'")
        elif isinstance(n, ast.Call):
            func = _eval_node(n.func)
            args = [_eval_node(arg) for arg in n.args]
            if callable(func):
                return func(*args)
            raise ValueError("Call target is not callable.")
        else:
            raise ValueError(f"Unsupported syntax construct: {type(n).__name__}")

    res = _eval_node(node)
    if isinstance(res, (int, float)):
        return res
    raise ValueError(f"Expression did not evaluate to a number: {res}")


# ── Built-in Tool Implementations ─────────────────────────────────────────────

def tool_calculator(expression: str, **kwargs: Any) -> Dict[str, Any]:
    """Safe arithmetic calculation."""
    try:
        result = safe_eval_expression(expression)
        return {"expression": expression, "result": result, "status": "success"}
    except Exception as e:
        return {"expression": expression, "error": str(e), "status": "error"}


def tool_current_time(timezone_name: str = "UTC", **kwargs: Any) -> Dict[str, Any]:
    """Retrieve formatted current timestamp."""
    now = datetime.now(timezone.utc)
    return {
        "timestamp_utc": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S UTC"),
        "timezone": timezone_name,
        "status": "success",
    }


def tool_file_read(file_path: str, workspace_root: Optional[Path] = None, **kwargs: Any) -> Dict[str, Any]:
    """Read contents of a text file inside workspace."""
    root = workspace_root or Path("./data/workspace")
    try:
        target = validate_workspace_path(file_path, root)
        if not target.exists():
            return {"file_path": file_path, "error": f"File not found: {file_path}", "status": "error"}
        if not target.is_file():
            return {"file_path": file_path, "error": f"Path is not a regular file: {file_path}", "status": "error"}
        
        # Max file read limit: 1MB
        if target.stat().st_size > 1024 * 1024:
            return {"file_path": file_path, "error": "File size exceeds 1MB limit", "status": "error"}

        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "file_path": file_path,
            "content": content,
            "size_bytes": len(content.encode("utf-8")),
            "status": "success",
        }
    except Exception as e:
        return {"file_path": file_path, "error": str(e), "status": "error"}


def tool_document_lookup(query: str, workspace_root: Optional[Path] = None, **kwargs: Any) -> Dict[str, Any]:
    """Search for matching keywords across text files in customer workspace."""
    root = workspace_root or Path("./data/workspace")
    if not root.exists():
        return {"query": query, "matches": [], "status": "success", "note": "Workspace directory empty."}

    query_lower = query.lower().strip()
    words = [w for w in re.split(r"\W+", query_lower) if w]
    matches: List[Dict[str, Any]] = []

    for file_path in root.glob("**/*"):
        if file_path.is_file() and not file_path.name.startswith("."):
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                text_lower = text.lower()
                # Score matching words
                matched_words = [w for w in words if w in text_lower]
                if matched_words:
                    rel_path = str(file_path.relative_to(root))
                    # Extract sample matching snippets
                    first_pos = min(text_lower.find(w) for w in matched_words)
                    start = max(0, first_pos - 60)
                    end = min(len(text), first_pos + 120)
                    snippet = text[start:end].replace("\n", " ").strip()
                    matches.append({
                        "file": rel_path,
                        "matched_terms": matched_words,
                        "snippet": snippet,
                    })
            except Exception:
                continue

    return {
        "query": query,
        "total_matches": len(matches),
        "matches": matches[:10],
        "status": "success",
    }


def tool_structured_http(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0,
    allowed_domains: Optional[List[str]] = None,
    allow_private: bool = False,
    egress_policy: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Safe outbound HTTP request with SSRF and data-loss protections.

    SECURITY (SHC-05/SHC-06): ``validate_outbound_url`` remains the first line of
    defence (SSRF / DNS-rebinding). When an ``egress_policy`` is supplied, the
    canonical :class:`autoforge_security.egress.EgressPolicy` additionally
    applies destination *and* content control before transmission, so an approved
    destination still cannot receive secrets, credentials, or API keys.
    """
    try:
        safe_url = validate_outbound_url(url, allowed_domains=allowed_domains, allow_private=allow_private)
        m = method.upper()
        if m not in ("GET", "POST"):
            return {"error": f"Unsupported HTTP method '{m}'", "status": "error"}

        req_headers = headers or {}
        req_headers.setdefault("User-Agent", "CustomerAIAgent/1.0")

        # SHC-06: content control runs before any bytes leave the process.
        if egress_policy is not None:
            verdict = egress_policy.enforce(
                safe_url, headers=req_headers, params=params, body=json_body, method=m
            )
            from autoforge_security.egress import EgressDecision as _ED

            if verdict.decision is _ED.DENY:
                return {
                    "url": url,
                    "error": f"Egress policy denied the request: {verdict.reason}",
                    "status": "error",
                    "blocked_by": "egress_policy",
                }
            if verdict.decision is _ED.REDACT and verdict.sanitized_payload is not None:
                req_headers = verdict.sanitized_payload.get("headers") or req_headers
                params = verdict.sanitized_payload.get("params") or params
                json_body = verdict.sanitized_payload.get("body")

        # Follow redirects safely up to 3 hops, validating each destination against SSRF policies
        session = requests.Session()
        current_url = safe_url
        resp = None

        for _ in range(4):  # initial request + up to 3 redirects
            resp = session.request(
                method=m,
                url=current_url,
                headers=req_headers,
                params=params if current_url == safe_url else None,
                json=json_body if current_url == safe_url else None,
                timeout=min(timeout, 30.0),
                allow_redirects=False,
            )
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    break
                next_url = urllib.parse.urljoin(current_url, location)
                # Re-validate redirected destination URL
                current_url = validate_outbound_url(
                    next_url,
                    allowed_domains=allowed_domains,
                    allow_private=allow_private,
                )
            else:
                break

        if resp is None:
            return {"url": url, "error": "No HTTP response received.", "status": "error"}
        
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text[:2000]

        return {
            "url": current_url,
            "status_code": resp.status_code,
            "response": body,
            "status": "success" if resp.status_code < 400 else "error",
        }
    except Exception as e:
        return {"url": url, "error": str(e), "status": "error"}


# ── Declarative Tool Registry ─────────────────────────────────────────────────

def authorize_tool_call(
    tool_name: str,
    allowed_tools: Optional[List[str]] = None,
    *,
    registered_tools: Optional[Iterable[str]] = None,
) -> None:
    """Deterministically authorize a tool call immediately before execution.

    SECURITY (SHG-01): ``allowed_tools`` is a *capability declaration*, so it must
    be enforced at the moment of the side effect, not merely used to decide which
    tool schemas are advertised to the model. Before this check, an agent whose
    specification restricted it to ``["calculator"]`` could still execute
    ``structured_http`` and perform a real outbound network request, because
    ``execute_tool`` only verified that the tool was registered.

    This function is fail-closed:

    * unknown / unregistered tool -> ``PermissionError``
    * registered but not in the allowlist -> ``PermissionError``
    * ``allowed_tools=None`` means "no capability declaration available" and is
      treated as *deny all*; callers that legitimately want the full registry must
      pass an explicit allowlist.
    """
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise PermissionError("Tool name must be a non-empty string.")

    if registered_tools is not None and tool_name not in set(registered_tools):
        raise PermissionError(f"Tool '{tool_name}' is not registered.")

    if allowed_tools is None:
        raise PermissionError(
            f"No tool allowlist was supplied; refusing to execute '{tool_name}' "
            "without an explicit capability declaration."
        )

    if tool_name not in set(allowed_tools):
        raise PermissionError(
            f"Tool '{tool_name}' is not in the authorized tool allowlist "
            f"{sorted(allowed_tools)}. Call was blocked before execution."
        )


class ToolRegistry:
    """
    Isolated Tool Registry for Customer Agents.
    Enforces that the agent can ONLY invoke explicitly registered and authorized tools.
    """

    def __init__(self, workspace_root: Optional[Path | str] = None, allow_private_http: bool = False, egress_policy: Optional[Any] = None):
        self.workspace_root = Path(workspace_root or "./data/workspace").resolve()
        self.allow_private_http = allow_private_http
        # SHC-06: canonical content control for the outbound HTTP tool.
        self.egress_policy = egress_policy
        self._tools: Dict[str, AgentToolConfig] = {}
        self._handlers: Dict[str, Callable[..., Dict[str, Any]]] = {}

        # Register default initial commercial tools
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register_tool(
            AgentToolConfig(
                name="calculator",
                description="Evaluate a mathematical expression safely.",
                parameters={
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"]
                },
                risk_level=ToolRiskLevel.COMPUTATION,
            ),
            tool_calculator,
        )
        self.register_tool(
            AgentToolConfig(
                name="current_time",
                description="Get the current date and time.",
                parameters={
                    "type": "object",
                    "properties": {"timezone": {"type": "string", "default": "UTC"}},
                },
                risk_level=ToolRiskLevel.COMPUTATION,
            ),
            tool_current_time,
        )
        self.register_tool(
            AgentToolConfig(
                name="file_read",
                description="Read contents of a text file inside workspace.",
                parameters={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"]
                },
                risk_level=ToolRiskLevel.SAFE_READ,
            ),
            lambda file_path, **kw: tool_file_read(file_path, workspace_root=self.workspace_root, **kw),
        )
        self.register_tool(
            AgentToolConfig(
                name="document_lookup",
                description="Search for keywords across workspace text documents.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]
                },
                risk_level=ToolRiskLevel.SAFE_READ,
            ),
            lambda query, **kw: tool_document_lookup(query, workspace_root=self.workspace_root, **kw),
        )
        self.register_tool(
            AgentToolConfig(
                name="structured_http",
                description="Make an outbound HTTP request.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "method": {"type": "string", "default": "GET"},
                        "params": {"type": "object"},
                        "json_body": {"type": "object"}
                    },
                    "required": ["url"]
                },
                risk_level=ToolRiskLevel.NETWORK_IO,
            ),
            lambda **kw: tool_structured_http(
                allow_private=self.allow_private_http, egress_policy=self.egress_policy, **kw
            ),
        )

    def register_tool(
        self,
        config: AgentToolConfig,
        handler: Callable[..., Dict[str, Any]],
    ) -> None:
        """Registers a tool specification and its execution handler."""
        self._tools[config.name] = config
        self._handlers[config.name] = handler

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_tool_config(self, name: str) -> Optional[AgentToolConfig]:
        return self._tools.get(name)

    def get_schemas_for_tools(self, tool_names: List[str]) -> List[Dict[str, Any]]:
        """Converts registered tools to OpenAI / Ollama compatible function schema format."""
        schemas = []
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                })
        return schemas

    def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        allowed_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Executes a registered tool within isolated boundaries.

        SECURITY (SHG-01): ``allowed_tools`` is now enforced *at the execution
        point*, not only when advertising schemas to the model. Callers MUST pass
        the agent specification's ``allowed_tools``. Omitting it is treated as
        "no declared capability" and fails closed.

        Enforcement happens immediately before the side effect so that a model
        cannot reach an unauthorized tool by emitting a tool call directly.
        """
        try:
            authorize_tool_call(
                name,
                allowed_tools,
                registered_tools=self._tools.keys(),
            )
        except PermissionError as denied:
            return {"error": str(denied), "status": "error", "blocked_by": "tool_authorization"}

        handler = self._handlers[name]
        try:
            return handler(**arguments)
        except TypeError as te:
            return {"error": f"Invalid arguments for tool '{name}': {te}", "status": "error"}
        except Exception as ex:
            return {"error": f"Execution failure in tool '{name}': {ex}", "status": "error"}
