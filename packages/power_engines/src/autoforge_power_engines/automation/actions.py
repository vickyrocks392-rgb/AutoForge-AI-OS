"""Declarative Action Registry, Built-in Safe Operations & Security Boundaries (18-COMMERCIAL-C)."""

from __future__ import annotations

import ast
import ipaddress
import json
import logging
import math
import os
import re
import urllib.parse
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import requests

from autoforge_power_engines.automation.spec import ActionRiskLevel, ActionSpec

logger = logging.getLogger("autoforge.power_engines.automation.actions")


# ── Security Exceptions ────────────────────────────────────────────────────────

class ActionSecurityError(RuntimeError):
    """Base error for security policy violations during action execution."""


class WorkspaceSecurityError(ActionSecurityError):
    """Raised when an action attempts an illegal path traversal or symlink escape."""


class SSRFSecurityError(ActionSecurityError):
    """Raised when an outbound HTTP request targets a forbidden internal network or cloud metadata IP."""


# ── Path & SSRF Security Validators ───────────────────────────────────────────

def validate_workspace_path(
    requested_path: str | Path,
    workspace_root: str | Path,
    allow_create: bool = False,
) -> Path:
    """
    Strictly confines file system operations to the customer workspace root.
    Rejects directory traversal (../), absolute root escaping, and symlink breakout.
    """
    root = Path(workspace_root).resolve()
    target = (root / requested_path).resolve()

    # Reject traversal outside root
    if not target.is_relative_to(root):
        raise WorkspaceSecurityError(
            f"Path traversal denied: '{requested_path}' resolves outside workspace boundary '{root}'"
        )

    # Check for forbidden sensitive file extensions/names
    forbidden_files = {".env", ".git", ".ssh", "id_rsa", "credentials", ".aws", "shadow", "passwd"}
    for part in target.parts:
        if part.lower() in forbidden_files:
            raise WorkspaceSecurityError(f"Access to sensitive target denied: '{part}'")

    # Symlink escape verification
    if target.exists() and target.is_symlink():
        sym_target = target.resolve()
        if not sym_target.is_relative_to(root):
            raise WorkspaceSecurityError(
                f"Symlink breakout denied: '{target.name}' points outside workspace to '{sym_target}'"
            )

    return target


def validate_outbound_url(url: str, allow_private_networks: bool = False) -> str:
    """
    Validates outbound URLs to prevent Server-Side Request Forgery (SSRF).
    Denies loopback (127.0.0.1), link-local cloud metadata (169.254.169.254),
    and RFC 1918 private subnets unless allow_private_networks is True.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFSecurityError(f"Prohibited URL scheme '{parsed.scheme}'. Only http and https permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("URL is missing a valid hostname.")

    # Explicit deny for localhost and metadata IPs
    forbidden_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"}
    if hostname.lower() in forbidden_hosts and not allow_private_networks:
        raise SSRFSecurityError(f"Outbound request to local/metadata host denied: '{hostname}'")

    # IP address range validation
    try:
        ip = ipaddress.ip_address(hostname)
        if not allow_private_networks:
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise SSRFSecurityError(f"Outbound request to private/reserved IP denied: '{hostname}'")
    except ValueError:
        # It's a domain name (not raw IP)
        pass

    return url


# ── AST-Safe Calculator ───────────────────────────────────────────────────────

class SafeCalculatorEvaluator(ast.NodeVisitor):
    """
    Evaluates pure mathematical expressions using AST.
    Zero use of Python eval() or exec().
    """
    SAFE_OPERATORS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b if b != 0 else float("inf"),
        ast.FloorDiv: lambda a, b: a // b if b != 0 else 0,
        ast.Mod: lambda a, b: a % b if b != 0 else 0,
        ast.Pow: lambda a, b: a ** b if b <= 100 else float("inf"),
        ast.USub: lambda a: -a,
        ast.UAdd: lambda a: a,
    }

    SAFE_FUNCTIONS = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "math_sqrt": math.sqrt,
        "math_floor": math.floor,
        "math_ceil": math.ceil,
    }

    def evaluate(self, expr: str, variables: Optional[Dict[str, Any]] = None) -> Any:
        self.variables = variables or {}
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid math syntax: {e}")
        return self.visit(tree.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type in math expression: {type(node.value)}")

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in self.variables:
            val = self.variables[node.id]
            if isinstance(val, (int, float)):
                return val
            raise ValueError(f"Variable '{node.id}' must be numeric, got {type(val)}")
        raise ValueError(f"Undefined variable in math expression: '{node.id}'")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        op_type = type(node.op)
        if op_type not in self.SAFE_OPERATORS:
            raise ValueError(f"Unsupported math operator: {op_type.__name__}")
        left = self.visit(node.left)
        right = self.visit(node.right)
        return self.SAFE_OPERATORS[op_type](left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op_type = type(node.op)
        if op_type not in self.SAFE_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = self.visit(node.operand)
        return self.SAFE_OPERATORS[op_type](operand)

    def visit_Call(self, node: ast.Call) -> Any:
        if isinstance(node.func, ast.Name):
            fname = node.func.id
            if fname in self.SAFE_FUNCTIONS:
                args = [self.visit(a) for a in node.args]
                return self.SAFE_FUNCTIONS[fname](*args)
        raise ValueError("Function calls other than safe math functions are prohibited.")

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Prohibited AST node in math evaluation: {type(node).__name__}")


def safe_eval_expression(expr: str, variables: Optional[Dict[str, Any]] = None) -> Any:
    return SafeCalculatorEvaluator().evaluate(expr, variables)


# ── Action Base & Implementation ──────────────────────────────────────────────

class Action(ABC):
    """Abstract executable action interface."""

    def __init__(self, name: str, risk_level: ActionRiskLevel = ActionRiskLevel.SAFE_TRANSFORM):
        self.name = name
        self.risk_level = risk_level

    @abstractmethod
    def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the action deterministically given inputs and runtime context."""


