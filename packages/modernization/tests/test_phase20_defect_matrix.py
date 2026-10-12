"""Phase 20 -- permanent 10-defect regression matrix, categories A-E.

Each class below was a real defect found while tracing the real DAILYPOST
workload. Each is pinned by a test named after the *class*, so a regression
identifies which invariant broke rather than merely failing a program.

Every program here is generic: invented names (``REC-A``, ``AMT-FLD``), never a
fixture name, and no expected-output bytes anywhere.

Matrix: A IF/ELSE nesting depth | B AT END vs NOT AT END | C EVALUATE subject
| D accumulating arithmetic verbs | E arithmetic tail consumption.
"""

from __future__ import annotations

import pytest

from autoforge_modernization.service import java_codegen as jc
from autoforge_modernization.service.cobol_program import build_program_model
from autoforge_modernization.service.cobol_proc import (
    _split_if_body,
    split_on_keywords,
)

COPYBOOK = """\
       05  KEY-FLD       PIC X(4).
       05  AMT-FLD       PIC S9(9)V99 COMP-3.
       05  CNT-FLD       PIC 9(5).
"""

PREAMBLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GENERIC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SRC-FILE ASSIGN TO "data/src.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT DST-FILE ASSIGN TO "out/dst.dat"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  SRC-FILE RECORD CONTAINS 40 CHARACTERS.
       01  REC-A.
           COPY "LAYOUT.cpy".
       FD  DST-FILE RECORD CONTAINS 40 CHARACTERS.
       01  REC-B.
           COPY "LAYOUT.cpy".
       WORKING-STORAGE SECTION.
       77  WS-TOTAL   PIC S9(13)V99 COMP-3.
       77  WS-RATE    PIC S9(13)V99 COMP-3.
       77  WS-FLAG    PIC X VALUE "N".
       PROCEDURE DIVISION.
       FIRST-PARA.
