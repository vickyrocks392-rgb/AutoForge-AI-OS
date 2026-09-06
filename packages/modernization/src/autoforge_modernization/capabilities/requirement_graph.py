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

        # ── CICS ───────────────────────────────────────────────────────────
        self.register_requirements(
            "CICS",
            [
                CapabilityRequirement(
                    technology="CICS",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="cics_command_parsing",
                    description="Parsing of EXEC CICS statements, maps, programs, and dataset operations.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="CICS",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="cics_transaction_program_mapping",
                    description="Mapping of CICS transaction IDs to COBOL programs and BMS maps.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
            ],
        )

        # ── BMS ────────────────────────────────────────────────────────────
        self.register_requirements(
            "BMS",
            [
                CapabilityRequirement(
                    technology="BMS",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="bms_map_parsing",
                    description="Parsing of BMS map definitions (DFHMSD/DFHMDI/DFHMDF).",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="BMS",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="bms_screen_field_extraction",
                    description="Extraction of 3270 screen coordinates and emission of modern UI screen models.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
            ],
        )

        # ── VSAM ───────────────────────────────────────────────────────────
        self.register_requirements(
            "VSAM",
            [
                CapabilityRequirement(
                    technology="VSAM",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="vsam_file_definition_analysis",
                    description="Analysis of VSAM datasets, organizations (KSDS/ESDS/RRDS), and key offsets.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="VSAM",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="vsam_key_crud_mapping",
                    description="Analysis of VSAM READ/WRITE/REWRITE/DELETE operations.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
            ],
        )

        # ── DB2 / EMBEDDED SQL ─────────────────────────────────────────────
        self.register_requirements(
            "DB2",
            [
                CapabilityRequirement(
                    technology="DB2",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="db2_embedded_sql_extraction",
                    description="Extraction of EXEC SQL statements, host variables, and SQLCA checks.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="DB2",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="db2_ddl_schema_analysis",
                    description="Analysis of DB2 table schemas, indexes, and primary/foreign keys.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
            ],
        )

        # ── COPYBOOK ───────────────────────────────────────────────────────
        copybook_reqs = [
            CapabilityRequirement(
                technology="COPYBOOK",
                capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                capability_name="copybook_resolution_expansion",
                description="Recursive resolution and expansion of COPY statements across libraries.",
                mandatory=True,
                minimum_level=CapabilityLevel.ANALYZE,
            ),
            CapabilityRequirement(
                technology="COPYBOOK",
                capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                capability_name="copybook_catalog_indexing",
                description="Catalog indexing and nested copybook graph construction.",
                mandatory=True,
                minimum_level=CapabilityLevel.ANALYZE,
            ),
        ]
        self.register_requirements("COPYBOOK", copybook_reqs)
        self.register_requirements("COBOL_COPYBOOK", copybook_reqs)

        # ── BATCH & TRANSACTION DEPENDENCIES ───────────────────────────────
        self.register_requirements(
            "DEPENDENCIES",
            [
                CapabilityRequirement(
                    technology="DEPENDENCIES",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="batch_job_step_flow_analysis",
                    description="Analysis of batch job step execution order and dataset linkages.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="DEPENDENCIES",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="cross_technology_call_graph",
                    description="Multigraph representation of JCL -> COBOL -> CICS -> VSAM/DB2 interactions.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
            ],
        )

        # ── SQL / RELATIONAL DATABASES ─────────────────────────────────────
        self.register_requirements(
            "SQL",
            [
                CapabilityRequirement(
                    technology="SQL",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="sql_ddl_parsing",
                    description="Parsing and extraction of relational tables, columns, and constraints.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="SQL",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="sql_schema_verification",
                    description="Executable schema verification against SQLite or relational engine.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── SPRING BOOT (Target) ───────────────────────────────────────────
        self.register_requirements(
            "SPRING_BOOT",
            [
                CapabilityRequirement(
                    technology="SPRING_BOOT",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="spring_boot_project_generation",
                    description="Generation of Spring Boot project layout, models, repositories, and controllers.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="SPRING_BOOT",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="spring_component_verification",
                    description="Structural verification of Spring Boot components and annotations.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── FASTAPI (Target) ───────────────────────────────────────────────
        self.register_requirements(
            "FASTAPI",
            [
                CapabilityRequirement(
                    technology="FASTAPI",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="fastapi_route_generation",
                    description="Generation of FastAPI router endpoints, Pydantic models, and dependencies.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="FASTAPI",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="fastapi_route_verification",
                    description="Verification of FastAPI routes and Pydantic schemas via AST.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── NODEJS (Target / Runtime) ──────────────────────────────────────
        self.register_requirements(
            "NODEJS",
            [
                CapabilityRequirement(
                    technology="NODEJS",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="nodejs_project_generation",
                    description="Generation of package.json, runtime scripts, and module structures.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="NODEJS",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="node_syntax_check",
                    description="Node.js execution and syntax verification.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── EXPRESS (Target) ───────────────────────────────────────────────
        self.register_requirements(
            "EXPRESS",
            [
                CapabilityRequirement(
                    technology="EXPRESS",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="express_route_generation",
                    description="Generation of Express router handlers, middleware, and app setups.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="EXPRESS",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="express_route_verification",
                    description="Verification of Express router scripts via Node runtime.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── REACT (Target) ─────────────────────────────────────────────────
        self.register_requirements(
            "REACT",
            [
                CapabilityRequirement(
                    technology="REACT",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="react_component_generation",
                    description="Generation of modern functional React components with hooks and TypeScript props.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="REACT",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="react_component_syntax_check",
                    description="Verification of React component structure and JSX syntax.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── GO (Target) ────────────────────────────────────────────────────
        self.register_requirements(
            "GO",
            [
                CapabilityRequirement(
                    technology="GO",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="go_source_generation",
                    description="Generation of idiomatic Go packages, structs, and interfaces.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="GO",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="go_syntax_check",
                    description="Verification of Go syntax and package compilation.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                    remediation_hint="Install Go toolchain (e.g. brew install go) to enable Go verification.",
                ),
            ],
        )

        # ── REST API ───────────────────────────────────────────────────────
        self.register_requirements(
            "REST_API",
            [
                CapabilityRequirement(
                    technology="REST_API",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="openapi_spec_generation",
                    description="Emission of OpenAPI 3.0 / 3.1 REST contract specifications.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="REST_API",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="rest_contract_validation",
                    description="Structural validation of REST contracts and OpenAPI schemas.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                ),
            ],
        )

        # ── DOCKER ─────────────────────────────────────────────────────────
        self.register_requirements(
            "DOCKER",
            [
                CapabilityRequirement(
                    technology="DOCKER",
                    capability_class=CapabilityClass.TARGET_GENERATION,
                    capability_name="dockerfile_generation",
                    description="Emission of production-grade, multi-stage Dockerfiles and container specs.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.FULL_TRANSFORM,
                ),
                CapabilityRequirement(
                    technology="DOCKER",
                    capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                    capability_name="docker_syntax_validation",
                    description="Static understanding and structural validation of Dockerfile instructions.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.ANALYZE,
                ),
                CapabilityRequirement(
                    technology="DOCKER",
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name="docker_container_execution",
                    description="Docker Engine build, run, and container execution.",
                    mandatory=False,
                    minimum_level=CapabilityLevel.VERIFY,
                    remediation_hint="Install Docker Engine / Docker Desktop (brew install --cask docker).",
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
