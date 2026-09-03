"""Helper utilities for the G.2 reconnaissance pipeline.

This module centralises deterministic scanning logic that does not
belong inside ReconnaissanceEngine itself:

* sanitisation of detected secrets
* deployment descriptor discovery
* database connection discovery with credential sanitisation
* dependency cycle detection
* architecture graph construction from source headers
* specialist tooling discovery
* document / business evidence discovery
* RAG boundary wiring
* context budget tracking
* throughput observation
* market research model wiring
* planning inputs factory
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from autoforge_modernization.reconnaissance.models import (
    ArchitectureEdge,
    ArchitectureGraph,
    ArchitectureNode,
    ArchitectureNodeKind,
    ArchitectureProvenance,
    BusinessEvidence,
    ComparisonOutcome,
    DatabaseInventory,
    DatabaseKind,
    DatabaseObject,
    DatabaseObjectKind,
    DeploymentSpec,
    DeploymentTarget,
    DetectedTechnology,
    DocumentDiscovery,
    EvidenceSource,
    EvidenceSourceKind,
    FactConfidence,
    SQLDialect,
    ProjectToolRequirement,
    ToolRequirementKind,
)

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^'\"\s]+"), "password"),
    (re.compile(r"(?i)(api[_-]?key|apikey|api[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]+"), "api_key"),
    (re.compile(r"(?i)(secret|client[_-]?secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]+"), "secret"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "bearer_token"),
    (re.compile(r"postgres(?:ql)?://[^:]+:[^@]+@"), "postgres_url"),
    (re.compile(r"mysql://[^:]+:[^@]+@"), "mysql_url"),
    (re.compile(r"mongodb(\+srv)?://[^:]+:[^@]+@"), "mongo_url"),
]


def sanitize_text(text: str) -> tuple[str, list[str]]:
    """Return ``(sanitized_text, list_of_redaction_kinds)``.

    Replaces secret-shaped substrings with ``<REDACTED>`` while keeping
    line numbers intact.
    """
    if not text:
        return text, []
    found: list[str] = []
    sanitized = text
    for pattern, kind in _SECRET_PATTERNS:
        new = pattern.sub("<REDACTED>", sanitized)
        if new != sanitized:
            if kind not in found:
                found.append(kind)
            sanitized = new
    return sanitized, found


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Deployment discovery ────────────────────────────────────────────────────────
DEPLOYMENT_FILE_KIND: dict[str, tuple[DeploymentTarget, str]] = {
    "Dockerfile": (DeploymentTarget.CONTAINER, "dockerfile"),
    "docker-compose.yml": (DeploymentTarget.CONTAINER, "docker_compose"),
    "docker-compose.yaml": (DeploymentTarget.CONTAINER, "docker_compose"),
    "compose.yaml": (DeploymentTarget.CONTAINER, "docker_compose"),
    "k8s.yaml": (DeploymentTarget.KUBERNETES, "kubernetes"),
    "kustomization.yaml": (DeploymentTarget.KUBERNETES, "kubernetes"),
    "Jenkinsfile": (DeploymentTarget.UNKNOWN, "ci_cd"),
    ".gitlab-ci.yml": (DeploymentTarget.UNKNOWN, "ci_cd"),
    "azure-pipelines.yml": (DeploymentTarget.UNKNOWN, "ci_cd"),
    "Procfile": (DeploymentTarget.PAAS, "heroku"),
    "serverless.yml": (DeploymentTarget.SERVERLESS, "serverless"),
}


def build_deployment_spec(
    files: list[str], content_read: Any
) -> DeploymentSpec:
    """Build a DeploymentSpec from a list of relative file paths and
    a ``content_read(path) -> str | None`` callable.
    """
    target = DeploymentTarget.UNKNOWN
    containerized = False
    evidence: list[str] = []
    os_assumptions: list[str] = []
    for f in files:
        for key, (tg, kind) in DEPLOYMENT_FILE_KIND.items():
            if f.endswith(key) or os.path.basename(f) == key:
                evidence.append(f"{kind}:{f}")
                if tg == DeploymentTarget.CONTAINER:
                    containerized = True
                if target == DeploymentTarget.UNKNOWN or (
                    target != DeploymentTarget.KUBERNETES
                    and tg == DeploymentTarget.KUBERNETES
                ):
                    target = tg
                try:
                    text = content_read(f)
                    if text:
                        os_match = re.search(
                            r"^FROM\s+([^\s]+)", text, re.MULTILINE
                        )
                        if os_match and "/" in os_match.group(1):
                            base = os_match.group(1).split("/")[-1].split(":")[0]
                            if base and base not in ("scratch",):
                                os_assumptions.append(f"docker_base:{base}")
                except Exception:
                    pass
    return DeploymentSpec(
        target=target,
        containerized=containerized,
        evidence=evidence,
        os_assumptions=os_assumptions,
        confidence=FactConfidence.HIGH if evidence else FactConfidence.UNKNOWN,
    )


# ── Database discovery ──────────────────────────────────────────────────────────
_DB_HINTS: list[tuple[re.Pattern[str], tuple[str, DatabaseKind, SQLDialect]]] = [
    (re.compile(r"jdbc:postgresql:", re.IGNORECASE),
     ("postgresql", DatabaseKind.RELATIONAL, SQLDialect.POSTGRESQL)),
    (re.compile(r"jdbc:mysql:", re.IGNORECASE),
     ("mysql", DatabaseKind.RELATIONAL, SQLDialect.MYSQL)),
    (re.compile(r"jdbc:oracle:", re.IGNORECASE),
     ("oracle", DatabaseKind.RELATIONAL, SQLDialect.ORACLE)),
    (re.compile(r"jdbc:sqlserver:", re.IGNORECASE),
     ("sql_server", DatabaseKind.RELATIONAL, SQLDialect.SQL_SERVER)),
    (re.compile(r"jdbc:db2:", re.IGNORECASE),
     ("db2", DatabaseKind.MAINFRAME, SQLDialect.DB2)),
    (re.compile(r"sqlite3", re.IGNORECASE),
     ("sqlite", DatabaseKind.FILE_BASED, SQLDialect.SQLITE)),
    (re.compile(r"redis://", re.IGNORECASE),
     ("redis", DatabaseKind.KEY_VALUE, SQLDialect.GENERIC)),
    (re.compile(r"mongodb", re.IGNORECASE),
     ("mongodb", DatabaseKind.NOSQL, SQLDialect.GENERIC)),
]


def discover_databases(
    content_iter: Iterable[tuple[str, str]],
) -> DatabaseInventory:
    """Inspect ``(path, content)`` pairs and produce a DatabaseInventory.

    Connection strings with embedded credentials are stored in their
    sanitised form.
    """
    inventory = DatabaseInventory()
    seen_dialects: dict[str, SQLDialect] = {}
    seen_kinds: dict[str, DatabaseKind] = {}
    for path, text in content_iter:
        for pattern, (name, kind, dialect) in _DB_HINTS:
            if pattern.search(text):
                if name not in inventory.databases:
                    inventory.databases.append(name)
                seen_dialects[name] = dialect
                seen_kinds[name] = kind
                sanitized, _ = sanitize_text(text)
                for match in pattern.finditer(sanitized):
                    inventory.connection_strings.append(
                        f"{path}: {match.group(0)}"
                    )
                    break
    inventory.dialects = seen_dialects
    inventory.database_kind = seen_kinds
    inventory.confidence = (
        FactConfidence.HIGH if inventory.databases else FactConfidence.UNKNOWN
    )
    return inventory


# ── Dependency graph ────────────────────────────────────────────────────────────
_IMPORT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [re.compile(r"^(?:from|import)\s+([\w.]+)", re.MULTILINE)],
    "javascript": [
        re.compile(r"^require\s*\(\s*['\"]([^'\"]+)['\"]", re.MULTILINE),
        re.compile(r"^import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    ],
    "typescript": [
        re.compile(r"^import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    ],
    "java": [re.compile(r"^import\s+([\w.]+);?", re.MULTILINE)],
    "ruby": [re.compile(r"^require(?:_relative)?\s+['\"]([^'\"]+)['\"]", re.MULTILINE)],
    "go": [re.compile(r'^\s*"([^"]+)"', re.MULTILINE)],
    "rust": [re.compile(r"^\s*(?:use|extern\s+crate)\s+([\w:]+)", re.MULTILINE)],
    "cobol": [re.compile(r"^\s{7}\s*(?:COPY|INCLUDE)\s+([A-Z0-9]+)", re.MULTILINE)],
    "pli": [re.compile(r"^\s*%INCLUDE\s+([\w.]+)", re.MULTILINE)],
    "c": [re.compile(r'^\s*#include\s*[<"]([^>"]+)[">]', re.MULTILINE)],
    "cpp": [re.compile(r'^\s*#include\s*[<"]([^>"]+)[">]', re.MULTILINE)],
}


def build_dependency_graph(
    scanned_files: list[Any],
    content_iter: Iterable[tuple[str, str]],
) -> Any:
    """Build a DependencyGraph from scanned files and (path, content) pairs."""
    from autoforge_modernization.reconnaissance.models import (
        DependencyEdge, DependencyGraph, DependencyKind,
    )
    nodes: dict[str, bool] = {}
    for sf in scanned_files:
        rel = getattr(sf, "relative_path", getattr(sf, "path", ""))
        module = rel.split("/")[0] if "/" in rel else rel
        if module and module not in nodes:
            nodes[module] = getattr(sf, "is_generated", False)

    edges_raw: list[tuple[str, str, str]] = []
    for path, text in content_iter:
        lang = ""
        for sf in scanned_files:
            if getattr(sf, "relative_path", "") == path:
                lang = getattr(sf, "detected_language", "") or ""
                break
        patterns = _IMPORT_PATTERNS.get(lang, _IMPORT_PATTERNS.get("javascript", []))
        file_module = path.split("/")[0] if "/" in path else path
        for pat in patterns:
            for m in pat.finditer(text):
                dep = m.group(1).split(".")[0].split("/")[0]
                if dep and dep != file_module:
                    edges_raw.append((file_module, dep, lang))
                    if dep not in nodes:
                        nodes[dep] = False

    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for src, dst, _ in edges_raw:
        if src in adj and dst in adj:
            adj[src].append(dst)

    cycles: list[list[str]] = []
    visited: dict[str, bool] = {}
    stack: dict[str, bool] = {}

    def dfs(node: str, path: list[str]) -> None:
        visited[node] = True
        stack[node] = True
        for nb in adj.get(node, []):
            if nb not in visited:
                dfs(nb, path + [nb])
            elif stack.get(nb, False):
                cyc = path[path.index(nb):] + [nb]
                cycles.append(cyc)
        stack[node] = False

    for n in nodes:
        if n not in visited:
            dfs(n, [n])

    edges: list[DependencyEdge] = []
    seen: set[tuple[str, str]] = set()
    for src, dst, lang in edges_raw:
        key = (src, dst)
        if key not in seen:
            seen.add(key)
            edges.append(DependencyEdge(
                from_node=src, to_node=dst,
                kind=DependencyKind.EXTERNAL,
                evidence=f"{lang}:{src}->{dst}",
                confidence=FactConfidence.HIGH,
            ))

    return DependencyGraph(
        nodes=list(nodes.keys()),
        edges=edges,
        circular_dependencies=cycles[:10],
    )




# ── Architecture graph ────────────────────────────────────────────────────────────
def build_architecture_graph(scanned_files):
    """Build an ArchitectureGraph from directory structure."""
    from autoforge_modernization.reconnaissance.models import (
        ArchitectureGraph, ArchitectureNode, ArchitectureNodeKind,
        ArchitectureProvenance,
    )
    top_dirs = {}
    for sf in scanned_files:
        rel = getattr(sf, "relative_path", "")
        if not rel:
            continue
        top = rel.split("/")[0]
        if top not in top_dirs:
            top_dirs[top] = {"files": [], "languages": set(), "generated": False}
        top_dirs[top]["files"].append(rel)
        lang = getattr(sf, "detected_language", "")
        if lang:
            top_dirs[top]["languages"].add(lang)
        if getattr(sf, "is_generated", False):
            top_dirs[top]["generated"] = True
    nodes = []
    for name, info in top_dirs.items():
        kind = ArchitectureNodeKind.MODULE
        if "test" in name.lower():
            kind = ArchitectureNodeKind.UNKNOWN
        elif "config" in name.lower() or "conf" in name.lower():
            kind = ArchitectureNodeKind.UNKNOWN
        elif "deploy" in name.lower() or "docker" in name.lower():
            kind = ArchitectureNodeKind.SERVICE
        nodes.append(ArchitectureNode(
            node_id=name, name=name, kind=kind,
            path=name,
            technologies=list(info["languages"]),
            provenance=ArchitectureProvenance.OBSERVED,
            confidence=FactConfidence.HIGH,
            evidence=info["files"][:5],
        ))
    return ArchitectureGraph(
        nodes=nodes, edges=[],
        built_at=datetime.now(timezone.utc),
    )


# ── Specialist tooling discovery ──────────────────────────────────────────────────
_TOOL_REGISTRY = [
    ("cobc", ["cobc", "cobolc", "gnucobol"], "PARSER_ANALYZER"),
    ("javac", ["javac"], "PARSER_ANALYZER"),
    ("node", ["node", "nodejs"], "RUNTIME_ENVIRONMENT"),
    ("python3", ["python3", "python"], "RUNTIME_ENVIRONMENT"),
    ("cargo", ["cargo"], "BUILD_TOOL"),
    ("mvn", ["mvn"], "BUILD_TOOL"),
    ("gradle", ["gradle"], "BUILD_TOOL"),
    ("docker", ["docker"], "CONTAINER_TOOL"),
    ("kubectl", ["kubectl"], "CONTAINER_TOOL"),
    ("psql", ["psql"], "DATABASE_TOOL"),
    ("redis-cli", ["redis-cli"], "DATABASE_TOOL"),
]


def discover_specialist_tools(detected):
    """Check host environment for required specialist tooling.
    
    Checks shutil.which() for each known tool. Never installs anything.
    """
    from autoforge_modernization.reconnaissance.models import (
        ProjectToolRequirement, ToolRequirementKind,
    )
    tools = []
    detected_names = {getattr(t, "name", "") for t in detected}
    for tool_name, executables, kind_name in _TOOL_REGISTRY:
        for exe in executables:
            if shutil.which(exe):
                kind = getattr(ToolRequirementKind, kind_name)
                tools.append(ProjectToolRequirement(
                    tool_name=tool_name,
                    tool_kind=kind,
                    technology=tool_name,
                    purpose=f"detected_tool:{exe}",
                    status="found_not_required",
                    currently_installed=True,
                ))
                break
    return tools


# ── Document / business evidence discovery ────────────────────────────────────────
_DOC_PATTERNS = [
    (re.compile(r"(?i)\brequirement"), "REQUIREMENTS_DOC"),
    (re.compile(r"(?i)\bbusiness\s+rule"), "BUSINESS_RULES"),
    (re.compile(r"(?i)\bspec"), "SPECIFICATION"),
    (re.compile(r"(?i)\bopenapi|swagger"), "API_CONTRACT"),
    (re.compile(r"(?i)\boperational|runbook|ops"), "OPERATIONAL_DOC"),
    (re.compile(r"(?i)\btest\s+plan"), "TESTS"),
    (re.compile(r"(?i)\bmigration\s+guide"), "MIGRATION_DOC"),
    (re.compile(r"(?i)\bchangelog|change\s+log"), "CHANGELOG"),
    (re.compile(r"(?i)\breadme"), "README"),
]


def discover_documents(paths_and_content):
    """Classify documents and build DocumentDiscovery + BusinessEvidence list."""
    from autoforge_modernization.reconnaissance.models import (
        DocumentDiscovery, BusinessEvidence, EvidenceSourceKind,
    )
    discovery = DocumentDiscovery()
    evidence = []
    for rel, text in paths_and_content:
        lower_name = rel.lower()
        if not lower_name.endswith((".md", ".rst", ".txt", ".adoc")):
            continue
        matched_kind = EvidenceSourceKind.UNKNOWN
        for pattern, kind_name in _DOC_PATTERNS:
            if pattern.search(lower_name) or (text and pattern.search(text[:1000])):
                matched_kind = getattr(EvidenceSourceKind, kind_name)
                break
        if rel not in discovery.documents:
            discovery.documents.append(rel)
        discovery.doc_types[rel] = matched_kind
        if matched_kind == EvidenceSourceKind.REQUIREMENTS_DOC:
            discovery.requirements_docs.append(rel)
        elif matched_kind == EvidenceSourceKind.BUSINESS_RULES:
            discovery.business_rule_docs.append(rel)
        elif matched_kind == EvidenceSourceKind.API_CONTRACT:
            discovery.api_specs.append(rel)
        if matched_kind in (
            EvidenceSourceKind.REQUIREMENTS_DOC,
            EvidenceSourceKind.BUSINESS_RULES,
            EvidenceSourceKind.SPECIFICATION,
        ):
            evidence.append(BusinessEvidence(
                source=matched_kind,
                source_path=rel,
                description=f"Document classified as {matched_kind.value}",
                confidence=FactConfidence.MEDIUM,
                autoforge_ready=True,
            ))
    discovery.confidence = (
        FactConfidence.MEDIUM if discovery.documents else FactConfidence.UNKNOWN
    )
    return discovery, evidence


# ── Lockdown / RAG boundary helpers ──────────────────────────────────────────────
def classify_research_safety(question):
    """Advisory sanitizer. Returns (is_safe, indicators_found)."""
    if not question:
        return True, []
    lower = question.lower()
    indicators = [
        kw for kw in (
            "source code", "our system", "our application", "our codebase",
            "the client", "internal logic", "private api",
        ) if kw in lower
    ]
    return (len(indicators) == 0, indicators)


def check_lockdown_violation(operation, lockdown_enabled):
    """Raise LockdownViolationError if operation is forbidden in lockdown."""
    if lockdown_enabled and operation in {
        "web_research", "market_research", "competitor_research",
        "external_retrieval",
    }:
        from autoforge_modernization.errors import LockdownViolationError
        raise LockdownViolationError(operation=operation)
    return False
