"""
Behavioral tests for Legacy Analyzers, Legacy System Models, Evidence Tracking, and Unknown Technologies.
"""

from __future__ import annotations
import pytest
import uuid
from pathlib import Path

from autoforge_execution import WorkspaceEnvironment
from autoforge_workflows.models import TaskDefinition

from autoforge_workforce.legacy_analyzers import (
    COBOLAnalyzer,
    JavaMonolithAnalyzer,
    SQLAnalyzer,
    UnknownTechnologyAnalyzer,
    get_analyzer_for_file,
)
from autoforge_workforce.legacy_models import LegacySystemModel, FactState
from autoforge_workforce.loops import LegacyDiscoveryLoop, BusinessRuleExtractionLoop


def test_cobol_analyzer():
    """
    COBOL Analyzer must detect COBOL syntax, paragraphs, COPYBOOKs, and SELECT files.
    """
    content = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MY-FILE ASSIGN TO "DATA.TXT".
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       PROCEDURE DIVISION.
       MAIN-PARAGRAPH.
           COPY USER-DEF.
           DISPLAY "Hello, Mainframe".
           STOP RUN.
    """
    analyzer = COBOLAnalyzer()
    assert analyzer.detect(content, "HELLO.cbl") is True

    analysis = analyzer.analyze(content, "HELLO.cbl")
    assert analysis["language"] == "COBOL"
    assert "copybook:USER-DEF" in analysis["dependencies"]
    assert "file:MY-FILE" in analysis["data_access"]
    assert "paragraph:MAIN-PARAGRAPH" in analysis["symbols"]


def test_java_monolith_analyzer():
    """
    Java Monolith Analyzer must detect Java classes, imports, database mappings, and REST endpoints.
    """
    content = """
       package com.legacy.app;
       import java.sql.Connection;
       import org.springframework.web.bind.annotation.RequestMapping;
       
       @Table(name = "CUSTOMERS")
       public class LegacyController {
           @RequestMapping("/getDetails")
           public String getDetails() {
               String query = "SELECT * FROM ACCOUNT";
               return "Data";
           }
       }
    """
    analyzer = JavaMonolithAnalyzer()
    assert analyzer.detect(content, "LegacyController.java") is True

    analysis = analyzer.analyze(content, "LegacyController.java")
    assert analysis["language"] == "Java"
    assert "import:java.sql.Connection" in analysis["dependencies"]
    assert "table:ACCOUNT" in analysis["data_access"]
    assert "table:CUSTOMERS" in analysis["data_access"]
    assert "endpoint:/getDetails" in analysis["interfaces"]


def test_sql_stored_procedures_analyzer():
    """
    SQL Analyzer must detect tables, procedures, views, and data operations.
    """
    content = """
       CREATE TABLE USERS (
           ID INT PRIMARY KEY,
           NAME VARCHAR(50)
       );

       CREATE PROCEDURE GetUserById
       AS
       BEGIN
           SELECT * FROM USERS JOIN ROLES ON USERS.ROLE_ID = ROLES.ID;
       END;
    """
    analyzer = SQLAnalyzer()
    assert analyzer.detect(content, "schema.sql") is True

    analysis = analyzer.analyze(content, "schema.sql")
    assert analysis["language"] == "SQL"
    assert "table:USERS" in analysis["symbols"]
    assert "procedure:GetUserById" in analysis["symbols"]
    assert "table:ROLES" in analysis["data_access"]


def test_unknown_technology_handling():
    """
    Unknown technology must fallback to generic analyzer, raising uncertainty and analysis gaps.
    """
    content = """
       fn handle_incoming_request(req: Request) -> Response {
           using database_conn;
           // Unsupported legacy/unfamiliar framework
           compute_custom_hash(req.data);
       }
    """
    # Test file-matching rules fallback to Unknown
    analyzer = get_analyzer_for_file(content, "custom_logic.xyz")
    assert isinstance(analyzer, UnknownTechnologyAnalyzer)

    analysis = analyzer.analyze(content, "custom_logic.xyz")
    assert analysis["language"] == "UNKNOWN"
    assert "generic_symbol:handle_incoming_request" in analysis["symbols"]
    assert "generic_dep:database_conn" in analysis["dependencies"]
    assert "analysis_gap" in analysis
    assert "unknown" in analysis["analysis_gap"].lower()


@pytest.mark.asyncio
async def test_legacy_discovery_loop_e2e(tmp_path: Path):
    """
    Legacy Discovery Loop must scan workspace files, build a LegacySystemModel,
    categorize FactStates, capture evidence ledger, and record gaps.
    """
    env = WorkspaceEnvironment(tmp_path)
    
    # Write representative synthetic legacy files into workspace
    cobol_content = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           COPY MY-BOOK.\n"
    )
    java_content = "package com.app; public class Service {}"
    unknown_content = "fn unknown_logic() {}"

    env.filesystem.write_text("src/MAIN.cbl", cobol_content)
    env.filesystem.write_text("src/Service.java", java_content)
    env.filesystem.write_text("src/custom.xyz", unknown_content)

    loop = LegacyDiscoveryLoop(
        environment=env,
        ai_provider=None,
    )

    task_def = TaskDefinition(
        task_id="task-legacy-intake-01",
        name="Ingest Legacy Core",
        task_type="legacy_discovery",
    )
    context = pytest.importorskip("autoforge_execution.context").ExecutionContext.from_task_definition(task_def, env.root)

    passed, artifacts, eval_res = await loop.run(context, "legacy-archaeologist-xyz")

    assert passed is True
    assert len(artifacts) == 1
    assert artifacts[0].name == "legacy_system_model.json"
    
    # Parse LegacySystemModel from artifact output
    import json
    model_data = json.loads(artifacts[0].content)
    
    assert model_data["technologies"]["COBOL"] == FactState.FACT.value
    assert model_data["technologies"]["Java"] == FactState.FACT.value
    assert model_data["technologies"]["UNKNOWN"] == FactState.FACT.value

    # Validate evidence collection
    assert len(model_data["evidence_ledger"]) > 0
    # COBOL file should have symbol extraction evidence
    evidence_sources = [ev["source_file"] for ev in model_data["evidence_ledger"]]
    assert "src/MAIN.cbl" in evidence_sources

    # Validate analysis gaps (Unknown tech raises gap)
    assert len(model_data["analysis_gaps"]) == 1
    assert "generic structural analysis" in model_data["analysis_gaps"][0]["description"]
