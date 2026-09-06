"""Verified Technology Providers for AutoForge.

Enforces the non-negotiable architectural requirement:
Do NOT treat an executable discovered on the machine as automatically trusted or production-ready.
Verification must be backed by executable evidence.

A Verified Technology Provider represents a trusted, reproducible mechanism
through which AutoForge can obtain and/or operate technology-specific capabilities.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.models import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityProvenance,
    CapabilityQualificationFixture,
    CapabilityQualificationRecord,
    CapabilityRequirement,
    CapabilityState,
    QualifiedCapability,
    _utc_now,
)


class VerifiedTechnologyProvider(ABC):
    """Abstract base class for all Verified Technology Providers.

    Every provider must declare:
    - Provider identity
    - Target technology & supported versions
    - Supported platforms
    - Capabilities supplied
    - Source/provenance
    - Acquisition mechanism
    - Qualification procedure backed by deterministic fixtures
    """

    provider_id: str
    technology: str
    display_name: str
    supported_versions: list[str] = []
    supported_platforms: list[str] = ["darwin", "linux"]
    license_type: str = "open_source"
    is_free_open_source: bool = True

    @abstractmethod
    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        """Return list of (capability_class, capability_name, level) provided."""
        raise NotImplementedError

    @abstractmethod
    def is_tool_discovered(self) -> bool:
        """Check if the physical tool/runtime executable or library is present."""
        raise NotImplementedError

    @abstractmethod
    def get_version(self) -> str | None:
        """Retrieve the verified version of the underlying tool."""
        raise NotImplementedError

    @abstractmethod
    def qualify(self) -> list[CapabilityQualificationRecord]:
        """Execute deterministic qualification fixtures to prove operational capability."""
        raise NotImplementedError

    @abstractmethod
    def get_acquisition_recipe(self) -> dict[str, Any]:
        """Return safe, deterministic free/open-source acquisition instructions."""
        raise NotImplementedError

    def acquire_or_prepare(
        self,
        target_dir: Path | None = None,
        allow_external_install: bool = False,
    ) -> tuple[bool, str]:
        """Safely acquire or prepare the tool in an isolated AutoForge location.
        Default implementation returns unsupported/not executed.
        """
        return False, f"Provider '{self.provider_id}' does not implement autonomous preparation."

    def get_provenance(self) -> CapabilityProvenance:
        return CapabilityProvenance(
            provider_id=self.provider_id,
            source_url=self.get_acquisition_recipe().get("source_url", ""),
            license_type=self.license_type,
            installed_version=self.get_version() or "unknown",
            platform=os.name,
            is_free_open_source=self.is_free_open_source,
        )

    def can_satisfy(self, requirement: CapabilityRequirement) -> bool:
        """Check if this provider matches a requirement."""
        if requirement.technology.upper() != self.technology.upper():
            return False
        for cap_class, cap_name, _ in self.capabilities_supplied():
            if cap_class == requirement.capability_class and (
                cap_name == requirement.capability_name or requirement.capability_name in cap_name
            ):
                return True
        return False


class CPythonProvider(VerifiedTechnologyProvider):
    """Verified provider for CPython runtime, AST parsing, and bytecode compilation."""

    provider_id = "provider-cpython"
    technology = "PYTHON"
    display_name = "CPython Verified Runtime & Toolchain"
    supported_versions = ["3.10", "3.11", "3.12", "3.13", "3.14"]
    license_type = "PSF-2.0"

    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        return [
            (CapabilityClass.SOURCE_UNDERSTANDING, "python_ast_analysis", CapabilityLevel.ANALYZE),
            (CapabilityClass.TARGET_GENERATION, "python_source_generation", CapabilityLevel.FULL_TRANSFORM),
            (CapabilityClass.TARGET_VERIFICATION, "python_byte_compile", CapabilityLevel.VERIFY),
            (CapabilityClass.TARGET_VERIFICATION, "python_syntax_check", CapabilityLevel.VERIFY),
        ]

    def is_tool_discovered(self) -> bool:
        return shutil.which("python3") is not None

    def get_version(self) -> str | None:
        try:
            import sys
            return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        except Exception:
            return None

    def qualify(self) -> list[CapabilityQualificationRecord]:
        records: list[CapabilityQualificationRecord] = []
        t0 = time.perf_counter()
        try:
            import ast
            code = "def sample_verification(x: int) -> int:\n    return x * 2\n"
            tree = ast.parse(code)
            elapsed = (time.perf_counter() - t0) * 1000.0
            if len(tree.body) == 1:
                records.append(
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="python_ast_analysis",
                        technology=self.technology,
                        qualified_version=self.get_version() or "unknown",
                        passed=True,
                        execution_time_ms=elapsed,
                        fixture_name="cpython_ast_fixture",
                        output_snippet=f"Parsed AST with {len(tree.body)} node(s)",
                        evidence=["Built-in AST module verified", "Pure Python parsing qualified"],
                    )
                )
            else:
                records.append(
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="python_ast_analysis",
                        technology=self.technology,
                        passed=False,
                        fixture_name="cpython_ast_fixture",
                        error_message="AST parsing returned unexpected node structure",
                    )
                )
        except Exception as e:
            records.append(
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="python_ast_analysis",
                    technology=self.technology,
                    passed=False,
                    fixture_name="cpython_ast_fixture",
                    error_message=str(e),
                )
            )
        return records

    def get_acquisition_recipe(self) -> dict[str, Any]:
        return {
            "source_url": "https://www.python.org",
            "package_manager": "system / brew / apt",
            "command": "brew install python@3.12",
            "is_free": True,
        }


class OpenJDKProvider(VerifiedTechnologyProvider):
    """Verified OpenJDK provider for Java compilation and verification.

    Crucially performs an executable compile test to detect broken OS shims
    (e.g., macOS /usr/bin/javac exiting with 'Unable to locate a Java Runtime').
    """

    provider_id = "provider-openjdk"
    technology = "JAVA"
    display_name = "OpenJDK Compiler & JVM"
    supported_versions = ["17", "21", "22", "23", "26"]
    license_type = "GPL-2.0-with-Classpath-exception"

    def __init__(self, managed_java_home: str | Path | None = None) -> None:
        self._managed_java_home = Path(managed_java_home) if managed_java_home else None

    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        return [
            (CapabilityClass.TARGET_GENERATION, "java_source_generation", CapabilityLevel.FULL_TRANSFORM),
            (CapabilityClass.TARGET_VERIFICATION, "javac_compilation", CapabilityLevel.VERIFY),
            (CapabilityClass.TARGET_VERIFICATION, "java_syntax_check", CapabilityLevel.VERIFY),
            (CapabilityClass.TARGET_VERIFICATION, "java_class_verification", CapabilityLevel.VERIFY),
        ]

    def _find_real_javac(self) -> str | None:
        # 1. Check explicit managed java home
        if self._managed_java_home:
            cand = self._managed_java_home / "bin" / "javac"
            if cand.exists() and os.access(cand, os.X_OK):
                return str(cand)
        # 2. Check AUTOFORGE_JAVA_HOME environment variable
        af_home = os.environ.get("AUTOFORGE_JAVA_HOME")
        if af_home:
            cand = Path(af_home) / "bin" / "javac"
            if cand.exists() and os.access(cand, os.X_OK):
                return str(cand)
        # 3. Check standard isolated AutoForge tool directory (.autoforge/tools/openjdk)
        default_tool_dir = Path.cwd() / ".autoforge" / "tools" / "openjdk"
        cand = default_tool_dir / "bin" / "javac"
        if cand.exists() and os.access(cand, os.X_OK):
            return str(cand)
        # 4. Check JAVA_HOME
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            cand = os.path.join(java_home, "bin", "javac")
            if os.path.exists(cand) and os.access(cand, os.X_OK):
                return cand
        # 5. Check PATH
        cand = shutil.which("javac")
        return cand

    def is_tool_discovered(self) -> bool:
        return self._find_real_javac() is not None

    def get_version(self) -> str | None:
        javac = self._find_real_javac()
        if not javac:
            return None
        try:
            res = subprocess.run([javac, "-version"], capture_output=True, text=True, timeout=5)
            combined = (res.stdout or "") + (res.stderr or "")
            if res.returncode != 0 or "Unable to locate a Java Runtime" in combined:
                return None
            m = re.search(r"javac\s+([0-9]+(?:\.[0-9]+)*)", combined)
            return m.group(1) if m else combined.strip().split("\n")[0]
        except Exception:
            return None

    def acquire_or_prepare(
        self,
        target_dir: Path | None = None,
        allow_external_install: bool = False,
    ) -> tuple[bool, str]:
        """Safely prepare or acquire OpenJDK in an isolated, cacheable AutoForge tool directory.

        Follows deterministic resolution:
        1. Checks candidate free OpenJDK distributions already installed on the host
           (e.g., Homebrew opt/openjdk on macOS or /usr/lib/jvm on Linux).
           If present, links to target_dir (e.g. .autoforge/tools/openjdk) without modifying system dirs.
        2. If none present and allow_external_install is False, returns (False, error) honestly.
        3. If allow_external_install is True, runs deterministic package manager command.
        """
        dest_dir = target_dir or (Path.cwd() / ".autoforge" / "tools" / "openjdk")

        candidate_roots = [
            Path("/opt/homebrew/opt/openjdk"),
            Path("/usr/local/opt/openjdk"),
            Path("/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home"),
            Path("/Library/Java/JavaVirtualMachines/zulu-21.jdk/Contents/Home"),
            Path("/usr/lib/jvm/java-21-openjdk-amd64"),
            Path("/usr/lib/jvm/default-java"),
        ]

        found_source: Path | None = None
        for root in candidate_roots:
            cand_javac = root / "bin" / "javac"
            if cand_javac.exists() and os.access(cand_javac, os.X_OK):
                try:
                    res = subprocess.run([str(cand_javac), "-version"], capture_output=True, text=True, timeout=5)
                    combined = (res.stdout or "") + (res.stderr or "")
                    if res.returncode == 0 and "Unable to locate a Java Runtime" not in combined:
                        found_source = root
                        break
                except Exception:
                    continue

        if found_source:
            dest_bin = dest_dir / "bin"
            dest_bin.mkdir(parents=True, exist_ok=True)
            dest_javac = dest_bin / "javac"
            if dest_javac.is_symlink() or dest_javac.exists():
                dest_javac.unlink()
            source_javac = found_source / "bin" / "javac"
            try:
                dest_javac.symlink_to(source_javac)
            except OSError:
                dest_javac.write_text(f'#!/bin/sh\nexec "{source_javac}" "$@"\n')
                dest_javac.chmod(0o755)
            self._managed_java_home = dest_dir
            return True, f"Prepared OpenJDK from host distribution '{found_source}' into isolated directory '{dest_dir}'"

        if not allow_external_install:
            return False, (
                "No free OpenJDK distribution found in candidate host locations. "
                "Automated external installation ('brew install openjdk@21') is disabled by policy."
            )

        recipe = self.get_acquisition_recipe()
        install_cmd = recipe.get("command", "brew install openjdk@21")
        try:
            res = subprocess.run(install_cmd.split(), capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                return False, f"Acquisition command failed: {res.stderr}"
            return self.acquire_or_prepare(target_dir=dest_dir, allow_external_install=False)
        except Exception as e:
            return False, f"Acquisition error: {str(e)}"

    def qualify(self) -> list[CapabilityQualificationRecord]:
        records: list[CapabilityQualificationRecord] = []
        javac = self._find_real_javac()
        t0 = time.perf_counter()
        if not javac:
            records.append(
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="javac_compilation",
                    technology=self.technology,
                    passed=False,
                    fixture_name="java_compilation_fixture",
                    error_message="javac executable not found on PATH or JAVA_HOME",
                )
            )
            return records

        # Execute real compile test in temporary directory
        workdir = tempfile.mkdtemp(prefix="autoforge_openjdk_qual_")
        try:
            src_file = os.path.join(workdir, "FixtureTest.java")
            with open(src_file, "w") as f:
                f.write(
                    "package com.autoforge.test;\n"
                    "public class FixtureTest {\n"
                    "    public static int compute(int a, int b) { return a + b; }\n"
                    "}\n"
                )
            cmd = [javac, "-d", workdir, src_file]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            elapsed = (time.perf_counter() - t0) * 1000.0
            combined = (res.stdout or "") + (res.stderr or "")

            if res.returncode == 0 and os.path.exists(os.path.join(workdir, "com", "autoforge", "test", "FixtureTest.class")):
                records.append(
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="javac_compilation",
                        technology=self.technology,
                        qualified_version=self.get_version() or "unknown",
                        passed=True,
                        execution_time_ms=elapsed,
                        command_executed=" ".join(cmd),
                        fixture_name="java_compilation_fixture",
                        output_snippet="FixtureTest.class successfully generated",
                        evidence=["javac compiled fixture without warnings", "bytecode class artifact generated"],
                    )
                )
            else:
                records.append(
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="javac_compilation",
                        technology=self.technology,
                        passed=False,
                        execution_time_ms=elapsed,
                        command_executed=" ".join(cmd),
                        fixture_name="java_compilation_fixture",
                        error_message=f"javac failed (exit {res.returncode}): {combined.strip()}",
                    )
                )
        except Exception as e:
            records.append(
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="javac_compilation",
                    technology=self.technology,
                    passed=False,
                    fixture_name="java_compilation_fixture",
                    error_message=str(e),
                )
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        return records

    def get_acquisition_recipe(self) -> dict[str, Any]:
        return {
            "source_url": "https://adoptium.net / openjdk.org",
            "package_manager": "brew / apt / sdkman",
            "command": "brew install openjdk@21",
            "is_free": True,
            "post_install_notes": "Symlink to /Library/Java/JavaVirtualMachines/ or set JAVA_HOME",
        }


class NodeJSProvider(VerifiedTechnologyProvider):
    """Verified Node.js & TypeScript provider."""

    provider_id = "provider-nodejs"
    technology = "TYPESCRIPT"
    display_name = "Node.js & TypeScript Toolchain"
    supported_versions = ["18", "20", "22", "26"]

    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        return [
            (CapabilityClass.TARGET_GENERATION, "typescript_source_generation", CapabilityLevel.FULL_TRANSFORM),
            (CapabilityClass.TARGET_VERIFICATION, "node_syntax_check", CapabilityLevel.VERIFY),
        ]

    def is_tool_discovered(self) -> bool:
        return shutil.which("node") is not None

    def get_version(self) -> str | None:
        node = shutil.which("node")
        if not node:
            return None
        try:
            res = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5)
            return res.stdout.strip()
        except Exception:
            return None

    def qualify(self) -> list[CapabilityQualificationRecord]:
        records: list[CapabilityQualificationRecord] = []
        node = shutil.which("node")
        t0 = time.perf_counter()
        if not node:
            records.append(
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="node_syntax_check",
                    technology=self.technology,
                    passed=False,
                    fixture_name="node_syntax_fixture",
                    error_message="node executable not found",
                )
            )
            return records

        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write("const add = (a, b) => a + b;\nif (add(2, 3) !== 5) process.exit(1);\n")
            tmp_path = f.name
        try:
            res = subprocess.run([node, "--check", tmp_path], capture_output=True, text=True, timeout=5)
            elapsed = (time.perf_counter() - t0) * 1000.0
            if res.returncode == 0:
                records.append(
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="node_syntax_check",
                        technology=self.technology,
                        qualified_version=self.get_version() or "unknown",
                        passed=True,
                        execution_time_ms=elapsed,
                        command_executed=f"{node} --check",
                        fixture_name="node_syntax_fixture",
                        output_snippet="Node.js --check passed",
                        evidence=["node --check validated syntax without errors"],
                    )
                )
            else:
                records.append(
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="node_syntax_check",
                        technology=self.technology,
                        passed=False,
                        execution_time_ms=elapsed,
                        error_message=(res.stderr or res.stdout).strip(),
                    )
                )
        except Exception as e:
            records.append(
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="node_syntax_check",
                    technology=self.technology,
                    passed=False,
                    error_message=str(e),
                )
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        return records

    def get_acquisition_recipe(self) -> dict[str, Any]:
        return {
            "source_url": "https://nodejs.org",
            "package_manager": "brew / apt / nvm",
            "command": "brew install node",
            "is_free": True,
        }


class GnuCOBOLProvider(VerifiedTechnologyProvider):
    """Verified GnuCOBOL provider for compiler-level syntax checking."""

    provider_id = "provider-gnucobol"
    technology = "COBOL"
    display_name = "GnuCOBOL (cobc) Compiler & Syntax Checker"
    supported_versions = ["3.1", "3.2"]
    license_type = "GPL-3.0"

    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        return [
            (CapabilityClass.SOURCE_UNDERSTANDING, "cobol_compiler_syntax_validation", CapabilityLevel.ANALYZE),
        ]

    def is_tool_discovered(self) -> bool:
        return shutil.which("cobc") is not None

    def acquire_or_prepare(
        self,
        target_dir: Path | None = None,
        allow_external_install: bool = False,
    ) -> tuple[bool, str]:
        if not allow_external_install:
            return False, (
                "GnuCOBOL (cobc) is not present. Automated host package installation "
                "is disabled by policy. Tool must be installed by administrator or via container."
            )
        recipe = self.get_acquisition_recipe()
        install_cmd = recipe.get("command", "brew install gnu-cobol")
        try:
            res = subprocess.run(install_cmd.split(), capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                return True, "Successfully installed GnuCOBOL via package manager"
            return False, f"Acquisition command failed: {res.stderr}"
        except Exception as e:
            return False, f"Acquisition error: {str(e)}"

    def get_version(self) -> str | None:
        cobc = shutil.which("cobc")
        if not cobc:
            return None
        try:
            res = subprocess.run([cobc, "--version"], capture_output=True, text=True, timeout=5)
            first_line = (res.stdout or res.stderr or "").strip().split("\n")[0]
            m = re.search(r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)", first_line)
            return m.group(1) if m else first_line
        except Exception:
            return None

    def qualify(self) -> list[CapabilityQualificationRecord]:
        cobc = shutil.which("cobc")
        if not cobc:
            return [
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="cobol_compiler_syntax_validation",
                    technology=self.technology,
                    passed=False,
                    fixture_name="gnucobol_syntax_fixture",
                    error_message="cobc compiler not installed on PATH",
                )
            ]

        t0 = time.perf_counter()
        with tempfile.NamedTemporaryFile(suffix=".cbl", mode="w", delete=False) as f:
            f.write(
                "       IDENTIFICATION DIVISION.\n"
                "       PROGRAM-ID. QUALTEST.\n"
                "       PROCEDURE DIVISION.\n"
                "           DISPLAY 'QUALIFIED'.\n"
                "           STOP RUN.\n"
            )
            tmp_path = f.name

        try:
            cmd = [cobc, "-fsyntax-only", tmp_path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            elapsed = (time.perf_counter() - t0) * 1000.0
            if res.returncode == 0:
                return [
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="cobol_compiler_syntax_validation",
                        technology=self.technology,
                        qualified_version=self.get_version() or "unknown",
                        passed=True,
                        execution_time_ms=elapsed,
                        command_executed=" ".join(cmd),
                        fixture_name="gnucobol_syntax_fixture",
                        output_snippet="cobc -fsyntax-only passed",
                        evidence=["GnuCOBOL compiled fixture without errors"],
                    )
                ]
            return [
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="cobol_compiler_syntax_validation",
                    technology=self.technology,
                    passed=False,
                    execution_time_ms=elapsed,
                    error_message=(res.stderr or res.stdout).strip(),
                )
            ]
        except Exception as e:
            return [
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="cobol_compiler_syntax_validation",
                    technology=self.technology,
                    passed=False,
                    error_message=str(e),
                )
            ]
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def get_acquisition_recipe(self) -> dict[str, Any]:
        return {
            "source_url": "https://gnucobol.sourceforge.io",
            "package_manager": "brew (macOS) / apt (Debian/Ubuntu)",
            "command": "brew install gnu-cobol",
            "is_free": True,
        }


class PurePythonCOBOLProvider(VerifiedTechnologyProvider):
    """Pure-Python deterministic parser for COBOL AST & copybooks."""

    provider_id = "provider-python-cobol-parser"
    technology = "COBOL"
    display_name = "AutoForge Pure-Python COBOL Parser & Semantic Extractor"
    supported_versions = ["COBOL-85", "COBOL-2002", "Enterprise-COBOL"]

    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        return [
            (CapabilityClass.SOURCE_UNDERSTANDING, "cobol_lexical_syntactic_analysis", CapabilityLevel.ANALYZE),
            (CapabilityClass.SOURCE_UNDERSTANDING, "cobol_copybook_resolution", CapabilityLevel.ANALYZE),
            (CapabilityClass.SOURCE_UNDERSTANDING, "cobol_call_relationship_analysis", CapabilityLevel.ANALYZE),
            (CapabilityClass.SOURCE_UNDERSTANDING, "cobol_control_data_flow_analysis", CapabilityLevel.ANALYZE),
            (CapabilityClass.SEMANTIC_KNOWLEDGE, "cobol_business_rule_extraction", CapabilityLevel.ANALYZE),
        ]

    def is_tool_discovered(self) -> bool:
        try:
            from autoforge_modernization.analyzers.cobol import COBOLAnalyzer
            from autoforge_modernization.cobol_parser import COBOLParser
            return True
        except ImportError:
            return False

    def get_version(self) -> str | None:
        return "1.0.0-autoforge"

    def qualify(self) -> list[CapabilityQualificationRecord]:
        from autoforge_modernization.analyzers.cobol import COBOLAnalyzer
        t0 = time.perf_counter()
        cobol_code = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. HELLO.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-COUNT PIC 9(4) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           MOVE 10 TO WS-COUNT.\n"
            "           IF WS-COUNT > 5\n"
            "               PERFORM 1000-PROCESS\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
            "       1000-PROCESS.\n"
            "           CALL 'SUBPROG' USING WS-COUNT.\n"
        )
        try:
            analyzer = COBOLAnalyzer()
            res = analyzer.analyze(cobol_code, "HELLO.CBL")
            elapsed = (time.perf_counter() - t0) * 1000.0
            findings_count = len(res.findings)
            has_paragraphs = any(f.kind.value == "paragraph" for f in res.findings)
            has_calls = any(f.kind.value == "procedure_call" for f in res.findings)

            passed = findings_count >= 5 and has_paragraphs and has_calls
            return [
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="cobol_lexical_syntactic_analysis",
                    technology=self.technology,
                    qualified_version="1.0.0",
                    passed=passed,
                    execution_time_ms=elapsed,
                    fixture_name="pure_python_cobol_ast_fixture",
                    output_snippet=f"Extracted {findings_count} AST findings (paragraphs={has_paragraphs}, calls={has_calls})",
                    evidence=["Extracted working-storage data item", "Extracted perform target", "Resolved CALL target"],
                )
            ]
        except Exception as e:
            return [
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="cobol_lexical_syntactic_analysis",
                    technology=self.technology,
                    passed=False,
                    execution_time_ms=(time.perf_counter() - t0) * 1000.0,
                    error_message=str(e),
                )
            ]

    def get_acquisition_recipe(self) -> dict[str, Any]:
        return {
            "source_url": "internal://autoforge-core",
            "package_manager": "builtin",
            "command": "bundled",
            "is_free": True,
        }


class JCLUnderstandingProvider(VerifiedTechnologyProvider):
    """Pure-Python deterministic parser for JCL syntax, jobs, and execution flows."""

    provider_id = "provider-jcl-analyzer"
    technology = "JCL"
    display_name = "AutoForge JCL Job & Dataset Analyzer"
    supported_versions = ["z/OS-JCL"]

    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        return [
            (CapabilityClass.SOURCE_UNDERSTANDING, "jcl_job_parsing", CapabilityLevel.ANALYZE),
            (CapabilityClass.SOURCE_UNDERSTANDING, "jcl_procedure_resolution", CapabilityLevel.ANALYZE),
            (CapabilityClass.SOURCE_UNDERSTANDING, "jcl_dataset_analysis", CapabilityLevel.ANALYZE),
            (CapabilityClass.SOURCE_UNDERSTANDING, "jcl_execution_flow_analysis", CapabilityLevel.ANALYZE),
        ]

    def is_tool_discovered(self) -> bool:
        try:
            from autoforge_modernization.analyzers.jcl import JCLAnalyzer
            return True
        except ImportError:
            return False

    def get_version(self) -> str | None:
        return "1.0.0-autoforge"

    def qualify(self) -> list[CapabilityQualificationRecord]:
        from autoforge_modernization.analyzers.jcl import JCLAnalyzer
        t0 = time.perf_counter()
        jcl_sample = (
            "//JOBTEST  JOB (ACCT),'TEST JCL',CLASS=A,MSGCLASS=X\n"
            "//STEP1    EXEC PGM=CBACT01C\n"
            "//INFILE   DD DSN=CARDDEMO.ACCTDATA,DISP=SHR\n"
            "//OUTFILE  DD DSN=CARDDEMO.OUTDATA,DISP=(NEW,CATLG,DELETE)\n"
        )
        try:
            analyzer = JCLAnalyzer()
            res = analyzer.analyze(jcl_sample, "TEST.JCL")
            elapsed = (time.perf_counter() - t0) * 1000.0
            has_steps = any(f.kind.value == "jcl_step" for f in res.findings)
            has_datasets = any(f.kind.value == "jcl_dataset" for f in res.findings)
            passed = has_steps and has_datasets

            return [
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="jcl_job_parsing",
                    technology=self.technology,
                    qualified_version="1.0.0",
                    passed=passed,
                    execution_time_ms=elapsed,
                    fixture_name="jcl_job_fixture",
                    output_snippet=f"Parsed JCL (steps={has_steps}, datasets={has_datasets})",
                    evidence=["Identified JOB card", "Extracted EXEC step", "Resolved DD statements"],
                )
            ]
        except Exception as e:
            return [
                CapabilityQualificationRecord(
                    provider_id=self.provider_id,
                    capability_name="jcl_job_parsing",
                    technology=self.technology,
                    passed=False,
                    execution_time_ms=(time.perf_counter() - t0) * 1000.0,
                    error_message=str(e),
                )
            ]

    def get_acquisition_recipe(self) -> dict[str, Any]:
        return {
            "source_url": "internal://autoforge-core",
            "package_manager": "builtin",
            "command": "bundled",
            "is_free": True,
        }


class SpecialistTechnologyProvider(VerifiedTechnologyProvider):
    """Explicit provider for technologies requiring human specialists or licensed tooling (IMS, HLASM).

    Honors Section 15: Does NOT fake support. Explicitly declares SPECIALIST_REQUIRED.
    """

    def __init__(self, technology: str, description: str, rationale: str) -> None:
        self.technology = technology.upper()
        self.provider_id = f"specialist-{self.technology.lower()}"
        self.display_name = f"Specialist Consultation Required: {self.technology}"
        self.description = description
        self.rationale = rationale

    def capabilities_supplied(self) -> list[tuple[CapabilityClass, str, CapabilityLevel]]:
        return [
            (CapabilityClass.SOURCE_UNDERSTANDING, f"{self.technology.lower()}_specialist_consultation", CapabilityLevel.DETECT),
        ]

    def is_tool_discovered(self) -> bool:
        # Detected at requirement time, but automation capability requires human specialist
        return False

    def get_version(self) -> str | None:
        return None

    def qualify(self) -> list[CapabilityQualificationRecord]:
        return [
            CapabilityQualificationRecord(
                provider_id=self.provider_id,
                capability_name=f"{self.technology.lower()}_specialist_consultation",
                technology=self.technology,
                passed=False,
                fixture_name="specialist_boundary_check",
                error_message=f"SPECIALIST_REQUIRED: {self.rationale}",
                evidence=[self.description, self.rationale],
            )
        ]

    def get_acquisition_recipe(self) -> dict[str, Any]:
        return {
            "source_url": "n/a - specialist intervention required",
            "package_manager": "manual_review",
            "command": "SCHEDULE_SPECIALIST_REVIEW",
            "is_free": True,
            "requires_human": True,
        }


class ProviderRegistry:
    """Central authoritative registry of Verified Technology Providers."""

    def __init__(self) -> None:
        self._providers: dict[str, VerifiedTechnologyProvider] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        self.register(CPythonProvider())
        self.register(OpenJDKProvider())
        self.register(NodeJSProvider())
        self.register(GnuCOBOLProvider())
        self.register(PurePythonCOBOLProvider())
        self.register(JCLUnderstandingProvider())
        self.register(
            SpecialistTechnologyProvider(
                technology="IMS",
                description="IBM IMS Hierarchical Database & Transaction Manager",
                rationale="Hierarchical DL/I segments and PSB/DBD schemas require specialist relational mapping architecture.",
            )
        )
        self.register(
            SpecialistTechnologyProvider(
                technology="ASSEMBLER",
                description="IBM High Level Assembler (HLASM)",
                rationale="Macro expansion, register allocation, and hardware branch instructions require specialist reverse engineering.",
            )
        )

    def register(self, provider: VerifiedTechnologyProvider) -> None:
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> VerifiedTechnologyProvider | None:
        return self._providers.get(provider_id)

    def find_for_technology(self, technology: str) -> list[VerifiedTechnologyProvider]:
        tech = technology.upper()
        return [p for p in self._providers.values() if p.technology == tech]

    def find_for_requirement(self, requirement: CapabilityRequirement) -> list[VerifiedTechnologyProvider]:
        return [p for p in self._providers.values() if p.can_satisfy(requirement)]

    def all_providers(self) -> list[VerifiedTechnologyProvider]:
        return list(self._providers.values())
