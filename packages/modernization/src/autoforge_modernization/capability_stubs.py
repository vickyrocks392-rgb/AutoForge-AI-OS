"""Capability stubs for CICS/BMS/IMS/VSAM/PL-I/Assembler (Phase 18-G.3).

Each capability provides:
  - detect(content) -> bool
  - classify(content) -> CapabilityClassification (ANALYZE_ONLY|REVIEW_REQUIRED|BLOCKED)

These are real, honest capability declarations: they detect the technology,
classify the work, and produce a coverage indicator. They do NOT pretend
to transform — for these legacy-only technologies, the output is an
analysis report, not a transformation.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum


class CapabilityMode(str, Enum):
    ANALYZE_ONLY = "ANALYZE_ONLY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass
class CapabilityResult:
    technology: str
    detected: bool
    mode: CapabilityMode
    evidence: dict = field(default_factory=dict)
    rationale: str = ""


class CapabilityStub:
    technology: str = "UNKNOWN"

    def detect(self, content: str) -> bool:
        raise NotImplementedError

    def classify(self, content: str) -> CapabilityResult:
        if not self.detect(content):
            return CapabilityResult(self.technology, False, CapabilityMode.ANALYZE_ONLY, rationale="not detected")
        return self._classify_detected(content)

    def _classify_detected(self, content: str) -> CapabilityResult:
        return CapabilityResult(self.technology, True, CapabilityMode.REVIEW_REQUIRED, rationale="detected; requires human review")


class CICSCapability(CapabilityStub):
    technology = "CICS"

    def detect(self, content: str) -> bool:
        return bool(re.search(r"\bEXEC\s+CICS\b", content, re.IGNORECASE))

    def _classify_detected(self, content: str) -> CapabilityResult:
        verbs = set(re.findall(r"EXEC\s+CICS\s+(\w+)", content, re.IGNORECASE))
        return CapabilityResult(
            technology=self.technology,
            detected=True,
            mode=CapabilityMode.REVIEW_REQUIRED,
            evidence={"cics_verbs": sorted(verbs), "lines": content.count("\n")},
            rationale="CICS detected: requires CICS-aware runtime + manual binding (Spring CICS bridge or openUTAU/TX/T4C)",
        )


class BMSCapability(CapabilityStub):
    technology = "BMS"

    def detect(self, content: str) -> bool:
        return bool(re.search(r"DFHMSD|DFHMDI|DFHMDF", content))

    def _classify_detected(self, content: str) -> CapabilityResult:
        maps = re.findall(r"DFHMDI\s+(\w+)", content)
        return CapabilityResult(
            technology=self.technology,
            detected=True,
            mode=CapabilityMode.REVIEW_REQUIRED,
            evidence={"maps": sorted(set(maps))},
            rationale="BMS mapset detected: requires manual UI redesign (React/Angular) + CICS bridge",
        )


class IMSCapability(CapabilityStub):
    technology = "IMS"

    def detect(self, content: str) -> bool:
        return bool(re.search(r"\b(IMS|MPP|DLI|PSB|PCB|PSBGEN)\b", content))

    def _classify_detected(self, content: str) -> CapabilityResult:
        return CapabilityResult(
            technology=self.technology,
            detected=True,
            mode=CapabilityMode.BLOCKED,
            rationale="IMS detected: requires specialized IMS-aware runtime (IMS Connect / OpenUTAU). Outside G.3 scope.",
        )


class VSAMCapability(CapabilityStub):
    technology = "VSAM"

    def detect(self, content: str) -> bool:
        return bool(re.search(r"DEFINE\s+CLUSTER|IDCAMS|RECATLG|KEYS\s+\(\s*\d+\s+\d+", content, re.IGNORECASE))

    def _classify_detected(self, content: str) -> CapabilityResult:
        clusters = re.findall(r"DEFINE\s+CLUSTER\s*\(\s*NAME\(([^)]+)\)", content, re.IGNORECASE)
        return CapabilityResult(
            technology=self.technology,
            detected=True,
            mode=CapabilityMode.ANALYZE_ONLY,
            evidence={"clusters": sorted(set(clusters))},
            rationale="VSAM cluster definitions: inventory only. Modernization target: RocksDB/Kafka/S3.",
        )


class PLICapability(CapabilityStub):
    technology = "PL/I"

    def detect(self, content: str) -> bool:
        return bool(re.search(r"\b(PROC|OPTIONS\s*\(|DCL\s+\w+\s+(CHAR|FIXED|BIN|FLOAT|PTR))", content, re.IGNORECASE))

    def _classify_detected(self, content: str) -> CapabilityResult:
        return CapabilityResult(
            technology=self.technology,
            detected=True,
            mode=CapabilityMode.REVIEW_REQUIRED,
            rationale="PL/I detected: requires PL/I-to-Java migration toolchain (e.g., XLR-to-Java, mainframe decomposer).",
        )


class AssemblerCapability(CapabilityStub):
    technology = "ASM"

    def detect(self, content: str) -> bool:
        return bool(re.search(r"^\s*(CSECT|DSECT|DS\s+|DC\s+|\bBALR\s+|\bUSING\s+)", content, re.MULTILINE | re.IGNORECASE))

    def _classify_detected(self, content: str) -> CapabilityResult:
        return CapabilityResult(
            technology=self.technology,
            detected=True,
            mode=CapabilityMode.BLOCKED,
            rationale="Assembler detected: requires deep recompile and instruction-level migration. Outside G.3 scope.",
        )


class CapabilityDetector:
    """Dispatch detector: pick the right capability stub based on content."""

    STUBS = [CICSCapability(), BMSCapability(), IMSCapability(), VSAMCapability(), PLICapability(), AssemblerCapability()]

    def detect_all(self, content: str) -> list[CapabilityResult]:
        out = []
        for stub in self.STUBS:
            r = stub.classify(content)
            if r.detected:
                out.append(r)
        return out


__all__ = [
    "CapabilityStub", "CapabilityMode", "CapabilityResult",
    "CICSCapability", "BMSCapability", "IMSCapability",
    "VSAMCapability", "PLICapability", "AssemblerCapability",
    "CapabilityDetector",
]
