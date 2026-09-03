"""Free/Open-Source Specialist Tooling Resolver (Phase 18-G.3)."""
from __future__ import annotations
import re
import subprocess
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ToolAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"
    INCOMPATIBLE = "incompatible"


class ToolVerificationResult(BaseModel):
    tool_name: str
    availability: ToolAvailability
    version: str | None = None
    verified_at: datetime = Field(default_factory=_utc_now)
    verification_command: str | None = None
    error: str | None = None
    installation_path: str | None = None
    license_type: str = "unknown"


class ToolingResolver:
    """Resolver for free/open-source specialist tooling."""

    def __init__(self):
        self._cache: dict[str, ToolVerificationResult] = {}
        self._tools = self._build_tool_knowledge()

    def _build_tool_knowledge(self) -> dict[str, list[dict]]:
        return {
            "COBOL": [
                {"name": "cobc", "package": "gnu-cobol", "install": "brew install gnu-cobol  # macOS; apt-get install open-cobol  # Debian", "verify": "cobc --version", "purpose": "COBOL compiler / syntax validation", "capability": "compile + syntax_check", "license": "GPL", "vpat": r"([0-9]+\.[0-9]+)"},
            ],
            "SQL": [
                {"name": "sqlglot", "package": "sqlglot", "install": "pip install sqlglot", "verify": "python3 -c 'import sqlglot; print(sqlglot.__version__)'", "purpose": "SQL parser and transpiler", "capability": "parse + transpile + analyze", "license": "MIT", "vpat": r"([0-9]+\.[0-9]+)"},
            ],
            "JCL": [
                {"name": "jcl-check", "package": "jcl-check", "install": "pip install jcl-check", "verify": "python3 -c 'import jcl_check' 2>/dev/null || echo NOT_FOUND", "purpose": "JCL syntax checker", "capability": "syntax_validation", "license": "MIT", "vpat": r"([0-9]+\.[0-9]+)", "note": "Limited free tooling for JCL. Manual review recommended."},
            ],
            "DB2": [
                {"name": "sqlglot", "package": "sqlglot", "install": "pip install sqlglot", "verify": "python3 -c 'import sqlglot; print(sqlglot.__version__)'", "purpose": "DB2 SQL parsing and transpilation", "capability": "parse + transpile", "license": "MIT", "vpat": r"([0-9]+\.[0-9]+)"},
            ],
            "JAVA": [
                {"name": "javac", "package": "OpenJDK", "install": "brew install openjdk", "verify": "java --version 2>&1 | head -1", "purpose": "Java compilation and analysis", "capability": "compile + analyze", "license": "GPL v2", "vpat": r"([0-9]+\.[0-9]+)"},
            ],
        }

    def resolve(self, technology: str, purpose: str | None = None, force_refresh: bool = False) -> list[ToolVerificationResult]:
        cache_key = f"{technology}:{purpose}"
        if cache_key in self._cache and not force_refresh:
            return [self._cache[cache_key]]
        tools = self._tools.get(technology, [])
        results = []
        for tool in tools:
            if purpose and purpose.lower() not in tool.get("purpose", "").lower():
                continue
            result = self._verify(tool)
            results.append(result)
            self._cache[f"{technology}:{tool['name']}"] = result
        return results

    def _verify(self, tool: dict) -> ToolVerificationResult:
        name, vcmd, vpat = tool["name"], tool.get("verify", ""), tool.get("vpat", r"([0-9]+\.[0-9]+)")
        r = ToolVerificationResult(tool_name=name, availability=ToolAvailability.UNKNOWN, license_type=tool.get("license", "unknown"), capability_scope=tool.get("capability", "unknown"))
        if not vcmd:
            return r
        try:
            out = subprocess.run(vcmd, shell=True, capture_output=True, text=True, timeout=10).stdout.strip()
            if "NOT_FOUND" in out or not out:
                r.availability = ToolAvailability.MISSING
                r.installation_path = tool.get("install", "")
                return r
            vm = re.search(vpat, out, re.IGNORECASE)
            r.version = vm.group(1) if vm else None
            r.availability = ToolAvailability.AVAILABLE
            r.verification_command = vcmd
        except subprocess.TimeoutExpired:
            r.availability = ToolAvailability.UNKNOWN; r.error = "timeout"
        except FileNotFoundError:
            r.availability = ToolAvailability.MISSING; r.installation_path = tool.get("install", "")
        except Exception as e:
            r.availability = ToolAvailability.UNKNOWN; r.error = str(e)
        return r

    def get_instructions(self, technology: str, purpose: str | None = None) -> list[dict]:
        results = self.resolve(technology, purpose)
        missing = [r for r in results if r.availability == ToolAvailability.MISSING]
        tools = self._tools.get(technology, [])
        instructions = []
        for tool in tools:
            for m in missing:
                if m.tool_name == tool["name"]:
                    instructions.append({"tool": tool["name"], "purpose": tool.get("purpose", ""), "install_command": tool.get("install", ""), "license": tool.get("license", "unknown"), "note": tool.get("note", "")})
        return instructions

    def report(self) -> dict[str, Any]:
        report = {}
        for tech, tools in self._tools.items():
            results = self.resolve(tech)
            report[tech] = {"known": len(tools), "available": [r.tool_name for r in results if r.availability == ToolAvailability.AVAILABLE], "missing": [r.tool_name for r in results if r.availability == ToolAvailability.MISSING]}
        return report

    capability_scope: str = "unknown"
