"""Phase 20 -- qualified COBOL name resolution regression suite.

Every test here locks in a defect that was found by tracing the real
``DAILYPOST`` program, not by guessing at the grammar. The suite exists so the
same class of defect cannot return silently.

The defects it guards against, in the order they were diagnosed:

1. ``TXN-TS OF TXN-IN-REC`` decomposed into ``['TXN-TS', 'OF', 'TXN-IN-REC']``
   by the operand splitter, so ``OF`` reached symbol lookup as a field name.
2. The arithmetic tokenizer split the same qualified names, and the
   recursive-descent parser then *silently dropped* the rest of the expression.
3. A relation built with ``right=None`` was stringified into the literal text
   ``"None"`` and looked up as if it were a COBOL operand.
4. ``EVALUATE`` ignored its subject, making every ``WHEN`` branch compare its
   own literal against ``null`` -- constantly true.
5. ``AT END`` matched inside ``NOT AT END``, inverting the READ branches.
6. ``ADD x TO y`` was emitted as an assignment, discarding ``y``.
7. ``WRITE rec FROM rec`` named a group item the symbol table could not see,
   so a blank record was written.
"""

from __future__ import annotations

import pytest

from autoforge_modernization.service import java_codegen as jc
from autoforge_modernization.service.cobol_ir import is_name_part, join_qualified
from autoforge_modernization.service.cobol_proc import (
    _parse_statement,
    _split_if_body,
    _split_operands,
    parse_condition,
    split_on_keywords,
)
from autoforge_modernization.service.cobol_program import build_program_model

COPYBOOK = """\
       05  ACCT-ID       PIC X(12).
       05  CUST-ID       PIC X(12).
       05  PRODUCT-CODE  PIC X(4).
       05  ACCT-STATUS   PIC X(1).
       05  CURR-BAL      PIC S9(11)V99 COMP-3.
       05  OVERDRAFT-LIMIT PIC S9(9)V99 COMP-3.
       05  TXN-ID        PIC X(16).
       05  ORIG-TXN-ID   PIC X(16).
       05  TXN-CODE      PIC X(4).
       05  TXN-AMOUNT    PIC S9(9)V99 COMP-3.
       05  TXN-TS        PIC 9(14).
       05  CHANNEL       PIC X(4).
"""

SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUALIFIED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TXN-FILE ASSIGN TO "data/txns.dat"
               ORGANIZATION IS SEQUENTIAL.
           SELECT EXC-FILE ASSIGN TO "out/exceptions.dat"
               ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  TXN-FILE RECORD CONTAINS 72 CHARACTERS.
       01  TXN-IN-REC.
           COPY "TXN-REC.cpy".
       FD  EXC-FILE RECORD CONTAINS 72 CHARACTERS.
       01  EXC-REC.
           COPY "TXN-REC.cpy".
       WORKING-STORAGE SECTION.
       77  TODAY      PIC 9(8) VALUE 20250101.
       77  NEW-BAL    PIC S9(11)V99 COMP-3.
       PROCEDURE DIVISION.
       MAIN.
           MOVE TXN-TS OF TXN-IN-REC TO NEW-BAL
           IF TXN-CODE OF TXN-IN-REC = "DEPO"
              ADD TXN-AMOUNT OF TXN-IN-REC
                  TO CURR-BAL OF TXN-IN-REC
           END-IF
           EVALUATE TXN-CODE OF TXN-IN-REC
              WHEN "DEPO"
                 ADD TXN-AMOUNT OF TXN-IN-REC
                     TO CURR-BAL OF TXN-IN-REC
              WHEN "WDRW"
                 COMPUTE NEW-BAL = CURR-BAL OF TXN-IN-REC
                                  - TXN-AMOUNT OF TXN-IN-REC
           END-EVALUATE
           CLOSE TXN-FILE EXC-FILE
           GOBACK.
