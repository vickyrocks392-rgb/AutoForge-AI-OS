"""Technology detector for Phase 18-G.2."""
from __future__ import annotations
from autoforge_modernization.reconnaissance.models import (
    ScannedFile, DetectedTechnology, TechnologyKind, TechnologyCategory,
    TechnologyEvidence, EvidenceKind, EvidenceSource, DetectionMethod,
    FactConfidence, ComparisonOutcome, ProjectCapabilityComparison,
    BuildSystem, DependencyGraph, DatabaseInventory, DeploymentSpec,
    DeploymentTarget, RuntimeSpec,
)

TECHNOLOGY_CANONICAL: dict[str, str] = {
    "java": "java", "java_ee": "java_ee", "java_se": "java_se",
    "spring": "spring", "hibernate": "hibernate",
    "maven": "maven", "gradle": "gradle", "ant": "ant",
    "cobol": "cobol", "pli": "pl_i", "jcl": "jcl", "rpg": "rpg",
    "cobol_copybook": "cobol_copybook", "bms_map": "bms_map",
    "db2_sql": "db2_sql", "oracle_package": "oracle_package",
    "javascript": "javascript", "typescript": "typescript",
    "node": "node_js", "python": "python", "php": "php",
    "ruby": "ruby", "go": "go", "rust": "rust",
    "csharp": "csharp", "vbnet": "vbnet", "cpp": "cpp", "c": "c",
    "scala": "scala", "kotlin": "kotlin", "swift": "swift",
    "objective_c": "objective_c", "perl": "perl",
    "dockerfile": "docker", "docker": "docker",
    "kubernetes": "kubernetes", "terraform": "terraform",
    "jenkins": "jenkins", "gitlab": "gitlab_ci",
    "azure_devops": "azure_devops", "circleci": "circleci",
    "travis": "travis_ci", "sql": "sql", "fortran": "fortran",
    "groovy": "groovy", "sbt": "sbt",
}

TECH_KIND_MAP: dict[str, TechnologyKind] = {
    "java": TechnologyKind.LANGUAGE, "java_ee": TechnologyKind.FRAMEWORK,
    "spring": TechnologyKind.FRAMEWORK, "hibernate": TechnologyKind.FRAMEWORK,
    "maven": TechnologyKind.TOOL, "gradle": TechnologyKind.TOOL,
    "cobol": TechnologyKind.LANGUAGE, "pli": TechnologyKind.LANGUAGE,
    "jcl": TechnologyKind.LANGUAGE, "rpg": TechnologyKind.LANGUAGE,
    "javascript": TechnologyKind.LANGUAGE, "typescript": TechnologyKind.LANGUAGE,
    "node": TechnologyKind.RUNTIME, "python": TechnologyKind.LANGUAGE,
    "php": TechnologyKind.LANGUAGE, "ruby": TechnologyKind.LANGUAGE,
    "go": TechnologyKind.LANGUAGE, "rust": TechnologyKind.LANGUAGE,
    "csharp": TechnologyKind.LANGUAGE, "cpp": TechnologyKind.LANGUAGE,
    "c": TechnologyKind.LANGUAGE, "scala": TechnologyKind.LANGUAGE,
    "kotlin": TechnologyKind.LANGUAGE, "swift": TechnologyKind.LANGUAGE,
    "sql": TechnologyKind.LANGUAGE, "fortran": TechnologyKind.LANGUAGE,
    "dockerfile": TechnologyKind.CONTAINER, "docker": TechnologyKind.CONTAINER,
    "kubernetes": TechnologyKind.ORCHESTRATION,
    "terraform": TechnologyKind.INFRASTRUCTURE,
    "jenkins": TechnologyKind.CI_CD, "gitlab": TechnologyKind.CI_CD,
}

TECH_CATEGORY_MAP: dict[str, TechnologyCategory] = {
    "cobol": TechnologyCategory.MAINFRAME, "pli": TechnologyCategory.MAINFRAME,
    "jcl": TechnologyCategory.MAINFRAME, "rpg": TechnologyCategory.MAINFRAME,
    "java": TechnologyCategory.JAVA_ENTERPRISE,
    "spring": TechnologyCategory.JAVA_ENTERPRISE,
    "hibernate": TechnologyCategory.JAVA_ENTERPRISE,
    "scala": TechnologyCategory.JAVA_ENTERPRISE,
    "kotlin": TechnologyCategory.JAVA_ENTERPRISE,
    "javascript": TechnologyCategory.WEB_FRONTEND,
    "typescript": TechnologyCategory.WEB_FRONTEND,
    "node": TechnologyCategory.WEB_BACKEND,
    "python": TechnologyCategory.GENERAL_PURPOSE,
    "php": TechnologyCategory.WEB_BACKEND, "ruby": TechnologyCategory.GENERAL_PURPOSE,
    "go": TechnologyCategory.GENERAL_PURPOSE, "rust": TechnologyCategory.GENERAL_PURPOSE,
    "csharp": TechnologyCategory.WEB_BACKEND,
    "cpp": TechnologyCategory.EMBEDDED, "c": TechnologyCategory.EMBEDDED,
    "fortran": TechnologyCategory.GENERAL_PURPOSE,
    "sql": TechnologyCategory.DATA_ENGINEERING,
    "docker": TechnologyCategory.CLOUD_NATIVE,
    "kubernetes": TechnologyCategory.CLOUD_NATIVE,
    "terraform": TechnologyCategory.CLOUD_NATIVE,
    "terraform": TechnologyCategory.CLOUD_NATIVE,
}


