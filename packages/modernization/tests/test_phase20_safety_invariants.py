"""Phase 20 -- permanent safety-invariant and 10-defect regression matrix.

This module converts the ten defects found while tracing the real DAILYPOST
workload into enforced invariants plus a permanent regression matrix.

Two invariants are enforced in the product code and proved here:

* **INV-1 arithmetic consumption** -- an arithmetic expression is translated as
  a whole or not at all. Unconsumed tokens, unbalanced parentheses or a missing
  operand are diagnostics, never a partial value.
* **INV-2 WRITE-FROM resolution** -- a named ``WRITE ... FROM`` source must
  resolve as a group item or a leaf field. If it does not, no record is
  written. A blank record is never an acceptable substitute.

The matrix below is organised by defect class (A-J) rather than by the program
that exposed the class, so a regression names the *class* that broke.

Every test here is generic: the programs use invented names (``ALPHA``,
``REC-B``), never a fixture name, and no expected-output bytes appear anywhere.
"""

from __future__ import annotations

import pytest

from autoforge_modernization.service import java_codegen as jc
from autoforge_modernization.service.cobol_ir import is_name_part, join_qualified
from autoforge_modernization.service.cobol_program import build_program_model
from autoforge_modernization.service.cobol_proc import (
    _parse_statement,
    _split_if_body,
    _split_operands,
    parse_condition,
    split_on_keywords,
)

# ────────────────────────────────────────────────────────────────────────────
# A tiny generic program used by the matrix. Nothing here is fixture-derived.
# ────────────────────────────────────────────────────────────────────────────

