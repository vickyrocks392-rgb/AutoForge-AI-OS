"""Legacy + Target Technology Knowledge Layer (Phase 18-G.3)."""


from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

class TechnologyFamily(str, Enum):
    MAINFRAME_LANGUAGE = "mainframe_language"
    MAINFRAME_BATCH = "mainframe_batch"
    MAINFRAME_TRANSACTION = "mainframe_transaction"
    MAINFRAME_DATABASE = "mainframe_database"
    MAINFRAME_DATA = "mainframe_data"
    MAINFRAME_UI = "mainframe_ui"
    SYSTEM_LANGUAGE = "system_language"
    ENTERPRISE_LANGUAGE = "enterprise_language"
    ENTERPRISE_FRAMEWORK = "enterprise_framework"
    ENTERPRISE_RUNTIME = "enterprise_runtime"
    SCRIPTING_LANGUAGE = "scripting_language"
    WEB_FRONTEND = "web_frontend"
    WEB_BACKEND = "web_backend"
    RELATIONAL_DATABASE = "relational_database"
    NOSQL_DATABASE = "nosql_database"
    BUILD_TOOL = "build_tool"
    CONTAINER = "container"
    ORCHESTRATION = "orchestration"
    MESSAGING = "messaging"
    API = "api"
    CI_CD = "ci_cd"
    INFRASTRUCTURE = "infrastructure"
    CLOUD_NATIVE = "cloud_native"
    UNKNOWN = "unknown"

class ClaimKind(str, Enum):
    OBSERVED = "observed"
    DETERMINISTIC = "deterministic"
    PARSER_DERIVED = "parser_derived"
    RAG_DERIVED = "rag_derived"
    LLM_INFERRED = "llm_inferred"
    HUMAN_CONFIRMED = "human_confirmed"
    KNOWLEDGE_BASE = "knowledge_base"
    UNKNOWN = "unknown"

class TechnologyRelationshipKind(str, Enum):
    DEPENDS_ON = "depends_on"
    RUNS_ON = "runs_on"
    MIGRATES_TO = "migrates_to"
    MIGRATES_FROM = "migrates_from"
    REQUIRES = "requires"
    INCOMPATIBLE_WITH = "incompatible_with"
    REPLACES = "replaces"
    HAS_ARTIFACT = "has_artifact"
    COMPILES_TO = "compiles_to"
    TRANSPILED_FROM = "transpiled_from"
    UNKNOWN = "unknown"
class KnowledgeClaim(BaseModel):
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    statement: str
    kind: ClaimKind = ClaimKind.KNOWLEDGE_BASE
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = "knowledge_base"
    evidence: list[str] = Field(default_factory=list)

class TechnologyRelationship(BaseModel):
    relationship_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: TechnologyRelationshipKind
    target_technology: str
    target_version: str | None = None
    description: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    claim_kind: ClaimKind = ClaimKind.KNOWLEDGE_BASE

class ModernizationPath(BaseModel):
    path_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_technology: str
    target_version: str | None = None
    target_family: TechnologyFamily = TechnologyFamily.UNKNOWN
    strategy: str = "refactor"
    description: str = ""
    compatibility: str = "partial"
    semantic_differences: list[str] = Field(default_factory=list)
    required_adapters: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    claim_kind: ClaimKind = ClaimKind.KNOWLEDGE_BASE
    evidence: list[str] = Field(default_factory=list)

class DialectInfo(BaseModel):
    dialect_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str | None = None
    description: str = ""
    detection_evidence: list[str] = Field(default_factory=list)
    command: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    claim_kind: ClaimKind = ClaimKind.KNOWLEDGE_BASE

