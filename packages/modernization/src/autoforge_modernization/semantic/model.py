"""Technology-Neutral Semantic Intermediate Model for AutoForge.

Enforces Section 11 of the architectural mandate:
The transformation engine should not translate syntax directly:
COBOL AST -> Java text

Instead:
SOURCE ARTIFACTS
       ↓
SOURCE SEMANTIC ANALYSIS
       ↓
TECHNOLOGY-NEUTRAL SEMANTIC MODEL
       ↓
TARGET TRANSFORMATION PLAN
       ↓
TARGET GENERATION

Represents deep semantic concepts independent of source and target languages while
retaining full source provenance and explicitly tracking uncertainty and unsupported constructs.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResolutionStatus(str, Enum):
    """Explicit epistemic state of a semantic construct or relationship."""

    RESOLVED = "RESOLVED"
    INFERRED = "INFERRED"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    SPECIALIST_REQUIRED = "SPECIALIST_REQUIRED"


class SourceProvenance(BaseModel):
    """Full traceability linking any semantic construct back to source evidence."""

    source_file: str
    line_start: int | None = None
    line_end: int | None = None
    source_sha256: str = ""
    original_construct: str = ""  # e.g., "PERFORM 1000-PROCESS UNTIL WS-DONE = 'Y'"
    analyzer_id: str = "autoforge-semantic-extractor"
    confidence: float = 1.0


class SemanticDataType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    RECORD = "record"
    ARRAY = "array"
    RAW_BYTES = "raw_bytes"
    UNKNOWN = "unknown"


class SemanticField(BaseModel):
    """A data item or variable definition with rich type and layout semantics."""

    field_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    data_type: SemanticDataType = SemanticDataType.UNKNOWN
    original_type_descriptor: str = ""  # e.g. "PIC S9(7)V99 COMP-3"
    level: int | None = None
    default_value: str | None = None
    is_constant: bool = False
    is_primary_key: bool = False
    is_foreign_key: bool = False
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    is_signed: bool = False
    is_nullable: bool | None = None
    constraints: list[str] = Field(default_factory=list)
    redefines: str | None = None
    parent_record_name: str | None = None
    children: list[SemanticField] = Field(default_factory=list)
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    provenance: SourceProvenance | None = None


class SemanticEntity(BaseModel):
    """A cohesive data entity, record structure, copybook definition, or database table."""

    entity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    entity_type: str = "record"  # record, copybook, table, view, dataset_schema, screen
    fields: list[SemanticField] = Field(default_factory=list)
    primary_key_fields: list[str] = Field(default_factory=list)
    foreign_keys: list[dict[str, Any]] = Field(default_factory=list)
    record_length: int | None = None
    source_technology: str = ""
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    provenance: SourceProvenance | None = None


class SemanticCondition(BaseModel):
    """A branch or loop condition expression."""

    expression: str
    left_operand: str = ""
    operator: str = ""  # EQUALS, GREATER, LESS, NOT_EQUALS, IN, etc.
    right_operand: str = ""
    is_complex: bool = False
    logic_operator: str = "AND"
    sub_conditions: list[SemanticCondition] = Field(default_factory=list)
    provenance: SourceProvenance | None = None


class SemanticOperationKind(str, Enum):
    ASSIGNMENT = "assignment"
    COMPUTATION = "computation"
    CALL = "call"
    BRANCH = "branch"
    LOOP = "loop"
    IO_READ = "io_read"
    IO_WRITE = "io_write"
    DB_QUERY = "db_query"
    TRANSACTION = "transaction"
    EXTERNAL_SERVICE = "external_service"
    RETURN = "return"
    ERROR_HANDLING = "error_handling"
    UNSUPPORTED = "unsupported"


class SemanticIOKind(str, Enum):
    """Technology-neutral generalized I/O operation kinds."""

    DATA_READ = "DATA_READ"
    DATA_WRITE = "DATA_WRITE"
    DATA_UPDATE = "DATA_UPDATE"
    DATA_DELETE = "DATA_DELETE"
    DATABASE_READ = "DATABASE_READ"
    DATABASE_WRITE = "DATABASE_WRITE"
    TRANSACTION_INPUT = "TRANSACTION_INPUT"
    TRANSACTION_OUTPUT = "TRANSACTION_OUTPUT"
    FILE_OPEN = "FILE_OPEN"
    FILE_CLOSE = "FILE_CLOSE"
    EXTERNAL_INTERACTION = "EXTERNAL_INTERACTION"


class SemanticIOOperation(BaseModel):
    """A generalized I/O interaction with an external file, dataset, database, or screen."""

    io_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: SemanticIOKind
    resource_name: str  # e.g. ACCTFILE, ACCTDAT, CARD_TRANSACTION, ACCTMAP
    resource_type: str = "file"  # file, vsam, db2_table, cics_map, queue
    target_record_or_field: str = ""
    access_mode: str = "sequential"  # sequential, random, dynamic, input, output, io
    status_field: str = ""
    line_number: int | None = None
    original_construct: str = ""
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    provenance: SourceProvenance | None = None


class SemanticOperation(BaseModel):
    """An atomic or compound operation within a procedure/method with explicit control flow."""

    op_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: SemanticOperationKind
    description: str
    target: str = ""  # target variable, procedure name, or table
    parameters: list[str] = Field(default_factory=list)
    condition: SemanticCondition | None = None
    nested_operations: list[SemanticOperation] = Field(default_factory=list)
    true_operations: list[SemanticOperation] = Field(default_factory=list)
    false_operations: list[SemanticOperation] = Field(default_factory=list)
    loop_kind: str | None = None  # UNTIL, VARYING, TIMES, WHILE, INFINITE
    loop_condition: SemanticCondition | None = None
    exit_kind: str | None = None  # NORMAL, ABNORMAL, RETURN, STOP_RUN, GOBACK
    is_error_path: bool = False
    referenced_fields: list[str] = Field(default_factory=list)
    mutated_fields: list[str] = Field(default_factory=list)
    provenance: SourceProvenance | None = None


class DataFlowEdge(BaseModel):
    """Explicit directional data flow relationship: SOURCE -> TRANSFORMATION -> TARGET."""

    flow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    source_kind: str = "FIELD"  # FIELD, CONSTANT, DATASET, INPUT, RECORD
    target: str
    target_kind: str = "FIELD"  # FIELD, DATASET, OUTPUT, RECORD
    transformation_kind: str = "ASSIGNMENT"  # ASSIGNMENT, ARITHMETIC, CONCATENATION, DIRECT, AGGREGATION, VALIDATION
    expression: str = ""
    procedure_name: str | None = None
    confidence: float = 1.0
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    provenance: SourceProvenance | None = None


class BusinessRulePredicate(BaseModel):
    """Atomic predicate inside a structured business rule."""

    left_operand: str
    operator: str  # EQUALS, NOT_EQUALS, GREATER, LESS, IN, EQUAL_TO_ZERO, etc.
    right_operand: str = ""
    logic_operator: str = "AND"


class BusinessRuleAction(BaseModel):
    """Action or mutation triggered by a business rule outcome."""

    target: str
    action_type: str = "MUTATION"  # MUTATION, CALL, ERROR_ABEND, RETURN, IO
    expression: str = ""


class SemanticBusinessRule(BaseModel):
    """Extracted business policy, validation, or calculation invariant."""

    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    statement: str
    conditions: list[str] = Field(default_factory=list)
    predicates: list[BusinessRulePredicate] = Field(default_factory=list)
    referenced_fields: list[str] = Field(default_factory=list)
    actions: list[BusinessRuleAction] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    provenance: SourceProvenance | None = None


class SemanticErrorHandling(BaseModel):
    """Structured representation of error and exception handling paths."""

    error_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status_field: str = ""
    expected_status: str = ""
    error_condition: str = ""
    handler_procedure: str = ""
    is_abnormal_termination: bool = False
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    provenance: SourceProvenance | None = None


class UnresolvedReference(BaseModel):
    """Explicitly tracked unresolved reference in a system model (anti-fabrication)."""

    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_module: str
    target_name: str
    reference_kind: str  # PROGRAM_CALL, COPYBOOK_INCLUDE, DATASET, SQL_TABLE, TRANSACTION
    line_number: int | None = None
    reason: str = ""
    confidence: float = 0.0
    provenance: SourceProvenance | None = None


class UnsupportedSemanticConstruct(BaseModel):
    """Represents a construct that cannot be safely translated automatically."""

    construct_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology: str
    construct_name: str
    raw_text: str
    reason: str
    required_specialist: str
    provenance: SourceProvenance | None = None


class SemanticProcedure(BaseModel):
    """A procedure, paragraph, method, or function."""

    procedure_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    kind: str = "procedure"  # procedure, paragraph, method, step
    parameters: list[SemanticField] = Field(default_factory=list)
    return_type: SemanticDataType | None = None
    operations: list[SemanticOperation] = Field(default_factory=list)
    called_procedures: list[str] = Field(default_factory=list)
    referenced_fields: list[str] = Field(default_factory=list)
    mutated_fields: list[str] = Field(default_factory=list)
    business_rules: list[SemanticBusinessRule] = Field(default_factory=list)
    cyclomatic_complexity: int = 1
    provenance: SourceProvenance | None = None


class SemanticGraphNode(BaseModel):
    """A node in the unified semantic graph."""

    node_id: str
    name: str
    kind: str  # PROGRAM, JOB, STEP, COPYBOOK, DATASET, TABLE, VIEW, PROCEDURE, FIELD, BUSINESS_RULE, TRANSACTION, SCREEN
    technology: str = ""
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    attrs: dict[str, Any] = Field(default_factory=dict)
    provenance: SourceProvenance | None = None


class SemanticGraphEdge(BaseModel):
    """A typed directional edge in the unified semantic graph."""

    src: str
    dst: str
    kind: str  # CALLS, INCLUDES, READS, WRITES, EXECUTES, DEFINES, FEEDS, USED_BY, BRANCHES_TO, FLOWS_TO, HANDLES_ERROR, TRANSFERS_TO
    confidence: float = 1.0
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    attrs: dict[str, Any] = Field(default_factory=dict)
    provenance: SourceProvenance | None = None


class SemanticGraph(BaseModel):
    """Unified, composable graph covering dependencies, calls, control flow, data flow, and I/O."""

    nodes: dict[str, SemanticGraphNode] = Field(default_factory=dict)
    edges: list[SemanticGraphEdge] = Field(default_factory=list)

    def add_node(self, node: SemanticGraphNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, edge: SemanticGraphEdge) -> None:
        self.edges.append(edge)

    def get_node(self, node_id: str) -> SemanticGraphNode | None:
        return self.nodes.get(node_id)

    def incoming_edges(self, node_id: str, kind: str | None = None) -> list[SemanticGraphEdge]:
        return [e for e in self.edges if e.dst == node_id and (kind is None or e.kind == kind)]

    def outgoing_edges(self, node_id: str, kind: str | None = None) -> list[SemanticGraphEdge]:
        return [e for e in self.edges if e.src == node_id and (kind is None or e.kind == kind)]

    def neighbors(self, node_id: str, direction: str = "out") -> list[SemanticGraphNode]:
        if direction == "out":
            target_ids = {e.dst for e in self.edges if e.src == node_id}
        else:
            target_ids = {e.src for e in self.edges if e.dst == node_id}
        return [self.nodes[tid] for tid in target_ids if tid in self.nodes]

    def filter_facet(self, facet: str) -> SemanticGraph:
        """Extract a filtered subgraph for a specific engineering facet."""
        facet_upper = facet.upper()
        facet_edge_kinds = {
            "DEPENDENCY": {"CALLS", "INCLUDES", "EXECUTES", "READS", "WRITES", "DEFINES"},
            "CALL": {"CALLS", "EXECUTES", "TRANSFERS_TO"},
            "CONTROL_FLOW": {"BRANCHES_TO", "CALLS", "HANDLES_ERROR"},
            "DATA_FLOW": {"FLOWS_TO", "FEEDS", "USED_BY", "WRITES"},
            "IO": {"READS", "WRITES", "BINDS"},
        }
        allowed = facet_edge_kinds.get(facet_upper, set())
        sub_edges = [e for e in self.edges if not allowed or e.kind in allowed]
        active_nodes = {e.src for e in sub_edges} | {e.dst for e in sub_edges}
        sub_nodes = {nid: n for nid, n in self.nodes.items() if nid in active_nodes}
        return SemanticGraph(nodes=sub_nodes, edges=sub_edges)


class SemanticModule(BaseModel):
    """A program, class, job, or compilation unit."""

    module_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    module_type: str = "program"  # program, job, library, service
    source_technology: str
    source_file_path: str = ""
    source_sha256: str = ""
    fields: list[SemanticField] = Field(default_factory=list)
    entities: list[SemanticEntity] = Field(default_factory=list)
    procedures: list[SemanticProcedure] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    io_operations: list[SemanticIOOperation] = Field(default_factory=list)
    data_flows: list[DataFlowEdge] = Field(default_factory=list)
    error_handlers: list[SemanticErrorHandling] = Field(default_factory=list)
    database_operations: list[SemanticOperation] = Field(default_factory=list)
    unsupported_constructs: list[UnsupportedSemanticConstruct] = Field(default_factory=list)
    business_rules: list[SemanticBusinessRule] = Field(default_factory=list)
    entry_point: str | None = None
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED
    provenance: SourceProvenance | None = None


class TechnologyNeutralSemanticModel(BaseModel):
    """Authoritative technology-neutral semantic representation of a project or system."""

    model_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    modules: dict[str, SemanticModule] = Field(default_factory=dict)
    entities: dict[str, SemanticEntity] = Field(default_factory=dict)
    io_operations: list[SemanticIOOperation] = Field(default_factory=list)
    data_flows: list[DataFlowEdge] = Field(default_factory=list)
    error_handlers: list[SemanticErrorHandling] = Field(default_factory=list)
    unresolved_references: list[UnresolvedReference] = Field(default_factory=list)
    global_business_rules: list[SemanticBusinessRule] = Field(default_factory=list)
    semantic_graph: SemanticGraph = Field(default_factory=SemanticGraph)
    created_at: datetime = Field(default_factory=_utc_now)

    def add_module(self, module: SemanticModule) -> None:
        self.modules[module.name] = module

    def get_module(self, name: str) -> SemanticModule | None:
        return self.modules.get(name)

    def add_entity(self, entity: SemanticEntity) -> None:
        self.entities[entity.name] = entity

    def get_entity(self, name: str) -> SemanticEntity | None:
        return self.entities.get(name)

    def add_io_operation(self, op: SemanticIOOperation) -> None:
        self.io_operations.append(op)

    def add_data_flow(self, flow: DataFlowEdge) -> None:
        self.data_flows.append(flow)

    def add_unresolved_reference(self, ref: UnresolvedReference) -> None:
        self.unresolved_references.append(ref)

    @property
    def total_modules(self) -> int:
        return len(self.modules)

    @property
    def total_entities(self) -> int:
        return len(self.entities)

    @property
    def total_procedures(self) -> int:
        return sum(len(m.procedures) for m in self.modules.values())

    @property
    def total_operations(self) -> int:
        return sum(len(proc.operations) for m in self.modules.values() for proc in m.procedures)

    @property
    def total_fields(self) -> int:
        module_fields = sum(len(m.fields) for m in self.modules.values())
        entity_fields = sum(len(e.fields) for e in self.entities.values())
        return module_fields + entity_fields

    @property
    def total_business_rules(self) -> int:
        return len(self.global_business_rules) + sum(len(m.business_rules) for m in self.modules.values())

    @property
    def total_io_operations(self) -> int:
        return len(self.io_operations) + sum(len(m.io_operations) for m in self.modules.values())

    @property
    def total_data_flows(self) -> int:
        return len(self.data_flows) + sum(len(m.data_flows) for m in self.modules.values())

    @property
    def total_unsupported_constructs(self) -> int:
        return sum(len(m.unsupported_constructs) for m in self.modules.values())

    @property
    def total_unresolved_references(self) -> int:
        return len(self.unresolved_references)