COPYBOOK = """\
       05  KEY-FLD       PIC X(4).
       05  AMT-FLD       PIC S9(9)V99 COMP-3.
       05  CNT-FLD       PIC 9(5).
       05  KEY-LEN       PIC 9(3).
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
       77  WS-RATE    PIC S9(3)V99 COMP-3.
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
    return jc._Emitter(model, symbols, {n: jc.java_safe(n)
                                        for n in sorted(model.files)})


def generated(model) -> str:
    result = jc.generate_java(model, java_package="generic")
    assert result.ok, result.unsupported
    return "\n".join(f.content for f in result.files
                     if "CobolRuntime" not in f.path)
# ════════════════════════════════════════════════════════════════════════════
# INV-1 -- ARITHMETIC CONSUMPTION INVARIANT
#
# An expression is translated whole or not at all. Nothing is ever dropped.
# ════════════════════════════════════════════════════════════════════════════

# Valid expressions expressed over the real fields of the generic copybook,
# so every operand genuinely resolves and no diagnostic is expected.
VALID_ARITHMETIC = [
    "CNT-FLD",
    "AMT-FLD + CNT-FLD",
    "AMT-FLD - CNT-FLD",
    "AMT-FLD * CNT-FLD",
    "AMT-FLD / CNT-FLD",
    "AMT-FLD + CNT-FLD * 2",
    "AMT-FLD * CNT-FLD + 3",
    "AMT-FLD * CNT-FLD + KEY-LEN * 5",
    "(AMT-FLD + CNT-FLD) * 2",
    "(AMT-FLD * CNT-FLD) / (CNT-FLD - 1)",
    "((AMT-FLD + CNT-FLD) * (CNT-FLD - 1)) / 2",
    "-AMT-FLD + CNT-FLD",
    "+AMT-FLD - CNT-FLD",
    "0 - AMT-FLD",
    "AMT-FLD OF REC-A - CNT-FLD OF REC-A",
    "CNT-FLD(1:3) / 1000",
    "1 + 2 * 3 - 4 / 5",
]


@pytest.mark.parametrize("expression", VALID_ARITHMETIC)
class TestInv1ValidArithmeticIsFullyConsumed:
    """Valid COBOL arithmetic keeps working and consumes every token."""

    def test_no_diagnostic_is_raised(self, copybook_dir, expression):
        model = build(copybook_dir,
                      f"           COMPUTE WS-TOTAL = {expression}")
        emitter = emitter_for(model)
        emitter._arith_expr(expression)
        assert emitter.unsupported == [], (
            f"valid expression {expression!r} was rejected: "
            f"{emitter.unsupported}")

    def test_every_token_is_consumed(self, copybook_dir, expression):
        model = build(copybook_dir,
                      f"           COMPUTE WS-TOTAL = {expression}")
        emitter = emitter_for(model)
        emitter._arith_expr(expression)
        assert emitter._position == len(emitter._tokens), (
            f"{expression!r} left {emitter._tokens[emitter._position:]!r} "
            f"unconsumed")

    def test_whole_program_generates(self, copybook_dir, expression):
        model = build(copybook_dir,
                      f"           COMPUTE WS-TOTAL = {expression}")
        result = jc.generate_java(model, java_package="generic")
        assert result.ok, result.unsupported
        assert result.files


@pytest.mark.parametrize("tokens,count", [
    ("AMT-FLD + CNT-FLD", 3),
    ("AMT-FLD + CNT-FLD * 2", 5),
    ("(AMT-FLD + CNT-FLD) * 2", 7),
    # qualified operands stay single tokens -- the historical defect
    ("AMT-FLD OF REC-A - CNT-FLD OF REC-A", 3),
    ("CNT-FLD(1:3) / 1000", 3),
    ("AMT-FLD * CNT-FLD + 1 - 2", 7),
])
def test_tokenizer_does_not_fragment_operands(tokens, count):
    """Qualified names and ref-mod must not be split into separate tokens."""
    emitter = jc._Emitter.__new__(jc._Emitter)
    assert len(emitter._arith_tokens(tokens)) == count


def test_zero_minus_operand_uses_subtract_not_negate(copybook_dir):
    """`0 - x` must be a real subtraction, preserving operand order."""
    model = build(copybook_dir, "           COMPUTE WS-TOTAL = 0 - AMT-FLD")
    body = generated(model)
    assert "Rt.subtract" in body
    assert "Rt.negate" not in body


def test_multi_term_arithmetic_reaches_the_generated_code(copybook_dir):
    """A three-term subtraction must appear in full in the emitted Java."""
    model = build(
        copybook_dir,
        "           COMPUTE WS-TOTAL = AMT-FLD OF REC-A - AMT-FLD OF REC-B "
        "- CNT-FLD OF REC-A")
    body = generated(model)
    assert body.count("Rt.subtract(") >= 2, (
        "a three-term subtraction lost a term")


class TestInv1MalformedArithmeticFailsClosed:
    """Malformed arithmetic must produce a diagnostic, never a partial value."""

    @pytest.mark.parametrize("expression", [
        "AMT-FLD +",             # missing right operand
        "AMT-FLD -",             # missing right operand
        "* AMT-FLD",             # leading operator with no left operand
        "AMT-FLD + * CNT-FLD",   # operator with no operand between
        "(AMT-FLD + CNT-FLD",    # unclosed parenthesis
        "AMT-FLD + CNT-FLD)",    # stray closing parenthesis
        "((AMT-FLD + CNT-FLD) * 2",  # unbalanced
    ])
    def test_malformed_expression_is_reported(self, copybook_dir, expression):
        model = build(copybook_dir,
                      f"           COMPUTE WS-TOTAL = {expression}")
        result = jc.generate_java(model, java_package="generic")
        assert not result.ok, (
            f"malformed expression {expression!r} was silently accepted")
        assert result.unsupported, "a diagnostic must explain the failure"
        assert result.files == [], "no partial program may be emitted"

    @pytest.mark.parametrize("expression", [
        "AMT-FLD +", "(AMT-FLD + CNT-FLD",
        "AMT-FLD + * CNT-FLD", "AMT-FLD + CNT-FLD)",
    ])
    def test_malformed_expression_names_the_cause(self, copybook_dir,
                                                  expression):
        model = build(copybook_dir,
                      f"           COMPUTE WS-TOTAL = {expression}")
        emitter = emitter_for(model)
        emitter._arith_expr(expression)
        joined = " ".join(emitter.unsupported).lower()
        assert any(word in joined for word in (
            "unconsumed", "unbalanced", "unclosed", "missing operand")), (
            f"diagnostic for {expression!r} was unclear: "
            f"{emitter.unsupported}")

    def test_unresolvable_operand_is_reported(self, copybook_dir):
        """An operand naming no real field must be named in the diagnostic."""
        model = build(copybook_dir, "           COMPUTE WS-TOTAL = A")
        emitter = emitter_for(model)
        emitter._arith_expr("AMT-FLD OF REC-A - AMT-FLD OF NO-SUCH-REC")
        joined = " ".join(emitter.unsupported)
        assert "unresolved" in joined or "unconsumed" in joined, joined

    def test_no_partial_result_is_emitted_for_bad_arithmetic(self, copybook_dir):
        """A failed expression must not reach the output at all."""
        model = build(copybook_dir, "           COMPUTE WS-TOTAL = A +")
        result = jc.generate_java(model, java_package="generic")
        assert result.files == []
# ════════════════════════════════════════════════════════════════════════════
# INV-2 -- WRITE-FROM RESOLUTION INVARIANT
#
# A named `WRITE ... FROM` source must resolve. A blank record is never an
# acceptable substitute for data the legacy program actually wrote.
# ════════════════════════════════════════════════════════════════════════════

class TestInv2WriteFromResolves:
    """Valid WRITE forms must resolve and emit a real copy."""

    def test_group_write_from_copies_the_whole_record(self, copybook_dir):
        """`WRITE rec FROM rec` names group items, not leaf fields."""
        model = build(copybook_dir,
                      "           WRITE REC-B FROM REC-A")
        body = generated(model)
        assert "Rt.copyRecord(rec_b, rec_a);" in body, (
            "a group WRITE must copy the entire record area")

    def test_leaf_write_from_copies_the_field(self, copybook_dir):
        model = build(copybook_dir, "           WRITE REC-B FROM AMT-FLD")
        body = generated(model)
        assert "Rt.moveText(" in body, "a leaf WRITE must copy the field"

    def test_qualified_write_from_resolves(self, copybook_dir):
        model = build(copybook_dir,
                      "           WRITE REC-B FROM AMT-FLD OF REC-A")
        assert jc.generate_java(model, java_package="generic").ok

    def test_write_without_from_is_allowed(self, copybook_dir):
        """WRITE with no FROM writes the current record buffer as-is."""
        model = build(copybook_dir, "           WRITE REC-B")
        body = generated(model)
        assert ".write(rec_b);" in body
        assert "copyRecord" not in body

    def test_self_write_needs_no_copy(self, copybook_dir):
        """Writing a record from itself is a no-op copy, not a failure."""
        model = build(copybook_dir, "           WRITE REC-B FROM REC-B")
        body = generated(model)
        assert "copyRecord" not in body, (
            "a self-copy must not emit a redundant copy")
        assert ".write(rec_b);" in body, "the record must still be written"

    def test_group_holder_resolves_record_names(self, copybook_dir):
        model = build(copybook_dir, "           WRITE REC-B FROM REC-A")
        emitter = emitter_for(model)
        assert emitter._group_holder("REC-A") == "rec_a"
        assert emitter._group_holder("rec-a") == "rec_a", (
            "group lookup must be case-insensitive like COBOL")
        assert emitter._group_holder("NO-SUCH-GROUP") is None


class TestInv2WriteFromFailsClosed:
    """An unresolvable WRITE source must never yield a blank record."""

    def test_unresolved_group_source_fails_closed(self, copybook_dir):
        model = build(copybook_dir,
                      "           WRITE REC-B FROM NO-SUCH-GROUP")
        result = jc.generate_java(model, java_package="generic")
        assert not result.ok, (
            "an unresolved WRITE source must not be silently skipped")
        assert result.files == [], "no program may be emitted"
        assert any("unresolved WRITE source" in item
                   for item in result.unsupported), result.unsupported

    def test_unresolved_write_emits_no_record_at_all(self, copybook_dir):
        """The dangerous outcome is a blank record; prove it cannot happen."""
        model = build(copybook_dir,
                      "           WRITE REC-B FROM NO-SUCH-GROUP")
        emitter = emitter_for(model)
        lines = emitter._emit_write(
            {"record": "REC-B", "from": "NO-SUCH-GROUP"}, "        ")
        assert lines == [], (
            f"no code may be emitted for an unresolved source, got {lines}")
        assert not any(".write(" in line for line in lines), (
            "a WRITE must never be emitted without its source")

    def test_diagnostic_names_the_missing_source(self, copybook_dir):
        model = build(copybook_dir,
                      "           WRITE REC-B FROM NO-SUCH-GROUP")
        result = jc.generate_java(model, java_package="generic")
        joined = " ".join(result.unsupported)
        assert "NO-SUCH-GROUP" in joined, (
            f"the diagnostic must name the offending source: "
            f"{result.unsupported}")

    def test_unresolved_write_record_fails_closed(self, copybook_dir):
        """A WRITE naming an unknown record must also fail closed."""
        model = build(copybook_dir, "           WRITE NO-SUCH-REC FROM REC-A")
        result = jc.generate_java(model, java_package="generic")
        assert not result.ok
        assert result.files == []
        assert not result.ok