class HTTPRequestAction(Action):
    """
    Outbound HTTP request action with SSRF protection, timeout, and response parsing.
    """

    def __init__(self, allow_private_networks: bool = False):
        super().__init__("http_request", ActionRiskLevel.EXTERNAL_CALL)
        self.allow_private_networks = allow_private_networks

    def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        url = parameters.get("url")
        if not url:
            raise ValueError("HTTPRequestAction requires 'url' parameter.")

        # Security check
        validate_outbound_url(url, allow_private_networks=self.allow_private_networks)

        method = parameters.get("method", "GET").upper()
        headers = parameters.get("headers", {})
        json_body = parameters.get("json_body")
        timeout = float(parameters.get("timeout", 15.0))

        # Block dangerous or forbidden methods
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise ValueError(f"Unsupported HTTP method: {method}")

        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )

        try:
            resp_data = resp.json()
        except Exception:
            resp_data = resp.text

        return {
            "status_code": resp.status_code,
            "success": 200 <= resp.status_code < 300,
            "data": resp_data,
            "headers": dict(resp.headers),
        }


class TransformDataAction(Action):
    """
    Deterministic data transformation, mapping, and projection without eval.
    """

    def __init__(self):
        super().__init__("transform_data", ActionRiskLevel.SAFE_TRANSFORM)

    def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        data = parameters.get("data", {})
        mapping = parameters.get("mapping", {})  # target_key -> source_key or constant
        filter_keys = parameters.get("filter_keys")  # list of keys to keep
        compute = parameters.get("compute", {})  # target_key -> math expression over data

        result = dict(data) if isinstance(data, dict) else {"raw": data}

        # Apply mapping
        if mapping:
            transformed = {}
            for target_k, source_k in mapping.items():
                if isinstance(source_k, str) and source_k in result:
                    transformed[target_k] = result[source_k]
                else:
                    transformed[target_k] = source_k
            result = transformed

        # Apply filtering
        if filter_keys:
            result = {k: v for k, v in result.items() if k in filter_keys}

        # Apply safe compute
        if compute:
            for target_k, expr in compute.items():
                if isinstance(expr, str):
                    result[target_k] = safe_eval_expression(expr, result)

        return {"result": result}