class TechnologyKnowledge(BaseModel):
    """Structured knowledge for a single technology."""
    knowledge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology_name: str
    version: str | None = None
    family: TechnologyFamily = TechnologyFamily.UNKNOWN
    display_name: str = ""
    description: str = ""
    execution_model: str = ""
    runtime: str = ""
    compiler: str = ""
    build_tool: str = ""
    file_extensions: list[str] = Field(default_factory=list)
    file_patterns: list[str] = Field(default_factory=list)
    artifact_types: list[str] = Field(default_factory=list)
    dialects: list[DialectInfo] = Field(default_factory=list)
    relationships: list[TechnologyRelationship] = Field(default_factory=list)
    modernization_paths: list[ModernizationPath] = Field(default_factory=list)
    parser_available: bool = False
    parser_tool: str = ""
    ast_tool: str = ""
    static_analyzer: str = ""
    constraints: list[str] = Field(default_factory=list)
    known_antipatterns: list[str] = Field(default_factory=list)
    known_patterns: list[str] = Field(default_factory=list)
    minimum_target_understanding: str = "unknown"
    claims: list[KnowledgeClaim] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=_utc_now)
    source: str = "knowledge_base"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    def get_modernization_path(self, target: str) -> ModernizationPath | None:
        for p in self.modernization_paths:
            if p.target_technology == target:
                return p
        return None

    def has_relationship_to(self, other: str, kind: TechnologyRelationshipKind) -> bool:
        for r in self.relationships:
            if r.target_technology == other and r.kind == kind:
                return True
        return False

    def is_mappable_to(self, target: str) -> bool:
        return any(p.target_technology == target for p in self.modernization_paths)


__all__ = [
    "TechnologyFamily", "ClaimKind", "TechnologyRelationshipKind",
    "KnowledgeClaim", "TechnologyRelationship", "ModernizationPath",
    "DialectInfo", "TechnologyKnowledge",
    "TechnologyKnowledgeLayer",
]

# ── Technology Knowledge Layer ────────────────────────────────────────────────


