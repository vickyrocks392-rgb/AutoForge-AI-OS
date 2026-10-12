"""Phase 20 -- permanent 10-defect regression matrix, categories F-J.

Companion to ``test_phase20_defect_matrix.py`` (categories A-E). Same rule: a
regression must name the *class* that broke.

Matrix: F group WRITE ... FROM | G labelled first paragraph / entry point
| H generated-Java compilation and exception handling
| I None/missing operand fail-closed | J qualified-name joining.

Every program is generic (invented names, no fixture, no expected bytes).
"""

from __future__ import annotations

import pytest

from autoforge_modernization.service import java_codegen as jc
from autoforge_modernization.service.cobol_ir import is_name_part, join_qualified
from autoforge_modernization.service.cobol_program import build_program_model
from autoforge_modernization.service.cobol_proc import _split_operands

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


def build(tmp_path, body: str, paragraphs: str = ""):
    source = PREAMBLE + body + "\n" + paragraphs + "           GOBACK.\n"
    return build_program_model(
        source, source_path="cobol/GENERIC.cbl", copybook_dirs=[tmp_path])


def emitter_for(model) -> jc._Emitter:
    symbols = jc._SymbolTable()
    jc._collect_buffers(model, symbols)
    return jc._Emitter(model, symbols,
                       {n: jc.java_safe(n) for n in sorted(model.files)})


def generated(model) -> str:
    result = jc.generate_java(model, java_package="generic")
    assert result.ok, result.unsupported
    return "\n".join(f.content for f in result.files
                     if "CobolRuntime" not in f.path)


# ════════════════════════════════════════════════════════════════════════════
# F. GROUP WRITE ... FROM
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixFGroupWriteFrom:
    """A named WRITE source must resolve; a blank record is never acceptable."""

    def test_group_source_copies_the_whole_record(self, copybook_dir):
        model = build(copybook_dir, "           WRITE REC-B FROM REC-A")
        assert "Rt.copyRecord(rec_b, rec_a);" in generated(model)

    def test_leaf_source_copies_the_field(self, copybook_dir):
        model = build(copybook_dir, "           WRITE REC-B FROM AMT-FLD")
        assert "Rt.moveText(" in generated(model)

    def test_self_write_needs_no_copy(self, copybook_dir):
        model = build(copybook_dir, "           WRITE REC-B FROM REC-B")
        body = generated(model)
        assert "copyRecord" not in body
        assert ".write(rec_b);" in body

    def test_unresolved_source_emits_no_record(self, copybook_dir):
        """The dangerous outcome is a blank record; prove it cannot happen."""
        emitter = emitter_for(build(
            copybook_dir, "           WRITE REC-B FROM NO-SUCH-GROUP"))
        lines = emitter._emit_write(
            {"record": "REC-B", "from": "NO-SUCH-GROUP"}, "        ")
        assert lines == [], f"no code may be emitted, got {lines}"
        assert not any(".write(" in line for line in lines), (
            "a WRITE must never be emitted without its source")

    def test_unresolved_source_fails_the_whole_program(self, copybook_dir):
        result = jc.generate_java(
            build(copybook_dir, "           WRITE REC-B FROM NO-SUCH-GROUP"),
            java_package="generic")
        assert not result.ok
        assert result.files == []
        assert any("unresolved WRITE source" in item
                   for item in result.unsupported)
# ════════════════════════════════════════════════════════════════════════════
# G. LABELLED FIRST PARAGRAPH / ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixGEntryPoint:
    """A labelled first paragraph must still be executed."""

    def test_labelled_first_paragraph_is_invoked(self, copybook_dir):
        model = build(copybook_dir, "           MOVE 1 TO WS-RATE",
                      paragraphs="       SECOND-PARA.\n")
        execute_body = generated(model).split("public void execute()", 1)[1]
        assert "first_para();" in execute_body, (
            "execute() must invoke the entry paragraph")

    def test_implicit_main_line_is_unaffected(self):
        """A program with no paragraph label keeps its implicit main line."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMPLICIT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       77  WS-FLAG PIC X VALUE "N".
       PROCEDURE DIVISION.
           MOVE "Y" TO WS-FLAG
           GOBACK.
"""
        result = jc.generate_java(
            build_program_model(source, source_path="cobol/I.cbl",
                                copybook_dirs=[]),
            java_package="generic")
        body = "\n".join(f.content for f in result.files
                         if "CobolRuntime" not in f.path)
        execute_body = body.split("public void execute()", 1)[1]
        assert "ws_flag" in execute_body, (
            "an implicit main line must execute directly")
        assert "first_para();" not in execute_body

    def test_execute_is_never_empty(self, copybook_dir):
        body = generated(build(copybook_dir, "           MOVE 1 TO WS-RATE"))
        execute_body = body.split("public void execute()", 1)[1]
        execute_body = execute_body.split("public static void main", 1)[0]
        assert "no translatable statements" not in execute_body, (
            "an empty execute() means the program does nothing")