"""


@pytest.fixture
def copybook_dir(tmp_path):
    (tmp_path / "LAYOUT.cpy").write_text(COPYBOOK)
    return tmp_path


def build(tmp_path, body: str):
    """Model a complete generic program whose paragraph body is ``body``."""
    source = PREAMBLE + body + "\n           GOBACK.\n"
    return build_program_model(
        source, source_path="cobol/GENERIC.cbl", copybook_dirs=[tmp_path])


def emitter_for(model) -> jc._Emitter:
    symbols = jc._SymbolTable()
    jc._collect_buffers(model, symbols)
    return jc._Emitter(model, symbols,
                       {n: jc.java_safe(n) for n in sorted(model.files)})


def generated(model) -> str:
    """Generate and return the program body, asserting translation succeeded."""
    result = jc.generate_java(model, java_package="generic")
    assert result.ok, result.unsupported
    return "\n".join(f.content for f in result.files
                     if "CobolRuntime" not in f.path)


# ════════════════════════════════════════════════════════════════════════════
# A. IF / ELSE NESTING DEPTH
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixAIfElseNestingDepth:
    """An ELSE arm must not lose statements after a nested IF."""

    @pytest.mark.parametrize("depth", [1, 2, 3])
    def test_trailing_statement_survives_nesting(self, depth):
        nested = " ".join(["IF F = 1 MOVE 1 TO G END-IF"] * depth)
        body = f" MOVE 1 TO A ELSE MOVE 2 TO B {nested} PERFORM TAIL"
        then_text, else_text = _split_if_body(" " + body)
        assert "PERFORM TAIL" in else_text, (
            f"depth {depth}: the trailing statement was dropped")

    def test_then_branch_ends_at_else(self):
        then_text, else_text = _split_if_body(
            " A = 1 MOVE 1 TO B ELSE MOVE 2 TO C")
        assert then_text.strip() == "A = 1 MOVE 1 TO B"
        assert else_text.strip() == "MOVE 2 TO C"

    def test_no_else_yields_empty_else(self):
        then_text, else_text = _split_if_body(" A = 1 MOVE 1 TO B")
        assert "MOVE 1 TO B" in then_text
        assert else_text.strip() == ""

    def test_generated_if_else_keeps_both_branches(self, copybook_dir):
        model = build(
            copybook_dir,
            '           IF KEY-FLD = "A"\n'
            "              MOVE 1 TO WS-RATE\n"
            "           ELSE\n"
            "              MOVE 2 TO WS-RATE\n"
            "           END-IF")
        assert "} else {" in generated(model), (
            "the ELSE branch must survive codegen")


# ════════════════════════════════════════════════════════════════════════════
# B. AT END vs NOT AT END (LONGEST MATCH)
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixBAtEndLongestMatch:
    """`AT END` must not match inside `NOT AT END`."""

    @pytest.mark.parametrize("short,long", [
        ("AT END", "NOT AT END"),
        ("INVALID KEY", "NOT INVALID KEY"),
    ])
    def test_longer_keyword_wins(self, short, long):
        segments = split_on_keywords(
            f"F {short} SHORT {long} LONG END", (short, long, "END"))
        by_keyword = dict(segments)
        assert by_keyword[short].strip() == "SHORT", (
            f"{short} captured the wrong span")
        assert by_keyword[long].strip() == "LONG"

    def test_read_branches_are_not_inverted(self, copybook_dir):
        """The historical defect: processing ran only at EOF."""
        model = build(
            copybook_dir,
            "           READ SRC-FILE\n"
            '               AT END MOVE "Y" TO WS-FLAG\n'
            "               NOT AT END MOVE 1 TO WS-RATE\n"
            "           END-READ")
        body = generated(model)
        read_at = body.index(".read(")
        then_brace = body.index("{", read_at)
        else_at = body.index("} else {", read_at)
        success_branch = body[then_brace:else_at]
        eof_branch = body[else_at:]
        assert "Rt.storeValue(ws_rate" in success_branch, (
            "the NOT AT END body must run when the read succeeds")
        assert "ws_flag" not in success_branch, (
            "the AT END body must not run on a successful read")
        assert "ws_flag" in eof_branch, "the AT END body must run at EOF"

    def test_plain_at_end_still_parses(self, copybook_dir):
        model = build(
            copybook_dir,
            "           READ SRC-FILE\n"
            '               AT END MOVE "Y" TO WS-FLAG\n'
            "           END-READ")
        assert jc.generate_java(model, java_package="generic").ok


# ════════════════════════════════════════════════════════════════════════════
# C. EVALUATE SUBJECT SEMANTICS
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixCEvaluateSubjectSemantics:
    """Every WHEN must compare the subject against its value."""

    def _evaluate(self, copybook_dir, whens: str):
        return build(copybook_dir,
                     "           EVALUATE KEY-FLD\n" + whens +
                     "           END-EVALUATE")

    def test_when_compares_subject_to_value(self, copybook_dir):
        model = self._evaluate(copybook_dir,
                               '              WHEN "A" MOVE 1 TO WS-RATE\n')
        body = generated(model)
        offset = emitter_for(model)._resolve("KEY-FLD")[0].offset
        assert f'Rt.getText(rec_a, {offset}, 4), "A"' in body, (
            "the WHEN must compare the EVALUATE subject against the value")

    def test_when_branch_is_never_constant_true(self, copybook_dir):
        """The historical defect: every branch compared a literal to null."""
        model = self._evaluate(copybook_dir,
                               '              WHEN "A" MOVE 1 TO WS-RATE\n')
        assert "null)" not in generated(model), (
            "no branch may compare against null")

    def test_all_whens_produce_distinct_tests(self, copybook_dir):
        model = self._evaluate(
            copybook_dir,
            '              WHEN "A" MOVE 1 TO WS-RATE\n'
            '              WHEN "B" MOVE 2 TO WS-RATE\n'
            '              WHEN "C" MOVE 3 TO WS-RATE\n')
        body = generated(model)
        for literal in ('"A"', '"B"', '"C"'):
            assert f", {literal}) == 0)" in body, f"{literal} branch missing"

    def test_qualified_evaluate_subject_resolves(self, copybook_dir):
        model = build(
            copybook_dir,
            "           EVALUATE KEY-FLD OF REC-A\n"
            '              WHEN "A" MOVE 1 TO WS-RATE\n'
            "           END-EVALUATE")
        assert jc.generate_java(model, java_package="generic").ok


# ════════════════════════════════════════════════════════════════════════════
# D. ACCUMULATING ARITHMETIC VERBS (ADD / SUBTRACT / MULTIPLY / DIVIDE)
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixDAccumulatingArithmeticVerbs:
    """ADD/SUBTRACT/MULTIPLY accumulate; GIVING assigns to a new field."""

    def test_add_is_not_a_plain_store(self, copybook_dir):
        """The historical defect: the receiver was overwritten, not updated."""
        model = build(copybook_dir, "           ADD AMT-FLD TO WS-TOTAL")
        assert "Rt.add(" in generated(model)

    @pytest.mark.parametrize("statement", [
        "ADD AMT-FLD TO WS-TOTAL",
        "SUBTRACT AMT-FLD FROM WS-TOTAL",
        "MULTIPLY AMT-FLD BY WS-TOTAL",
    ])
    def test_accumulating_verb_reads_the_receiver(self, copybook_dir, statement):
        model = build(copybook_dir, f"           {statement}")
        body = generated(model)
        assert "Rt.getPacked(ws_total" in body, (
            f"{statement} must read the existing value of the receiver")

    @pytest.mark.parametrize("statement", [
        "ADD AMT-FLD TO WS-TOTAL GIVING WS-RATE",
        "SUBTRACT AMT-FLD FROM WS-TOTAL GIVING WS-RATE",
        "MULTIPLY AMT-FLD BY WS-TOTAL GIVING WS-RATE",
    ])
    def test_giving_form_does_not_read_the_receiver(self, copybook_dir,
                                                    statement):
        """GIVING computes into a NEW field; it must not accumulate into it."""
        model = build(copybook_dir, f"           {statement}")
        body = generated(model)
        assert "Rt.getPacked(ws_total" not in body, (
            "a GIVING target must not read the receiving field")

    def test_add_to_multiple_receivers(self, copybook_dir):
        model = build(copybook_dir,
                      "           ADD AMT-FLD TO WS-TOTAL WS-RATE")
        assert generated(model).count("Rt.add(") == 2, (
            "each receiver must be updated independently")

    def test_divide_still_divides_by_the_receiver(self, copybook_dir):
        model = build(copybook_dir, "           DIVIDE AMT-FLD INTO WS-TOTAL")
        assert "Rt.divide(" in generated(model)


# ════════════════════════════════════════════════════════════════════════════
# E. ARITHMETIC TAIL CONSUMPTION
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixEArithmeticTailConsumption:
    """No arithmetic operand may ever be silently discarded."""

    @pytest.mark.parametrize("expression", [
        "AMT-FLD - CNT-FLD",
        "AMT-FLD - CNT-FLD - AMT-FLD",
        "AMT-FLD + CNT-FLD * 2 - 1",
        "(AMT-FLD - CNT-FLD) * 2",
        "AMT-FLD OF REC-A - CNT-FLD OF REC-A",
    ])
    def test_every_token_is_consumed(self, copybook_dir, expression):
        model = build(copybook_dir,
                      f"           COMPUTE WS-TOTAL = {expression}")
        emitter = emitter_for(model)
        emitter._arith_expr(expression)
        assert emitter._position == len(emitter._tokens), (
            f"{expression!r} discarded {emitter._tokens[emitter._position:]!r}")

    def test_no_diagnostic_for_valid_arithmetic(self, copybook_dir):
        model = build(copybook_dir,
                      "           COMPUTE WS-TOTAL = AMT-FLD - CNT-FLD")
        emitter = emitter_for(model)
        emitter._arith_expr("AMT-FLD - CNT-FLD")
        assert emitter.unsupported == []

    def test_three_term_subtraction_keeps_every_term(self, copybook_dir):
        model = build(
            copybook_dir,
            "           COMPUTE WS-TOTAL = AMT-FLD - CNT-FLD - KEY-FLD")
        assert generated(model).count("Rt.subtract(") >= 2, (
            "a three-term subtraction lost a term")

    @pytest.mark.parametrize("expression", [
        "AMT-FLD +", "(AMT-FLD - CNT-FLD", "AMT-FLD - CNT-FLD)",
    ])
    def test_malformed_arithmetic_fails_closed(self, copybook_dir, expression):
        """A partial arithmetic result must never be emitted."""
        result = jc.generate_java(
            build(copybook_dir, f"           COMPUTE WS-TOTAL = {expression}"),
            java_package="generic")
        assert not result.ok, f"{expression!r} was silently accepted"
        assert result.files == [], "no partial program may be emitted"
        assert result.unsupported, "a diagnostic must explain the failure"