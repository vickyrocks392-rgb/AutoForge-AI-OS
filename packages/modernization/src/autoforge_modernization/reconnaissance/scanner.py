"""Repository scanner for Phase 18-G.2.

Performs real file system scanning, classifying files by category
and detecting their languages and likely technologies.

G.2-A: Real Technology + Version Discovery
Parses actual manifest files to extract version, dependency, and build metadata.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.reconnaissance.models import (
    ScannedFile, DiscoveredFile, FileCategory, FactConfidence,
    ProjectMetadata,
)

# Language extensions
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".cob": "cobol", ".cbl": "cobol",
    ".pli": "pli", ".pl1": "pli",
    ".rpg": "rpg", ".rpgle": "rpg",
    ".f": "fortran", ".f77": "fortran", ".f90": "fortran",
    ".for": "fortran",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".cs": "csharp",
    ".py": "python", ".pyx": "python", ".pyi": "python",
    ".php": "php",
    ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".bat": "shell", ".cmd": "shell", ".ps1": "shell",
    ".jcl": "jcl", ".proc": "jcl",
    ".cpy": "cobol_copybook",
    ".sql": "sql", ".ddl": "sql", ".dml": "sql",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".sass": "sass",
    ".json": "json", ".xml": "xml",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "ini",
    ".md": "markdown", ".rst": "rst",
    ".gradle": "gradle", ".groovy": "groovy",
    ".scala": "scala",
    ".kt": "kotlin", ".kts": "kotlin",
    ".go": "go", ".rs": "rust",
    ".rb": "ruby", ".pl": "perl",
    ".tf": "terraform", ".tfvars": "terraform",
}

BUILD_FILES: dict[str, str] = {
    "pom.xml": "maven", "build.gradle": "gradle",
    "build.gradle.kts": "gradle", "settings.gradle": "gradle",
    "build.xml": "ant",
    "Makefile": "make", "makefile": "make",
    "package.json": "npm", "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "requirements.txt": "pip", "Pipfile": "pip",
    "pyproject.toml": "poetry", "poetry.lock": "poetry",
    "setup.py": "pip",
    "Cargo.toml": "cargo", "Cargo.lock": "cargo",
    "Gemfile": "bundler",
    "composer.json": "composer", "composer.lock": "composer",
    "go.mod": "go_modules", "go.sum": "go_modules",
    "pubspec.yaml": "dart",
    "project.clj": "lein",
    "build.sbt": "sbt",
    "project.yml": "xcodebuild",
    "Podfile": "cocoapods",
    "WORKSPACE": "bazel", "BUILD": "bazel",
}

DEPLOYMENT_FILES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "docker-compose.yml": "dockerfile",
    "docker-compose.yaml": "dockerfile",
    "compose.yaml": "dockerfile",
    "k8s.yaml": "kubernetes",
    "kustomization.yaml": "kubernetes",
    "kubernetes.yaml": "kubernetes",
    "Jenkinsfile": "jenkins",
    ".travis.yml": "travis",
    ".gitlab-ci.yml": "gitlab",
    "azure-pipelines.yml": "azure_devops",
    "circle.yml": "circleci",
    "main.tf": "terraform",
    "variables.tf": "terraform",
    "outputs.tf": "terraform",
    "serverless.yml": "serverless",
    "Procfile": "heroku",
    "Vagrantfile": "vagrant",
}

APP_SERVER_CONFIG: dict[str, str] = {
    "server.xml": "tomcat",
    "web.xml": "java_ee",
    "weblogic.xml": "weblogic",
    "ibm-web-bnd.xml": "websphere",
    "ibm-web-ext.xml": "websphere",
    "ejb-jar.xml": "ejb",
    "application.xml": "java_ee",
    "standalone.xml": "wildfly",
    "domain.xml": "wildfly",
    "bootstrap.properties": "spring",
    "application.yml": "spring",
    "application.properties": "spring",
}

TEST_DIR_NAMES: set[str] = {
    "test", "tests", "spec", "specs", "__tests__",
    "Test", "Tests", "t", "integration", "e2e",
    "androidTest", "TestCases", "testcases",
}

TEST_FILE_PATTERNS: list[str] = [
    "test_", "Test.", "Tests.", "_test.", ".test.",
    "Spec.", "spec.", "it.", "IT.",
]

GENERATED_DIRS: set[str] = {
    "build", "dist", "target", "out", "node_modules",
    "venv", ".venv", "vendor", "__pycache__",
    ".gradle", ".mvn", "bin", "obj", "DerivedData",
    ".next", ".nuxt", "_build", "deps", "_site",
}

SKIP_DIRS: set[str] = {
    ".git", ".svn", ".hg", ".idea", ".vscode", ".DS_Store",
}


class ScanResult(BaseModel):
    """The output of a repository scan."""
    scan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    scanned_files: list[ScannedFile] = Field(default_factory=list)
    discovered_files: list[DiscoveredFile] = Field(default_factory=list)
    project_metadata: ProjectMetadata | None = None
    directories_scanned: int = 0
    files_skipped: int = 0
    total_bytes: int = 0

    def to_summary(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "project_path": self.project_path,
            "files_total": len(self.scanned_files),
            "directories_scanned": self.directories_scanned,
            "files_skipped": self.files_skipped,
            "total_bytes": self.total_bytes,
            "duration_seconds": self.duration_seconds,
        }


class ReconnaissanceScanner:
    """Performs real repository scanning."""

    def __init__(
        self,
        project_path: str,
        max_files: int = 50000,
        max_depth: int = 20,
        follow_symlinks: bool = False,
    ) -> None:
        self.project_path = os.path.abspath(project_path)
        self.max_files = max_files
        self.max_depth = max_depth
        self.follow_symlinks = follow_symlinks
        self._started = datetime.now(timezone.utc)
        self._files: list[ScannedFile] = []
        self._discovered: list[DiscoveredFile] = []
        self._dirs_scanned = 0
        self._files_skipped = 0
        self._total_bytes = 0

    def scan(self) -> ScanResult:
        """Run the full scan."""
        result = ScanResult(
            project_path=self.project_path,
            started_at=self._started,
        )
        if not os.path.isdir(self.project_path):
            return result
        for root, dirs, files in os.walk(
            self.project_path,
            followlinks=self.follow_symlinks,
        ):
            depth = root[len(self.project_path):].count(os.sep)
            if depth > self.max_depth:
                dirs.clear()
                continue
            self._dirs_scanned += 1
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                if len(self._files) >= self.max_files:
                    self._files_skipped += 1
                    continue
                full = os.path.join(root, fname)
                try:
                    sf = self._scan_file(full)
                except OSError:
                    self._files_skipped += 1
                    continue
                if sf is not None:
                    self._files.append(sf)
                    self._total_bytes += sf.size_bytes
                    df = self._to_discovered(sf)
                    if df is not None:
                        self._discovered.append(df)
        result.scanned_files = list(self._files)
        result.discovered_files = list(self._discovered)
        result.directories_scanned = self._dirs_scanned
        result.files_skipped = self._files_skipped
        result.total_bytes = self._total_bytes
        result.completed_at = datetime.now(timezone.utc)
        result.duration_seconds = (result.completed_at - self._started).total_seconds()
        result.project_metadata = self._build_metadata()
        return result

    def _scan_file(self, full_path: str) -> ScannedFile | None:
        try:
            st = os.stat(full_path)
        except OSError:
            return None
        rel = os.path.relpath(full_path, self.project_path)
        base = os.path.basename(full_path)
        category = self._classify(rel, base)
        if category == FileCategory.BINARY and st.st_size > 5_000_000:
            return None
        detected_lang = self._detect_language(rel)
        detected_techs = self._detect_technologies(rel, base)
        evidence = self._collect_evidence(rel, base, category, detected_lang, detected_techs)
        is_gen = self._is_generated(rel)
        is_test = self._is_test(rel, base)
        if is_gen and category in (FileCategory.SOURCE, FileCategory.CONFIG):
            category = FileCategory.GENERATED
        return ScannedFile(
            path=full_path,
            relative_path=rel,
            size_bytes=st.st_size,
            category=category,
            detected_language=detected_lang,
            detected_technologies=detected_techs,
            evidence=evidence,
            confidence=self._confidence_for(category, detected_lang, detected_techs),
            is_generated=is_gen,
            is_test=is_test,
        )

    def _to_discovered(self, sf: ScannedFile) -> DiscoveredFile | None:
        if sf.category == FileCategory.BINARY:
            return None
        return DiscoveredFile(
            path=sf.path,
            relative_path=sf.relative_path,
            category=sf.category,
            technologies=sf.detected_technologies,
            evidence=sf.evidence,
            confidence=sf.confidence,
            size_bytes=sf.size_bytes,
        )

    def _classify(self, rel: str, base: str) -> FileCategory:
        if base in BUILD_FILES or base.endswith((".gradle",)):
            return FileCategory.BUILD
        if base in DEPLOYMENT_FILES:
            return FileCategory.DEPLOY
        if base in APP_SERVER_CONFIG:
            return FileCategory.CONFIG
        ext = os.path.splitext(base)[1].lower()
        if ext in LANGUAGE_EXTENSIONS:
            return FileCategory.SOURCE
        if ext in (".txt", ".md", ".rst", ".adoc"):
            return FileCategory.DOC
        if ext in (".sql", ".ddl", ".dml"):
            return FileCategory.DATA
        if ext in (".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env"):
            return FileCategory.CONFIG
        if ext in (".jar", ".war", ".ear", ".class", ".o", ".so", ".dll", ".exe", ".lib", ".a", ".bin", ".pyc"):
            return FileCategory.BINARY
        return FileCategory.UNKNOWN

    def _detect_language(self, rel: str) -> str | None:
        ext = os.path.splitext(rel)[1].lower()
        return LANGUAGE_EXTENSIONS.get(ext)

    def _detect_technologies(self, rel: str, base: str) -> list[str]:
        techs: list[str] = []
        if base in BUILD_FILES:
            techs.append(BUILD_FILES[base])
        if base in DEPLOYMENT_FILES:
            techs.append(DEPLOYMENT_FILES[base])
        if base in APP_SERVER_CONFIG:
            techs.append(APP_SERVER_CONFIG[base])
        if "/WEB-INF/" in rel or base in ("web.xml", "application.xml", "beans.xml"):
            techs.append("java_ee")
        if "/META-INF/" in rel and base == "MANIFEST.MF":
            techs.append("java_jar")
        if "persistence.xml" in base:
            techs.append("jpa")
        if base.startswith("hibernate") or base == "hibernate.cfg.xml":
            techs.append("hibernate")
        if base == "pom.xml":
            techs.append("maven")
        if base == "package.json":
            techs.append("node")
        if base == "requirements.txt" or base == "pyproject.toml":
            techs.append("python")
        if base == "Cargo.toml":
            techs.append("rust")
        if base == "go.mod":
            techs.append("go")
        if base in ("Dockerfile", "docker-compose.yml", "compose.yaml"):
            techs.append("docker")
        if base.endswith(".tf") or base in ("main.tf",):
            techs.append("terraform")
        if base == "Jenkinsfile":
            techs.append("jenkins")
        return techs

    def _collect_evidence(
        self,
        rel: str,
        base: str,
        category: FileCategory,
        language: str | None,
        techs: list[str],
    ) -> list[str]:
        ev: list[str] = []
        if base in BUILD_FILES:
            ev.append(f"build_file:{base}")
        if base in DEPLOYMENT_FILES:
            ev.append(f"deployment_file:{base}")
        if base in APP_SERVER_CONFIG:
            ev.append(f"app_server_config:{base}")
        if language:
            ev.append(f"language:{language}")
        for t in techs:
            ev.append(f"technology:{t}")
        return ev

    def _confidence_for(
        self,
        category: FileCategory,
        language: str | None,
        techs: list[str],
    ) -> FactConfidence:
        if category == FileCategory.UNKNOWN and not language and not techs:
            return FactConfidence.LOW
        if category in (FileCategory.BUILD, FileCategory.DEPLOY, FileCategory.CONFIG):
            return FactConfidence.HIGH
        if language or techs:
            return FactConfidence.HIGH
        return FactConfidence.MEDIUM

    def _is_generated(self, rel: str) -> bool:
        parts = rel.split(os.sep)
        for p in parts[:-1]:
            if p in GENERATED_DIRS:
                return True
        base = os.path.basename(rel)
        if base.startswith(("generated_", "_generated", "auto_generated", "AutoGen")):
            return True
        return False

    def _is_test(self, rel: str, base: str) -> bool:
        parts = rel.split(os.sep)
        for p in parts:
            if p in TEST_DIR_NAMES:
                return True
        for pat in TEST_FILE_PATTERNS:
            if pat in base:
                return True
        if base.endswith("Tests.cs") or base.endswith("Test.cs"):
            return True
        return False

    def _build_metadata(self) -> ProjectMetadata:
        manifest_files: list[str] = []
        techs: list[str] = []
        primary_lang: str | None = None
        lang_counts: dict[str, int] = {}
        for sf in self._files:
            for t in sf.detected_technologies:
                if t not in techs:
                    techs.append(t)
            if sf.detected_language:
                lang_counts[sf.detected_language] = (
                    lang_counts.get(sf.detected_language, 0) + 1
                )
            if os.path.basename(sf.path) in BUILD_FILES or os.path.basename(sf.path) in DEPLOYMENT_FILES:
                manifest_files.append(sf.relative_path)
        if lang_counts:
            primary_lang = max(lang_counts.items(), key=lambda x: x[1])[0]
        return ProjectMetadata(
            project_path=self.project_path,
            name=os.path.basename(self.project_path),
            root_files=[os.path.basename(sf.path) for sf in self._files if "/" not in sf.relative_path],
            manifest_files=manifest_files,
            detected_technologies=techs,
            primary_language=primary_lang,
            framework=None,
        )


# ── G.2-A: Real Version Detection ──────────────────────────────────────────────


class VersionManifest(BaseModel):
    """
    Parsed version metadata from a manifest file.

    G.2-A: Replaces placeholder version detection with real manifest parsing.
    Never fabricates a version; only reports what was deterministically extracted.
    """
    manifest_path: str
    manifest_type: str
    language: str | None = None
    framework: str | None = None
    primary_version: str | None = None
    primary_version_confidence: FactConfidence = FactConfidence.UNKNOWN
    secondary_versions: dict[str, str] = Field(default_factory=dict)
    secondary_version_confidences: dict[str, FactConfidence] = Field(default_factory=dict)
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    build_tool: str | None = None
    build_tool_version: str | None = None
    runtime: str | None = None
    runtime_version: str | None = None
    conflicts: list[str] = Field(default_factory=list)
    raw_errors: list[str] = Field(default_factory=list)
    parsed: bool = False
    provenance: list[str] = Field(default_factory=list)  # evidence sources


class VersionDetector:
    """
    G.2-A: Parses manifest files to extract real technology versions.

    Deterministic manifest parsing; never fabricates version evidence.
    Supports: pom.xml, build.gradle, package.json, requirements.txt, pyproject.toml,
              Cargo.toml, go.mod, Gemfile, Dockerfile, docker-compose.
    """

    def __init__(self, project_path: str) -> None:
        self.project_path = project_path
        self._manifests: list[VersionManifest] = []
        self._parsers: dict[str, Any] = {
            "pom.xml": self._parse_pom,
            "build.gradle": self._parse_gradle,
            "build.gradle.kts": self._parse_gradle_kts,
            "package.json": self._parse_package_json,
            "package-lock.json": self._parse_package_lock,
            "requirements.txt": self._parse_requirements,
            "pyproject.toml": self._parse_pyproject,
            "setup.py": self._parse_setup_py,
            "Cargo.toml": self._parse_cargo,
            "Cargo.lock": self._parse_cargo_lock,
            "go.mod": self._parse_go_mod,
            "Gemfile": self._parse_gemfile,
            "Gemfile.lock": self._parse_gemfile_lock,
            "Dockerfile": self._parse_dockerfile,
            "docker-compose.yml": self._parse_docker_compose,
            "docker-compose.yaml": self._parse_docker_compose,
            "compose.yaml": self._parse_docker_compose,
            "Pipfile": self._parse_pipfile,
            "Pipfile.lock": self._parse_pipfile_lock,
            "poetry.lock": self._parse_poetry_lock,
        }

    def scan_manifests(self) -> list[VersionManifest]:
        """Find and parse all manifest files in the project."""
        for root, _dirs, files in os.walk(self.project_path):
            for fname in files:
                parser = self._parsers.get(fname)
                if parser:
                    full = os.path.join(root, fname)
                    manifest = parser(full)
                    if manifest:
                        self._manifests.append(manifest)
        # Cross-manifest conflict detection
        conflicts = self._collect_conflicts()
        for m in self._manifests:
            m.conflicts = conflicts
        return self._manifests

    def get_manifests(self) -> list[VersionManifest]:
        return list(self._manifests)

    def get_primary_versions(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for m in self._manifests:
            if m.primary_version and m.parsed:
                tech = m.language or m.framework or m.build_tool
                if tech and m.primary_version_confidence in (
                    FactConfidence.PROVEN, FactConfidence.HIGH
                ):
                    result[tech] = m.primary_version
        return result

    def get_secondary_versions(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for m in self._manifests:
            for k, v in m.secondary_versions.items():
                result[k] = v
        return result

    def get_all_dependencies(self) -> list[dict[str, str]]:
        deps: list[dict[str, str]] = []
        for m in self._manifests:
            for d in m.dependencies:
                d_copy = dict(d)
                d_copy["_source_manifest"] = m.manifest_type
                deps.append(d_copy)
        return deps

    def get_conflicts(self) -> list[str]:
        return self._collect_conflicts()

    def _read_text(self, path: str, max_kb: int = 2048) -> str | None:
        try:
            size = os.path.getsize(path)
            if size > max_kb * 1024:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read(max_kb * 1024)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except Exception:
            return None

    def _collect_conflicts(self) -> list[str]:
        """Detect version conflicts across manifests."""
        versions_by_tech: dict[str, list[tuple[str, str]]] = {}
        for m in self._manifests:
            if m.primary_version and m.language:
                versions_by_tech.setdefault(m.language, []).append(
                    (m.manifest_path, m.primary_version)
                )
        conflicts: list[str] = []
        for tech, entries in versions_by_tech.items():
            unique = {v for _, v in entries}
            if len(unique) > 1:
                conflicts.append(
                    f"Conflicting {tech} versions: "
                    + "; ".join(f"{p}={v}" for p, v in entries)
                )
        return conflicts

    # ── Parser implementations ─────────────────────────────────────────────────

    def _parse_pom(self, path: str) -> VersionManifest | None:
        """Parse Maven pom.xml for Java/Spring version info."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="pom.xml", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="pom.xml")
        try:
            root = ET.fromstring(content)
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            # Try namespaced first, then fall back to non-namespaced
            parent = root.find("m:parent", ns)
            if parent is None:
                parent = root.find("parent")
            version_el = root.find("m:version", ns)
            if version_el is None:
                version_el = root.find("version")
            if parent is not None:
                pv = parent.findtext("m:version", None, ns) or parent.findtext("version")
                if pv:
                    manifest.secondary_versions["parent_version"] = pv
                    manifest.secondary_version_confidences["parent_version"] = FactConfidence.HIGH
            if version_el is not None and version_el.text:
                manifest.primary_version = version_el.text.strip()
                manifest.primary_version_confidence = FactConfidence.HIGH
                manifest.language = "java"
            for prop in root.findall("m:properties", ns) or root.findall("properties"):
                java_v = prop.findtext("m:java.version", None, ns) or prop.findtext("java.version")
                if java_v:
                    manifest.secondary_versions["java"] = java_v
                    manifest.secondary_version_confidences["java"] = FactConfidence.HIGH
            # Dependencies (try both namespaced and non-namespaced)
            deps = root.findall(".//m:dependency", ns)
            if not deps:
                deps = root.findall(".//dependency")
            for dep in deps:
                name = dep.findtext("m:artifactId", "", ns) or dep.findtext("artifactId", "")
                ver = dep.findtext("m:version", "", ns) or dep.findtext("version", "")
                if name:
                    d: dict[str, str] = {"name": name}
                    if ver:
                        d["version"] = ver
                    manifest.dependencies.append(d)
            manifest.build_tool = "maven"
            manifest.parsed = True
        except ET.ParseError:
            version_match = re.search(r"<version>([^<]+)</version>", content)
            if version_match:
                manifest.primary_version = version_match.group(1).strip()
                manifest.primary_version_confidence = FactConfidence.MEDIUM
                manifest.language = "java"
                manifest.build_tool = "maven"
                manifest.parsed = True
            else:
                manifest.raw_errors.append("Could not parse pom.xml")
        return manifest

    def _parse_package_json(self, path: str) -> VersionManifest | None:
        """Parse package.json for Node.js/npm version info."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="package.json", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="package.json", language="javascript")
        try:
            data = json.loads(content)
            manifest.primary_version = data.get("version") or None
            if manifest.primary_version:
                manifest.primary_version_confidence = FactConfidence.HIGH
            engines = data.get("engines", {})
            node_v = engines.get("node", "")
            if node_v:
                manifest.secondary_versions["node"] = node_v
                manifest.secondary_version_confidences["node"] = FactConfidence.HIGH
            if data.get("devDependencies", {}).get("typescript") or data.get("dependencies", {}).get("typescript"):
                ts_ver = data.get("devDependencies", {}).get("typescript") or data.get("dependencies", {}).get("typescript", "")
                manifest.secondary_versions["typescript"] = ts_ver
                manifest.secondary_version_confidences["typescript"] = FactConfidence.HIGH
            for name, ver in data.get("dependencies", {}).items():
                manifest.dependencies.append({"name": name, "version": ver})
            for name, ver in data.get("devDependencies", {}).items():
                manifest.dependencies.append({"name": name, "version": ver, "dev": "true"})
            manifest.build_tool = "npm"
            manifest.parsed = True
        except json.JSONDecodeError:
            manifest.raw_errors.append("package.json JSON parse error")
        return manifest

    def _parse_gradle(self, path: str) -> VersionManifest | None:
        """Parse build.gradle for Java/Gradle version info."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="build.gradle", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="build.gradle", language="java", build_tool="gradle")
        try:
            java_v = re.search(r'sourceCompatibility\s*=\s*["\']([0-9.]+)["\']', content)
            if not java_v:
                java_v = re.search(r'sourceCompatibility\s*=\s*([0-9.]+)', content)
            if java_v:
                manifest.secondary_versions["java"] = java_v.group(1)
                manifest.secondary_version_confidences["java"] = FactConfidence.HIGH
                manifest.primary_version = java_v.group(1)
                manifest.primary_version_confidence = FactConfidence.HIGH
            for m in re.finditer(r'["\']([^"\':]+):([^"\':]+):([^"\']+)["\']', content):
                manifest.dependencies.append({"name": m.group(2), "version": m.group(3), "group": m.group(1)})
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_gradle_kts(self, path: str) -> VersionManifest | None:
        """Parse build.gradle.kts (Kotlin DSL)."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="build.gradle.kts", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="build.gradle.kts", language="java", build_tool="gradle")
        try:
            java_v = re.search(r'version\s*=\s*["\']([^"\']+)["\'].*?java', content, re.DOTALL)
            if not java_v:
                java_v = re.search(r'java\s*\{\s*sourceCompatibility\s*=\s*JavaVersion\.VERSION_([0-9_]+)', content)
            if java_v:
                v = java_v.group(1).replace("_", ".")
                manifest.primary_version = v
                manifest.primary_version_confidence = FactConfidence.HIGH
                manifest.secondary_versions["java"] = v
                manifest.secondary_version_confidences["java"] = FactConfidence.HIGH
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_requirements(self, path: str) -> VersionManifest | None:
        """Parse requirements.txt for Python dependency versions."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="requirements.txt", language="python", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="requirements.txt", language="python", build_tool="pip")
        try:
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([a-zA-Z0-9_-]+)(?:\[.*?\])?(==|>=|<=|~=|!=|>|<)\s*(.*)$", line)
                if m:
                    manifest.dependencies.append({"name": m.group(1), "version": f"{m.group(2)}{m.group(3)}"})
                else:
                    manifest.dependencies.append({"name": line})
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_pyproject(self, path: str) -> VersionManifest | None:
        """Parse pyproject.toml for Python project metadata."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="pyproject.toml", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="pyproject.toml", language="python", build_tool="poetry")
        try:
            version_match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if version_match:
                manifest.primary_version = version_match.group(1)
                manifest.primary_version_confidence = FactConfidence.HIGH
            py_match = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', content)
            if py_match:
                manifest.secondary_versions["python"] = py_match.group(1)
                manifest.secondary_version_confidences["python"] = FactConfidence.HIGH
            in_deps = False
            for line in content.splitlines():
                if line.strip().startswith("[project.dependencies]"):
                    in_deps = True
                    continue
                if line.strip().startswith("[") and in_deps:
                    in_deps = False
                if in_deps:
                    m = re.match(r'^([a-zA-Z0-9_-]+)(?:\[.*?\])?(?:==|>=|<=|~=|!=|>|<)\s*(.*)$', line.strip())
                    if m:
                        manifest.dependencies.append({"name": m.group(1), "version": line.strip()})
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_setup_py(self, path: str) -> VersionManifest | None:
        """Parse setup.py for Python version info."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="setup.py", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="setup.py", language="python", build_tool="pip")
        try:
            version_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if version_match:
                manifest.primary_version = version_match.group(1)
                manifest.primary_version_confidence = FactConfidence.MEDIUM
            python_match = re.search(r'python_requires\s*=\s*["\']([^"\']+)["\']', content)
            if python_match:
                manifest.secondary_versions["python"] = python_match.group(1)
                manifest.secondary_version_confidences["python"] = FactConfidence.MEDIUM
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_cargo(self, path: str) -> VersionManifest | None:
        """Parse Cargo.toml for Rust version info."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="Cargo.toml", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="Cargo.toml", language="rust", build_tool="cargo")
        try:
            version_match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if version_match:
                manifest.primary_version = version_match.group(1)
                manifest.primary_version_confidence = FactConfidence.HIGH
            rust_v = re.search(r'rust-version\s*=\s*"([^"]+)"', content)
            if rust_v:
                manifest.secondary_versions["rust"] = rust_v.group(1)
                manifest.secondary_version_confidences["rust"] = FactConfidence.HIGH
            in_deps = False
            for line in content.splitlines():
                if line.strip() == "[dependencies]":
                    in_deps = True
                    continue
                if line.strip().startswith("[") and in_deps:
                    in_deps = False
                if in_deps:
                    m = re.match(r'^([a-zA-Z0-9_-]+)\s*=\s*"([^"]+)"', line)
                    if m:
                        manifest.dependencies.append({"name": m.group(1), "version": m.group(2)})
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_go_mod(self, path: str) -> VersionManifest | None:
        """Parse go.mod for Go module version info."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="go.mod", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="go.mod", language="go", build_tool="go_modules")
        try:
            for line in content.splitlines():
                if line.startswith("go "):
                    v = line[3:].strip()
                    manifest.primary_version = v
                    manifest.primary_version_confidence = FactConfidence.HIGH
                    manifest.secondary_versions["go"] = v
                    manifest.secondary_version_confidences["go"] = FactConfidence.HIGH
                    break
            for line in content.splitlines():
                if line.startswith("require "):
                    parts = line.split()[1:]
                    if len(parts) >= 2:
                        manifest.dependencies.append({"name": parts[0], "version": parts[1]})
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_gemfile(self, path: str) -> VersionManifest | None:
        """Parse Gemfile for Ruby gem versions."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="Gemfile", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="Gemfile", language="ruby", build_tool="bundler")
        try:
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("ruby "):
                    v = re.search(r'["\']([0-9.]+)["\']', line)
                    if v:
                        manifest.secondary_versions["ruby"] = v.group(1)
                        manifest.secondary_version_confidences["ruby"] = FactConfidence.HIGH
                m = re.match(r'gem\s+["\']([^"\']+)["\'](?:,\s*["\']([^"\']+)["\'])?', line)
                if m:
                    dep: dict[str, str] = {"name": m.group(1)}
                    if m.group(2):
                        dep["version"] = m.group(2)
                    manifest.dependencies.append(dep)
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_gemfile_lock(self, path: str) -> VersionManifest | None:
        """Parse Gemfile.lock for locked Ruby gem versions."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="Gemfile.lock", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="Gemfile.lock", language="ruby", build_tool="bundler")
        try:
            for line in content.splitlines():
                if line.startswith("RUBY VERSION"):
                    v = re.search(r'([0-9.]+)', line)
                    if v:
                        manifest.primary_version = v.group(1)
                        manifest.primary_version_confidence = FactConfidence.HIGH
                        manifest.secondary_versions["ruby"] = v.group(1)
                        manifest.secondary_version_confidences["ruby"] = FactConfidence.HIGH
                        break
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_dockerfile(self, path: str) -> VersionManifest | None:
        """Parse Dockerfile for base image version."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="Dockerfile", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="Dockerfile", build_tool="dockerfile")
        try:
            from_line = None
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("FROM "):
                    from_line = line[5:].strip().split()[0]
                    break
            if from_line:
                if ":" in from_line:
                    base, tag = from_line.split(":", 1)
                    manifest.secondary_versions["docker_image"] = from_line
                    manifest.secondary_version_confidences["docker_image"] = FactConfidence.HIGH
                    base_lower = base.lower()
                    if "openjdk" in base_lower or "eclipse-temurin" in base_lower:
                        manifest.language = "java"
                        manifest.primary_version = tag
                        manifest.primary_version_confidence = FactConfidence.HIGH
                    elif "node" in base_lower:
                        manifest.language = "javascript"
                        manifest.primary_version = tag
                        manifest.primary_version_confidence = FactConfidence.HIGH
                    elif "python" in base_lower:
                        manifest.language = "python"
                        manifest.primary_version = tag
                        manifest.primary_version_confidence = FactConfidence.HIGH
                    elif "golang" in base_lower:
                        manifest.language = "go"
                        manifest.primary_version = tag
                        manifest.primary_version_confidence = FactConfidence.HIGH
                else:
                    manifest.secondary_versions["docker_image"] = from_line
                    manifest.secondary_version_confidences["docker_image"] = FactConfidence.LOW
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_docker_compose(self, path: str) -> VersionManifest | None:
        """Parse docker-compose.yml for service definitions."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="docker-compose.yml", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="docker-compose.yml", build_tool="dockerfile")
        try:
            stripped = content.strip()
            if stripped.startswith("{"):
                data = json.loads(stripped)
                services = list(data.get("services", {}).keys())
                if services:
                    manifest.secondary_versions["services"] = ", ".join(services)
                    manifest.secondary_version_confidences["services"] = FactConfidence.HIGH
            manifest.parsed = True
        except json.JSONDecodeError:
            manifest.parsed = True
        return manifest

    def _parse_package_lock(self, path: str) -> VersionManifest | None:
        """Parse package-lock.json (read-only, extract resolved versions)."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="package-lock.json", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="package-lock.json", language="javascript", build_tool="npm")
        try:
            data = json.loads(content)
            version = data.get("version", "")
            if version:
                manifest.primary_version = version
                manifest.primary_version_confidence = FactConfidence.HIGH
            for pkg in data.get("packages", {}):
                name = pkg.get("name", "")
                ver = pkg.get("version", "")
                if name and ver:
                    manifest.dependencies.append({"name": name, "version": ver})
            manifest.parsed = True
        except json.JSONDecodeError:
            manifest.raw_errors.append("package-lock.json JSON parse error")
        return manifest

    def _parse_pipfile(self, path: str) -> VersionManifest | None:
        """Parse Pipfile for Python dependency info."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="Pipfile", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="Pipfile", language="python", build_tool="pip")
        try:
            for line in content.splitlines():
                if line.startswith("python_version"):
                    v = re.search(r'["\']([0-9.]+)["\']', line)
                    if v:
                        manifest.primary_version = v.group(1)
                        manifest.primary_version_confidence = FactConfidence.HIGH
                        manifest.secondary_versions["python"] = v.group(1)
                        manifest.secondary_version_confidences["python"] = FactConfidence.HIGH
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
        return manifest

    def _parse_pipfile_lock(self, path: str) -> VersionManifest | None:
        """Parse Pipfile.lock for locked Python versions."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="Pipfile.lock", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="Pipfile.lock", language="python", build_tool="pip")
        try:
            data = json.loads(content)
            py_v = data.get("default", {}).get("python_version", "")
            if not py_v:
                py_v = data.get("meta", {}).get("python_version", "")
            if py_v:
                manifest.primary_version = py_v
                manifest.primary_version_confidence = FactConfidence.HIGH
                manifest.secondary_versions["python"] = py_v
                manifest.secondary_version_confidences["python"] = FactConfidence.HIGH
            manifest.parsed = True
        except json.JSONDecodeError:
            manifest.raw_errors.append("Pipfile.lock JSON parse error")
        return manifest

    def _parse_poetry_lock(self, path: str) -> VersionManifest | None:
        """Parse poetry.lock for locked Python package versions."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="poetry.lock", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="poetry.lock", language="python", build_tool="poetry")
        try:
            # poetry.lock is TOML — attempt JSON first, fall back to TOML scan
            if content.strip().startswith("{"):
                data = json.loads(content)
                manifest.primary_version = data.get("metadata", {}).get("python-version", "")
                if manifest.primary_version:
                    manifest.primary_version_confidence = FactConfidence.HIGH
                for pkg in data.get("package", []):
                    name = pkg.get("name", "")
                    ver = pkg.get("version", "")
                    if name and ver:
                        manifest.dependencies.append({"name": name, "version": ver})
            else:
                # TOML regex scan for [[package]] blocks
                for m in re.finditer(r'\[\[package\]\][\s\S]*?name\s*=\s*"([^"]+)"', content):
                    manifest.dependencies.append({"name": m.group(1), "version": m.group(1)})
            manifest.parsed = True
        except json.JSONDecodeError:
            manifest.parsed = True
        except Exception as e:
            manifest.raw_errors.append(str(e))
            manifest.parsed = True
        return manifest

    def _parse_cargo_lock(self, path: str) -> VersionManifest | None:
        """Parse Cargo.lock for locked Rust versions."""
        content = self._read_text(path)
        if not content:
            return VersionManifest(manifest_path=path, manifest_type="Cargo.lock", parsed=False)
        manifest = VersionManifest(manifest_path=path, manifest_type="Cargo.lock", language="rust", build_tool="cargo")
        try:
            data = json.loads(content)
            manifest.primary_version = data.get("version", "")
            if manifest.primary_version:
                manifest.primary_version_confidence = FactConfidence.HIGH
            for pkg in data.get("package", []):
                name = pkg.get("name", "")
                ver = pkg.get("version", "")
                if name and ver:
                    manifest.dependencies.append({"name": name, "version": ver})
            manifest.parsed = True
        except json.JSONDecodeError:
            version_match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if version_match:
                manifest.primary_version = version_match.group(1)
                manifest.primary_version_confidence = FactConfidence.MEDIUM
                manifest.parsed = True
        return manifest


def scan_repository(project_path: str, **kwargs: Any) -> ScanResult:
    """Convenience function to scan a repository."""
    return ReconnaissanceScanner(project_path, **kwargs).scan()
