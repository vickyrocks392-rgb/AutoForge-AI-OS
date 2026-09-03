"""G.3 Specialist Tooling Discovery (Phase 18-G.3)."""
from __future__ import annotations
import importlib, shutil, subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

def _utc_now(): return datetime.now(timezone.utc)

class ToolLicense(str, Enum):
    MIT = "MIT"; APACHE2 = "Apache-1.0"; BSD = "BSD"; GPL = "GPL"; UNKNOWN = "UNKNOWN"

class ToolStatus(str, Enum):
    AVAILABLE = "available"; INSTALLED = "installed"; MISSING = "missing"; OFFLINE = "offline"; FALLBACK = "fallback"

@dataclass
class ToolEvidence:
    tool: str; status: ToolStatus
    checked_at: str = field(default_factory=lambda: _utc_now().isoformat())
    version: str = ""; license: str = "UNKNOWN"
    runtime_invocations: list = field(default_factory=list)
    fallback_used: str = ""; error: str = ""

@dataclass
class SpecialistTool:
    name: str; purpose: str; technology: str
    version: str = "unknown"; license: ToolLicense = ToolLicense.UNKNOWN
    module: str | None = None; executable: str | None = None
    capabilities: list = field(default_factory=list)
    fallback_description: str = ""; install_url: str = ""

    def availability(self) -> ToolEvidence:
        if self.module:
            try:
                mod = importlib.import_module(self.module)
                v = getattr(mod, "__version__", "unknown")
                return ToolEvidence(tool=self.name, status=ToolStatus.INSTALLED, version=str(v), license=self.license.value)
            except Exception as e:
                return ToolEvidence(tool=self.name, status=ToolStatus.FALLBACK, fallback_used=self.fallback_description, error=f"{self.module}: {e}")
        if self.executable:
            path = shutil.which(self.executable)
            if path:
                try:
                    out = subprocess.run([self.executable, "--version"], capture_output=True, text=True, timeout=5)
                    v = (out.stdout or out.stderr).strip().split("\n")[0]
                    return ToolEvidence(tool=self.name, status=ToolStatus.AVAILABLE, version=v, license=self.license.value, runtime_invocations=[self.executable])
                except Exception:
                    return ToolEvidence(tool=self.name, status=ToolStatus.AVAILABLE, license=self.license.value, runtime_invocations=[self.executable])
            return ToolEvidence(tool=self.name, status=ToolStatus.MISSING, fallback_used=self.fallback_description)
        return ToolEvidence(tool=self.name, status=ToolStatus.UNKNOWN)

    def is_available(self) -> bool:
        return self.availability().status in (ToolStatus.AVAILABLE, ToolStatus.INSTALLED)

SPECIALIST_TOOL_CATALOG = [
    SpecialistTool(name="sqlparse", purpose="SQL parser", technology="SQL", module="sqlparse", license=ToolLicense.BSD, capabilities=["parse", "tokens", "statement_segmentation"], fallback_description="G.3 regex-based SQL extractor"),
    SpecialistTool(name="PyYAML", purpose="YAML emitter", technology="YAML", module="yaml", license=ToolLicense.MIT, capabilities=["emit_yaml"], fallback_description="json emitter"),
    SpecialistTool(name="lark", purpose="EBNF parser generator", technology="MULTI", module="lark", license=ToolLicense.MIT, capabilities=["parse", "grammar", "ast"], fallback_description="G.3 hand-written parsers"),
    SpecialistTool(name="tree-sitter", purpose="Incremental parsing", technology="MULTI", module="tree_sitter", license=ToolLicense.MIT, capabilities=["parse", "cst", "ast"], fallback_description="G.3 hand-written deterministic tokenizer+AST"),
    SpecialistTool(name="cobol-parser", purpose="Pure-python COBOL parser", technology="COBOL", module="cobol_parser", license=ToolLicense.UNKNOWN, capabilities=["parse", "ast"], fallback_description="G.3 fixed-format line-oriented COBOL parser"),
    SpecialistTool(name="jcl-parser", purpose="JCL grammar parser", technology="JCL", module="jcl", license=ToolLicense.UNKNOWN, capabilities=["parse"], fallback_description="G.3 hand-written JCL state machine"),
]

class SpecialistToolingInventory:
    def __init__(self, catalog=None):
        self._catalog = catalog or SPECIALIST_TOOL_CATALOG
        self._evidence = {}
        self._refresh()
    def _refresh(self):
        for tool in self._catalog:
            self._evidence[tool.name] = tool.availability()
    def all_evidence(self): return dict(self._evidence)
    def available_tools(self, technology=None):
        return [t for t in self._catalog if self._evidence.get(t.name) and self._evidence[t.name].status in (ToolStatus.AVAILABLE, ToolStatus.INSTALLED) and (technology is None or t.technology in (technology.upper(), "MULTI"))]
    def missing_tools(self): return [t for t in self._catalog if self._evidence.get(t.name) and self._evidence[t.name].status == ToolStatus.MISSING]
    def fallback_tools(self): return [t for t in self._catalog if self._evidence.get(t.name) and self._evidence[t.name].status == ToolStatus.FALLBACK]
    def for_technology(self, tech): return [t for t in self._catalog if t.technology in (tech.upper(), "MULTI")]
    def tool(self, name): return next((t for t in self._catalog if t.name == name), None)
    def evidence_for(self, name): return self._evidence.get(name)

__all__ = ["SpecialistTool", "ToolEvidence", "ToolLicense", "ToolStatus", "SpecialistToolingInventory", "SPECIALIST_TOOL_CATALOG"]