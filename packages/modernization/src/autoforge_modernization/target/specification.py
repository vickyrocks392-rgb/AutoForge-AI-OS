"""Target Specification and Target Capability Derivation for AutoForge.

Enforces Section 12 of the architectural mandate:
Target Technology is a declarative specification:
- language
- framework
- runtime
- database
- build system
- deployment model
- verification requirements

Target specification drives target capability requirements independently of source.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.models import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityRequirement,
)
from autoforge_modernization.target_technology import (
    TargetTechnologyKnowledge,
    TargetTechnologyRegistry,
    default_target_technology_registry,
)


class TargetSpecification(BaseModel):
    """Declarative specification of the desired target platform."""

    language: str
    framework: str | None = None
    runtime: str | None = None
    database: str | None = None
    build_system: str | None = None
    deployment_model: str = "container"
    verification_requirements: list[str] = Field(
        default_factory=lambda: ["syntax", "compile", "tests"]
    )
    custom_conventions: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def java_spring_boot(cls) -> TargetSpecification:
        return cls(
            language="Java",
            framework="Spring Boot",
            runtime="OpenJDK 21",
            database="PostgreSQL",
            build_system="Maven",
            verification_requirements=["syntax", "compile", "tests"],
        )

    @classmethod
    def python_fastapi(cls) -> TargetSpecification:
        return cls(
            language="Python",
            framework="FastAPI",
            runtime="CPython 3.11",
            database="PostgreSQL",
            build_system="pip + pyproject.toml",
            verification_requirements=["syntax", "compile", "tests"],
        )

    @classmethod
    def typescript_node(cls) -> TargetSpecification:
        return cls(
            language="TypeScript",
            framework="Express",
            runtime="Node.js 20",
            build_system="npm",
            verification_requirements=["syntax", "tests"],
        )


class TargetCapabilityDeriver:
    """Translates TargetSpecification into required capabilities."""

    def __init__(self, target_registry: TargetTechnologyRegistry | None = None) -> None:
        self.target_registry = target_registry or default_target_technology_registry()

    def derive_requirements(self, spec: TargetSpecification) -> list[CapabilityRequirement]:
        reqs: list[CapabilityRequirement] = []
        lang_upper = spec.language.upper()

        # 1. Target Code Generation Requirement
        reqs.append(
            CapabilityRequirement(
                technology=lang_upper,
                capability_class=CapabilityClass.TARGET_GENERATION,
                capability_name=f"{spec.language.lower()}_source_generation",
                description=f"Generate idiomatic {spec.language}"
                + (f" with {spec.framework}" if spec.framework else "")
                + " code structures.",
                mandatory=True,
                minimum_level=CapabilityLevel.FULL_TRANSFORM,
            )
        )

        # 2. Target Compilation / Syntax Verification Requirement
        if "compile" in spec.verification_requirements or lang_upper in ("JAVA", "GOLANG", "CSHARP"):
            compile_cap = "javac_compilation" if lang_upper == "JAVA" else f"{spec.language.lower()}_byte_compile"
            reqs.append(
                CapabilityRequirement(
                    technology=lang_upper,
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name=compile_cap,
                    description=f"Execute compiler verification for {spec.language}.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                    remediation_hint=f"Ensure compiler toolchain for {spec.language} is verified on the host.",
                )
            )

        if "syntax" in spec.verification_requirements:
            syntax_cap = "node_syntax_check" if lang_upper in ("TYPESCRIPT", "JAVASCRIPT") else f"{spec.language.lower()}_syntax_check"
            reqs.append(
                CapabilityRequirement(
                    technology=lang_upper,
                    capability_class=CapabilityClass.TARGET_VERIFICATION,
                    capability_name=syntax_cap,
                    description=f"Validate AST / syntax for {spec.language}.",
                    mandatory=True,
                    minimum_level=CapabilityLevel.VERIFY,
                )
            )

        # 3. Target Knowledge match
        knowledge = self.target_registry.get(
            f"{spec.language.lower()}-{spec.framework.lower().replace(' ', '-')}"
            if spec.framework
            else spec.language.lower()
        )
        if knowledge is None:
            # Fallback to language lookup
            cand = self.target_registry.find(language=spec.language)
            knowledge = cand[0] if cand else None

        return reqs