class TechnologyKnowledgeLayer:
    """
    The canonical knowledge layer holding structured technology knowledge.

    This is the authoritative source of technology understanding for AutoForge.
    It contains pre-populated knowledge about common legacy and modern
    technologies. New technologies can be added via register().

    The layer is queryable by:
    - technology name
    - version
    - family
    - artifact pattern
    - modernization target

    Architecture:
    1. G.2 ReconnaissanceEngine discovers technologies from a repository
    2. G.3 LegacyAnalysisEngine queries this layer for technology understanding
    3. G.3 PlanningGate uses layer to assess modernization feasibility
    4. G.3 TransformationEngine uses layer to drive bounded mutation

    All entries are classified with ClaimKind for epistemic rigor.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, TechnologyKnowledge] = {}
        self._populated = False
        self._populate()

    def _populate(self) -> None:
        """Populate the knowledge layer with real technology knowledge."""
        if self._populated:
            return
        for entry in _KNOWLEDGE_ENTRIES():
            self._by_name[entry.technology_name] = entry
        self._populated = True

    def get(self, name: str) -> TechnologyKnowledge | None:
        """Get knowledge for a technology by name."""
        return self._by_name.get(name)

    def get_version(self, name: str, version: str | None) -> TechnologyKnowledge | None:
        """Get knowledge for a technology with specific version."""
        entry = self._by_name.get(name)
        if entry and version:
            for d in entry.dialects:
                if d.version == version:
                    return entry
        return entry

    def by_family(self, family: TechnologyFamily) -> list[TechnologyKnowledge]:
        """Get all technologies in a given family."""
        return [e for e in self._by_name.values() if e.family == family]

    def by_pattern(self, pattern: str) -> list[TechnologyKnowledge]:
        """Get technologies matching a file pattern."""
        results: list[TechnologyKnowledge] = []
        for entry in self._by_name.values():
            if pattern in entry.file_patterns or any(pattern in ext for ext in entry.file_extensions):
                results.append(entry)
        return results

    def can_modernize_to(self, source: str, target: str) -> bool:
        """Return True if source can be modernized to target."""
        entry = self._by_name.get(source)
        if not entry:
            return False
        return entry.is_mappable_to(target)

    def get_modernization_path(self, source: str, target: str) -> ModernizationPath | None:
        """Get the modernization path from source to target."""
        entry = self._by_name.get(source)
        if not entry:
            return None
        return entry.get_modernization_path(target)

    def register(self, entry: TechnologyKnowledge) -> None:
        """Register or update a technology knowledge entry."""
        self._by_name[entry.technology_name] = entry

    def all(self) -> list[TechnologyKnowledge]:
        """Return all technology knowledge entries."""
        return list(self._by_name.values())

    def mainframes(self) -> list[TechnologyKnowledge]:
        """Return all mainframe technologies."""
        families = {
            TechnologyFamily.MAINFRAME_LANGUAGE,
            TechnologyFamily.MAINFRAME_BATCH,
            TechnologyFamily.MAINFRAME_TRANSACTION,
            TechnologyFamily.MAINFRAME_DATABASE,
            TechnologyFamily.MAINFRAME_DATA,
            TechnologyFamily.MAINFRAME_UI,
        }
        return [e for e in self._by_name.values() if e.family in families]

    def targets(self) -> list[TechnologyKnowledge]:
        """Return all target (modern) technologies."""
        families = {
            TechnologyFamily.ENTERPRISE_LANGUAGE,
            TechnologyFamily.ENTERPRISE_FRAMEWORK,
            TechnologyFamily.ENTERPRISE_RUNTIME,
            TechnologyFamily.WEB_BACKEND,
            TechnologyFamily.RELATIONAL_DATABASE,
            TechnologyFamily.CONTAINER,
            TechnologyFamily.ORCHESTRATION,
            TechnologyFamily.API,
            TechnologyFamily.MESSAGING,
        }
        return [e for e in self._by_name.values() if e.family in families]


def _cobol_entries() -> list[TechnologyKnowledge]:
    """COBOL technology knowledge."""
    return [TechnologyKnowledge(
        technology_name="cobol",
        family=TechnologyFamily.MAINFRAME_LANGUAGE,
        display_name="COBOL",
        description="Common Business-Oriented Language. A high-level procedural language used primarily in mainframe business applications. Known for fixed-format source, English-like syntax, and 60+ years of stability in financial and government systems.",
        execution_model="compiled",
        runtime="z/OS, Micro Focus, GnuCOBOL, AWS Mainframe Modernization",
        compiler="cobc, COBOL II, Enterprise COBOL, COBOL/370, ILE COBOL",
        build_tool="make, JCL, COBOL compile/link JCL",
        file_extensions=[".cob", ".cbl", ".cobol"],
        file_patterns=["*.cbl", "*.cob"],
        artifact_types=["PROGRAM", "COPYBOOK", "LOAD_MODULE"],
        dialects=[
            DialectInfo(name="COBOL-85", version="85", description="ANSI 1985 standard", detection_evidence=["*>COBOL-85", "IDENTIFICATION DIVISION"], command="cobc --version"),
            DialectInfo(name="COBOL-2002", version="2002", description="Object-oriented COBOL", detection_evidence=["*>COBOL-2002"], command="cobc --version"),
            DialectInfo(name="IBM Enterprise COBOL", version="6.3", description="IBM Enterprise COBOL for z/OS", detection_evidence=["*>IBM Enterprise COBOL"], command="cob2 -V"),
        ],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.RUNS_ON, target_technology="cics", description="COBOL programs commonly invoked by CICS transactions", confidence=0.9),
            TechnologyRelationship(kind=TechnologyRelationshipKind.RUNS_ON, target_technology="jcl", description="COBOL programs are batch-executed via JCL", confidence=0.95),
            TechnologyRelationship(kind=TechnologyRelationshipKind.DEPENDS_ON, target_technology="cobol_copybook", description="COBOL programs include copybooks for shared data structures", confidence=0.95),
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="java", description="Primary modernization target is Java/Spring", confidence=0.9),
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="python", description="Alternative modernization target for new development", confidence=0.7),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="java", strategy="refactor", target_family=TechnologyFamily.ENTERPRISE_LANGUAGE, compatibility="partial", description="COBOL business logic to Java/Spring classes. Requires parser-driven conversion of DATA DIVISION to POJOs, PROCEDURE DIVISION to methods, COPY to imports.", semantic_differences=["COBOL fixed format -> free format", "DECIMAL arithmetic -> BigDecimal", "Paragraphs -> methods", "GOTO -> structured control flow", "Indexed I/O -> JPA/Spring Data"], required_adapters=["CICS-to-REST gateway for online transactions", "JCL-to-Spring-Batch for batch", "VSAM-to-PostgreSQL migration"], required_tools=["cobol parser (cobc)", "Heirloom Computing/Modernization tools", "AWS Blu Age / Micro Focus"], risks=["Loss of decimal precision", "Date handling (Y2K-era patterns)", "Performance differences", "Business rule misinterpretation"], unresolved_questions=["Which COBOL dialect exactly?", "GOTO-heavy logic", "Implicit dependencies on EBCDIC"], confidence=0.7, evidence=["IBM Redbooks on COBOL modernization", "AWS Mainframe Modernization service documentation"]),
            ModernizationPath(target_technology="python", strategy="refactor", target_family=TechnologyFamily.SCRIPTING_LANGUAGE, compatibility="partial", description="COBOL to Python with similar business logic preservation.", semantic_differences=["Fixed format -> Python indentation", "COBOL records -> dataclasses/pydantic", "Paragraphs -> functions"], required_tools=["cobol parser"], risks=["Type system differences", "Decimal precision"], confidence=0.5),
        ],
        parser_available=True,
        parser_tool="cobc / opencobol",
        ast_tool="cobolparser (python lib)",
        static_analyzer="SonarQube COBOL plugin",
        constraints=["Fixed 80-column format (in legacy)", "EBCDIC encoding for mainframe", "Division-based structure", "Paragraphs are not nested"],
        known_antipatterns=["GOTO-heavy code (1980s era)", "Modification of LINKAGE SECTION by reference", "Mixed record formats", "Hardcoded file paths in JCL"],
        known_patterns=["PERFORM/UNTIL for loops", "COPY for copybook inclusion", "Paragraph naming convention", "88-level condition names"],
        minimum_target_understanding="java+spring, OR python+sqlalchemy",
        confidence=0.95,
    )]


def _jcl_entries() -> list[TechnologyKnowledge]:
    """JCL technology knowledge."""
    return [TechnologyKnowledge(
        technology_name="jcl",
        family=TechnologyFamily.MAINFRAME_BATCH,
        display_name="JCL (Job Control Language)",
        description="IBM mainframe Job Control Language. Declares batch jobs as sequences of job steps that invoke programs, allocate datasets, and direct execution through the Job Entry Subsystem (JES2/JES3).",
        execution_model="batch",
        runtime="z/OS JES2/JES3",
        compiler="interpreted by JES",
        build_tool="JCL itself",
        file_extensions=[".jcl", ".proc"],
        file_patterns=["*.jcl", "*.proc"],
        artifact_types=["JOB", "PROC", "INCLUDED_MEMBER"],
        dialects=[
            DialectInfo(name="JCL-z/OS", version="2.5", description="z/OS JES2/JES3 JCL", detection_evidence=["// JOB", "// EXEC PGM=", "//DD"], command="jes2 -V"),
        ],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.REQUIRES, target_technology="cobol", description="JCL typically invokes COBOL batch programs", confidence=0.95),
            TechnologyRelationship(kind=TechnologyRelationshipKind.REQUIRES, target_technology="vsam", description="JCL DD statements reference VSAM datasets", confidence=0.9),
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="spring_batch", description="JCL batch to Spring Batch", confidence=0.85),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="spring_batch", strategy="refactor", target_family=TechnologyFamily.ENTERPRISE_FRAMEWORK, compatibility="partial", description="Each JCL job becomes a Spring Batch Job. EXEC PGM= -> Step. DD statements -> readers/writers.", semantic_differences=["Sequential EXEC -> parallel Step", "JCL RC -> Step exit status", "Conditional execution -> Decision"], required_adapters=["JCL-to-Spring-Batch translator (Heirloom/Micro Focus)", "VSAM-to-relational reader", "Sequential file reader"], required_tools=["spring-batch migration plugin", "AWS BluInsights", "Heirloom Computing"], risks=["GDG handling", "PROC library equivalence", "Conditional step execution semantics"], confidence=0.8),
        ],
        parser_available=True,
        parser_tool="regex-based (mainframe-aware)",
        ast_tool="custom JCL AST parsers exist",
        static_analyzer="IBM Debug Tool, Fault Analyzer",
        constraints=["80-column card format", "DD statement ordering", "Max 255 job steps per job", "JES-specific syntax variations"],
        known_antipatterns=["Hardcoded volumes in production", "Missing error handling for steps", "Use of symbolic parameters without overrides", "Unbalanced IF/THEN/ELSE/ENDIF"],
        known_patterns=["//* comment lines", "INCLUDE member for reusability", "PROC for parameterized jobs", "COND for conditional execution"],
        confidence=0.95,
    )]

def _cics_entries() -> list[TechnologyKnowledge]:
    """CICS technology knowledge."""
    return [TechnologyKnowledge(
        technology_name="cics",
        family=TechnologyFamily.MAINFRAME_TRANSACTION,
        display_name="CICS (Customer Information Control System)",
        description="IBM transaction processing subsystem for z/OS. Hosts online transaction applications.",
        execution_model="transactional",
        runtime="z/OS CICS TS region",
        compiler="CICS translator pre-processes COBOL/PLI",
        build_tool="CICS translator + JCL",
        file_extensions=[".cbl", ".csd", ".bms"],
        file_patterns=["*.cbl with EXEC CICS"],
        artifact_types=["TRANSACTION", "PROGRAM", "MAP", "MAPSET"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.HAS_ARTIFACT, target_technology="bms", description="CICS uses BMS maps for terminal UI", confidence=0.95),
            TechnologyRelationship(kind=TechnologyRelationshipKind.RUNS_ON, target_technology="cobol", description="CICS invokes COBOL programs", confidence=0.95),
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="spring", description="CICS transactions to Spring services", confidence=0.85),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="spring", strategy="refactor", target_family=TechnologyFamily.ENTERPRISE_FRAMEWORK, compatibility="partial", description="CICS transactions to REST endpoints. EXEC CICS LINK/XCTL -> service calls. Maps -> HTML/JSON.", semantic_differences=["Pseudo-conversational -> stateless", "BMS maps -> REST + UI", "COMMAREA -> DTO/JSON"], required_adapters=["CICS-to-REST gateway", "3270 terminal emulator for compatibility"], required_tools=["IBM CICS Transaction Gateway", "AWS Blu Age", "Heirloom"], risks=["Pseudo-conversational state management", "COMMAREA size limits", "EIBRESP error code mapping"], confidence=0.8),
        ],
        parser_available=False,
        parser_tool="regex-based for EXEC CICS",
        constraints=["Pseudo-conversational model", "24/7 availability requirement", "Map and Mapset pairing"],
        known_patterns=["Pseudo-conversational", "LINK/XCTL for program-to-program", "COMMAREA for data passing"],
        confidence=0.9,
    )]

def _db2_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="db2",
        family=TechnologyFamily.MAINFRAME_DATABASE,
        display_name="DB2 for z/OS",
        description="IBM relational database for z/OS. Programs embed SQL via EXEC SQL blocks. DDL describes tables, indexes, views.",
        execution_model="embedded SQL / DSN",
        runtime="DB2 subsystem (DSN)",
        compiler="DB2 precompiler (DB2RM, DSNHPC)",
        build_tool="DB2 precompile + COBOL compile + BIND/PLAN",
        file_extensions=[".sql", ".ddl"],
        file_patterns=["*.sql", "*.ddl"],
        artifact_types=["DBRM", "PLAN", "PACKAGE", "TABLE", "INDEX"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="postgresql", description="DB2 DDL to PostgreSQL DDL with semantic adjustments", confidence=0.8),
            TechnologyRelationship(kind=TechnologyRelationshipKind.RUNS_ON, target_technology="cobol", description="COBOL programs embed DB2 SQL", confidence=0.95),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="postgresql", strategy="refactor", target_family=TechnologyFamily.RELATIONAL_DATABASE, compatibility="partial", description="DB2 DDL to PostgreSQL DDL. EXEC SQL in COBOL to JDBC/JPA in Java.", semantic_differences=["DECIMAL(p,s) -> NUMERIC(p,s)", "VARCHAR(n) bytes vs chars", "FETCH FIRST n ROWS", "DSNTIAR error handling"], required_tools=["AWS DMS", "IBM Data Studio", "PostgreSQL native"], risks=["DECFLOAT vs DECIMAL precision", "DB2-specific functions", "LOCKMAX / BIND differences"], confidence=0.75),
        ],
        parser_available=True,
        parser_tool="regex for DDL; sqlglot for SQL",
        known_patterns=["EXEC SQL INCLUDE for SQLCA", "DECLARE CURSOR for result sets", "WHENEVER for error handling"],
        confidence=0.9,
    )]

def _bms_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="bms",
        family=TechnologyFamily.MAINFRAME_UI,
        display_name="BMS (Basic Mapping Support)",
        description="CICS map definition language. Describes 3270 terminal screens with fields, attributes, and field validation rules.",
        execution_model="interpreted by CICS",
        runtime="CICS TS",
        compiler="BMS assembler",
        build_tool="JCL + DFHMSDS macros",
        file_extensions=[".bms"],
        file_patterns=["*.bms", "DFHMSD"],
        artifact_types=["MAP", "MAPSET"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.RUNS_ON, target_technology="cics", description="BMS maps run inside CICS", confidence=0.95),
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="html", description="BMS 3270 screens to HTML/JSON", confidence=0.7),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="html", strategy="refactor", target_family=TechnologyFamily.WEB_FRONTEND, compatibility="partial", description="BMS maps to HTML forms. Field attributes -> input types. UNNUM -> auto-increment.", required_tools=["Heirloom / AWS Blu Age BMS translator", "3270 emulator for screenshots"], risks=["PF key mapping", "Color/attribute semantics", "Screen size adaptation"], confidence=0.7),
        ],
        parser_available=True,
        parser_tool="regex for DFHMSD/DFHMDI/DFHMDF",
        known_patterns=["DFHMDI for fields", "DFHMDF for field definitions", "UNNUM/UNNAMED for pagination"],
        confidence=0.85,
    )]

def _ims_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="ims",
        family=TechnologyFamily.MAINFRAME_DATABASE,
        display_name="IMS (Information Management System)",
        description="IBM hierarchical database / transaction manager. DBD describes database structure, PSB describes program access.",
        execution_model="hierarchical DL/I calls",
        runtime="IMS TM/DBCTL",
        compiler="IMS precompiler for COBOL/PLI",
        file_extensions=[".dbd", ".psb"],
        file_patterns=["*.dbd", "*.psb"],
        artifact_types=["DBD", "PSB", "ACBLIB", "MFS"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="postgresql", description="IMS hierarchical to relational", confidence=0.6),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="postgresql", strategy="re_architect", target_family=TechnologyFamily.RELATIONAL_DATABASE, compatibility="none", description="IMS hierarchical to relational requires significant re-architecture. Hierarchical navigation patterns do not map to SQL.", required_tools=["DB2/IMS bridges", "Custom extractors"], risks=["Loss of navigational efficiency", "Hierarchical to relational modeling gap", "Segment types vs tables"], confidence=0.5),
        ],
        parser_available=True,
        parser_tool="regex for DBD/PSB macros",
        known_patterns=["DBD/PCB/PSB", "GU/GN/GNP calls", "SSA (Segment Search Arguments)"],
        confidence=0.8,
    )]


def _vsam_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="vsam",
        family=TechnologyFamily.MAINFRAME_DATA,
        display_name="VSAM (Virtual Storage Access Method)",
        description="IBM mainframe file access method. KSDS, RRDS, ESDS, LDS. Used as flat file replacement with indexed access.",
        execution_model="direct/sequential access",
        runtime="z/OS, DFSMS",
        compiler="none (data definition only)",
        build_tool="IDCAMS utility for DEFINE/REPRO",
        file_extensions=[".dcl"],
        file_patterns=["*.dcl", "IDCAMS"],
        artifact_types=["CLUSTER", "AIX", "PATH"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="postgresql", description="VSAM to relational database", confidence=0.7),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="postgresql", strategy="refactor", target_family=TechnologyFamily.RELATIONAL_DATABASE, compatibility="partial", description="VSAM KSDS to PostgreSQL table with index. RRDS to table with PK. Records mapped via copybooks.", required_tools=["AWS DMS", "IBM Data Replication", "Custom ETL"], risks=["KSDS key preservation", "Record-level vs table-level operations", "AIXPATH handling"], confidence=0.65),
        ],
        parser_available=True,
        parser_tool="regex for IDCAMS control statements",
        known_patterns=["KSDS for indexed access", "IDCAMS DEFINE CLUSTER", "REPRO/PRINT for copying"],
        confidence=0.85,
    )]


def _assembler_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="assembler",
        family=TechnologyFamily.SYSTEM_LANGUAGE,
        display_name="IBM Assembler (HLASM)",
        description="IBM High Level Assembler. Low-level mainframe language used for systems programming, performance-critical routines, and exits.",
        execution_model="assembled and linked",
        runtime="z/OS, CMS",
        compiler="HLASM (ASMA90)",
        build_tool="JCL + HLASM",
        file_extensions=[".asm", ".mac"],
        file_patterns=["*.asm", "*.mac", "CSECT"],
        artifact_types=["TEXT", "CSECT", "MACRO"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="c", description="Assembler to C with significant effort", confidence=0.5),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="c", strategy="rewrite", target_family=TechnologyFamily.SYSTEM_LANGUAGE, compatibility="partial", description="Assembler macros to C functions. CSECT to .c file. BALR/branch instructions to C control flow.", required_tools=["Amode31/64 considerations", "Linkage conventions translator"], risks=["Performance regression", "Loss of register-level optimization", "Calling convention differences"], confidence=0.4),
        ],
        parser_available=True,
        parser_tool="HLASM ASMA90",
        known_patterns=["CSECT for control sections", "MACRO for reusability", "DS/DC for storage definition"],
        confidence=0.8,
    )]

def _rpg_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="rpg",
        family=TechnologyFamily.MAINFRAME_LANGUAGE,
        display_name="RPG (Report Program Generator)",
        description="IBM business programming language for IBM i (AS/400). Third-generation language for business applications.",
        execution_model="compiled",
        runtime="IBM i (AS/400), DB2/400",
        compiler="RPG ILE compiler",
        build_tool="CRTRPGMOD + CRTLIB",
        file_extensions=[".rpgle", ".rpg"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="java", description="RPG to Java modernization", confidence=0.7),
        ],
        parser_available=True,
        confidence=0.8,
    )]


def _pli_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="pli",
        family=TechnologyFamily.MAINFRAME_LANGUAGE,
        display_name="PL/I",
        description="Programming Language One. IBM mainframe language for business and systems programming.",
        execution_model="compiled",
        runtime="z/OS, z/VSE",
        compiler="IBM PL/I compiler (IBMPL1)",
        build_tool="JCL + PL/I compiler",
        file_extensions=[".pli", ".pl1"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_TO, target_technology="java", description="PL/I to Java modernization", confidence=0.6),
        ],
        modernization_paths=[
            ModernizationPath(target_technology="java", strategy="refactor", target_family=TechnologyFamily.ENTERPRISE_LANGUAGE, compatibility="partial", description="PL/I to Java with structured translation.", semantic_differences=["ON CONDITIONS -> exception handling", "POSIX -> java.io", "Built-in I/O -> Java streams"], required_tools=["PL/I parser", "Custom translator"], risks=["ON unit semantics", "Pointer handling", "Storage allocation differences"], confidence=0.5),
        ],
        parser_available=True,
        confidence=0.7,
    )]

def _java_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="java",
        family=TechnologyFamily.ENTERPRISE_LANGUAGE,
        display_name="Java (modern)",
        description="Object-oriented enterprise language. Primary target for COBOL modernization.",
        execution_model="compiled to JVM bytecode",
        runtime="JVM 11+",
        compiler="javac",
        build_tool="maven, gradle",
        file_extensions=[".java"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_FROM, target_technology="cobol", description="Java is primary target for COBOL modernization", confidence=0.9),
        ],
        parser_available=True,
        parser_tool="javac, Eclipse JDT",
        confidence=0.98,
    )]

def _python_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="python",
        family=TechnologyFamily.SCRIPTING_LANGUAGE,
        display_name="Python (modern)",
        description="High-level interpreted language. Alternative for modernization of procedural code.",
        execution_model="interpreted / JIT via PyPy",
        runtime="CPython 3.10+, PyPy",
        compiler="none (CPython), Nuitka, PyInstaller",
        build_tool="pip, poetry, pyproject.toml",
        file_extensions=[".py"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_FROM, target_technology="cobol", description="Python is alternative for COBOL modernization", confidence=0.7),
        ],
        parser_available=True,
        parser_tool="ast module, lib2to3",
        confidence=0.98,
    )]

def _spring_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="spring",
        family=TechnologyFamily.ENTERPRISE_FRAMEWORK,
        display_name="Spring / Spring Boot",
        description="Java enterprise framework. Primary target for CICS-to-REST and batch modernization.",
        execution_model="JVM application server",
        runtime="JVM 11+, Spring Boot embedded server",
        compiler="javac",
        build_tool="maven, gradle",
        file_extensions=[".java"],
        artifact_types=["CONTROLLER", "SERVICE", "REPOSITORY", "ENTITY"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_FROM, target_technology="cics", description="Spring replaces CICS for online transactions", confidence=0.85),
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_FROM, target_technology="jcl", description="Spring Batch replaces JCL for batch", confidence=0.85),
        ],
        parser_available=True,
        parser_tool="Spring Boot / JDT",
        confidence=0.98,
    )]

def _postgres_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="postgresql",
        family=TechnologyFamily.RELATIONAL_DATABASE,
        display_name="PostgreSQL",
        description="Advanced open-source relational database. Primary target for DB2/IMS/VSAM migration.",
        execution_model="client-server relational",
        runtime="PostgreSQL 13+",
        compiler="SQL",
        build_tool="psql, migrations (Flyway, Liquibase)",
        file_extensions=[".sql"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_FROM, target_technology="db2", description="PostgreSQL is primary target for DB2 migration", confidence=0.8),
            TechnologyRelationship(kind=TechnologyRelationshipKind.MIGRATES_FROM, target_technology="vsam", description="PostgreSQL replaces VSAM for file storage", confidence=0.7),
        ],
        parser_available=True,
        parser_tool="psql, pg_dump, sqlglot",
        confidence=0.98,
    )]

def _kafka_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="kafka",
        family=TechnologyFamily.MESSAGING,
        display_name="Apache Kafka",
        description="Distributed event streaming platform. Replaces mainframe messaging systems.",
        execution_model="distributed streaming",
        runtime="Java/Kotlin/Scala",
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.REPLACES, target_technology="ims", description="Kafka replaces IMS message queuing", confidence=0.6),
        ],
        parser_available=True,
        confidence=0.95,
    )]

def _docker_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="docker",
        family=TechnologyFamily.CONTAINER,
        display_name="Docker",
        description="Container runtime. Replaces mainframe z/OS environment.",
        execution_model="container runtime",
        runtime="containerd, runc",
        file_extensions=["Dockerfile", ".dockerignore"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.RUNS_ON, target_technology="linux", description="Docker containers run on Linux", confidence=0.98),
        ],
        parser_available=True,
        confidence=0.98,
    )]

def _kubernetes_entries() -> list[TechnologyKnowledge]:
    return [TechnologyKnowledge(
        technology_name="kubernetes",
        family=TechnologyFamily.ORCHESTRATION,
        display_name="Kubernetes",
        description="Container orchestration. Replaces mainframe scheduling and operations.",
        execution_model="container orchestration",
        runtime="containerd + kubelet",
        build_tool="kubectl, helm",
        file_extensions=["k8s.yaml", "kustomization.yaml"],
        relationships=[
            TechnologyRelationship(kind=TechnologyRelationshipKind.RUNS_ON, target_technology="docker", description="Kubernetes orchestrates Docker containers", confidence=0.95),
        ],
        parser_available=True,
        confidence=0.98,
    )]


def _KNOWLEDGE_ENTRIES() -> list[TechnologyKnowledge]:
    """Return the full list of populated technology knowledge entries."""
    return (
        _cobol_entries() + _jcl_entries() + _cics_entries()
        + _db2_entries() + _bms_entries() + _ims_entries()
        + _vsam_entries() + _assembler_entries()
        + _rpg_entries() + _pli_entries()
        + _java_entries() + _python_entries()
        + _spring_entries() + _postgres_entries()
        + _kafka_entries() + _docker_entries()
        + _kubernetes_entries()
    )