# ════════════════════════════════════════════════════════════════════════════
# H. GENERATED JAVA COMPILES AND HANDLES CHECKED EXCEPTIONS
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixHGeneratedJavaIsCompilable:
    """The generated source must satisfy the Java compiler's contracts."""

    def test_io_paragraphs_declare_the_checked_exception(self, copybook_dir):
        """OPEN/WRITE/CLOSE throw IOException; paragraphs must declare it."""
        model = build(
            copybook_dir,
            "           OPEN INPUT SRC-FILE\n"
            "           READ SRC-FILE\n"
            "               AT END CONTINUE\n"
            "           END-READ\n"
            "           WRITE REC-B FROM REC-A\n"
            "           CLOSE SRC-FILE DST-FILE")
        for line in generated(model).splitlines():
            stripped = line.strip()
            if stripped.startswith("private void ") and "(" in stripped:
                assert stripped.endswith(") throws IOException {"), (
                    f"I/O paragraph lacks the checked exception: {stripped}")

    def test_runtime_is_referenced_through_its_instance(self, copybook_dir):
        """The runtime keeps a private constructor; generated code must not
        call `new CobolRuntime()`."""
        body = generated(build(copybook_dir, "           MOVE 1 TO WS-RATE"))
        assert "CobolRuntime.INSTANCE" in body
        assert "new CobolRuntime()" not in body

    def test_io_import_is_present(self, copybook_dir):
        model = build(copybook_dir, "           WRITE REC-B FROM REC-A")
        assert "import java.io.IOException;" in generated(model)

    def test_braces_balance(self, copybook_dir):
        body = generated(build(copybook_dir, "           MOVE 1 TO WS-RATE"))
        assert body.count("{") == body.count("}"), "unbalanced braces"


# ════════════════════════════════════════════════════════════════════════════
# I. NONE / MISSING OPERAND FAILS CLOSED
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixINoneOperandFailsClosed:
    """Python None must never masquerade as a COBOL operand."""

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absent_operand_becomes_none(self, value):
        assert jc._Emitter._operand(value) is None

    def test_relation_with_none_right_operand_is_reported(self, copybook_dir):
        emitter = emitter_for(build(copybook_dir, "           MOVE 1 TO WS-RATE"))
        emitter._relation({"op": "=", "left": "KEY-FLD", "right": None}, "=")
        assert emitter.unsupported, "a None operand must be reported"
        assert "missing operand" in emitter.unsupported[0]

    def test_relation_with_none_left_operand_is_reported(self, copybook_dir):
        emitter = emitter_for(build(copybook_dir, "           MOVE 1 TO WS-RATE"))
        emitter._relation({"op": "=", "left": None, "right": "KEY-FLD"}, "=")
        assert emitter.unsupported

    def test_the_text_none_is_not_a_field(self, copybook_dir):
        """`str(None)` must never become the operand text "None"."""
        emitter = emitter_for(build(copybook_dir, "           MOVE 1 TO WS-RATE"))
        emitter.value_expr("None")
        assert emitter.unsupported, "'None' must not resolve to a symbol"

    def test_unresolved_move_target_is_reported(self, copybook_dir):
        result = jc.generate_java(
            build(copybook_dir, "           MOVE 1 TO NO-SUCH-FIELD"),
            java_package="generic")
        assert not result.ok
        assert result.files == []

    def test_unresolvable_perform_target_is_reported(self, copybook_dir):
        result = jc.generate_java(
            build(copybook_dir, "           PERFORM NO-SUCH-PARA"),
            java_package="generic")
        assert not result.ok
        assert result.files == []


# ════════════════════════════════════════════════════════════════════════════
# J. QUALIFIED-NAME JOINING
# ════════════════════════════════════════════════════════════════════════════

class TestMatrixJQualifiedNames:
    """Qualified data names must survive tokenization and reach resolution."""

    @pytest.mark.parametrize("text,expected", [
        ("KEY-FLD OF REC-A", ["KEY-FLD OF REC-A"]),
        ("A OF B OF C", ["A OF B OF C"]),
        ("A(1) OF B", ["A(1) OF B"]),
        ("A(1:8) OF B", ["A(1:8) OF B"]),
        ("TBL(I) OF GRP OF REC", ["TBL(I) OF GRP OF REC"]),
        ("'LIT OF X'", ["'LIT OF X'"]),
        ("20250101", ["20250101"]),
        ("A OF B, C OF D", ["A OF B", "C OF D"]),
    ])
    def test_operand_splitting_preserves_qualification(self, text, expected):
        assert _split_operands(text) == expected

    @pytest.mark.parametrize("tokens,expected", [
        (["A", "OF", "B"], ["A OF B"]),
        (["A", "OF", "B", "OF", "C"], ["A OF B OF C"]),
        (["20250101", "OF", "PAGE"], ["20250101", "OF", "PAGE"]),
        (["'DEPO'", "OF", "FIELD"], ["'DEPO'", "OF", "FIELD"]),
    ])
    def test_join_qualified_is_conservative(self, tokens, expected):
        assert join_qualified(tokens) == expected

    @pytest.mark.parametrize("token,expected", [
        ("TXN-TS", True), ("A(3)", True), ("B(1:8)", True),
        ("20250101", False), ('"DEPO"', False), ("", False),
    ])
    def test_only_identifier_shapes_are_name_parts(self, token, expected):
        assert is_name_part(token) is expected

    def test_qualified_name_resolves_to_a_real_symbol(self, copybook_dir):
        emitter = emitter_for(build(copybook_dir, "           MOVE 1 TO WS-RATE"))
        symbol, _, _ = emitter._resolve("AMT-FLD OF REC-A")
        assert symbol is not None
        assert symbol.owner == "REC-A"

    def test_unresolvable_qualified_name_fails_closed(self, copybook_dir):
        result = jc.generate_java(
            build(copybook_dir, "           MOVE 1 TO NO-SUCH-FIELD OF REC-A"),
            java_package="generic")
        assert not result.ok
        assert result.files == []

    def test_hyphenated_names_are_never_split(self):
        for name in ("TXN-TS", "CURR-BAL", "OVERDRAFT-LIMIT", "ACCT-ID"):
            assert _split_operands(name) == [name]
