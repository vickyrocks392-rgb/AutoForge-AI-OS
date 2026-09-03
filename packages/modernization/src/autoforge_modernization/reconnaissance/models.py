"""Reconnaissance data models for Phase 18-G.2."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FileCategory(str, Enum):
    SOURCE = "source"
    CONFIG = "config"
    BUILD = "build"
    DEPLOY = "deploy"
    DATA = "data"
    TEST = "test"
    DOC = "doc"
    GENERATED = "generated"
    BINARY = "binary"
    UNKNOWN = "unknown"


class EvidenceKind(str, Enum):
    MANIFEST = "manifest"
    IMPORT = "import"
    DEPENDENCY = "dependency"
    BUILD_FILE = "build_file"
    DEPLOY_DESC = "deployment_descriptor"
    CONFIG_FILE = "config_file"
    SOURCE_PATTERN = "source_pattern"
    FILE_HEADER = "file_header"
    COMPILER_METADATA = "compiler_metadata"
    PACKAGE_METADATA = "package_metadata"
    DIRECTORY_STRUCTURE = "directory_structure"
    CONTAINER_FILE = "container_file"
    CI_CD_DEF = "ci_cd_definition"
    DB_SCHEMA = "db_schema"
    SQL_SCRIPT = "sql_script"
    MIGRATION_SCRIPT = "migration_script"
    API_SPEC = "api_spec"
    MSG_SPEC = "message_spec"
    VERSION_STRING = "version_string"
    RUNTIME_CONFIG = "runtime_config"
    ENVIRONMENT_VAR = "environment_var"
    SOURCE_COMMENT = "source_comment"
    LLM_INFERENCE = "llm_inference"
    UNKNOWN = "unknown"


class FactConfidence(str, Enum):
    PROVEN = "proven"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class ScannedFile(BaseModel):
    file_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    path: str
    relative_path: str
    size_bytes: int = 0
    category: FileCategory = FileCategory.UNKNOWN
    detected_language: str | None = None
    detected_technologies: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: FactConfidence = FactConfidence.UNKNOWN
    is_generated: bool = False
    is_test: bool = False
    scanned_at: datetime = Field(default_factory=_utc_now)


class DiscoveredFile(BaseModel):
    file_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    path: str
    relative_path: str
    category: FileCategory
    technologies: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: FactConfidence
    size_bytes: int = 0


class TechnologyKind(str, Enum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    RUNTIME = "runtime"
    DATABASE = "database"
    TOOL = "tool"
    CONTAINER = "container"
    CI_CD = "ci_cd"
    INFRASTRUCTURE = "infrastructure"
    ORCHESTRATION = "orchestration"
    UNKNOWN = "unknown"


class TechnologyCategory(str, Enum):
    MAINFRAME = "mainframe"
    JAVA_ENTERPRISE = "java_enterprise"
    WEB_FRONTEND = "web_frontend"
    WEB_BACKEND = "web_backend"
    MOBILE = "mobile"
    EMBEDDED = "embedded"
    CLOUD_NATIVE = "cloud_native"
    DATA_ENGINEERING = "data_engineering"
    GENERAL_PURPOSE = "general_purpose"
    UNKNOWN = "unknown"


class EvidenceSource(str, Enum):
    FILE_EXTENSION = "file_extension"
    FILE_HEADER = "file_header"
    IMPORT_STMT = "import_statement"
    DEPENDENCY_MANIFEST = "dependency_manifest"
    BUILD_CONFIG = "build_config"
    DEPLOY_DESC = "deployment_descriptor"
    CONFIG_FILE = "config_file"
    CONTAINER_FILE = "container_file"
    DIRECTORY_PATTERN = "directory_pattern"
    COMPILER_INFO = "compiler_info"
    RUNTIME_INFO = "runtime_info"
    VERSION_FILE = "version_file"
    SOURCE_PATTERN = "source_pattern"
    LLM_ANALYSIS = "llm_analysis"
    UNKNOWN = "unknown"


class DetectionMethod(str, Enum):
    DETERMINISTIC = "deterministic"
    HEURISTIC = "heuristic"
    LLM_SUPPLEMENTED = "llm_supplemented"
    UNKNOWN = "unknown"


class TechnologyEvidence(BaseModel):
    evidence_kind: EvidenceKind
    evidence_source: EvidenceSource
    detection_method: DetectionMethod
    evidence: str
    file_path: str | None = None
    confidence: FactConfidence
    recorded_at: datetime = Field(default_factory=_utc_now)


class DetectedTechnology(BaseModel):
    technology_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str | None = None
    version_confidence: FactConfidence = FactConfidence.UNKNOWN
    kind: TechnologyKind
    category: TechnologyCategory = TechnologyCategory.UNKNOWN
    evidence: list[TechnologyEvidence] = Field(default_factory=list)
    confidence: FactConfidence
    is_primary: bool = False
    autoforge_capability_state: str | None = None
    autoforge_capability_level: str | None = None
    detected_at: datetime = Field(default_factory=_utc_now)
    is_generated: bool = False


class ProjectMetadata(BaseModel):
    metadata_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str
    name: str | None = None
    root_files: list[str] = Field(default_factory=list)
    manifest_files: list[str] = Field(default_factory=list)
    detected_technologies: list[str] = Field(default_factory=list)
    primary_language: str | None = None
    framework: str | None = None
    discovered_at: datetime = Field(default_factory=_utc_now)


class DependencyKind(str, Enum):
    DIRECT = "direct"
    TRANSITIVE = "transitive"
    INTERNAL = "internal"
    EXTERNAL = "external"
    FRAMEWORK = "framework"
    RUNTIME = "runtime"
    DATABASE = "database"
    SERVICE = "service"
    CIRCULAR = "circular"
    UNKNOWN = "unknown"


class DependencyEdge(BaseModel):
    from_node: str
    to_node: str
    kind: DependencyKind = DependencyKind.UNKNOWN
    evidence: str = ""
    confidence: FactConfidence = FactConfidence.UNKNOWN
    is_hotspot: bool = False


class DependencyGraph(BaseModel):
    graph_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nodes: list[str] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    circular_dependencies: list[list[str]] = Field(default_factory=list)
    hotspots: list[str] = Field(default_factory=list)
    deprecated_deps: list[str] = Field(default_factory=list)
    outdated_deps: list[str] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=_utc_now)


class BuildSystem(str, Enum):
    MAVEN = "maven"
    GRADLE = "gradle"
    ANT = "ant"
    MAKE = "make"
    CMAKE = "cmake"
    NPM = "npm"
    YARN = "yarn"
    PIP = "pip"
    POETRY = "poetry"
    CARGO = "cargo"
    BUNDLER = "bundler"
    COMPOSER = "composer"
    COBOL_COPYBOOK = "cobol_copybook"
    JCL = "jcl"
    MSBUILD = "msbuild"
    DOCKERFILE = "dockerfile"
    KUBERNETES = "kubernetes"
    TERRAFORM = "terraform"
    UNKNOWN = "unknown"


class BuildTarget(BaseModel):
    target_name: str
    build_system: BuildSystem
    build_file: str
    command: str | None = None
    artifacts: list[str] = Field(default_factory=list)


class RuntimeSpec(BaseModel):
    runtime_name: str
    version: str | None = None
    version_confidence: FactConfidence = FactConfidence.UNKNOWN
    evidence: list[str] = Field(default_factory=list)


class DeploymentTarget(str, Enum):
    ON_PREMISE = "on_premise"
    VM = "vm"
    CONTAINER = "container"
    KUBERNETES = "kubernetes"
    SERVERLESS = "serverless"
    PAAS = "paas"
    MAINFRAME = "mainframe"
    CLOUD_AWS = "cloud_aws"
    CLOUD_AZURE = "cloud_azure"
    CLOUD_GCP = "cloud_gcp"
    UNKNOWN = "unknown"


class DeploymentSpec(BaseModel):
    target: DeploymentTarget = DeploymentTarget.UNKNOWN
    containerized: bool = False
    orchestration: str | None = None
    environment_vars: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)
    external_services: list[str] = Field(default_factory=list)
    scheduled_jobs: list[str] = Field(default_factory=list)
    batch_processes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    os_assumptions: list[str] = Field(default_factory=list)
    confidence: FactConfidence = FactConfidence.UNKNOWN


class DatabaseKind(str, Enum):
    RELATIONAL = "relational"
    NOSQL = "nosql"
    KEY_VALUE = "key_value"
    FILE_BASED = "file_based"
    MAINFRAME = "mainframe"
    UNKNOWN = "unknown"


class SQLDialect(str, Enum):
    ORACLE = "oracle"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    MARIADB = "mariadb"
    SQL_SERVER = "sql_server"
    DB2 = "db2"
    SQLITE = "sqlite"
    ANSI = "ansi"
    GENERIC = "generic"
    UNKNOWN = "unknown"


class DatabaseObjectKind(str, Enum):
    TABLE = "table"
    VIEW = "view"
    STORED_PROCEDURE = "stored_procedure"
    TRIGGER = "trigger"
    FUNCTION = "function"
    INDEX = "index"
    SCHEMA = "schema"
    PACKAGE = "package"
    CURSOR = "cursor"
    UNKNOWN = "unknown"


class DatabaseObject(BaseModel):
    object_name: str
    object_kind: DatabaseObjectKind
    db_schema: str | None = None
    file_path: str | None = None
    sql_dialect: SQLDialect = SQLDialect.UNKNOWN
    line_count: int = 0


class DatabaseInventory(BaseModel):
    inventory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    databases: list[str] = Field(default_factory=list)
    versions: dict[str, str] = Field(default_factory=dict)
    version_confidences: dict[str, FactConfidence] = Field(default_factory=dict)
    dialects: dict[str, SQLDialect] = Field(default_factory=dict)
    database_kind: dict[str, DatabaseKind] = Field(default_factory=dict)
    objects: list[DatabaseObject] = Field(default_factory=list)
    connection_strings: list[str] = Field(default_factory=list)
    orm_frameworks: list[str] = Field(default_factory=list)
    migration_scripts: list[str] = Field(default_factory=list)
    confidence: FactConfidence = FactConfidence.UNKNOWN
    scanned_at: datetime = Field(default_factory=_utc_now)


class ArchitectureNodeKind(str, Enum):
    APPLICATION = "application"
    MODULE = "module"
    COMPONENT = "component"
    SERVICE = "service"
    LIBRARY = "library"
    SHARED_LIB = "shared_lib"
    ENTRY_POINT = "entry_point"
    DATA_STORE = "data_store"
    EXTERNAL_SYSTEM = "external_system"
    MESSAGE_QUEUE = "message_queue"
    BATCH_JOB = "batch_job"
    UNKNOWN = "unknown"


class ArchitectureProvenance(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class ArchitectureNode(BaseModel):
    node_id: str
    name: str
    kind: ArchitectureNodeKind
    path: str | None = None
    technologies: list[str] = Field(default_factory=list)
    provenance: ArchitectureProvenance = ArchitectureProvenance.UNKNOWN
    confidence: FactConfidence = FactConfidence.UNKNOWN
    evidence: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)


class ArchitectureEdge(BaseModel):
    from_node: str
    to_node: str
    edge_type: str
    provenance: ArchitectureProvenance = ArchitectureProvenance.UNKNOWN
    confidence: FactConfidence = FactConfidence.UNKNOWN
    evidence: list[str] = Field(default_factory=list)


class ArchitectureGraph(BaseModel):
    graph_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nodes: list[ArchitectureNode] = Field(default_factory=list)
    edges: list[ArchitectureEdge] = Field(default_factory=list)
    coupling_hotspots: list[str] = Field(default_factory=list)
    message_flows: list[str] = Field(default_factory=list)
    batch_flows: list[str] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=_utc_now)


class TestKind(str, Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PERFORMANCE = "performance"
    SECURITY = "security"
    SMOKE = "smoke"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


class TestDiscovery(BaseModel):
    discovery_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    test_frameworks: list[str] = Field(default_factory=list)
    test_locations: list[str] = Field(default_factory=list)
    test_count: int = 0
    test_kinds: dict[str, int] = Field(default_factory=dict)
    test_coverage_indicators: list[str] = Field(default_factory=list)
    coverage_files: list[str] = Field(default_factory=list)
    confidence: FactConfidence = FactConfidence.UNKNOWN


class EvidenceSourceKind(str, Enum):
    REQUIREMENTS_DOC = "requirements_doc"
    SPECIFICATION = "specification"
    BUSINESS_RULES = "business_rules"
    TESTS = "tests"
    API_CONTRACT = "api_contract"
    CONFIGURATION = "configuration"
    SOURCE_COMMENTS = "source_comments"
    OPERATIONAL_DOC = "operational_doc"
    MIGRATION_DOC = "migration_doc"
    README = "readme"
    CHANGELOG = "changelog"
    LICENSE = "license"
    UNKNOWN = "unknown"


class DocumentDiscovery(BaseModel):
    discovery_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    documents: list[str] = Field(default_factory=list)
    doc_types: dict[str, EvidenceSourceKind] = Field(default_factory=dict)
    requirements_docs: list[str] = Field(default_factory=list)
    business_rule_docs: list[str] = Field(default_factory=list)
    api_specs: list[str] = Field(default_factory=list)
    confidence: FactConfidence = FactConfidence.UNKNOWN


class BusinessEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: EvidenceSourceKind
    source_path: str
    description: str
    candidate_requirements: list[str] = Field(default_factory=list)
    candidate_business_rules: list[str] = Field(default_factory=list)
    confidence: FactConfidence = FactConfidence.UNKNOWN
    autoforge_ready: bool = False


class CountingMethodology(str, Enum):
    PHYSICAL = "physical"
    LOGICAL = "logical"
    GENERATED_EXCLUDED = "generated_excluded"
    COPYBOOK_INCLUDED = "copybook_included"
    COPYBOOK_EXCLUDED = "copybook_excluded"
    JCL_PROCEDURES = "jcl_procedures"
    DB2_DDL = "db2_ddl"
    MANUAL_AUDIT = "manual_audit"
    SEMANTIC_UNITS = "semantic_units"
    MULTI_METHOD = "multi_method"
    UNKNOWN = "unknown"


class SizingSource(str, Enum):
    FILE_SYSTEM = "file_system"
    AST_ANALYSIS = "ast_analysis"
    BUILD_SYSTEM = "build_system"
    LLM_ESTIMATION = "llm_estimation"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class ProjectSizing(BaseModel):
    sizing_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    total_physical_loc: int = 0
    logical_loc: int | None = None
    active_loc: int | None = None
    generated_loc: int | None = None
    test_loc: int | None = None
    comments_loc: int | None = None
    blank_loc: int | None = None
    total_files: int = 0
    modules: int | None = None
    components: int | None = None
    loc_by_language: dict[str, int] = Field(default_factory=dict)
    loc_by_module: dict[str, int] = Field(default_factory=dict)
    loc_by_component: dict[str, int] = Field(default_factory=dict)
    primary_methodology: CountingMethodology = CountingMethodology.UNKNOWN
    methodologies_used: list[CountingMethodology] = Field(default_factory=list)
    sources: list[SizingSource] = Field(default_factory=list)
    is_generated_excluded: bool = False
    copybook_loc: int | None = None
    jcl_proc_loc: int | None = None
    sql_loc: int | None = None
    confidence: FactConfidence = FactConfidence.UNKNOWN
    computed_at: datetime = Field(default_factory=_utc_now)


class ComparisonOutcome(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    TOOL_REQUIRED = "tool_required"
    ENVIRONMENT_REQUIRED = "environment_required"
    MODEL_REQUIRED = "model_required"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ToolRequirementKind(str, Enum):
    PARSER_ANALYZER = "parser_analyzer"
    TRANSFORMATION_TOOL = "transformation_tool"
    VERIFICATION_TOOL = "verification_tool"
    RUNTIME_ENVIRONMENT = "runtime_environment"
    BUILD_TOOL = "build_tool"
    DATABASE_TOOL = "database_tool"
    CONTAINER_TOOL = "container_tool"
    CI_CD_TOOL = "ci_cd_tool"
    UNKNOWN = "unknown"


class ProjectCapabilityComparison(BaseModel):
    comparison_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology: str
    detected_version: str | None = None
    detected_version_confidence: FactConfidence = FactConfidence.UNKNOWN
    outcome: ComparisonOutcome
    capability_level: str | None = None
    evidence: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    missing_envs: list[str] = Field(default_factory=list)
    missing_models: list[str] = Field(default_factory=list)
    blocks_modernization: bool = False
    compared_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _compute_blocks_modernization(self) -> "ProjectCapabilityComparison":
        # TOOL_REQUIRED, MODEL_REQUIRED, and UNSUPPORTED block modernization
        if self.outcome in (
            ComparisonOutcome.TOOL_REQUIRED,
            ComparisonOutcome.MODEL_REQUIRED,
            ComparisonOutcome.UNSUPPORTED,
        ):
            object.__setattr__(self, "blocks_modernization", True)
        else:
            object.__setattr__(self, "blocks_modernization", False)
        return self


class ProjectToolRequirement(BaseModel):
    requirement_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str
    tool_kind: ToolRequirementKind
    technology: str
    technology_version: str | None = None
    purpose: str
    license: str = "unknown"
    version: str | None = None
    install_command: str | None = None
    verification_command: str | None = None
    local_capable: bool = True
    currently_installed: bool = False
    verified: bool = False
    disk_estimate_mb: float | None = None
    requires_approval: bool = False
    status: str = "not_installed"


class HierarchicalSummary(BaseModel):
    repository_summary: str = ""
    module_summaries: dict[str, str] = Field(default_factory=dict)
    component_summaries: dict[str, str] = Field(default_factory=dict)
    symbol_summaries: dict[str, str] = Field(default_factory=dict)


class ContextRetrievalRecord(BaseModel):
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operation: str
    query: str
    retrieved_files: list[str] = Field(default_factory=list)
    retrieval_count: int = 0
    cache_hit: bool = False
    token_estimate: int = 0
    retrieval_latency_ms: float = 0.0
    compressed: bool = False
    deduplicated: bool = False
    recorded_at: datetime = Field(default_factory=_utc_now)


class RAGQueryRecord(BaseModel):
    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query_text: str
    results: list[str] = Field(default_factory=list)
    result_count: int = 0
    hits: list[dict[str, Any]] = Field(default_factory=list)
    scope: str = ""
    retrieved_at: datetime = Field(default_factory=_utc_now)


class ResearchSanitizationCheck(BaseModel):
    is_sanitized: bool
    client_data_indicators_found: list[str] = Field(default_factory=list)
    research_question: str
    checked_at: datetime = Field(default_factory=_utc_now)


class ReconnaissanceEventType(str, Enum):
    SCAN_STARTED = "reconnaissance.scan_started"
    SCAN_COMPLETE = "reconnaissance.scan_complete"
    FILE_DISCOVERED = "reconnaissance.file_discovered"
    TECHNOLOGY_DETECTED = "reconnaissance.technology_detected"
    VERSION_DETECTED = "reconnaissance.version_detected"
    DEPENDENCY_FOUND = "reconnaissance.dependency_found"
    ARCHITECTURE_NODE_DISCOVERED = "reconnaissance.architecture_node_discovered"
    SIZING_COMPLETE = "reconnaissance.sizing_complete"
    CAPABILITY_COMPARED = "reconnaissance.capability_compared"
    TOOL_GAP_IDENTIFIED = "reconnaissance.tool_gap_identified"
    RAG_QUERIED = "reconnaissance.rag_queried"
    RESEARCH_PERFORMED = "reconnaissance.research_performed"
    RESEARCH_BLOCKED = "reconnaissance.research_blocked"
    LOCKDOWN_VIOLATION_ATTEMPTED = "reconnaissance.lockdown_violation_attempted"
    CHECKPOINT_CREATED = "reconnaissance.checkpoint_created"
    INVENTORY_COMPLETE = "reconnaissance.inventory_complete"
    ERROR_OCCURRED = "reconnaissance.error_occurred"


class ReconnaissanceEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: ReconnaissanceEventType
    project_id: str
    job_id: str | None = None
    timestamp: datetime = Field(default_factory=_utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class ReconnaissanceEngineState(BaseModel):
    state_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str
    job_id: str | None = None
    is_running: bool = False
    current_operation: str = ""
    operations_completed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    files_scanned: int = 0
    files_remaining: int = 0
    technologies_detected: int = 0
    loc_analyzed: int = 0
    loc_remaining: int = 0
    started_at: datetime | None = None
    elapsed_seconds: float = 0.0
    last_checkpoint_at: datetime | None = None
    context_usage_bytes: int = 0
    token_estimate: int = 0
    cache_hits: int = 0
    lockdown_active: bool = False
    research_blocked: bool = False
    overall_confidence: FactConfidence = FactConfidence.UNKNOWN


class LegacyInventory(BaseModel):
    inventory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str
    project_name: str | None = None
    metadata: ProjectMetadata | None = None
    scanned_files: list[ScannedFile] = Field(default_factory=list)
    discovered_files: list[DiscoveredFile] = Field(default_factory=list)
    detected_technologies: list[DetectedTechnology] = Field(default_factory=list)
    dependency_graph: DependencyGraph | None = None
    build_systems: list[BuildSystem] = Field(default_factory=list)
    build_targets: list[BuildTarget] = Field(default_factory=list)
    runtime_specs: list[RuntimeSpec] = Field(default_factory=list)
    deployment_spec: DeploymentSpec | None = None
    database_inventory: DatabaseInventory | None = None
    architecture_graph: ArchitectureGraph | None = None
    test_discovery: TestDiscovery | None = None
    document_discovery: DocumentDiscovery | None = None
    business_evidence: list[BusinessEvidence] = Field(default_factory=list)
    sizing: ProjectSizing | None = None
    capability_comparisons: list[ProjectCapabilityComparison] = Field(default_factory=list)
    tool_requirements: list[ProjectToolRequirement] = Field(default_factory=list)
    dashboard_state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    scan_duration_seconds: float = 0.0
    overall_confidence: FactConfidence = FactConfidence.UNKNOWN
    incomplete_detections: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


