"""Deterministic Codebase Inventory Engine (18-COMMERCIAL-D).

Discovers files, directories, extensions, languages, physical LOC, non-comment NLOC,
build files, dependency manifests, tests, entrypoints, schemas, and binaries.
Strictly deterministic and reproducible without LLM guesswork.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from autoforge_power_engines.migration.safety import is_sensitive_path


class FileClassification(str, Enum):
    SOURCE = "source"
    TEST = "test"
    CONFIG = "config"
    BUILD = "build"
    DEPENDENCY_MANIFEST = "dependency_manifest"
    SCHEMA = "schema"
    DOCUMENTATION = "documentation"
    BINARY = "binary"
    GENERATED = "generated"
    UNSUPPORTED = "unsupported"


# Common binary file extensions
BINARY_EXTENSIONS: Set[str] = {
    ".class", ".jar", ".war", ".ear", ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".pyo", ".pyd", ".o", ".a", ".obj", ".bin", ".dat",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", ".gz"
}

# Known dependency manifests & build files
BUILD_MANIFEST_MAP: Dict[str, FileClassification] = {
    "pom.xml": FileClassification.BUILD,
    "build.gradle": FileClassification.BUILD,
    "build.gradle.kts": FileClassification.BUILD,
    "makefile": FileClassification.BUILD,
    "cmakelists.txt": FileClassification.BUILD,
    "package.json": FileClassification.DEPENDENCY_MANIFEST,
    "requirements.txt": FileClassification.DEPENDENCY_MANIFEST,
    "pyproject.toml": FileClassification.BUILD,
    "setup.py": FileClassification.BUILD,
    "cargo.toml": FileClassification.BUILD,
    "go.mod": FileClassification.DEPENDENCY_MANIFEST,
    "gemfile": FileClassification.DEPENDENCY_MANIFEST,
}

# Language extension mapping
EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    ".cbl": "cobol",
    ".cob": "cobol",
    ".cpy": "cobol",
    ".jcl": "jcl",
    ".sql": "sql",
    ".ddl": "sql",
    ".py": "python",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".sh": "bash",
    ".bash": "bash",
    ".rb": "ruby",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".php": "php",
    ".xml": "xml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
}


class FileInventoryRecord(BaseModel):
    """Deterministic metadata for a single file in the codebase."""
    relative_path: str
    absolute_path: str
    extension: str
    language: Optional[str] = None
    classification: FileClassification = FileClassification.SOURCE
    size_bytes: int = 0
    loc: int = 0
    nloc: int = 0
    is_binary: bool = False
    is_generated: bool = False
    is_entrypoint: bool = False
    has_api: bool = False
    has_database: bool = False
    sha256: str = ""


class CodebaseInventory(BaseModel):
    """Complete inventory scorecard for a customer codebase."""
    root_path: str
    total_files: int = 0
    total_directories: int = 0
    total_loc: int = 0
    total_nloc: int = 0
    language_breakdown: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    classification_breakdown: Dict[str, int] = Field(default_factory=dict)
    files: List[FileInventoryRecord] = Field(default_factory=list)
    entrypoints: List[str] = Field(default_factory=list)
    schema_artifacts: List[str] = Field(default_factory=list)
    build_files: List[str] = Field(default_factory=list)
    dependency_manifests: List[str] = Field(default_factory=list)
    test_files: List[str] = Field(default_factory=list)
    binary_files: List[str] = Field(default_factory=list)
    unsupported_files: List[str] = Field(default_factory=list)


class CodebaseInventoryEngine:
    """
    Scans a source tree and generates a deterministic, reproducible inventory.
    """

    def __init__(self, root_dir: Path, excluded_patterns: Optional[List[str]] = None):
        self.root_dir = Path(root_dir).resolve()
        self.excluded_patterns = excluded_patterns or [
            ".git", "node_modules", "__pycache__", ".venv", ".DS_Store", "target", "build"
        ]

    def _is_excluded(self, path: Path) -> bool:
        rel_str = str(path.relative_to(self.root_dir))
        for pat in self.excluded_patterns:
            if pat in rel_str.split(os.sep) or rel_str.startswith(pat):
                return True
        return False

    def _is_binary(self, path: Path) -> bool:
        if path.suffix.lower() in BINARY_EXTENSIONS:
            return True
        # Read initial chunk to detect null bytes
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024)
                if b"\x00" in chunk:
                    return True
        except Exception:
            return True
        return False

    def _compute_loc_nloc(self, path: Path, language: Optional[str]) -> Tuple[int, int]:
        """Calculates physical LOC and non-comment/non-blank NLOC deterministically."""
        loc = 0
        nloc = 0
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    loc += 1
                    s = line.strip()
                    if not s:
                        continue
                    # Language-specific comment heuristics
                    if language == "cobol":
                        # In COBOL, column 7 (index 6) '*' or '/' indicates comment
                        if len(line) > 6 and line[6] in ('*', '/', 'D', 'd'):
                            continue
                        if s.startswith("*>"):
                            continue
                    elif language in ("python", "bash"):
                        if s.startswith("#"):
                            continue
                    elif language in ("java", "c", "cpp", "javascript", "typescript", "csharp", "go", "rust"):
                        if s.startswith("//") or s.startswith("/*") or s.startswith("*"):
                            continue
                    elif language == "sql":
                        if s.startswith("--") or s.startswith("/*") or s.startswith("*"):
                            continue
                    elif language == "jcl":
                        if s.startswith("//*"):
                            continue
                    nloc += 1
        except Exception:
            pass
        return loc, nloc

    def _detect_entrypoint(self, content: str, language: Optional[str], filename: str) -> bool:
        if language == "cobol":
            return bool(re.search(r"\bPROCEDURE\s+DIVISION\b", content, re.IGNORECASE))
        if language == "python":
            return '__name__ == "__main__"' in content or "__name__ == '__main__'" in content
        if language == "java":
            return "public static void main(" in content or "@SpringBootApplication" in content
        if language == "c" or language == "cpp":
            return bool(re.search(r"\bint\s+main\s*\(", content))
        if language == "jcl":
            return True  # JCL jobs are batch entrypoints
        return False

    def _detect_api_or_db(self, content: str, language: Optional[str]) -> Tuple[bool, bool]:
        has_api = False
        has_db = False

        if language == "cobol":
            if re.search(r"\bEXEC\s+SQL\b", content, re.IGNORECASE):
                has_db = True
            if re.search(r"\bEXEC\s+CICS\b", content, re.IGNORECASE):
                has_api = True
        elif language == "sql":
            has_db = True
        else:
            if any(term in content for term in ("SELECT ", "INSERT INTO", "UPDATE ", "DELETE FROM", "cursor.execute", "session.query")):
                has_db = True
            if any(term in content for term in ("@app.", "@router.", "FastAPI", "Flask", "@GetMapping", "@PostMapping", "@RestController")):
                has_api = True

        return has_api, has_db

    def _is_generated(self, content: str) -> bool:
        lower = content[:500].lower()
        return any(term in lower for term in ("generated by", "auto-generated", "do not edit", "code generated"))

    def analyze(self) -> CodebaseInventory:
        """Runs the deterministic inventory scan."""
        import hashlib

        files_list: List[FileInventoryRecord] = []
        dir_count = 0
        total_loc = 0
        total_nloc = 0
        lang_stats: Dict[str, Dict[str, int]] = {}
        class_stats: Dict[str, int] = {}
        entrypoints: List[str] = []
        schemas: List[str] = []
        builds: List[str] = []
        manifests: List[str] = []
        tests: List[str] = []
        binaries: List[str] = []
        unsupported: List[str] = []

        for root, dirs, filenames in os.walk(self.root_dir):
            curr_path = Path(root)
            if self._is_excluded(curr_path):
                continue
            dir_count += len(dirs)

            for fname in sorted(filenames):
                fpath = curr_path / fname
                if self._is_excluded(fpath) or is_sensitive_path(str(fpath)):
                    continue

                rel_path = str(fpath.relative_to(self.root_dir))
                ext = fpath.suffix.lower()
                size = fpath.stat().st_size
                is_bin = self._is_binary(fpath)

                # Classification heuristics
                classification = FileClassification.SOURCE
                base_lower = fname.lower()

                if is_bin:
                    classification = FileClassification.BINARY
                elif base_lower in BUILD_MANIFEST_MAP:
                    classification = BUILD_MANIFEST_MAP[base_lower]
                elif "test" in base_lower or base_lower.startswith("test_") or base_lower.endswith("_test.py") or base_lower.endswith("test.java"):
                    classification = FileClassification.TEST
                elif ext in (".sql", ".ddl") or (ext in (".cbl", ".cpy") and "schema" in base_lower):
                    classification = FileClassification.SCHEMA
                elif ext in (".json", ".yaml", ".yml", ".ini", ".conf", ".cfg"):
                    classification = FileClassification.CONFIG
                elif ext in (".md", ".rst", ".txt", ".adoc"):
                    classification = FileClassification.DOCUMENTATION

                lang = EXTENSION_LANGUAGE_MAP.get(ext)
                if not lang and not is_bin:
                    classification = FileClassification.UNSUPPORTED

                loc, nloc = 0, 0
                is_gen = False
                is_entry = False
                has_api = False
                has_db = False
                sha256_hash = ""

                try:
                    with open(fpath, "rb") as bf:
                        content_bytes = bf.read()
                        sha256_hash = hashlib.sha256(content_bytes).hexdigest()

                    if not is_bin:
                        text_content = content_bytes.decode("utf-8", errors="replace")
                        loc, nloc = self._compute_loc_nloc(fpath, lang)
                        is_gen = self._is_generated(text_content)
                        is_entry = self._detect_entrypoint(text_content, lang, fname)
                        has_api, has_db = self._detect_api_or_db(text_content, lang)
                except Exception:
                    pass

                rec = FileInventoryRecord(
                    relative_path=rel_path,
                    absolute_path=str(fpath),
                    extension=ext,
                    language=lang,
                    classification=classification,
                    size_bytes=size,
                    loc=loc,
                    nloc=nloc,
                    is_binary=is_bin,
                    is_generated=is_gen,
                    is_entrypoint=is_entry,
                    has_api=has_api,
                    has_database=has_db,
                    sha256=sha256_hash,
                )
                files_list.append(rec)

                # Aggregations
                total_loc += loc
                total_nloc += nloc
                c_name = classification.value
                class_stats[c_name] = class_stats.get(c_name, 0) + 1

                if lang:
                    if lang not in lang_stats:
                        lang_stats[lang] = {"files": 0, "loc": 0, "nloc": 0}
                    lang_stats[lang]["files"] += 1
                    lang_stats[lang]["loc"] += loc
                    lang_stats[lang]["nloc"] += nloc

                if is_entry:
                    entrypoints.append(rel_path)
                if classification == FileClassification.SCHEMA:
                    schemas.append(rel_path)
                elif classification == FileClassification.BUILD:
                    builds.append(rel_path)
                elif classification == FileClassification.DEPENDENCY_MANIFEST:
                    manifests.append(rel_path)
                elif classification == FileClassification.TEST:
                    tests.append(rel_path)
                elif classification == FileClassification.BINARY:
                    binaries.append(rel_path)
                elif classification == FileClassification.UNSUPPORTED:
                    unsupported.append(rel_path)

        return CodebaseInventory(
            root_path=str(self.root_dir),
            total_files=len(files_list),
            total_directories=dir_count,
            total_loc=total_loc,
            total_nloc=total_nloc,
            language_breakdown=lang_stats,
            classification_breakdown=class_stats,
            files=files_list,
            entrypoints=entrypoints,
            schema_artifacts=schemas,
            build_files=builds,
            dependency_manifests=manifests,
            test_files=tests,
            binary_files=binaries,
            unsupported_files=unsupported,
        )