BUILD_SYSTEM_CANONICAL: dict[str, str] = {
    "maven": "maven", "gradle": "gradle", "ant": "ant",
    "npm": "npm", "pip": "pip", "poetry": "poetry",
    "cargo": "cargo", "bundler": "bundler", "composer": "composer",
    "jcl": "jcl", "cobol_copybook": "cobol_copybook",
    "docker": "docker", "terraform": "terraform", "kubernetes": "kubernetes",
}


class TechnologyDetector:
    """Detects technologies from scanned files."""

    def __init__(
        self,
        scanned_files: list[ScannedFile] | None = None,
        build_systems: list[BuildSystem] | None = None,
        db_inventory: DatabaseInventory | None = None,
        deployment_spec: DeploymentSpec | None = None,
    ) -> None:
        self.scanned_files = scanned_files or []
        self.build_systems = build_systems or []
        self.db_inventory = db_inventory
        self.deployment_spec = deployment_spec

    def detect_all(self) -> list[DetectedTechnology]:
        """Run all technology detection passes."""
        technologies: list[DetectedTechnology] = []
        seen: set[str] = set()
        for tech_name in self._detect_from_files():
            if tech_name not in seen:
                seen.add(tech_name)
                technologies.append(self._build_technology(tech_name))
        for bs in self.build_systems:
            name = BUILD_SYSTEM_CANONICAL.get(bs, bs.value)
            if name not in seen:
                seen.add(name)
                technologies.append(self._build_technology(name))
        if self.db_inventory:
            for db_name in self.db_inventory.databases:
                if db_name not in seen:
                    seen.add(db_name)
                    technologies.append(self._build_technology(db_name))
        if self.deployment_spec and self.deployment_spec.target != DeploymentTarget.UNKNOWN:
            target_name = self.deployment_spec.target.value
            if target_name not in seen:
                seen.add(target_name)
                technologies.append(self._build_technology(target_name))
        primary_lang = self._primary_language()
        for tech in technologies:
            if tech.name == primary_lang:
                tech.is_primary = True
        return technologies

    def _detect_from_files(self) -> list[str]:
        """Extract technology names from scanned files."""
        techs: list[str] = []
        for sf in self.scanned_files:
            for t in sf.detected_technologies:
                canonical = TECHNOLOGY_CANONICAL.get(t, t)
                if canonical not in techs:
                    techs.append(canonical)
            if sf.detected_language and sf.category.value == "source":
                lang = TECHNOLOGY_CANONICAL.get(sf.detected_language, sf.detected_language)
                if lang not in techs:
                    techs.append(lang)
        return techs

    def compare_capabilities(
        self,
        detected: list[DetectedTechnology],
        capability_registry: dict[str, str] | None = None,
    ) -> list[ProjectCapabilityComparison]:
        """Compare detected technologies against AutoForge capabilities."""
        registry = capability_registry or {}
        comparisons: list[ProjectCapabilityComparison] = []
        for tech in detected:
            cap_level = registry.get(tech.name, "unknown")
            if cap_level in ("full", "partial"):
                outcome = ComparisonOutcome.SUPPORTED if cap_level == "full" else ComparisonOutcome.PARTIALLY_SUPPORTED
            elif cap_level == "tool_required":
                outcome = ComparisonOutcome.TOOL_REQUIRED
            elif cap_level == "environment_required":
                outcome = ComparisonOutcome.ENVIRONMENT_REQUIRED
            elif cap_level == "model_required":
                outcome = ComparisonOutcome.MODEL_REQUIRED
            elif cap_level == "unsupported":
                outcome = ComparisonOutcome.UNSUPPORTED
            else:
                outcome = ComparisonOutcome.UNKNOWN
            comparisons.append(ProjectCapabilityComparison(
                technology=tech.name,
                detected_version=tech.version,
                detected_version_confidence=tech.version_confidence,
                outcome=outcome,
                capability_level=cap_level,
                evidence=[e.evidence for e in tech.evidence],
                blocks_modernization=outcome in (
                    ComparisonOutcome.UNSUPPORTED,
                    ComparisonOutcome.TOOL_REQUIRED,
                    ComparisonOutcome.MODEL_REQUIRED,
                ),
            ))
        return comparisons
        for sf in self.scanned_files:
            for t in sf.detected_technologies:
                canonical = TECHNOLOGY_CANONICAL.get(t, t)
                if canonical not in techs:
                    techs.append(canonical)
        return techs

    def _primary_language(self) -> str | None:
        """Determine primary language from file counts."""
        counts: dict[str, int] = {}
        for sf in self.scanned_files:
            if sf.category.value == "source" and not sf.is_generated:
                lang = sf.detected_language
                if lang:
                    canonical = TECHNOLOGY_CANONICAL.get(lang, lang)
                    counts[canonical] = counts.get(canonical, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda x: x[1])[0]

    def _build_technology(self, name: str) -> DetectedTechnology:
        """Build a DetectedTechnology from a name."""
        evidence = self._collect_evidence(name)
        kind = TECH_KIND_MAP.get(name, TechnologyKind.UNKNOWN)
        category = TECH_CATEGORY_MAP.get(name, TechnologyCategory.UNKNOWN)
        primary = self._is_primary(name)
        return DetectedTechnology(
            name=name,
            kind=kind,
            category=category,
            version=None,
            version_confidence=FactConfidence.UNKNOWN,
            evidence=evidence,
            confidence=FactConfidence.HIGH if evidence else FactConfidence.LOW,
            is_primary=primary,
        )

    def _collect_evidence(self, name: str) -> list[TechnologyEvidence]:
        """Collect evidence for a technology."""
        ev: list[TechnologyEvidence] = []
        for sf in self.scanned_files:
            if name in sf.detected_technologies or (
                sf.detected_language and
                TECHNOLOGY_CANONICAL.get(sf.detected_language, sf.detected_language) == name
            ):
                ev.append(TechnologyEvidence(
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.FILE_EXTENSION,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    evidence=f"Found in {sf.relative_path}",
                    file_path=sf.path,
                    confidence=FactConfidence.HIGH,
                ))
        return ev[:5]

    def _is_primary(self, name: str) -> bool:
        """Check if this technology is the primary one."""
        primary = self._primary_language()
        return primary is not None and TECHNOLOGY_CANONICAL.get(primary, primary) == name

    def build_runtime_specs(self) -> list[RuntimeSpec]:
        """Build runtime specifications from deployment and database info."""
        specs: list[RuntimeSpec] = []
        if self.deployment_spec and self.deployment_spec.target != DeploymentTarget.UNKNOWN:
            specs.append(RuntimeSpec(
                runtime_name=self.deployment_spec.target.value,
                evidence=[f"deployment_target:{self.deployment_spec.target.value}"],
            ))
        if self.db_inventory:
            for db in self.db_inventory.databases:
                specs.append(RuntimeSpec(
                    runtime_name=db,
                    version=self.db_inventory.versions.get(db),
                    evidence=[f"database:{db}"],
                ))
        return specs
        return specs

    def compare_capabilities(
        self,
        detected: list[DetectedTechnology],
        capability_registry: dict[str, str] | None = None,
    ) -> list[ProjectCapabilityComparison]:
        """Compare detected technologies against AutoForge capabilities."""
        registry = capability_registry or {}
        comparisons: list[ProjectCapabilityComparison] = []
        for tech in detected:
            cap_level = registry.get(tech.name, "unknown")
            if cap_level in ("full", "partial"):
                outcome = ComparisonOutcome.SUPPORTED if cap_level == "full" else ComparisonOutcome.PARTIALLY_SUPPORTED
            elif cap_level == "tool_required":
                outcome = ComparisonOutcome.TOOL_REQUIRED
            elif cap_level == "environment_required":
                outcome = ComparisonOutcome.ENVIRONMENT_REQUIRED
            elif cap_level == "model_required":
                outcome = ComparisonOutcome.MODEL_REQUIRED
            elif cap_level == "unsupported":
                outcome = ComparisonOutcome.UNSUPPORTED
            else:
                outcome = ComparisonOutcome.UNKNOWN
            comparisons.append(ProjectCapabilityComparison(
                technology=tech.name,
                detected_version=tech.version,
                detected_version_confidence=tech.version_confidence,
                outcome=outcome,
                capability_level=cap_level,
                evidence=[e.evidence for e in tech.evidence],
                blocks_modernization=outcome in (
                    ComparisonOutcome.UNSUPPORTED,
                    ComparisonOutcome.TOOL_REQUIRED,
                    ComparisonOutcome.MODEL_REQUIRED,
                ),
            ))
        return comparisons
