"""Adversarial and Generic Syntax Regression Suite for COBOL Lexer/Parser,
Statement Boundary Assembly, and Business Rule Extraction.
"""

from __future__ import annotations

import pytest
from autoforge_modernization.semantic.extractors import (
    SemanticModelExtractor,
    _clean_cobol_source,
    _split_cobol_statements,
)
from autoforge_modernization.composition.generator import (
    GenericTargetArtifactGenerator,
    GeneratedArtifact,
)
from autoforge_modernization.composition.planner import GenericTransformationPlanner
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.semantic.model import TechnologyNeutralSemanticModel
from autoforge_modernization.target.specification import TargetSpecification


def test_comment_stripping_and_safety():
    """Verify column 7 comments, line markers, and inline *> comments are safely stripped."""
    source = """       *---------------------------------------------------------------
       * IF Your user id is Z54321, please ignore this comment.
       *---------------------------------------------------------------
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TESTCOMM.
        PROCEDURE DIVISION.
        P001.
            MOVE 100 TO ACCT-BAL *> Inline comment with IF and COMPUTE
       *    IF ACCT-BAL > 500 MOVE 0 TO ACCT-BAL
            DISPLAY ACCT-BAL.
            GOBACK.
"""
    cleaned = _clean_cobol_source(source)
    assert "Your user id is Z54321" not in cleaned
    assert "Inline comment with IF" not in cleaned
    assert "ACCT-BAL > 500" not in cleaned

    extractor = SemanticModelExtractor()
    mod = extractor.extract_from_cobol(source, "TESTCOMM.cbl")
    assert len(mod.business_rules) == 0  # Zero false-positive rules from comments


def test_statement_splitting_with_then_and_scope_terminators():
    """Verify THEN, END-COMPUTE, END-IF, and inline statements split cleanly."""
    body = """
        IF USA-STATE = 'New York' THEN
            MOVE ACCT-LIMIT TO ACCT-LIMIT-O
            COMPUTE TLIMIT = TLIMIT + ACCT-LIMIT END-COMPUTE
        END-IF.
        READ ACCT-REC
            AT END MOVE 'Y' TO LASTREC
        END-READ.
        DIVIDE NUMERATOR BY DENOMINATOR GIVING RESULT.
    """
    stmts = _split_cobol_statements(body)
    assert any("IF USA-STATE = 'New York'" in s for s in stmts)
    assert any("MOVE ACCT-LIMIT TO ACCT-LIMIT-O" in s for s in stmts)
    assert any("COMPUTE TLIMIT = TLIMIT + ACCT-LIMIT" in s for s in stmts)
    assert any("END-IF" in s for s in stmts)
    assert any("MOVE 'Y' TO LASTREC" in s for s in stmts)
    assert any("DIVIDE NUMERATOR BY DENOMINATOR GIVING RESULT" in s for s in stmts)


def test_target_generation_and_compilation_adversarial():
    """Verify adversarial COBOL construct produces 100% valid compilable Java code."""
    source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. ADVSYN.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-FIELDS.
            05 USA-STATE      PIC X(15) VALUE 'New York'.
            05 ACCT-LIMIT     PIC 9(7)V99 VALUE 5000.00.
            05 TLIMIT         PIC 9(9)V99 VALUE 0.
            05 NUMERATOR      PIC 9(5) VALUE 100.
            05 DENOMINATOR    PIC 9(5) VALUE 20.
            05 RESULT         PIC 9(5) VALUE 0.
            05 ACCT-LIMIT-O   PIC X(10) VALUE SPACES.
        PROCEDURE DIVISION.
        MAIN-PROC.
            IF USA-STATE = 'New York' THEN
                MOVE ACCT-LIMIT TO ACCT-LIMIT-O
                COMPUTE TLIMIT = TLIMIT + ACCT-LIMIT END-COMPUTE
            END-IF
            DIVIDE NUMERATOR BY DENOMINATOR GIVING RESULT
            DISPLAY RESULT
            GOBACK.
    """
    extractor = SemanticModelExtractor()
    mod = extractor.extract_from_cobol(source, "ADVSYN.cbl")
    model = TechnologyNeutralSemanticModel(project_id="test-adv")
    model.add_module(mod)

    target_spec = TargetSpecification.java_spring_boot()
    planner = GenericTransformationPlanner()
    plan = planner.plan(model, target_spec)
    generator = GenericTargetArtifactGenerator()
    artifacts = generator.generate(model, plan, target_spec)

    verifier = TargetToolchainVerifier()
    res = verifier.verify(artifacts, target_spec)
    assert res.passed is True, f"Compilation failed: {res.diagnostics}"
    assert len(res.class_files_generated) >= 1
