"""Target-technology knowledge layer for production modernization.

Represents the TARGET side of a modernization transformation with enough
depth to generate valid, production-oriented code:

* language and language version
* framework and framework version
* build system and dependency management
* database technology and conventions
* API conventions
* testing conventions
* deployment/runtime conventions
* project-specific conventions
* architecture constraints

The layer is deliberately technology-agnostic and extensible.  Future targets
(Java, Kotlin, Python, TypeScript, C#, Go, SQL, Spring Boot, and other
frameworks/platforms) are registered as data - nothing is hard-coded around a
single language.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Convention blocks
# ---------------------------------------------------------------------------


class TargetLanguageConventions(BaseModel):
    """Language-level conventions needed to emit valid target code."""

    language: str
    version: str = ""
    file_extension: str = ".txt"
    comment_syntax: list[str] = Field(default_factory=lambda: ["//"])
    identifier_rules: str = ""
    package_or_namespace_keyword: str = "package"
    type_mapping_notes: str = ""
    decimal_type: str = "BigDecimal"
    long_integer_type: str = "long"
    string_type: str = "String"
    date_type: str = "LocalDate"
    boolean_type: str = "boolean"
    numeric_default_initializer: str = "0"
    class_keyword: str = "class"
    method_keyword: str = "public"
    null_literal: str = "null"
    reserved_words: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [
            f"Language: {self.language} {self.version}".strip(),
            f"File extension: {self.file_extension}",
            f"Comments: {', '.join(self.comment_syntax)}",
            f"Identifiers: {self.identifier_rules}",
            f"String: {self.string_type}  Decimal: {self.decimal_type}  "
            f"Long integer: {self.long_integer_type}  Date: {self.date_type}",
            f"Null literal: {self.null_literal}",
        ]
        if self.notes:
            lines.append("Language notes: " + "; ".join(self.notes))
        return "\n".join(lines)


class TargetFrameworkConventions(BaseModel):
    """Framework-level conventions (component model, layout, DI, config)."""

    framework: str
    version: str = ""
    component_annotation: str = ""
    package_layout: list[str] = Field(default_factory=list)
    dependency_injection_style: str = ""
    configuration_mechanism: str = ""
    transaction_annotation: str = ""
    rest_mapping_annotation: str = ""
    unit_runner: str = ""
    conventions: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [f"Framework: {self.framework} {self.version}".strip()]
        if self.component_annotation:
            lines.append(f"Component marker: {self.component_annotation}")
        if self.package_layout:
            lines.append("Package layout: " + ", ".join(self.package_layout))
        if self.dependency_injection_style:
            lines.append(f"DI style: {self.dependency_injection_style}")
        if self.configuration_mechanism:
            lines.append(f"Configuration: {self.configuration_mechanism}")
        if self.conventions:
            lines.append("Framework conventions: " + "; ".join(self.conventions))
        return "\n".join(lines)


class TargetBuildConventions(BaseModel):
    """Build tooling and dependency management conventions."""

    build_system: str = ""
    dependency_management: str = ""
    build_command: str = ""
    test_command: str = ""
    lint_command: str = ""
    source_directory: str = "src"
    dependency_file: str = ""
    notes: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [
            f"Build system: {self.build_system}",
            f"Dependency management: {self.dependency_management}",
            f"Build command: {self.build_command}",
            f"Test command: {self.test_command}",
        ]
        if self.notes:
            lines.append("Build notes: " + "; ".join(self.notes))
        return "\n".join(lines)


class TargetDatabaseConventions(BaseModel):
    """Database technology conventions (dialect, ORM, transactions)."""

    database: str = ""
    dialect: str = ""
    orm_or_mapping: str = ""
    transaction_notes: str = ""
    migration_tool: str = ""
    ddl_type_mapping: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [f"Database: {self.database} (dialect: {self.dialect})"]
        if self.orm_or_mapping:
            lines.append(f"ORM/mapping: {self.orm_or_mapping}")
        if self.migration_tool:
            lines.append(f"Migrations: {self.migration_tool}")
        if self.ddl_type_mapping:
            lines.append("DDL type mapping: " + ", ".join(
                f"{k}->{v}" for k, v in self.ddl_type_mapping.items()
            ))
        return "\n".join(lines)


class TargetApiConventions(BaseModel):
    """API design conventions for the target platform."""

    style: str = "REST"
    base_path: str = ""
    content_type: str = "application/json"
    error_response_schema: str = ""
    versioning: str = ""
    notes: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [
            f"API style: {self.style}",
            f"Base path: {self.base_path or '(n/a)'}",
            f"Content type: {self.content_type}",
        ]
        if self.versioning:
            lines.append(f"Versioning: {self.versioning}")
        return "\n".join(lines)


class TargetTestingConventions(BaseModel):
    """Testing conventions for generated code."""

    framework: str = ""
    test_file_suffix: str = "Test"
    assertion_style: str = ""
    test_annotation: str = ""
    test_discovery_command: str = ""
    notes: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [f"Test framework: {self.framework}", f"Test discovery: {self.test_discovery_command}"]
        if self.assertion_style:
            lines.append(f"Assertion style: {self.assertion_style}")
        return "\n".join(lines)


class TargetDeploymentConventions(BaseModel):
    """Deployment and runtime conventions."""

    runtime: str = ""
    packaging: str = ""
    container_base: str = ""
    health_check_pattern: str = ""
    env_config: str = ""
    port: int | None = None
    notes: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [
            f"Runtime: {self.runtime}",
            f"Packaging: {self.packaging}",
            f"Container base: {self.container_base}",
            f"Health check: {self.health_check_pattern}",
        ]
        if self.port:
            lines.append(f"Default port: {self.port}")
        return "\n".join(lines)


class TargetProjectConventions(BaseModel):
    """Project/local conventions applied to all generated code."""

    base_package: str = "com.autoforge.generated"
    generated_package: str = "com.autoforge.generated"
    resource_directory: str = "src/main/resources"
    module_layout: list[str] = Field(default_factory=list)
    coding_standards: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def to_context_text(self) -> str:
        lines = [
            f"Base package: {self.base_package}",
            f"Generated package: {self.generated_package}",
        ]
        if self.coding_standards:
            lines.append("Standards: " + "; ".join(self.coding_standards))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Aggregate target knowledge
# ---------------------------------------------------------------------------


class TargetTechnologyKnowledge(BaseModel):
    """The complete knowledge block for one target technology."""

    knowledge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str  # canonical id, e.g. "java-spring-boot"
    display_name: str = ""
    description: str = ""
    supported_source_technologies: list[str] = Field(default_factory=list)

    language: TargetLanguageConventions = Field(default_factory=TargetLanguageConventions)
    framework: TargetFrameworkConventions | None = None
    build: TargetBuildConventions = Field(default_factory=TargetBuildConventions)
    database: TargetDatabaseConventions | None = None
    api: TargetApiConventions = Field(default_factory=TargetApiConventions)
    testing: TargetTestingConventions = Field(default_factory=TargetTestingConventions)
    deployment: TargetDeploymentConventions = Field(default_factory=TargetDeploymentConventions)
    project: TargetProjectConventions = Field(default_factory=TargetProjectConventions)

    architecture_constraints: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)

    source: str = "knowledge_base"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    last_updated: datetime = Field(default_factory=_utc_now)

    @property
    def language_name(self) -> str:
        return self.language.language

    @property
    def language_version(self) -> str:
        return self.language.version

    @property
    def framework_name(self) -> str:
        return self.framework.framework if self.framework else ""

    @property
    def framework_version(self) -> str:
        return self.framework.version if self.framework else ""

    def supports_source(self, source_technology: str) -> bool:
        src = (source_technology or "").lower()
        return src in {s.lower() for s in self.supported_source_technologies}

    def to_context_text(self, max_chars: int = 4000) -> str:
        """Deterministic, bounded, provenance-labelled target knowledge block."""
        blocks = [
            f"[TARGET TECHNOLOGY KNOWLEDGE] id={self.name} "
            f"(source={self.source}, confidence={self.confidence:.2f})",
            self.language.to_context_text(),
        ]
        if self.framework is not None:
            blocks.append(self.framework.to_context_text())
        blocks.append(self.build.to_context_text())
        if self.database is not None:
            blocks.append(self.database.to_context_text())
        blocks.append(self.api.to_context_text())
        blocks.append(self.testing.to_context_text())
        blocks.append(self.deployment.to_context_text())
        blocks.append(self.project.to_context_text())
        if self.architecture_constraints:
            blocks.append(
                "Architecture constraints: " + "; ".join(self.architecture_constraints)
            )
        text = "\n".join(blocks)
        if len(text) > max_chars:
            text = text[: max_chars - 60] + "\n...[target knowledge truncated per budget]"
        return text

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "language": self.language_name,
            "language_version": self.language_version,
            "framework": self.framework_name,
            "framework_version": self.framework_version,
            "build_system": self.build.build_system,
            "dependency_management": self.build.dependency_management,
            "database": self.database.database if self.database else None,
            "api_style": self.api.style,
            "testing_framework": self.testing.framework,
            "runtime": self.deployment.runtime,
            "supported_source_technologies": self.supported_source_technologies,
        }


# ---------------------------------------------------------------------------
# Default target entries
# ---------------------------------------------------------------------------


def _java_spring_boot_entry() -> TargetTechnologyKnowledge:
    return TargetTechnologyKnowledge(
        name="java-spring-boot",
        display_name="Java 17 + Spring Boot 3",
        description="Enterprise Java with Spring Boot 3 for COBOL/JCL modernization.",
        supported_source_technologies=["cobol", "jcl", "cics", "bms", "pli", "rpg", "vsam"],
        language=TargetLanguageConventions(
            language="Java",
            version="17",
            file_extension=".java",
            comment_syntax=["//", "/* */", "/** */"],
            identifier_rules="UpperCamelCase classes, lowerCamelCase methods/fields; "
            "letters+digits+underscore, cannot start with digit",
            package_or_namespace_keyword="package",
            type_mapping_notes="COBOL PIC 9(n) -> int/long/BigDecimal; "
            "PIC X -> String; packed decimal -> BigDecimal; dates -> LocalDate",
            decimal_type="BigDecimal",
            long_integer_type="long",
            string_type="String",
            date_type="LocalDate",
            boolean_type="boolean",
            numeric_default_initializer="0",
            class_keyword="class",
            reserved_words=[
                "class", "public", "private", "protected", "void", "int",
                "long", "float", "double", "boolean", "new", "return", "if",
                "else", "switch", "case", "default", "for", "while", "do",
                "break", "continue", "static", "final", "extends", "implements",
                "import", "package", "try", "catch", "finally", "throw",
                "throws", "this", "super", "null", "true", "false", "abstract",
                "interface", "enum", "record",
            ],
            notes=[
                "Generated code targets Java 17: prefer records for data carriers.",
                "Use java.math.BigDecimal for all monetary values.",
                "Do not use raw types; avoid checked-exception misuse.",
            ],
        ),
        framework=TargetFrameworkConventions(
            framework="Spring Boot",
            version="3.x",
            component_annotation="@Component",
            package_layout=["controller", "service", "repository", "model", "config"],
            dependency_injection_style="constructor injection with final fields",
            configuration_mechanism="application.yml + @ConfigurationProperties",
            transaction_annotation="@Transactional",
            rest_mapping_annotation="@RestController + @RequestMapping",
            unit_runner="@SpringBootTest",
            conventions=[
                "Batch programs map to Spring Batch Jobs (Tasklet-based).",
                "CICS transactional logic maps to @Transactional service methods.",
                "VSAM files map to JPA entities or Spring Batch ItemReader/Writer.",
                "SQL embeds map to Spring Data JPA repositories.",
            ],
        ),
        build=TargetBuildConventions(
            build_system="Maven",
            dependency_management="pom.xml",
            build_command="mvn -q compile",
            test_command="mvn -q test",
            lint_command="mvn -q compile",
            source_directory="src/main/java",
            dependency_file="pom.xml",
            notes=["Generated sources belong under src/main/java."],
        ),
        database=TargetDatabaseConventions(
            database="PostgreSQL",
            dialect="PostgreSQL 15",
            orm_or_mapping="Spring Data JPA / Jakarta Persistence",
            transaction_notes="@Transactional boundaries per service method",
            migration_tool="Flyway or Liquibase",
            ddl_type_mapping={
                "VARCHAR": "varchar(255)",
                "DECIMAL": "decimal(19,2)",
                "DATE": "date",
                "TIMESTAMP": "timestamp",
                "INTEGER": "integer",
                "BIGINT": "bigint",
                "CHAR": "char(n)",
                "PIC9": "numeric",
            },
        ),
        api=TargetApiConventions(
            style="REST",
            base_path="/api",
            content_type="application/json",
            error_response_schema='{"status": int, "message": string, "timestamp": iso8601}',
        ),
        testing=TargetTestingConventions(
            framework="JUnit 5",
            test_file_suffix="Test",
            assertion_style="AssertJ fluent assertions",
            test_annotation="@Test",
            test_discovery_command="mvn -q test",
        ),
        deployment=TargetDeploymentConventions(
            runtime="JVM 17+",
            packaging="Spring Boot fat JAR (maven package)",
            container_base="eclipse-temurin:17-jre",
            health_check_pattern="/actuator/health",
            env_config="application.yml + env vars",
            port=8080,
        ),
        project=TargetProjectConventions(
            base_package="com.autoforge.generated",
            generated_package="com.autoforge.generated",
            resource_directory="src/main/resources",
            coding_standards=[
                "One top-level type per file.",
                "Constructor injection (no field injection).",
                "Never suppress lint warnings without justification.",
            ],
        ),
        architecture_constraints=[
            "No servlet-specific types in service layer.",
            "Batch jobs are idempotent and restartable.",
            "All external I/O crosses an adapter boundary.",
        ],
        aliases=["java", "java17", "spring-boot", "spring", "springboot"],
        confidence=0.92,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TargetTechnologyRegistry:
    """Registry of TargetTechnologyKnowledge entries.

    Extensible: new targets (Kotlin, TypeScript, C#, Go, ...) are registered
    as ordinary data. No code changes are required to add future targets.
    """

    def __init__(self, entries: list[TargetTechnologyKnowledge] | None = None) -> None:
        self._by_name: dict[str, TargetTechnologyKnowledge] = {}
        self._by_alias: dict[str, str] = {}
        for entry in entries or []:
            self.register(entry)

    def register(self, entry: TargetTechnologyKnowledge) -> None:
        self._by_name[entry.name] = entry
        for alias in entry.aliases:
            self._by_alias[alias.lower()] = entry.name

    def register_many(self, entries: list[TargetTechnologyKnowledge]) -> None:
        for entry in entries:
            self.register(entry)

    def get(self, name: str) -> TargetTechnologyKnowledge | None:
        key = (name or "").lower()
        if key in self._by_name:
            return self._by_name[key]
        resolved = self._by_alias.get(key)
        return self._by_name.get(resolved) if resolved else None

    def all(self) -> list[TargetTechnologyKnowledge]:
        return list(self._by_name.values())

    def for_source(self, source_technology: str) -> list[TargetTechnologyKnowledge]:
        return [
            e for e in self._by_name.values()
            if e.supports_source(source_technology)
        ]

    def find(
        self,
        source_technology: str | None = None,
        language: str | None = None,
        framework: str | None = None,
    ) -> list[TargetTechnologyKnowledge]:
        results = list(self._by_name.values())
        if source_technology:
            results = [e for e in results if e.supports_source(source_technology)]
        if language:
            lang = language.lower()
            results = [e for e in results if e.language.language.lower() == lang]
        if framework:
            fw = framework.lower()
            results = [
                e for e in results
                if e.framework and e.framework.framework.lower() == fw
            ]
        return results

    def capabilities(self) -> dict[str, Any]:
        return {
            "targets": sorted(self._by_name),
            "targets_count": len(self._by_name),
        }


def _kotlin_spring_boot_entry() -> TargetTechnologyKnowledge:
    return TargetTechnologyKnowledge(
        name="kotlin-spring-boot",
        display_name="Kotlin + Spring Boot 3",
        description="Kotlin JVM target with Spring Boot 3 for modernization.",
        supported_source_technologies=["cobol", "jcl", "cics"],
        language=TargetLanguageConventions(
            language="Kotlin",
            version="1.9",
            file_extension=".kt",
            comment_syntax=["//", "/* */", "/** */"],
            identifier_rules="UpperCamelCase classes, lowerCamelCase functions/vars",
            package_or_namespace_keyword="package",
            type_mapping_notes="PIC X -> String; numeric -> BigDecimal/Long; dates -> LocalDate",
            decimal_type="BigDecimal",
            long_integer_type="Long",
            string_type="String",
            date_type="LocalDate",
            boolean_type="Boolean",
            null_literal="null",
            class_keyword="class",
            notes=["Data classes replace POJOs."],
        ),
        framework=TargetFrameworkConventions(
            framework="Spring Boot",
            version="3.x",
            component_annotation="@Component",
            dependency_injection_style="constructor injection via data class primary constructors",
            configuration_mechanism="application.yml",
            transaction_annotation="@Transactional",
            unit_runner="@SpringBootTest",
        ),
        build=TargetBuildConventions(
            build_system="Gradle",
            dependency_management="build.gradle.kts",
            build_command="gradle compileKotlin",
            test_command="gradle test",
            dependency_file="build.gradle.kts",
        ),
        aliases=["kotlin", "kotlin17", "kspring"],
        confidence=0.88,
    )


def _python_fastapi_entry() -> TargetTechnologyKnowledge:
    return TargetTechnologyKnowledge(
        name="python-fastapi",
        display_name="Python 3 + FastAPI",
        description="Python web/services target for interpreted modernization.",
        supported_source_technologies=["cobol", "jcl", "sql", "shell", "pli"],
        language=TargetLanguageConventions(
            language="Python",
            version="3.11",
            file_extension=".py",
            comment_syntax=["#"],
            identifier_rules="snake_case functions/vars, UpperCamelCase classes",
            package_or_namespace_keyword="from __future__ import annotations",
            type_mapping_notes="PIC X -> str; PIC 9 -> int/Decimal; dates -> datetime.date",
            decimal_type="Decimal",
            long_integer_type="int",
            string_type="str",
            date_type="datetime.date",
            boolean_type="bool",
            numeric_default_initializer="0",
            class_keyword="class",
            null_literal="None",
            notes=["Type hints are required on public signatures."],
        ),
        framework=TargetFrameworkConventions(
            framework="FastAPI",
            version="0.100+",
            package_layout=["api", "services", "repositories", "models"],
            dependency_injection_style="FastAPI Depends()",
            configuration_mechanism="pydantic-settings + .env",
            rest_mapping_annotation="@router decorator",
            unit_runner="pytest",
        ),
        build=TargetBuildConventions(
            build_system="pip + venv",
            dependency_management="pyproject.toml",
            build_command="python -m build",
            test_command="pytest -q",
            lint_command="ruff check .",
            dependency_file="pyproject.toml",
        ),
        database=TargetDatabaseConventions(
            database="PostgreSQL",
            dialect="PostgreSQL 15",
            orm_or_mapping="SQLAlchemy 2.0",
            migration_tool="Alembic",
        ),
        api=TargetApiConventions(
            style="REST",
            base_path="/api",
            content_type="application/json",
            error_response_schema='{"detail": string}',
        ),
        testing=TargetTestingConventions(
            framework="pytest",
            test_file_suffix="_test",
            assertion_style="assert",
            test_discovery_command="pytest -q",
        ),
        deployment=TargetDeploymentConventions(
            runtime="CPython 3.11",
            packaging="uvicorn + pip wheel",
            container_base="python:3.11-slim",
            health_check_pattern="/health",
            env_config=".env",
            port=8000,
        ),
        architecture_constraints=[
            "Async services only; no blocking HttpClient in request path.",
        ],
        aliases=["python", "py", "python3", "fastapi"],
        confidence=0.9,
    )


def _typescript_node_entry() -> TargetTechnologyKnowledge:
    return TargetTechnologyKnowledge(
        name="typescript-node",
        display_name="TypeScript + Node.js",
        description="TypeScript target for modernization toward Node services.",
        supported_source_technologies=["cobol", "jcl", "shell", "sql"],
        language=TargetLanguageConventions(
            language="TypeScript",
            version="5.x",
            file_extension=".ts",
            comment_syntax=["//", "/* */"],
            identifier_rules="UpperCamelCase classes/interfaces, lowerCamelCase members",
            package_or_namespace_keyword="import",
            type_mapping_notes="PIC X -> string; numeric -> number/BigInt",
            decimal_type="bigint",
            long_integer_type="number",
            string_type="string",
            date_type="Date",
            boolean_type="boolean",
            numeric_default_initializer="0",
            class_keyword="class",
            null_literal="null",
            notes=["Strict mode required; no implicit any."],
        ),
        framework=TargetFrameworkConventions(
            framework="Express",
            version="4.x",
            package_layout=["src/routes", "src/services", "src/repositories"],
            configuration_mechanism="dotenv",
            rest_mapping_annotation="app.get/post/put/delete",
            unit_runner="vitest",
        ),
        build=TargetBuildConventions(
            build_system="npm",
            dependency_management="package.json",
            build_command="npm run build",
            test_command="npm test",
            lint_command="eslint .",
            dependency_file="package.json",
        ),
        database=TargetDatabaseConventions(
            database="PostgreSQL",
            dialect="PostgreSQL 15",
            orm_or_mapping="Prisma ORM",
            migration_tool="prisma migrate",
        ),
        api=TargetApiConventions(
            style="REST",
            base_path="/api",
            content_type="application/json",
        ),
        testing=TargetTestingConventions(
            framework="vitest",
            test_file_suffix=".test",
            assertion_style="expect()",
            test_discovery_command="npm test",
        ),
        deployment=TargetDeploymentConventions(
            runtime="Node.js 20+",
            packaging="npm pack / Docker",
            container_base="node:20-alpine",
            health_check_pattern="/health",
            env_config=".env",
            port=3000,
        ),
        aliases=["typescript", "ts", "node", "nodejs", "express"],
        confidence=0.88,
    )


def _csharp_dotnet_entry() -> TargetTechnologyKnowledge:
    return TargetTechnologyKnowledge(
        name="csharp-dotnet",
        display_name="C# + .NET 8",
        description=".NET target for enterprise modernization.",
        supported_source_technologies=["cobol", "jcl", "sql", "cics", "vsam"],
        language=TargetLanguageConventions(
            language="C#",
            version="12",
            file_extension=".cs",
            comment_syntax=["//", "/* */", "///"],
            identifier_rules="PascalCase types, camelCase locals, _camelCase fields",
            package_or_namespace_keyword="namespace",
            type_mapping_notes="PIC X -> string; numeric -> decimal/long; dates -> DateTime",
            decimal_type="decimal",
            long_integer_type="long",
            string_type="string",
            date_type="DateTime",
            boolean_type="bool",
            numeric_default_initializer="0",
            class_keyword="class",
            null_literal="null",
        ),
        framework=TargetFrameworkConventions(
            framework="ASP.NET Core",
            version="8.0",
            component_annotation="[Service] via DI registration",
            package_layout=["Controllers", "Services", "Repositories", "Models"],
            dependency_injection_style="constructor injection (IServiceCollection)",
            configuration_mechanism="appsettings.json",
            transaction_annotation="[UnitOfWork]",
            rest_mapping_annotation="[ApiController] + [HttpPost]",
            unit_runner="xUnit",
        ),
        build=TargetBuildConventions(
            build_system="MSBuild/.NET SDK",
            dependency_management="NuGet (csproj)",
            build_command="dotnet build",
            test_command="dotnet test",
            dependency_file="*.csproj",
        ),
        database=TargetDatabaseConventions(
            database="SQL Server/PostgreSQL",
            dialect="T-SQL/PostgreSQL",
            orm_or_mapping="EF Core",
            migration_tool="dotnet ef migrations",
        ),
        api=TargetApiConventions(
            style="REST",
            base_path="/api",
            content_type="application/json",
        ),
        testing=TargetTestingConventions(
            framework="xUnit",
            test_file_suffix="Tests",
            assertion_style="FluentAssertions",
            test_annotation="[Fact]",
        ),
        deployment=TargetDeploymentConventions(
            runtime=".NET 8",
            packaging="docker image / self-contained",
            container_base="mcr.microsoft.com/dotnet/aspnet:8.0",
            health_check_pattern="/health",
            port=5000,
        ),
        aliases=["csharp", "cs", "dotnet", ".net", "net8"],
        confidence=0.87,
    )


def _golang_entry() -> TargetTechnologyKnowledge:
    return TargetTechnologyKnowledge(
        name="golang",
        display_name="Go 1.22",
        description="Go target for platform/service modernization.",
        supported_source_technologies=["jcl", "shell", "sql", "cobol"],
        language=TargetLanguageConventions(
            language="Go",
            version="1.22",
            file_extension=".go",
            comment_syntax=["//", "/* */"],
            identifier_rules="Exported names start uppercase; unexported lowercase; CamelCase",
            package_or_namespace_keyword="package",
            type_mapping_notes="PIC X -> string; numeric -> int64/float64",
            decimal_type="big.Rat",
            long_integer_type="int64",
            string_type="string",
            date_type="time.Time",
            boolean_type="bool",
            numeric_default_initializer="0",
            class_keyword="struct",
            null_literal="nil",
            notes=["Errors are values; no exceptions."],
        ),
        framework=TargetFrameworkConventions(
            framework="net/http stdlib",
            version="1.22",
            package_layout=["cmd", "internal/handler", "internal/service", "internal/store"],
            dependency_injection_style="constructor injection (functors)",
            configuration_mechanism="env + flag",
            unit_runner="go test",
        ),
        build=TargetBuildConventions(
            build_system="go build",
            dependency_management="go.mod",
            build_command="go build ./...",
            test_command="go test ./...",
            lint_command="go vet ./...",
            dependency_file="go.mod",
        ),
        database=TargetDatabaseConventions(
            database="PostgreSQL",
            dialect="PostgreSQL 15",
            orm_or_mapping="database/sql + pgx",
            migration_tool="goose",
        ),
        api=TargetApiConventions(
            style="REST",
            base_path="/api",
            content_type="application/json",
        ),
        testing=TargetTestingConventions(
            framework="testing",
            test_file_suffix="_test",
            assertion_style="table-driven tests",
            test_annotation="func Test*",
        ),
        deployment=TargetDeploymentConventions(
            runtime="static binary",
            packaging="docker scratch image",
            container_base="gcr.io/distroless/static",
            health_check_pattern="/healthz",
            port=8080,
        ),
        architecture_constraints=["No global mutable state across requests."],
        aliases=["go", "golang1.22", "golang"],
        confidence=0.86,
    )


def _sql_postgres_entry() -> TargetTechnologyKnowledge:
    return TargetTechnologyKnowledge(
        name="sql-postgresql",
        display_name="SQL / PostgreSQL 15",
        description="Database schema and SQL target for data-layer modernization.",
        supported_source_technologies=["sql", "vsam", "ims", "db2", "ddl", "dcl"],
        language=TargetLanguageConventions(
            language="SQL",
            version="PostgreSQL 15",
            file_extension=".sql",
            comment_syntax=["--", "/* */"],
            identifier_rules="snake_case identifiers, quoted only when necessary",
            package_or_namespace_keyword="",
            type_mapping_notes="PIC 9 -> numeric/int; PIC X -> varchar; dates -> date",
            decimal_type="numeric",
            long_integer_type="bigint",
            string_type="varchar",
            date_type="date",
            boolean_type="boolean",
            numeric_default_initializer="0",
            class_keyword="",
            null_literal="NULL",
            notes=["Use varchar(n) only for legacy width constraints."],
        ),
        build=TargetBuildConventions(
            build_system="psql",
            dependency_management="n/a",
            build_command="psql -f schema.sql",
            test_command="pgTAP or psql assertions",
            dependency_file="",
        ),
        database=TargetDatabaseConventions(
            database="PostgreSQL",
            dialect="PostgreSQL 15",
            orm_or_mapping="JPA/SQLAlchemy mapping",
            migration_tool="Flyway/Liquibase",
            ddl_type_mapping={
                "VARCHAR(n)": "varchar(n)",
                "CHAR(n)": "char(n)",
                "DECIMAL(p,s)": "numeric(p,s)",
                "DATE": "date",
                "TIMESTAMP": "timestamp",
                "SMALLINT": "smallint",
                "INTEGER": "integer",
                "BIGINT": "bigint",
            },
        ),
        api=TargetApiConventions(style="SQL", base_path="", content_type="text/sql"),
        testing=TargetTestingConventions(
            framework="pgTAP",
            test_file_suffix="_test.sql",
            assertion_style="SELECT tap.*",
            test_discovery_command="pg_prove",
        ),
        deployment=TargetDeploymentConventions(
            runtime="PostgreSQL 15",
            packaging=".sql migration scripts",
            container_base="postgres:15",
            health_check_pattern="SELECT 1",
            port=5432,
        ),
        architecture_constraints=[
            "Every table needs a primary key.",
            "Foreign keys reference stable natural keys where possible.",
        ],
        aliases=["sql", "postgres", "postgresql", "ddl"],
        confidence=0.93,
    )


def default_target_technology_registry() -> TargetTechnologyRegistry:
    """Build the default registry with the bundled target entries."""
    registry = TargetTechnologyRegistry()
    registry.register_many(
        [
            _java_spring_boot_entry(),
            _kotlin_spring_boot_entry(),
            _python_fastapi_entry(),
            _typescript_node_entry(),
            _csharp_dotnet_entry(),
            _golang_entry(),
            _sql_postgres_entry(),
        ]
    )
    return registry


__all__ = [
    "TargetLanguageConventions",
    "TargetFrameworkConventions",
    "TargetBuildConventions",
    "TargetDatabaseConventions",
    "TargetApiConventions",
    "TargetTestingConventions",
    "TargetDeploymentConventions",
    "TargetProjectConventions",
    "TargetTechnologyKnowledge",
    "TargetTechnologyRegistry",
    "default_target_technology_registry",
]