"""


@pytest.fixture
def copybook_dir(tmp_path):
    """A real on-disk copybook, so COPY resolution is exercised for real."""
    (tmp_path / "TXN-REC.cpy").write_text(COPYBOOK)
    return tmp_path


@pytest.fixture
def qualified_program(copybook_dir):
    return build_program_model(
        SOURCE, source_path="cobol/QUALIFIED.cbl",
        copybook_dirs=[copybook_dir],
    )


def _emitter_for(model) -> jc._Emitter:
    symbols = jc._SymbolTable()
    jc._collect_buffers(model, symbols)
    return jc._Emitter(model, symbols, {})
# ── 1. Simple qualified name ────────────────────────────────────────────────

def test_simple_qualified_name_survives_operand_split():
    assert _split_operands("TXN-TS OF TXN-IN-REC") == ["TXN-TS OF TXN-IN-REC"]


def test_qualified_move_source_is_kept_whole():
    stmts, gaps = _parse_statement("MOVE TXN-TS OF TXN-IN-REC TO WS-TS", 10)
    assert not gaps
    assert stmts[0].attrs["targets"] == ["WS-TS"]
    assert stmts[0].attrs["source"] == "TXN-TS OF TXN-IN-REC"


# ── 2. Nested / qualified references in conditions ──────────────────────────

def test_qualified_names_survive_condition_parsing():
    node = parse_condition(
        "ACCT-ID OF TXN-IN-REC > ACCT-ID OF ACCT-IN-REC", 20).as_dict()
    assert node["left"] == "ACCT-ID OF TXN-IN-REC"
    assert node["right"] == "ACCT-ID OF ACCT-IN-REC"


def test_conjunction_keeps_both_qualified_operands():
    node = parse_condition(
        'EOF-TXN = "Y" OR ACCT-ID OF TXN-IN-REC > ACCT-ID OF ACCT-IN-REC', 21
    ).as_dict()
    assert node["op"] == "OR"
    assert node["right"]["left"] == "ACCT-ID OF TXN-IN-REC"
    assert node["right"]["right"] == "ACCT-ID OF ACCT-IN-REC"


# ── 3. Qualified MOVE target ───────────────────────────────────────────────

def test_qualified_move_target_reaches_the_store():
    stmts, _ = _parse_statement(
        "MOVE NEW-BAL TO CURR-BAL OF ACCT-IN-REC", 30)
    assert stmts[0].attrs["targets"] == ["CURR-BAL OF ACCT-IN-REC"]


# ── 4. Qualified operands inside EVALUATE ───────────────────────────────────

def test_evaluate_keeps_qualified_subject():
    stmts, _ = _parse_statement(
        'EVALUATE TXN-CODE OF TXN-IN-REC WHEN "DEPO" '
        "ADD TXN-AMOUNT OF TXN-IN-REC TO CURR-BAL OF TXN-IN-REC "
        "END-EVALUATE", 40)
    attrs = stmts[0].attrs
    assert attrs["subject_text"] == "TXN-CODE OF TXN-IN-REC"
    body = attrs["whens"][0]["body"]
    assert body[0]["attrs"]["operands"] == ["TXN-AMOUNT OF TXN-IN-REC"]
    assert body[0]["attrs"]["receivers"] == ["CURR-BAL OF TXN-IN-REC"]


def test_evaluate_branch_tests_the_subject_not_the_literal(qualified_program):
    """Regression: every WHEN branch used to be constantly true.

    The WHEN text is a *value*; the branch must compare the EVALUATE subject
    against it. Comparing the literal with ``null`` was always true.
    """
    body = _generated_body(qualified_program)
    emitter = _emitter_for(qualified_program)
    subject = emitter._resolve("TXN-CODE OF TXN-IN-REC")[0]
    expected = (
        f'Rt.compareText(Rt.getText(txn_in_rec, {subject.offset}, 4), "DEPO")')
    assert expected in body, (
        "the WHEN branch must compare the EVALUATE subject against the value")
    assert 'compareText("DEPO", null)' not in body
    assert "null) == 0" not in body


# ── 5. Qualified operands inside IF ─────────────────────────────────────────

def test_qualified_if_condition_is_parsed_as_a_relation():
    stmts, _ = _parse_statement(
        'IF TXN-CODE OF TXN-IN-REC = "DEPO" '
        "ADD TXN-AMOUNT OF TXN-IN-REC TO CURR-BAL OF TXN-IN-REC END-IF", 50)
    attrs = stmts[0].attrs
    assert attrs["condition"]["left"] == "TXN-CODE OF TXN-IN-REC"
    assert attrs["condition"]["right"] == '"DEPO"'
    assert attrs["then"][0]["attrs"]["operands"] == ["TXN-AMOUNT OF TXN-IN-REC"]
# ── 6. Qualified operands inside arithmetic ─────────────────────────────────

def test_arithmetic_keeps_both_qualified_operands():
    stmts, _ = _parse_statement(
        "COMPUTE NEW-BAL = CURR-BAL OF ACCT-IN-REC - TXN-AMOUNT OF TXN-IN-REC",
        60)
    assert stmts[0].attrs["expression"] == (
        "CURR-BAL OF ACCT-IN-REC - TXN-AMOUNT OF TXN-IN-REC")


def test_arithmetic_tokenizer_does_not_drop_the_tail():
    """The whole expression must reduce to exactly three tokens."""
    emitter = jc._Emitter.__new__(jc._Emitter)
    tokens = emitter._arith_tokens(
        "CURR-BAL OF ACCT-IN-REC - TXN-AMOUNT OF TXN-IN-REC")
    assert tokens == [
        "CURR-BAL OF ACCT-IN-REC", "-", "TXN-AMOUNT OF TXN-IN-REC"]


def test_arithmetic_consumes_every_token(qualified_program):
    """Regression: leftover tokens were silently discarded."""
    emitter = _emitter_for(qualified_program)
    emitter._arith_expr("CURR-BAL OF TXN-IN-REC - TXN-AMOUNT OF TXN-IN-REC")
    assert emitter._position == len(emitter._tokens), (
        "arithmetic parser left tokens unconsumed")


# ── 7. Hyphenated field names ──────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "TXN-TS", "CURR-BAL", "OVERDRAFT-LIMIT", "ACCT-ID", "WS-NEG-LIMIT",
])
def test_hyphenated_names_are_never_split(name):
    assert _split_operands(name) == [name]


def test_hyphenated_qualified_name_stays_whole():
    assert _split_operands("OVERDRAFT-LIMIT OF ACCT-IN-REC") == [
        "OVERDRAFT-LIMIT OF ACCT-IN-REC"]


# ── 8. Invalid qualified names fail closed ──────────────────────────────────

def test_unresolvable_qualified_operand_fails_closed(copybook_dir):
    """A qualified name whose field does not exist must be reported."""
    source = SOURCE.replace(
        "TXN-CODE OF TXN-IN-REC", "NO-SUCH-FIELD OF TXN-IN-REC")
    model = build_program_model(
        source, source_path="cobol/QUALIFIED.cbl", copybook_dirs=[copybook_dir])
    result = jc.generate_java(model, java_package="modernized")
    assert not result.ok, "an unresolvable operand must not be accepted"
    assert result.files == [], "no partial output may be produced"
    assert result.unsupported, "a diagnostic must name the failure"


def test_unresolvable_move_target_fails_closed(copybook_dir):
    source = SOURCE.replace("TO NEW-BAL", "TO NO-SUCH-FIELD OF TXN-IN-REC")
    model = build_program_model(
        source, source_path="cobol/QUALIFIED.cbl", copybook_dirs=[copybook_dir])
    result = jc.generate_java(model, java_package="modernized")
    assert not result.ok
    assert any("NO-SUCH-FIELD" in item for item in result.unsupported), (
        result.unsupported)


# ── 9. None operands are rejected ───────────────────────────────────────────

def test_none_is_never_accepted_as_an_operand():
    assert jc._Emitter._operand(None) is None


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_or_absent_operands_become_none(value):
    assert jc._Emitter._operand(value) is None


def test_relation_with_a_none_operand_fails_closed(qualified_program):
    """The exact defect that produced `unresolved operand: None`."""
    emitter = _emitter_for(qualified_program)
    emitter._relation({"op": "=", "left": "TXN-ID", "right": None}, "=")
    assert emitter.unsupported, "a None operand must produce a diagnostic"
    assert "missing operand" in emitter.unsupported[0]


def test_the_literal_text_none_is_not_a_silent_operand(qualified_program):
    """`str(None)` must never masquerade as a field name."""
    emitter = _emitter_for(qualified_program)
    emitter.value_expr("None")
    assert emitter.unsupported, "'None' must not resolve to a symbol"

# ── 10. Existing unqualified names keep working ─────────────────────────────

@pytest.mark.parametrize("statement,operand", [
    ("MOVE WS-TS TO WS-TS-DATE", "WS-TS"),
    ("ADD TXN-AMOUNT TO CURR-BAL", "TXN-AMOUNT"),
    ("MOVE 1 TO EOF-ACCT", "EOF-ACCT"),
])
def test_unqualified_names_still_parse(statement, operand):
    stmts, gaps = _parse_statement(statement, 70)
    assert not gaps
    assert operand in str(stmts[0].attrs)


def test_unqualified_program_still_generates(copybook_dir):
    """A program with no qualified names at all must keep working."""
    source = SOURCE.replace("TXN-CODE OF TXN-IN-REC", "TXN-CODE")
    source = source.replace("TXN-AMOUNT OF TXN-IN-REC", "TXN-AMOUNT")
    source = source.replace("CURR-BAL OF TXN-IN-REC", "CURR-BAL")
    source = source.replace("TXN-TS OF TXN-IN-REC", "TXN-TS")
    model = build_program_model(
        source, source_path="cobol/QUALIFIED.cbl", copybook_dirs=[copybook_dir])
    result = jc.generate_java(model, java_package="modernized")
    assert result.ok, result.unsupported
    assert result.files


# ── Structure regressions found while tracing DAILYPOST ────────────────────

def test_add_to_is_accumulating_not_assigning(qualified_program):
    """`ADD x TO y` must add to the existing value of y."""
    body = _generated_body(qualified_program)
    assert "Rt.add(Rt.getPacked(" in body, (
        "ADD x TO y must compile to an accumulating add, not a plain store")


def test_not_at_end_is_not_matched_as_at_end():
    """`AT END` must not match inside `NOT AT END`."""
    segments = split_on_keywords(
        'ACCT-FILE AT END MOVE "Y" TO EOF NOT AT END MOVE "Z" TO WS END-READ',
        ("AT END", "NOT AT END", "INVALID KEY", "END-READ"),
    )
    by_keyword = dict(segments)
    assert by_keyword["AT END"].strip() == 'MOVE "Y" TO EOF'
    assert by_keyword["NOT AT END"].strip() == 'MOVE "Z" TO WS'


def test_if_else_body_does_not_lose_its_tail():
    """A nested IF inside an ELSE must not swallow the statements after it.

    This is the exact shape DAILYPOST uses: an ELSE arm containing a nested
    IF ... END-IF followed by more statements. Scanning from depth 0 made the
    inner END-IF terminate the scan and silently drop the trailing PERFORM,
    which turned the generated program into an infinite loop.
    """
    body = (" MOVE 1 TO WS-TS "
            "ELSE "
            "MOVE 2 TO WS-TS-DATE "
            "IF WS-TS-DATE = TODAY MOVE 3 TO WS-FLAG END-IF "
            "PERFORM READ-NEXT-TXN")
    then_text, else_text = _split_if_body(body)
    assert then_text.strip() == "MOVE 1 TO WS-TS"
    assert "PERFORM READ-NEXT-TXN" in else_text, (
        "the statement after a nested IF must survive the ELSE split")
    assert "IF WS-TS-DATE = TODAY" in else_text


def test_execute_invokes_the_first_paragraph(qualified_program):
    """A program whose first paragraph is labelled still has to run."""
    body = _generated_body(qualified_program)
    assert "public void execute()" in body
    execute_body = body.split("public void execute()", 1)[1]
    assert "main();" in execute_body, (
        "execute() must call the entry paragraph, not be empty")


def test_write_from_a_group_item_copies_the_record(qualified_program):
    """`WRITE r FROM r` names group items, not leaf fields."""
    emitter = _emitter_for(qualified_program)
    assert emitter._group_holder("TXN-IN-REC") == "txn_in_rec"
    lines = emitter._emit_write(
        {"record": "EXC-REC", "from": "TXN-IN-REC"}, "        ")
    assert any("copyRecord(exc_rec, txn_in_rec)" in line for line in lines), lines


# ── The qualification boundary itself ───────────────────────────────────────

def test_qualified_chain_is_rejoined():
    assert join_qualified(["A", "OF", "B", "OF", "C"]) == ["A OF B OF C"]


def test_subscripted_and_reference_modified_levels_are_supported():
    assert join_qualified(["A(3)", "OF", "B(1:8)"]) == ["A(3) OF B(1:8)"]


def test_of_between_literals_and_numbers_is_not_qualification():
    """Qualification needs an identifier level on *both* sides of `OF`.

    A quoted literal or a numeric literal can never be a data name, so `OF`
    beside one is prose and must survive untouched.
    """
    assert join_qualified(["20250101", "OF", "PAGE"]) == [
        "20250101", "OF", "PAGE"]
    assert join_qualified(["'DEPO'", "OF", "FIELD"]) == [
        "'DEPO'", "OF", "FIELD"]
    assert join_qualified(["'A OF B'", "TO", "X"]) == ["'A OF B'", "TO", "X"]


def test_joined_operands_must_still_resolve_or_fail_closed(qualified_program):
    """Joining `A OF B` is safe precisely because resolution is checked.

    Any operand that survives the join but names no real field is reported as
    an unsupported construct, and no files are emitted. That is what stops an
    over-eager join from turning into a silently wrong program.
    """
    result = jc.generate_java(qualified_program, java_package="modernized")
    assert result.ok, result.unsupported
    # Every operand the generator emits must be a real symbol, a literal or a
    # figurative constant -- never a bare `OF`.
    emitter = _emitter_for(qualified_program)
    for candidate in ("TXN-CODE OF TXN-IN-REC", "TXN-AMOUNT OF TXN-IN-REC",
                      "CURR-BAL OF TXN-IN-REC", "TXN-TS OF TXN-IN-REC"):
        emitter.value_expr(candidate)
    assert not emitter.unsupported, emitter.unsupported


def test_of_after_a_literal_is_not_qualification():
    assert join_qualified(["'START OF EXECUTION'", "OF", "FIELD"]) == [
        "'START OF EXECUTION'", "OF", "FIELD"]


@pytest.mark.parametrize("token,expected", [
    ("TXN-TS", True),
    ("A(3)", True),
    ("B(1:8)", True),
    ("20250101", False),
    ('"DEPO"', False),
    ("", False),
])
def test_name_part_recognises_only_identifier_shapes(token, expected):
    assert is_name_part(token) is expected


def test_literal_containing_of_is_never_joined():
    assert _split_operands("'START OF EXECUTION'") == ["'START OF EXECUTION'"]

def _generated_body(model) -> str:
    """The generated program body, without the runtime."""
    result = jc.generate_java(model, java_package="modernized")
    assert result.ok, result.unsupported
    return "\n".join(
        f.content for f in result.files if "CobolRuntime" not in f.path)