class SafeCalculatorAction(Action):
    """
    Pure arithmetic evaluation action.
    """

    def __init__(self):
        super().__init__("safe_calculator", ActionRiskLevel.READ_ONLY)

    def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        expr = parameters.get("expression")
        if not expr:
            raise ValueError("SafeCalculatorAction requires 'expression' parameter.")
        variables = parameters.get("variables", {})
        val = safe_eval_expression(expr, variables)
        return {"expression": expr, "result": val}


class FileOperationAction(Action):
    """
    Workspace-confined file operations (read, write, append, exists, list).
    """

    def __init__(self, workspace_root: Optional[str] = None):
        super().__init__("file_operation", ActionRiskLevel.MUTATING_DATA)
        self.workspace_root = workspace_root or "./data/workspace"

    def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        op = parameters.get("operation", "read").lower()
        rel_path = parameters.get("path")
        if not rel_path:
            raise ValueError("FileOperationAction requires 'path' parameter.")

        target = validate_workspace_path(rel_path, self.workspace_root, allow_create=(op in ("write", "append")))

        if op == "read":
            if not target.exists():
                raise FileNotFoundError(f"File not found: {rel_path}")
            return {"path": rel_path, "content": target.read_text(encoding="utf-8")}

        elif op == "write":
            content = parameters.get("content", "")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"path": rel_path, "bytes_written": len(content.encode("utf-8")), "status": "written"}

        elif op == "append":
            content = parameters.get("content", "")
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
            return {"path": rel_path, "status": "appended"}

        elif op == "exists":
            return {"path": rel_path, "exists": target.exists()}

        elif op == "list":
            if not target.exists() or not target.is_dir():
                return {"path": rel_path, "files": []}
            files = [f.name for f in target.iterdir()]
            return {"path": rel_path, "files": files}

        else:
            raise ValueError(f"Unsupported file operation: {op}")


class DocumentLookupAction(Action):
    """
    Keyword search across customer documents in the workspace.
    """

    def __init__(self, workspace_root: Optional[str] = None):
        super().__init__("document_lookup", ActionRiskLevel.READ_ONLY)
        self.workspace_root = workspace_root or "./data/workspace"

    def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        query = parameters.get("query", "").strip().lower()
        if not query:
            return {"query": "", "results": []}

        root = Path(self.workspace_root).resolve()
        if not root.exists():
            return {"query": query, "results": []}

        words = query.split()
        results = []

        for p in root.glob("**/*"):
            if p.is_file() and p.suffix.lower() in (".txt", ".md", ".json", ".csv"):
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    matches = [w for w in words if w in text.lower()]
                    if matches:
                        # Extract snippet
                        snippet = text[:200].replace("\n", " ")
                        results.append({
                            "file": str(p.relative_to(root)),
                            "matched_words": matches,
                            "snippet": snippet,
                        })
                except Exception:
                    pass

        return {"query": query, "results": results[:10]}


class SendOutputAction(Action):
    """
    Formats and routes structured workflow output or notification.
    """

    def __init__(self):
        super().__init__("send_output", ActionRiskLevel.SAFE_TRANSFORM)

    def execute(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        output_data = parameters.get("output", {})
        channel = parameters.get("channel", "audit_log")
        return {
            "channel": channel,
            "output": output_data,
            "status": "delivered",
        }


# ── Action Registry ───────────────────────────────────────────────────────────

class ActionRegistry:
    """Registry managing available, authorized workflow actions."""

    def __init__(self, workspace_root: str = "./data/workspace", allow_private_networks: bool = False):
        self.workspace_root = workspace_root
        self._actions: Dict[str, Action] = {}

        # Register default commercial safe action set
        self.register(HTTPRequestAction(allow_private_networks=allow_private_networks))
        self.register(TransformDataAction())
        self.register(SafeCalculatorAction())
        self.register(FileOperationAction(workspace_root=workspace_root))
        self.register(DocumentLookupAction(workspace_root=workspace_root))
        self.register(SendOutputAction())

    def register(self, action: Action) -> None:
        self._actions[action.name] = action

    def get(self, action_name: str) -> Optional[Action]:
        return self._actions.get(action_name)

    def list_actions(self) -> List[str]:
        return list(self._actions.keys())
