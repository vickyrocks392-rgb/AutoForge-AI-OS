"""Capability Requirement Graph for AutoForge.

Enforces Section 5 of the architectural mandate:
Maps:
technology -> required capabilities
WITHOUT hardcoding migration pairs.

Technologies declare what is needed to understand, generate, or verify them
independently of what source or target they might be paired with.
"""

from __future__ import annotations

from typing import Any

from autoforge_modernization.capabilities.models import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityRequirement,
)


class CapabilityRequirementGraph:
    """Authoritative mapping from Technology to Capability Requirements."""

    def __init__(self) -> None:
        self._tech_rules: dict[str, list[CapabilityRequirement]] = {}
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        # ── COBOL ──────────────────────────────────────────────────────────
        self.register_requirements(
            "COBOL",
            [
                CapabilityRequirement(
                    technology="COBOL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="cobol_lexical_syntactic_analysis",
                    description="Syntactic parsing and AST construction of COBOL divisions and paragraphs.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="COBOL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="cobol_copybook_resolution",
                    description="Resolution and expansion of COPY statements and external copybook files.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="COBOL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="cobol_call_relationship_analysis",
                    description="Analysis of static and dynamic CALL statements and external module links.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="COBOL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="cobol_control_data_flow_analysis",
                    description="Extraction of PERFORM flow, branches, loops, and data item dependencies.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="COBOL",
                    capability_class=CapabilityClass.SEMANTIC_KNOWLEDGE,
                    capability_name="cobol_business_rule_extraction",
                    description="Extraction of business logic into technology-neutral rule statements.",
                    mandatory=False,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
            ],
        )

        # ── JCL ────────────────────────────────────────────────────────────
        self.register_requirements(
            "JCL",
            [
                CapabilityRequirement(
                    technology="JCL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="jcl_job_parsing",
                    description="Parsing of JOB cards, EXEC steps, and DD dataset definitions.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="JCL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="jcl_procedure_resolution",
                    description="Resolution of cataloged/instream procedures (PROC/INCLUDE).",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="JCL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="jcl_dataset_analysis",
                    description="Analysis of DD statements, dispositions, and dataset dependencies.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="JCL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="jcl_execution_flow_analysis",
                    description="Analysis of job step flow, COND evaluation, and execution order.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
            ],
        )

        # ── JAVA (Target) ──────────────────────────────────────────────────
        self.register_requirements(
            "JAVA",
            [
                CapabilityRequirement(
                    technology="JAVA",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="java_source_generation",
                    description="Emission of idiomatic, type-safe Java classes, records, and methods.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="JAVA",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="javac_compilation",
                    description="Real bytecode compilation verification using OpenJDK javac.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                    remediation_hint="Install OpenJDK (e.g. brew install openjdk@21) and configure JAVA_HOME.",
                ),
                CapabilityRequirement(
                    technology="JAVA",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="java_class_verification",
                    description="Structural and syntactic verification of emitted Java source.",
                    mandatory=False,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── PYTHON (Target) ────────────────────────────────────────────────
        self.register_requirements(
            "PYTHON",
            [
                CapabilityRequirement(
                    technology="PYTHON",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="python_source_generation",
                    description="Emission of idiomatic, typed Python modules, classes, and async functions.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="PYTHON",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="python_syntax_check",
                    description="AST syntax validation using the CPython parser.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
                CapabilityRequirement(
                    technology="PYTHON",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="python_byte_compile",
                    description="Real bytecode compilation verification using Python compile().",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── TYPESCRIPT (Target) ───────────────────────────────────────────
        self.register_requirements(
            "TYPESCRIPT",
            [
                CapabilityRequirement(
                    technology="TYPESCRIPT",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="typescript_source_generation",
                    description="Emission of TypeScript classes, interfaces, and modules.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="TYPESCRIPT",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="node_syntax_check",
                    description="Syntax and runtime check using Node.js.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── SPECIALIST TECHNOLOGIES (IMS, ASSEMBLER) ──────────────────────
        self.register_requirements(
            "IMS",
            [
                CapabilityRequirement(
                    technology="IMS",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="ims_specialist_consultation",
                    description="Specialist consultation for IMS DBD/PSB hierarchical database and DL/I.",
                    mandatory=False,
                    minimum_level=CapabilityLevel.DETECT,
                    remediation_hint="Specialist intervention required for IMS hierarchical modeling.",
                ),
            ],
        )
        self.register_requirements(
            "ASSEMBLER",
            [
                CapabilityRequirement(
                    technology="ASSEMBLER",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="assembler_specialist_consultation",
                    description="Specialist consultation for IBM High Level Assembler (HLASM) reverse engineering.",
                    mandatory=False,
                    minimum_level=CapabilityLevel.DETECT,
                    remediation_hint="Specialist intervention required for low-level register/macro assembly.",
                ),
            ],
        )

    def register_requirements(self, technology: str, requirements: list[CapabilityRequirement]) -> None:
        tech_key = technology.upper()
        self._tech_rules.setdefault(tech_key, []).extend(requirements)

    def get_requirements(self, technology: str) -> list[CapabilityRequirement]:
        return list(self._tech_rules.get(technology.upper(), []))

    def get_requirements_for_technologies(self, technologies: list[str]) -> list[CapabilityRequirement]:
        reqs: list[CapabilityRequirement] = []
        for t in technologies:
            reqs.extend(self.get_requirements(t))
        return reqs
