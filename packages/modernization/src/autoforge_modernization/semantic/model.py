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

Represents semantic concepts independent of source and target languages while
retaining full source provenance and explicitly tracking unsupported constructs.
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


class SourceProvenance(BaseModel):
    """Full traceability linking any semantic construct back to source evidence."""

    source_file: str
    line_start: int | None = None
    line_end: int | None = None
    source_sha256: str = ""
    original_construct: str = ""  # e.g., "PERFORM 1000-PROCESS UNTIL WS-DONE = 'Y'"
    analyzer_id: str = "autoforge-semantic-extractor"


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
    """A data item or variable definition."""

    field_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    data_type: SemanticDataType = SemanticDataType.UNKNOWN
    original_type_descriptor: str = ""  # e.g. "PIC S9(7)V99 COMP-3"
    level: int | None = None
    default_value: str | None = None
    is_constant: bool = False
    is_primary_key: bool = False
    is_foreign_key: bool = False
    parent_record_name: str | None = None
    children: list[SemanticField] = Field(default_factory=list)
    provenance: SourceProvenance | None = None


class SemanticCondition(BaseModel):
    """A branch or loop condition expression."""

    expression: str
    left_operand: str = ""
    operator: str = ""  # EQUALS, GREATER, LESS, NOT_EQUALS, IN, etc.
    right_operand: str = ""
    is_complex: bool = False
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


class SemanticOperation(BaseModel):
    """An atomic or compound operation within a procedure/method."""

    op_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: SemanticOperationKind
    description: str
    target: str = ""  # target variable, procedure name, or table
    parameters: list[str] = Field(default_factory=list)
    condition: SemanticCondition | None = None
    nested_operations: list[SemanticOperation] = Field(default_factory=list)
    provenance: SourceProvenance | None = None


class SemanticBusinessRule(BaseModel):
    """Extracted business policy or invariant."""

    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    statement: str
    conditions: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    confidence: float = 1.0
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
    business_rules: list[SemanticBusinessRule] = Field(default_factory=list)
    cyclomatic_complexity: int = 1
    provenance: SourceProvenance | None = None


class SemanticModule(BaseModel):
    """A program, class, job, or compilation unit."""

    module_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    module_type: str = "program"  # program, job, library, service
    source_technology: str
    source_file_path: str = ""
    source_sha256: str = ""
    fields: list[SemanticField] = Field(default_factory=list)
    procedures: list[SemanticProcedure] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    database_operations: list[SemanticOperation] = Field(default_factory=list)
    unsupported_constructs: list[UnsupportedSemanticConstruct] = Field(default_factory=list)
    business_rules: list[SemanticBusinessRule] = Field(default_factory=list)
    entry_point: str | None = None
    provenance: SourceProvenance | None = None


class TechnologyNeutralSemanticModel(BaseModel):
    """Authoritative technology-neutral semantic representation of a project or system."""

    model_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    modules: dict[str, SemanticModule] = Field(default_factory=dict)
    global_business_rules: list[SemanticBusinessRule] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)

    def add_module(self, module: SemanticModule) -> None:
        self.modules[module.name] = module

    def get_module(self, name: str) -> SemanticModule | None:
        return self.modules.get(name)

    @property
    def total_modules(self) -> int:
        return len(self.modules)

    @property
    def total_procedures(self) -> int:
        return sum(len(m.procedures) for m in self.modules.values())

    @property
    def total_unsupported_constructs(self) -> int:
        return sum(len(m.unsupported_constructs) for m in self.modules.values())
