"""
Pluggable Legacy Analyzers.
"""

from __future__ import annotations
import re
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class LegacyAnalyzer(Protocol):
    """
    Protocol for pluggable legacy technology/language analyzers.
    """
    def detect(self, file_content: str, file_path: str) -> bool:
        ...

    def analyze(self, file_content: str, file_path: str) -> dict[str, Any]:
        ...

    def extract_symbols(self, file_content: str, file_path: str) -> list[str]:
        ...

    def extract_dependencies(self, file_content: str, file_path: str) -> list[str]:
        ...

    def extract_data_access(self, file_content: str, file_path: str) -> list[str]:
        ...

    def extract_interfaces(self, file_content: str, file_path: str) -> list[str]:
        ...

    def extract_configuration(self, file_content: str, file_path: str) -> dict[str, Any]:
        ...


class COBOLAnalyzer:
    """
    Deterministic analyzer for COBOL / Mainframe files.
    """
    def detect(self, file_content: str, file_path: str) -> bool:
        path_lower = file_path.lower()
        if path_lower.endswith((".cbl", ".cob", ".cpy", ".cobol")):
            return True
        # Check content markers
        if "IDENTIFICATION DIVISION" in file_content or "PROCEDURE DIVISION" in file_content:
            return True
        return False

    def analyze(self, file_content: str, file_path: str) -> dict[str, Any]:
        return {
            "language": "COBOL",
            "symbols": self.extract_symbols(file_content, file_path),
            "dependencies": self.extract_dependencies(file_content, file_path),
            "data_access": self.extract_data_access(file_content, file_path),
            "interfaces": self.extract_interfaces(file_content, file_path),
            "configuration": self.extract_configuration(file_content, file_path),
        }

    def extract_symbols(self, file_content: str, file_path: str) -> list[str]:
        # Extract variables from DATA DIVISION or paragraph names
        symbols = []
        # Find paragraphs
        paragraphs = re.findall(r"^\s{7,11}([A-Z0-9\-]+)\.\s*$", file_content, re.MULTILINE)
        symbols.extend([f"paragraph:{p}" for p in paragraphs])
        return symbols

    def extract_dependencies(self, file_content: str, file_path: str) -> list[str]:
        # Extract COPYBOOK statements
        copybooks = re.findall(r"COPY\s+([A-Z0-9\-]+)", file_content, re.IGNORECASE)
        return [f"copybook:{c}" for c in copybooks]

    def extract_data_access(self, file_content: str, file_path: str) -> list[str]:
        # Extract file references / SELECT statements or DB2 EXEC SQL
        access = []
        files = re.findall(r"SELECT\s+([A-Z0-9\-]+)\s+ASSIGN\s+TO", file_content, re.IGNORECASE)
        access.extend([f"file:{f}" for f in files])
        db2 = re.findall(r"EXEC SQL\s+(?:SELECT|INSERT|UPDATE|DELETE)\s+FROM\s+([A-Z0-9\-]+)", file_content, re.IGNORECASE | re.DOTALL)
        access.extend([f"table:{t}" for t in db2])
        return access

    def extract_interfaces(self, file_content: str, file_path: str) -> list[str]:
        # CALL statements to other programs
        calls = re.findall(r"CALL\s+'([A-Z0-9\-]+)'", file_content, re.IGNORECASE)
        return [f"call:{c}" for c in calls]

    def extract_configuration(self, file_content: str, file_path: str) -> dict[str, Any]:
        return {}


class JavaMonolithAnalyzer:
    """
    Deterministic analyzer for older Java / Java EE monolith applications.
    """
    def detect(self, file_content: str, file_path: str) -> bool:
        if file_path.lower().endswith(".java"):
            return True
        if "package " in file_content and "class " in file_content:
            return True
        return False

    def analyze(self, file_content: str, file_path: str) -> dict[str, Any]:
        return {
            "language": "Java",
            "symbols": self.extract_symbols(file_content, file_path),
            "dependencies": self.extract_dependencies(file_content, file_path),
            "data_access": self.extract_data_access(file_content, file_path),
            "interfaces": self.extract_interfaces(file_content, file_path),
            "configuration": self.extract_configuration(file_content, file_path),
        }

    def extract_symbols(self, file_content: str, file_path: str) -> list[str]:
        # Find package and class names
        pkg = re.search(r"package\s+([a-zA-Z0-9_\.]+);", file_content)
        cls = re.search(r"public\s+class\s+([a-zA-Z0-9_]+)", file_content)
        symbols = []
        if pkg and cls:
            symbols.append(f"class:{pkg.group(1)}.{cls.group(1)}")
        elif cls:
            symbols.append(f"class:{cls.group(1)}")
        return symbols

    def extract_dependencies(self, file_content: str, file_path: str) -> list[str]:
        # Import statements
        imports = re.findall(r"import\s+([a-zA-Z0-9_\.\*]+);", file_content)
        return [f"import:{i}" for i in imports]

    def extract_data_access(self, file_content: str, file_path: str) -> list[str]:
        # Database connectivity queries or annotations
        access = []
        queries = re.findall(r"\"(?:SELECT|INSERT|UPDATE|DELETE)[^\"]+FROM\s+([a-zA-Z0-9_]+)[^\"]*\"", file_content, re.IGNORECASE)
        access.extend([f"table:{q}" for q in queries])
        hibernate = re.findall(r"@Table\(name\s*=\s*\"([a-zA-Z0-9_]+)\"\)", file_content)
        access.extend([f"table:{h}" for h in hibernate])
        return access

    def extract_interfaces(self, file_content: str, file_path: str) -> list[str]:
        # REST / SOAP / EJB endpoints
        interfaces = []
        endpoints = re.findall(r"@RequestMapping\(\s*(?:value\s*=\s*)?\"([^\"]+)\"", file_content)
        interfaces.extend([f"endpoint:{e}" for e in endpoints])
        ws = re.findall(r"@WebService", file_content)
        if ws:
            interfaces.append("soap_webservice")
        return interfaces

    def extract_configuration(self, file_content: str, file_path: str) -> dict[str, Any]:
        return {}


