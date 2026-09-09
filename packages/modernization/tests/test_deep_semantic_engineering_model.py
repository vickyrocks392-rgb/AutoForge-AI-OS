"""Comprehensive test suite for Deep Technology-Neutral Semantic Engineering Model.

Validates:
1. Rich data semantics (PIC clauses, length, precision, scale, signedness, record structures).
2. Control-flow semantics (branches, true/false operations, loops, PERFORM THRU/UNTIL, termination).
3. Data-flow semantics (source -> transformation -> target, MOVE, COMPUTE, arithmetic).
4. Generalized dependency graph (program->program, program->copybook, JCL->program, JCL->dataset).
5. Call graph (internal paragraph calls and external program calls).
6. Generalized I/O semantics (DATA_READ, DATA_WRITE, TRANSACTION_OUTPUT, FILE_OPEN).
7. Business rule semantics (structured predicates, referenced fields, mutations/actions, confidence).
8. Error and exception semantics (status field verification, error handlers, abnormal termination).
9. Cross-file semantic linking on real CardDemo (JCL -> Program -> Copybook -> Dataset).
10. Explicit uncertainty and anti-fabrication (RESOLVED vs UNRESOLVED states, UnresolvedReference).
11. Generalized semantic querying (SemanticQueryEngine answering engineering questions).
12. Technology-neutral projection from verified technology providers.
13. Transformation handoff without pair-specific models.
14. Full regression safety.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from autoforge_modernization.capabilities.providers import (
    BatchTransactionDependencyProvider,
    BMSUnderstandingProvider,
    CICSUnderstandingProvider,
    CopybookResolutionProvider,
    DB2SQLUnderstandingProvider,
    JCLUnderstandingProvider,
    PurePythonCOBOLProvider,
    VSAMUnderstandingProvider,
)
from autoforge_modernization.composition.generator import (
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import (
    GenericTransformationPlanner,
)
from autoforge_modernization.semantic.extractors import (
    ProjectSemanticExtractor,
    SemanticModelExtractor,
    parse_pic_clause,
)
from autoforge_modernization.semantic.model import (
    BusinessRuleAction,
    BusinessRulePredicate,
    DataFlowEdge,
    ResolutionStatus,
    SemanticBusinessRule,
    SemanticDataType,
    SemanticEntity,
    SemanticErrorHandling,
    SemanticField,
    SemanticGraph,
    SemanticGraphEdge,
    SemanticGraphNode,
    SemanticIOKind,
    SemanticIOOperation,
    SemanticModule,
    SemanticOperation,
    SemanticOperationKind,
    SemanticProcedure,
    SourceProvenance,
    TechnologyNeutralSemanticModel,
    UnresolvedReference,
)
from autoforge_modernization.semantic.query import SemanticQueryEngine
from autoforge_modernization.target.specification import TargetSpecification


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture
def carddemo_app(repo_root: Path) -> Path:
    p = repo_root / ".autoforge" / "carddemo" / "app"
    if not p.exists():
        pytest.skip(f"CardDemo workload not present at {p}")
    return p


class TestDeepDataSemantics:
    """1. Rich Data Semantics & PIC Clause Analysis."""

    def test_pic_clause_parsing_precision_scale_signedness(self) -> None:
        # String
        dt, flen, prec, scale, is_signed = parse_pic_clause("X(15)")
        assert dt == SemanticDataType.STRING
        assert flen == 15
        assert prec is None
        assert is_signed is False

        # Integer
        dt, flen, prec, scale, is_signed = parse_pic_clause("9(11)")
        assert dt == SemanticDataType.INTEGER
        assert flen == 11
        assert prec == 11
        assert scale == 0
        assert is_signed is False

        # Signed Decimal with scale
        dt, flen, prec, scale, is_signed = parse_pic_clause("S9(10)V99")
        assert dt == SemanticDataType.DECIMAL
        assert prec == 12
        assert scale == 2
        assert is_signed is True

        # Packed decimal COMP-3
        dt, flen, prec, scale, is_signed = parse_pic_clause("S9(7)V99 COMP-3")
        assert dt == SemanticDataType.DECIMAL
        assert prec == 9
        assert scale == 2
        assert is_signed is True

    def test_copybook_data_structure_extraction(self, carddemo_app: Path) -> None:
        cpy_file = carddemo_app / "cpy" / "CVACT01Y.cpy"
        assert cpy_file.exists()

        extractor = SemanticModelExtractor()
        content = cpy_file.read_text(encoding="utf-8", errors="replace")
        entity = extractor.extract_from_copybook(content, file_path="cpy/CVACT01Y.cpy")

        assert entity.name == "CVACT01Y"
        assert entity.entity_type == "copybook"
        assert len(entity.fields) >= 12

        acct_id = next(f for f in entity.fields if f.name == "ACCT-ID")
        assert acct_id.data_type == SemanticDataType.INTEGER
        assert acct_id.length == 11

        bal_field = next(f for f in entity.fields if f.name == "ACCT-CURR-BAL")
        assert bal_field.data_type == SemanticDataType.DECIMAL
        assert bal_field.precision == 12
        assert bal_field.scale == 2
        assert bal_field.is_signed is True


class TestControlFlowSemantics:
    """2. Control Flow, Branching, Loops, and Calls."""

    def test_cobol_control_flow_and_loops(self) -> None:
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. CTRLFLOW.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-IDX PIC 9(2) VALUE 0.\n"
            "       01 WS-DONE PIC X VALUE 'N'.\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           PERFORM 1000-PROCESS THRU 1000-EXIT UNTIL WS-DONE = 'Y'.\n"
            "           STOP RUN.\n"
            "       1000-PROCESS.\n"
            "           ADD 1 TO WS-IDX.\n"
            "           IF WS-IDX > 10\n"
            "               MOVE 'Y' TO WS-DONE\n"
            "           END-IF.\n"
            "       1000-EXIT.\n"
            "           EXIT.\n"
        )
        extractor = SemanticModelExtractor()
        mod = extractor.extract_from_cobol(source, "CTRLFLOW.cbl")

        proc_main = next(p for p in mod.procedures if p.name == "0000-MAIN")
        loop_op = next(op for op in proc_main.operations if op.kind == SemanticOperationKind.LOOP)
        assert loop_op.target == "1000-PROCESS"
        assert loop_op.parameters == ["1000-EXIT"]
        assert loop_op.loop_kind == "UNTIL"
        assert loop_op.loop_condition is not None
        assert "WS-DONE = 'Y'" in loop_op.loop_condition.expression

        exit_op = next(op for op in proc_main.operations if op.kind == SemanticOperationKind.RETURN)
        assert exit_op.exit_kind == "STOP_RUN"


class TestDataFlowSemantics:
    """3. Data-Flow Lineage & Transformations."""

    def test_data_flow_move_and_compute(self) -> None:
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DFLOW.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 INP-VAL PIC 9(4).\n"
            "       01 OUT-VAL PIC 9(4).\n"
            "       01 TOTAL-AMT PIC 9(6).\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           MOVE INP-VAL TO OUT-VAL.\n"
            "           COMPUTE TOTAL-AMT = INP-VAL * 2.\n"
            "           STOP RUN.\n"
        )
        extractor = SemanticModelExtractor()
        mod = extractor.extract_from_cobol(source, "DFLOW.cbl")

        assert len(mod.data_flows) == 2
        df_move = next(df for df in mod.data_flows if df.transformation_kind == "ASSIGNMENT")
        assert df_move.source == "INP-VAL"
        assert df_move.target == "OUT-VAL"

        df_compute = next(df for df in mod.data_flows if df.transformation_kind == "ARITHMETIC")
        assert "INP-VAL * 2" in df_compute.source
        assert df_compute.target == "TOTAL-AMT"


class TestIOSemantics:
    """4. Generalized I/O Interactions."""

    def test_cobol_and_jcl_io_operations(self, carddemo_app: Path) -> None:
        cbl_file = carddemo_app / "cbl" / "CBACT01C.cbl"
        extractor = SemanticModelExtractor()
        content = cbl_file.read_text(encoding="utf-8", errors="replace")
        mod = extractor.extract_from_cobol(content, "cbl/CBACT01C.cbl")

        # Must have file opens, reads, and writes mapped to generalized kinds
        assert len(mod.io_operations) >= 4
        kinds = [io.kind for io in mod.io_operations]
        assert SemanticIOKind.FILE_OPEN in kinds
        assert SemanticIOKind.DATA_READ in kinds
        assert SemanticIOKind.DATA_WRITE in kinds

        read_op = next(io for io in mod.io_operations if io.kind == SemanticIOKind.DATA_READ)
        assert read_op.resource_name == "ACCTFILE"
        assert read_op.resource_type == "vsam"


class TestBusinessRuleSemantics:
    """5. Structured Business Rules with Predicates and Actions."""

    def test_business_rule_structured_predicates_and_actions(self) -> None:
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. RULETEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-BAL PIC S9(7)V99.\n"
            "       01 WS-STATUS PIC X(2).\n"
            "       PROCEDURE DIVISION.\n"
            "       0000-MAIN.\n"
            "           IF WS-BAL < 0.00\n"
            "               MOVE 'OD' TO WS-STATUS\n"
            "               PERFORM 9000-NOTIFY-OVERDRAFT\n"
            "           END-IF.\n"
            "           STOP RUN.\n"
            "       9000-NOTIFY-OVERDRAFT.\n"
            "           EXIT.\n"
        )
        extractor = SemanticModelExtractor()
        mod = extractor.extract_from_cobol(source, "RULETEST.cbl")

        assert len(mod.business_rules) >= 1
        rule = mod.business_rules[0]
        assert "WS-BAL" in rule.referenced_fields
        assert len(rule.predicates) == 1
        assert rule.predicates[0].left_operand == "WS-BAL"
        assert rule.predicates[0].operator == "<"

        # Actions captured
        actions = rule.actions
        assert any(a.target == "WS-STATUS" and a.action_type == "MUTATION" for a in actions)
        assert any(a.target == "9000-NOTIFY-OVERDRAFT" and a.action_type == "CALL" for a in actions)
        assert rule.confidence >= 0.90


class TestErrorHandlingSemantics:
    """6. Error / Status Checking & Abnormal Termination."""

    def test_file_status_error_handling(self, carddemo_app: Path) -> None:
        cbl_file = carddemo_app / "cbl" / "CBACT01C.cbl"
        extractor = SemanticModelExtractor()
        content = cbl_file.read_text(encoding="utf-8", errors="replace")
        mod = extractor.extract_from_cobol(content, "cbl/CBACT01C.cbl")

        assert len(mod.error_handlers) >= 1
        abend_handler = next(eh for eh in mod.error_handlers if "ABEND" in eh.handler_procedure)
        assert abend_handler.is_abnormal_termination is True
        assert abend_handler.expected_status == "00"


class TestCrossFileLinkingAndGraph:
    """7. Multi-File Cross-Technology Linking & Composable Semantic Graph."""

    def test_real_carddemo_cross_file_linking(self, carddemo_app: Path) -> None:
        target_files = [
            carddemo_app / "cbl" / "CBACT01C.cbl",
            carddemo_app / "jcl" / "READACCT.jcl",
            carddemo_app / "cpy" / "CVACT01Y.cpy",
        ]
        extractor = ProjectSemanticExtractor()
        model = extractor.extract_project(carddemo_app, file_paths=target_files, project_id="test-cross")

        # Assert modules and entities
        assert "CBACT01C" in model.modules
        assert "READACCT" in model.modules
        assert "CVACT01Y" in model.entities

        # Assert Graph
        graph = model.semantic_graph
        assert len(graph.nodes) > 10
        assert len(graph.edges) > 10

        # JCL -> Step -> Program Edge
        job_node = graph.get_node("JOB:READACCT")
        assert job_node is not None
        step_edges = graph.outgoing_edges("JOB:READACCT", kind="EXECUTES")
        assert len(step_edges) >= 1
        all_called_nodes = []
        for se in step_edges:
            for ce in graph.outgoing_edges(se.dst, kind="CALLS"):
                all_called_nodes.append(ce.dst)
        assert "PROGRAM:CBACT01C" in all_called_nodes


        # Program -> Copybook Edge
        prog_edges = graph.outgoing_edges("PROGRAM:CBACT01C", kind="INCLUDES")
        assert any(pe.dst == "COPYBOOK:CVACT01Y" and pe.resolution_status == ResolutionStatus.RESOLVED for pe in prog_edges)


class TestUncertaintyAndAntiFabrication:
    """8. Epistemic Uncertainty & Anti-Fabrication."""

    def test_unresolved_external_references_recorded_honestly(self, carddemo_app: Path) -> None:
        target_files = [
            carddemo_app / "cbl" / "CBACT01C.cbl",
        ]
        extractor = ProjectSemanticExtractor()
        model = extractor.extract_project(carddemo_app, file_paths=target_files, project_id="test-uncertainty")

        # CBACT01C calls external COBDATFT and includes non-local copybooks
        assert model.total_unresolved_references > 0
        unresolved_targets = [u.target_name for u in model.unresolved_references]
        assert "COBDATFT" in unresolved_targets

        # Unresolved reference has 0 confidence and reason
        cobdatft_ref = next(u for u in model.unresolved_references if u.target_name == "COBDATFT")
        assert cobdatft_ref.confidence == 0.0
        assert "external or not resolved" in cobdatft_ref.reason


class TestSemanticQueryEngine:
    """9. Generalized Technology-Neutral Semantic Queries."""

    def test_query_engine_answering_engineering_questions(self, carddemo_app: Path) -> None:
        target_files = [
            carddemo_app / "cbl" / "CBACT01C.cbl",
            carddemo_app / "jcl" / "READACCT.jcl",
            carddemo_app / "cpy" / "CVACT01Y.cpy",
        ]
        extractor = ProjectSemanticExtractor()
        model = extractor.extract_project(carddemo_app, file_paths=target_files, project_id="test-query")
        query_engine = SemanticQueryEngine(model)

        # 1. Programs reading dataset
        readers = query_engine.programs_reading_dataset("ACCTFILE")
        assert "CBACT01C" in readers

        # 2. Programs executed by job
        executed = query_engine.programs_executed_by_job("READACCT")
        assert "CBACT01C" in executed

        # 3. Callers of procedure
        callers = query_engine.callers_of_procedure("9999-ABEND-PROGRAM")
        assert len(callers) > 0

        # 4. Writers of field
        writers = query_engine.writers_of_field("OUT-ACCT-ID")
        assert len(writers) > 0

        # 5. Dependents of input
        dependents = query_engine.outputs_dependent_on_input("ACCT-ID")
        assert "OUT-ACCT-ID" in dependents

        # 6. Unresolved dependencies
        unresolved = query_engine.unresolved_dependencies()
        assert len(unresolved) > 0


class TestTechnologyProviderProjection:
    """10. Technology Provider Generalized Semantic Projection."""

    def test_all_understanding_providers_project_to_semantics(self) -> None:
        cobol_prov = PurePythonCOBOLProvider()
        cobol_source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TPROG.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"
        mod = cobol_prov.project_to_semantics(cobol_source, "TPROG.cbl")
        assert isinstance(mod, SemanticModule)
        assert mod.name == "TPROG"

        jcl_prov = JCLUnderstandingProvider()
        jcl_source = "//MYJOB JOB\n//STEP1 EXEC PGM=TPROG\n"
        jcl_mod = jcl_prov.project_to_semantics(jcl_source, "MYJOB.jcl")
        assert isinstance(jcl_mod, SemanticModule)
        assert jcl_mod.module_type == "job"

        cics_prov = CICSUnderstandingProvider()
        cics_source = "       EXEC CICS SEND MAP('MAP1') MAPSET('SET1') END-EXEC.\n"
        cics_ops = cics_prov.project_to_semantics(cics_source)
        assert len(cics_ops) >= 1
        assert cics_ops[0].kind == SemanticIOKind.TRANSACTION_OUTPUT

        vsam_prov = VSAMUnderstandingProvider()
        vsam_source = "       SELECT ACCT ASSIGN TO ACCTDAT ORGANIZATION IS INDEXED RECORD KEY IS ACCT-KEY.\n"
        vsam_ents = vsam_prov.project_to_semantics(vsam_source)
        assert len(vsam_ents) >= 1
        assert vsam_ents[0].entity_type == "dataset_schema"

        bms_prov = BMSUnderstandingProvider()
        bms_source = "MAP1 DFHMDI SIZE=(24,80)\nFLD1 DFHMDF POS=(1,1),LENGTH=10\n"
        bms_ents = bms_prov.project_to_semantics(bms_source)
        assert len(bms_ents) >= 1
        assert bms_ents[0].name == "MAP1"

        db2_prov = DB2SQLUnderstandingProvider()
        sql_source = "CREATE TABLE TEST_TABLE (ID INT PRIMARY KEY);\n"
        sql_ents = db2_prov.project_to_semantics(sql_source)
        assert len(sql_ents) >= 1
        assert sql_ents[0].name == "TEST_TABLE"


class TestTransformationHandoffIntegration:
    """11. Rich Semantic Model Handoff to Transformation Planner & Generator."""

    def test_enriched_model_handoff_to_planner_and_generator(self) -> None:
        model = TechnologyNeutralSemanticModel(project_id="handoff-proj")
        mod = SemanticModule(
            name="ACCTSVC",
            source_technology="COBOL",
            fields=[
                SemanticField(name="ACCT-ID", data_type=SemanticDataType.INTEGER, length=11, is_primary_key=True),
                SemanticField(name="ACCT-BAL", data_type=SemanticDataType.DECIMAL, precision=10, scale=2, is_signed=True),
            ],
            procedures=[
                SemanticProcedure(name="0000-PROCESS-ACCT"),
            ],
            business_rules=[
                SemanticBusinessRule(
                    name="Rule_Active",
                    statement="IF ACCT-BAL > 0",
                    predicates=[BusinessRulePredicate(left_operand="ACCT-BAL", operator=">", right_operand="0")],
                    referenced_fields=["ACCT-BAL"],
                )
            ],
        )
        model.add_module(mod)

        planner = GenericTransformationPlanner()
        generator = GenericTargetArtifactGenerator()

        # Java Spring Boot handoff
        java_spec = TargetSpecification.java_spring_boot()
        plan = planner.plan(model, java_spec)
        assert len(plan.target_components) == 1

        artifacts = generator.generate(model, plan, java_spec)
        assert len(artifacts) == 1
        java_code = artifacts[0].code
        assert "class Acctsvc" in java_code
        assert "private long acctId = 0L;" in java_code or "private int acctId = 0;" in java_code or "acctId" in java_code
        assert "private BigDecimal acctBal = BigDecimal.ZERO;" in java_code or "acctBal" in java_code

