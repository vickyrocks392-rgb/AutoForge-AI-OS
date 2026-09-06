"""Generalized Project Technology Discovery Engine.

Orchestrates multi-provider evidence gathering and synthesizes findings into
the authoritative ProjectTechnologyInventory with implied capability requirements.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from autoforge_modernization.capabilities.requirement_graph import (
    CapabilityRequirementGraph,
)
from autoforge_modernization.discovery.evidence import (
    EvidenceProvider,
    FileSystemEvidenceProvider,
    SyntaxEvidenceProvider,
    TechnologyEvidenceRecord,
)
from autoforge_modernization.discovery.inventory import (
    DetectedTechnologySummary,
    ProjectTechnologyInventory,
)
from autoforge_modernization.reconnaissance.models import FactConfidence


class ProjectTechnologyDiscoveryEngine:
    """Discovers all technologies present in a project codebase using evidence providers."""

    def __init__(
        self,
        evidence_providers: list[EvidenceProvider] | None = None,
        requirement_graph: CapabilityRequirementGraph | None = None,
        max_file_size_bytes: int = 5_000_000,
    ) -> None:
        self.evidence_providers = evidence_providers or [
            FileSystemEvidenceProvider(),
            SyntaxEvidenceProvider(),
        ]
        self.requirement_graph = requirement_graph or CapabilityRequirementGraph()
        self.max_file_size_bytes = max_file_size_bytes

    def discover(self, project_root: str | Path) -> ProjectTechnologyInventory:
        """Scan project_root and produce the ProjectTechnologyInventory."""
        root_path = Path(project_root).resolve()
        inventory = ProjectTechnologyInventory(
            project_path=str(root_path),
            detection_providers_used=[p.provider_id for p in self.evidence_providers],
        )

        tech_data: dict[str, dict[str, Any]] = {}
        total_scanned_files = 0
        total_loc = 0

        skip_dirs = {".git", "target", "build", "node_modules", "__pycache__", ".pytest_cache"}

        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]

            for fn in filenames:
                if fn.startswith("."):
                    continue

                abs_file_path = os.path.join(dirpath, fn)
                rel_file_path = os.path.relpath(abs_file_path, root_path)

                try:
                    stat = os.stat(abs_file_path)
                    if stat.st_size > self.max_file_size_bytes:
                        continue
                except OSError:
                    continue

                total_scanned_files += 1

                # Read content safely
                content = None
                try:
                    with open(abs_file_path, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                except Exception:
                    content = None

                # Count lines
                phys_lines = 0
                log_lines = 0
                if content is not None:
                    lines = content.splitlines()
                    phys_lines = len(lines)
                    log_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith(("*", "//", "#")))
                    total_loc += phys_lines

                # Run evidence providers
                file_evidence: list[TechnologyEvidenceRecord] = []
                for provider in self.evidence_providers:
                    evs = provider.scan_file(abs_file_path, rel_file_path, content)
                    file_evidence.extend(evs)

                for ev in file_evidence:
                    tech_key = ev.technology.upper()
                    if tech_key not in tech_data:
                        tech_data[tech_key] = {
                            "technology": tech_key,
                            "files": set(),
                            "physical_loc": 0,
                            "logical_loc": 0,
                            "evidence": [],
                            "confidence_points": 0.0,
                        }

                    entry = tech_data[tech_key]
                    if rel_file_path not in entry["files"]:
                        entry["files"].add(rel_file_path)
                        entry["physical_loc"] += phys_lines
                        entry["logical_loc"] += log_lines

                    entry["evidence"].append(ev)
                    # Weight confidence points
                    pts = 1.0 if ev.confidence == FactConfidence.PROVEN else 0.7 if ev.confidence == FactConfidence.HIGH else 0.4
                    entry["confidence_points"] += pts

        inventory.total_files_scanned = total_scanned_files
        inventory.total_physical_loc = total_loc

        # Assemble summary per detected technology
        for tech_key, d in tech_data.items():
            files_list = sorted(list(d["files"]))
            evidence_list: list[TechnologyEvidenceRecord] = d["evidence"]

            # Compute normalized confidence
            # If at least one proven evidence or multiple high evidence, confidence is high
            has_proven = any(e.confidence == FactConfidence.PROVEN for e in evidence_list)
            num_ev = len(evidence_list)
            conf = 0.99 if has_proven else min(0.95, 0.5 + 0.1 * num_ev)

            # Query implied capability requirements from the graph
            implied_reqs = self.requirement_graph.get_requirements(tech_key)

            summary = DetectedTechnologySummary(
                technology=tech_key,
                confidence=conf,
                detection_method="multi_provider_evidence",
                files_count=len(files_list),
                physical_loc=d["physical_loc"],
                logical_loc=d["logical_loc"],
                sample_files=files_list[:5],
                affected_files=files_list,
                evidence=evidence_list[:50],
                implied_requirements=implied_reqs,
            )
            inventory.add_technology(summary)

        return inventory