class SQLAnalyzer:
    """
    Deterministic analyzer for SQL scripts and Stored Procedures.
    """
    def detect(self, file_content: str, file_path: str) -> bool:
        if file_path.lower().endswith((".sql", ".prc", ".tab", ".pkb", ".pks")):
            return True
        # Look for CREATE TABLE or CREATE PROCEDURE
        if "CREATE TABLE" in file_content.upper() or "CREATE PROCEDURE" in file_content.upper():
            return True
        return False

    def analyze(self, file_content: str, file_path: str) -> dict[str, Any]:
        return {
            "language": "SQL",
            "symbols": self.extract_symbols(file_content, file_path),
            "dependencies": self.extract_dependencies(file_content, file_path),
            "data_access": self.extract_data_access(file_content, file_path),
            "interfaces": self.extract_interfaces(file_content, file_path),
            "configuration": self.extract_configuration(file_content, file_path),
        }

    def extract_symbols(self, file_content: str, file_path: str) -> list[str]:
        # Discover stored procedures, triggers, views, tables
        symbols = []
        tables = re.findall(r"CREATE\s+TABLE\s+([a-zA-Z0-9_\.]+)", file_content, re.IGNORECASE)
        symbols.extend([f"table:{t}" for t in tables])
        procs = re.findall(r"CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+([a-zA-Z0-9_\.]+)", file_content, re.IGNORECASE)
        symbols.extend([f"procedure:{p}" for p in procs])
        views = re.findall(r"CREATE\s+VIEW\s+([a-zA-Z0-9_\.]+)", file_content, re.IGNORECASE)
        symbols.extend([f"view:{v}" for v in views])
        return symbols

    def extract_dependencies(self, file_content: str, file_path: str) -> list[str]:
        # Stored procedure calls or foreign keys
        deps = []
        fk = re.findall(r"FOREIGN\s+KEY[^\)]+REFERENCES\s+([a-zA-Z0-9_\.]+)", file_content, re.IGNORECASE)
        deps.extend([f"fk_ref:{f}" for f in fk])
        return deps

    def extract_data_access(self, file_content: str, file_path: str) -> list[str]:
        # Discover tables used in SELECT/INSERT/UPDATE/DELETE queries
        tables = re.findall(r"(?:FROM|JOIN|INTO|UPDATE)\s+([a-zA-Z0-9_\.]+)", file_content, re.IGNORECASE)
        # Exclude common SQL syntax keywords
        keywords = {"SELECT", "WHERE", "JOIN", "SET", "VALUES", "ON", "AND", "OR"}
        valid_tables = [t for t in tables if t.upper() not in keywords]
        return [f"table:{t}" for t in valid_tables]

    def extract_interfaces(self, file_content: str, file_path: str) -> list[str]:
        return []

    def extract_configuration(self, file_content: str, file_path: str) -> dict[str, Any]:
        return {}


class UnknownTechnologyAnalyzer:
    """
    Fallback analyzer for unknown/unfamiliar technologies.
    Degrades gracefully, records structural elements, raises analysis gaps.
    """
    def detect(self, file_content: str, file_path: str) -> bool:
        # Fallback catches everything
        return True

    def analyze(self, file_content: str, file_path: str) -> dict[str, Any]:
        # Marks technology as unknown, extracts metadata deterministically where possible
        return {
            "language": "UNKNOWN",
            "symbols": self.extract_symbols(file_content, file_path),
            "dependencies": self.extract_dependencies(file_content, file_path),
            "data_access": self.extract_data_access(file_content, file_path),
            "interfaces": self.extract_interfaces(file_content, file_path),
            "configuration": self.extract_configuration(file_content, file_path),
            "analysis_gap": f"Technology in '{file_path}' is unknown or unsupported. Deterministic parsing fell back to generic structural analysis."
        }

    def extract_symbols(self, file_content: str, file_path: str) -> list[str]:
        # Detect function/class-like keywords generically
        symbols = []
        funcs = re.findall(r"(?:def|fn|function|class|struct)\s+([a-zA-Z0-9_]+)", file_content)
        symbols.extend([f"generic_symbol:{f}" for f in funcs])
        return symbols

    def extract_dependencies(self, file_content: str, file_path: str) -> list[str]:
        # Detect import/include-like keywords generically
        deps = []
        includes = re.findall(r"(?:import|include|require|using)\s+([a-zA-Z0-9_\.\"/\\'\-]+)", file_content)
        deps.extend([f"generic_dep:{i}" for i in includes])
        return deps

    def extract_data_access(self, file_content: str, file_path: str) -> list[str]:
        return []

    def extract_interfaces(self, file_content: str, file_path: str) -> list[str]:
        return []

    def extract_configuration(self, file_content: str, file_path: str) -> dict[str, Any]:
        return {}


# Extensible analyzer registry
_ANALYZERS: list[LegacyAnalyzer] = [
    COBOLAnalyzer(),
    JavaMonolithAnalyzer(),
    SQLAnalyzer(),
    UnknownTechnologyAnalyzer(), # Must be last as fallback
]

def get_analyzer_for_file(file_content: str, file_path: str) -> LegacyAnalyzer:
    for analyzer in _ANALYZERS:
        if analyzer.detect(file_content, file_path):
            return analyzer
    return UnknownTechnologyAnalyzer()
