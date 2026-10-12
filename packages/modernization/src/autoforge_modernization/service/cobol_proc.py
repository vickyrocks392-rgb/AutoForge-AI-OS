"""PROCEDURE DIVISION parser for the Phase 20 COBOL modernization scope.

Turns real COBOL procedure text into a statement AST that a code generator can
translate deterministically. The verb set covers the batch programs in the
certified workloads; anything outside it becomes an
:class:`~autoforge_modernization.service.cobol_ir.UnsupportedConstruct` so the
pipeline fails closed instead of silently dropping behaviour.

Supported verbs
---------------
MOVE, COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE, IF/ELSE/END-IF,
EVALUATE/WHEN/WHEN OTHER/END-EVALUATE, PERFORM (paragraph, THRU, UNTIL,
inline body), DISPLAY, OPEN, CLOSE, READ (+AT END / NOT AT END),
WRITE, REWRITE, CALL, SET, INITIALIZE, CONTINUE, EXIT, GOBACK, STOP RUN.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from autoforge_modernization.service.cobol_ir import (
    UnsupportedConstruct,
    join_qualified,
    source_lines,
    strip_trailing_period,
)

__all__ = ["Cond", "Stmt", "parse_procedure", "split_condition"]


@dataclass
class Cond:
    """A relational/logical condition node."""

    op: str  # = | != | > | < | >= | <= | AND | OR | NOT | cond | true
    left: Any = None
    right: Any = None
    join: str | None = None  # AND / OR joining this node to the previous
    line: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "left": self.left.as_dict() if isinstance(self.left, Cond) else self.left,
            "right": self.right.as_dict() if isinstance(self.right, Cond) else self.right,
            "join": self.join,
        }


@dataclass
class Stmt:
    """One procedural statement or a block of statements."""

    kind: str
    line: int
    text: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "line": self.line, "text": self.text, "attrs": self.attrs}


# ── Condition splitting ─────────────────────────────────────────────────────

_REL_OPS = ("NOT =", "NOT>", "NOT<", "<=", ">=", "!=", "=", "<", ">")


def split_condition(text: str, line: int = 0) -> list[Cond]:
    """Split a COBOL relation into (left, op, right) operands.

    Handles ``X OF Y``, reference modification ``X(1:8)``, literals, figurative
    constants and the six relational operators. A relation containing AND/OR is
    split into a conjunction/disjunction tree by :func:`parse_condition`.
    """
    upper = text.upper()
    best: tuple[int, str] | None = None
    for op in _REL_OPS:
        start = 0
        while True:
            index = upper.find(op, start)
            if index == -1:
                break
            # Must be a word-delimited operator, not part of a name.
            before_ok = index == 0 or not (upper[index - 1].isalnum() or upper[index - 1] == "-")
            after = index + len(op)
            after_ok = after >= len(upper) or not (upper[after].isalnum() or upper[after] == "-")
            if before_ok and after_ok:
                # Prefer the earliest position; among equals, the longest op.
                if best is None or index < best[0] or (index == best[0] and len(op) > len(best[1])):
                    best = (index, op)
                break
            start = index + 1
    if best is None:
        return [Cond(op="cond", left=text.strip(), line=line)]
    index, op = best
    left = text[:index].strip()
    right = text[index + len(op):].strip()
    return [Cond(op=op, left=left, right=right, line=line)]


_AND_OR_RE = re.compile(r"\s+(AND|OR)\s+", re.IGNORECASE)


#: COBOL class conditions (``X IS NUMERIC``, ``X NOT ALPHABETIC`` …).
_CLASS_CONDITION_RE = re.compile(
    r"^(?P<field>.+?)\s+(?P<negated>IS\s+NOT|NOT)\s+"
    r"(?P<class>NUMERIC|ALPHABETIC|ALPHABETIC-LOWER|ALPHABETIC-UPPER|OMITTED)\s*$",
    re.IGNORECASE,
)


def parse_condition(text: str, line: int = 0) -> Cond:
    """Parse a condition, honouring OR before AND (COBOL precedence)."""
    text = strip_trailing_period(text.strip())
    if not text:
        return Cond(op="true", line=line)

    class_match = _CLASS_CONDITION_RE.match(text)
    if class_match:
        return Cond(
            op="class",
            left=class_match.group("field").strip(),
            right=class_match.group("class").strip().upper(),
            join="NOT" if "NOT" in class_match.group("negated").upper() else None,
            line=line,
        )

    upper = text.upper()
    or_parts = re.split(r"\s+OR\s+", text, flags=re.IGNORECASE)
    if len(or_parts) > 1:
        node = _combine(or_parts, "OR", line)
        return node
    and_parts = re.split(r"\s+AND\s+", text, flags=re.IGNORECASE)
    if len(and_parts) > 1:
        return _combine(and_parts, "AND", line)

    if upper.startswith("NOT "):
        inner = parse_condition(text[4:], line)
        return Cond(op="NOT", left=inner, line=line)
    relation = split_condition(text, line)[0]
    relation.line = line
    return relation


def _combine(parts: list[str], joiner: str, line: int) -> Cond:
    node = parse_condition(parts[0].strip(), line)
    for part in parts[1:]:
        right = parse_condition(part.strip(), line)
        right.join = joiner
        node = Cond(op=joiner, left=node, right=right, line=line)
    return node
def _mask_literals(text: str) -> str:
    """Replace quoted literal contents with spaces, preserving offsets.

    Statement and keyword splitting must never trip over a literal such as
    ``MOVE 'END-IF' TO WS-FLAG``.
    """
    out = list(text)
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in ("'", '"'):
            quote = char
            index += 1
            while index < length:
                if text[index] == quote:
                    if index + 1 < length and text[index + 1] == quote:
                        index += 1
                        index += 1
                        continue
                    break
                out[index] = " "
                index += 1
            index += 1
            continue
        index += 1
    return "".join(out)


def join_procedure(
    body_lines: list[tuple[int, str]],
) -> tuple[str, list[tuple[int, int, int]]]:
    """Join procedure lines into one string, keeping an offset->line map."""
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    offset = 0
    for number, code in body_lines:
        text = code.strip()
        if not text:
            continue
        parts.append(text)
        spans.append((offset, offset + len(text), number))
        offset += len(text) + 1
    return " ".join(parts), spans


def _line_for(spans: list[tuple[int, int, int]], position: int) -> int:
    for start, end, number in spans:
        if start <= position <= end:
            return number
    return spans[-1][2] if spans else 0


#: Verbs that may begin a new statement. Used by the block-aware splitter to
#: resolve COBOL's period-optional statement separation.
_STATEMENT_INITIAL = frozenset(
    {
        "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "DISPLAY",
        "CALL", "SET", "INITIALIZE", "OPEN", "CLOSE", "WRITE", "REWRITE",
        "DELETE", "START", "GO", "EVALUATE", "STOP", "GOBACK", "EXIT",
        "CONTINUE", "READ", "IF", "PERFORM", "ACCEPT", "SEARCH", "INSPECT",
    }
)


def _count(pattern: str, masked_upper: str) -> int:
    """Count word-delimited occurrences, treating ``-`` as part of a word.

    COBOL names use hyphens, so ``END-IF`` must not be counted as ``IF``.
    """
    return len(re.findall(r"(?<![A-Z0-9\-])" + pattern + r"(?![A-Z0-9\-])", masked_upper))


def _depth_delta(masked_upper: str) -> int:
    """Net block-nesting change introduced by one statement-initial token.

    ``READ`` opens a block whenever it begins a statement. Whether the author
    wrote ``END-READ`` is decided by the caller, which can look ahead over the
    buffered text; gating the open on ``AT``/``END`` appearing in the *same*
    token would let ``END-READ`` close a block that was never opened, dropping
    the depth to zero mid-statement and orphaning the rest of the READ.
    """
    if masked_upper.strip(".,;") == "PERFORM" or "PERFORM" in masked_upper:
        opens = 1 if "UNTIL" in masked_upper else 0
    else:
        opens = 0
    opens += _count("IF", masked_upper)
    opens += _count("EVALUATE", masked_upper)
    if masked_upper.strip(".,;") == "READ":
        opens += 1
    closes = (
        _count("END-IF", masked_upper)
        + _count("END-PERFORM", masked_upper)
        + _count("END-EVALUATE", masked_upper)
        + _count("END-READ", masked_upper)
    )
    return opens - closes


def _split_statements_from_tokens(tokens: list[str]) -> list[str]:
    """Split a whitespace token stream into statements using block depth.

    A READ that does not use ``END-READ`` must not leave the depth permanently
    raised, so a pending READ is flushed as soon as the next statement-initial
    verb appears without a matching ``END-READ``.
    """
    statements: list[str] = []
    buffer: list[str] = []
    buffered_read = False
    depth = 0
    for token in tokens:
        upper = _mask_literals(token).upper().strip(".,;")
        if buffer and depth == 0 and upper in _STATEMENT_INITIAL:
            statements.append(" ".join(buffer))
            buffer = []
            buffered_read = False
        elif buffer and buffered_read and depth == 0:
            # An unterminated READ: it cannot own anything that follows.
            statements.append(" ".join(buffer))
            buffer = []
            buffered_read = False
        buffer.append(token)
        delta = _depth_delta(upper)
        depth = max(0, depth + delta)
        if delta > 0 and upper == "READ":
            buffered_read = True
        if "END-READ" in upper:
            buffered_read = False
    if buffer:
        statements.append(" ".join(buffer))
    return statements


_BLOCK_TERMINATORS = frozenset({"END-READ", "END-IF", "END-PERFORM", "END-EVALUATE"})


def _looks_like_label(text: str) -> bool:
    """True when a line is a bare paragraph label such as ``READ-NEXT-TXN.``.

    Block terminators are excluded: ``END-READ.`` closes a phrase and does not
    introduce a paragraph.
    """
    stripped = text.strip().upper()
    if not stripped or " " in stripped or not stripped.endswith("."):
        return False
    return stripped[:-1] not in _BLOCK_TERMINATORS


def split_statements(
    body_lines: list[tuple[int, str]],
) -> list[tuple[int, str]]:
    """Split normalized procedure lines into statements.

    COBOL permits omitting the separating period, and real legacy programs use
    that freedom heavily (DAILYPOST does). Splitting on periods alone therefore
    merges whole program bodies into one statement.

    This splitter therefore also ends a statement when a line *begins* with a
    statement-initial verb while no block is open. Block depth is tracked from
    ``IF``/``END-IF``, ``PERFORM UNTIL``/``END-PERFORM``,
    ``EVALUATE``/``END-EVALUATE`` and ``READ``/``END-READ`` so that verbs
    appearing *inside* an open block stay with their parent statement.
    """
    statements: list[tuple[int, str]] = []
    buffer: list[str] = []
    depth = 0
    start_line = 0
    buffered_read = False

    for number, code in body_lines:
        text = code.strip()
        if not text:
            continue
        masked = _mask_literals(text).upper()
        words = masked.split()
        first = words[0].strip(".,;:") if words else ""

        # A line that is nothing but a label ("READ-NEXT-TXN.") starts a new
        # paragraph; it must not be absorbed into the previous statement.
        boundary = bool(buffer) and depth == 0 and (
            first in _STATEMENT_INITIAL or _looks_like_label(text)
        )
        # An unterminated READ cannot own whatever follows it.
        if buffer and buffered_read and depth == 0:
            boundary = True
        if boundary:
            statements.append((start_line, " ".join(buffer)))
            buffer = []
            buffered_read = False

        if not buffer:
            start_line = number
        buffer.append(text)
        delta = _depth_delta(first if len(words) == 1 else masked)
        depth = max(0, depth + delta)
        if delta > 0 and first == "READ":
            buffered_read = True
        if "END-READ" in masked:
            buffered_read = False

        if depth == 0 and text.endswith("."):
            statements.append((start_line, " ".join(buffer)))
            buffer = []
            buffered_read = False

    if buffer and " ".join(buffer).strip():
        statements.append((start_line, " ".join(buffer)))
    return statements


_IF_KEYWORD_RE = re.compile(r"(?<![A-Z0-9\-])(IF|ELSE|END-IF)(?![A-Z0-9\-])")


def _split_if_body(body: str) -> tuple[str, str]:
    """Split an IF body into ``(then_text, else_text)``.

    ``body`` is everything after the leading ``IF`` keyword, so this function
    starts *inside* one open ``IF`` block: the caller's depth is 1, not 0.

    Real programs nest ``IF`` inside ``ELSE``, so the ELSE that belongs to
    *this* IF is the last one seen at nesting depth one, and the terminator is
    the first ``END-IF`` that brings the depth back to zero. Scanning with depth
    tracking is what makes the difference between a correct split and silently
    dropping the tail of an ELSE block.

    Starting the scan at depth 0 would let an inner ``END-IF`` terminate the
    split early: the statements after a nested ``IF ... END-IF`` inside an ELSE
    (for example the trailing ``PERFORM`` that advances the transaction file)
    would be discarded, and the generated program would loop forever.
    """
    masked = _mask_literals(body).upper()
    depth = 1  # the caller's own `IF` is already open
    else_position = -1
    end_position = len(body)
    for match in _IF_KEYWORD_RE.finditer(masked):
        kind = match.group(1)
        if kind == "IF":
            depth += 1
        elif kind == "END-IF":
            depth -= 1
            if depth == 0:
                end_position = match.start()
                break
        else:  # ELSE
            if depth == 1 and else_position == -1:
                else_position = match.start()
    inner = body[else_position + len("ELSE"):end_position] if else_position != -1 else ""
    then_text = body[:else_position] if else_position != -1 else body[:end_position]
    return then_text, inner


def split_on_keywords(text: str, keywords: tuple[str, ...]) -> list[tuple[str, str]]:
    """Split ``text`` at each top-level occurrence of any keyword.

    Returns ``(keyword, following_text)`` pairs. The first pair always has an
    empty keyword and carries the text *before* the first keyword; each later
    pair carries the keyword and the text that **follows** it. Quoted literals
    are ignored, so a literal that happens to spell a keyword cannot split a
    statement.
    """
    masked = _mask_literals(text).upper()
    marks: list[tuple[int, int, str]] = []
    for keyword in keywords:
        pattern = re.compile(
            r"(?<![A-Z0-9\-])" + re.escape(keyword) + r"(?![A-Z0-9\-])"
        )
        for match in pattern.finditer(masked):
            marks.append((match.start(), match.end(), keyword))
    # A shorter keyword can match *inside* a longer one: ``AT END`` occurs within
    # ``NOT AT END``. Keeping both would make the NOT AT END segment empty and
    # hand its body to the AT END branch, silently inverting the READ. Drop any
    # mark whose span is contained in another mark's span so the longest
    # keyword always wins.
    marks = [
        mark for mark in marks
        if not any(
            other is not mark
            and other[0] <= mark[0]
            and other[1] >= mark[1]
            and (other[1] - other[0]) > (mark[1] - mark[0])
            for other in marks
        )
    ]
    marks.sort()
    segments: list[tuple[str, str]] = []
    if not marks:
        return [("", text)]
    segments.append(("", text[: marks[0][0]]))
    for index, (position, _end, keyword) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        segments.append((keyword, text[position + len(keyword):end]))
    return segments
def _split_operands(text: str) -> list[str]:
    """Split an operand list, keeping quoted literals and qualified names intact.

    A literal such as ``'START OF EXECUTION'`` contains spaces, so splitting the
    masked text would tear it apart. This walks the original text and only
    breaks on whitespace/commas outside quotes and outside parentheses.

    A qualified data name (``TXN-TS OF TXN-IN-REC``) also contains spaces, and
    those spaces are *syntax*, not separators. The raw whitespace split therefore
    runs first and :func:`~autoforge_modernization.service.cobol_ir.join_qualified`
    then re-assembles the ``A OF B`` chains, so ``OF`` never survives as an
    operand of its own.
    """
    out: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in ("'", '"'):
            quote = char
            current.append(char)
            index += 1
            while index < length:
                current.append(text[index])
                if text[index] == quote:
                    if index + 1 < length and text[index + 1] == quote:
                        current.append(text[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if depth == 0 and (char.isspace() or char == ","):
            if current:
                out.append("".join(current).strip())
                current = []
        else:
            current.append(char)
        index += 1
    if current:
        out.append("".join(current).strip())
    return join_qualified([operand for operand in out if operand])


#: Verbs that may terminate a relational condition in an IF/EVALUATE header.
_BOUNDARY_VERBS = (
    "PERFORM", "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    "DISPLAY", "WRITE", "CALL", "IF", "EVALUATE", "GOBACK", "CLOSE", "OPEN",
    "READ", "SET", "CONTINUE", "EXIT", "STOP", "INITIALIZE", "GO", "STRING",
    "UNSTRING", "DELETE", "REWRITE", "INSPECT", "SORT", "MERGE", "ALTER",
)


def _condition_extent(masked_upper: str, start: int) -> int:
    """Return the end offset of a relational condition beginning at ``start``."""
    best: int | None = None
    for verb in _BOUNDARY_VERBS:
        pattern = re.compile(
            r"(?<![A-Z0-9\-])" + re.escape(verb) + r"(?![A-Z0-9\-])"
        )
        match = pattern.search(masked_upper, start)
        if match and (best is None or match.start() < best):
            best = match.start()
    return best if best is not None else len(masked_upper)


def _split_block_statements(text: str) -> list[str]:
    """Split a block body into statements.

    A block body may omit separating periods, exactly like the top level of a
    program. Splitting only on periods would therefore merge a nested
    ``MOVE ... COMPUTE ... IF ... EVALUATE ...`` sequence into a single MOVE with
    dozens of bogus targets.

    Block depth is tracked from ``IF``/``END-IF``,
    ``EVALUATE``/``END-EVALUATE``, ``READ``/``END-READ`` and
    ``PERFORM UNTIL``/``END-PERFORM`` so verbs *inside* an open block stay with
    their parent statement.
    """
    statements = _split_statements_from_tokens(text.split())
    return statements


def _parse_block(
    text: str, line: int
) -> tuple[list[Stmt], list[UnsupportedConstruct]]:
    """Parse a sequence of statements embedded in a block."""
    stmts: list[Stmt] = []
    gaps: list[UnsupportedConstruct] = []
    for chunk in _split_block_statements(text):
        chunk = chunk.strip().rstrip(".")
        if not chunk:
            continue
        parsed, chunk_gaps = _parse_statement(chunk, line)
        stmts.extend(parsed)
        gaps.extend(chunk_gaps)
    return stmts, gaps


def _parse_statement(
    text: str, line: int
) -> tuple[list[Stmt], list[UnsupportedConstruct]]:
    """Parse one statement into AST nodes, or record a fail-closed gap."""
    raw = strip_trailing_period(text.strip())
    if not raw:
        return [], []
    gaps: list[UnsupportedConstruct] = []
    masked = _mask_literals(raw).upper()

    def gap(construct: str, reason: str) -> None:
        gaps.append(
            UnsupportedConstruct(
                construct=construct, line=line, text=raw[:160], reason=reason
            )
        )

    words = masked.split()
    # When the text was joined from tokens, the last token of a
    # period-terminated statement keeps its period (e.g. "GOBACK."), so verbs
    # are compared without surrounding punctuation.
    word = words[0].strip(".,;:") if words else ""

    # ── IF / ELSE / END-IF ─────────────────────────────────────────────────
    if word == "IF":
        rest = raw[2:].strip()
        end = _condition_extent(_mask_literals(rest).upper(), 0)
        condition_text = rest[:end].strip()
        if condition_text.upper().endswith(" THEN"):
            condition_text = condition_text[: -len(" THEN")].strip()
        body = rest[end:].strip()
        then_text, else_text = _split_if_body(body)
        then_stmts, then_gaps = _parse_block(then_text, line)
        else_stmts, else_gaps = _parse_block(else_text, line)
        gaps.extend(then_gaps)
        gaps.extend(else_gaps)
        return [
            Stmt(
                kind="if",
                line=line,
                text=raw[:160],
                attrs={
                    "condition_text": condition_text,
                    "condition": parse_condition(condition_text, line).as_dict(),
                    "then": [s.as_dict() for s in then_stmts],
                    "else": [s.as_dict() for s in else_stmts],
                },
            )
        ], gaps

    # ── EVALUATE / WHEN / END-EVALUATE ─────────────────────────────────────
    if word == "EVALUATE":
        segments = split_on_keywords(raw, ("EVALUATE", "WHEN", "END-EVALUATE"))
        subject = strip_trailing_period(segments[1][1].strip()) if len(segments) > 1 else "TRUE"
        whens: list[dict[str, Any]] = []
        for keyword, segment in segments[2:]:
            if keyword == "END-EVALUATE":
                break
            if keyword != "WHEN":
                continue
            segment_masked = _mask_literals(segment).upper()
            cond_end = _condition_extent(segment_masked, 0)
            condition_text = segment[:cond_end].strip()
            body_text = segment[cond_end:].strip()
            is_other = condition_text.upper().startswith("OTHER")
            body_stmts, body_gaps = _parse_block(body_text, line)
            gaps.extend(body_gaps)
            whens.append(
                {
                    "condition_text": condition_text,
                    "condition": parse_condition(condition_text, line).as_dict(),
                    "is_other": is_other,
                    "body": [s.as_dict() for s in body_stmts],
                }
            )
        return [
            Stmt(
                kind="evaluate",
                line=line,
                text=raw[:160],
                attrs={
                    "subject_text": subject,
                    "subject": parse_condition(subject, line).as_dict(),
                    "whens": whens,
                },
            )
        ], gaps

    # ── PERFORM ────────────────────────────────────────────────────────────
    if word == "PERFORM":
        rest = raw[len("PERFORM"):].strip()
        rest_masked = _mask_literals(rest).upper()

        # PERFORM UNTIL may name a paragraph first: `PERFORM P UNTIL cond`.
        target = ""
        thru = None
        if not rest_masked.startswith("UNTIL"):
            thru_index = rest_masked.find(" THRU ")
            if thru_index != -1:
                target = rest[:thru_index].strip()
                tail = rest[thru_index + len(" THRU "):]
                stop = _condition_extent(_mask_literals(tail).upper(), 0)
                thru = tail[:stop].strip()
                rest = tail[stop:].strip()
            else:
                stop = _condition_extent(rest_masked, 0)
                target = rest[:stop].strip()
                rest = rest[stop:].strip()
            rest_masked = _mask_literals(rest).upper()

        if rest_masked.startswith("VARYING") or rest_masked.lstrip().startswith(
            "PERFORM"
        ) or re.match(r"^\S+\s+TIMES", rest_masked):
            gap("perform-varying", "PERFORM VARYING/TIMES is not in the certified scope")
            return [], gaps

        if rest_masked.startswith("UNTIL"):
            after_until = rest[len("UNTIL"):].strip()
            stop = _condition_extent(_mask_literals(after_until).upper(), 0)
            condition_text = after_until[:stop].strip()
            remainder = after_until[stop:].strip()
            # Everything up to END-PERFORM is the inline loop body.
            body = split_on_keywords(remainder, ("END-PERFORM",))[0][1]
            body_stmts, body_gaps = _parse_block(body, line)
            gaps.extend(body_gaps)
            return [
                Stmt(
                    kind="perform_until",
                    line=line,
                    text=raw[:160],
                    attrs={
                        "target": target or None,
                        "thru": thru,
                        "condition_text": condition_text,
                        "condition": parse_condition(condition_text, line).as_dict(),
                        "body": [s.as_dict() for s in body_stmts],
                    },
                )
            ], gaps

        if target:
            return [
                Stmt(
                    kind="perform_para",
                    line=line,
                    text=raw[:160],
                    attrs={"target": target, "thru": thru},
                )
            ], gaps
        gap("perform", "PERFORM without a resolvable target")
        return [], gaps

    # ── MOVE ───────────────────────────────────────────────────────────────
    if word == "MOVE":
        rest = raw[len("MOVE"):].strip()
        to_index = _mask_literals(rest).upper().find(" TO ")
        if to_index == -1:
            gap("move", "MOVE without a TO clause")
            return [], gaps
        source = rest[:to_index].strip()
        targets = _split_operands(rest[to_index + 4:])
        if not targets:
            gap("move", "MOVE with no receiving field")
            return [], gaps
        return [
            Stmt(kind="move", line=line, text=raw[:160],
                 attrs={"source": source, "targets": targets})
        ], gaps

    # ── COMPUTE ────────────────────────────────────────────────────────────
    if word == "COMPUTE":
        rest = raw[len("COMPUTE"):].strip()
        if "=" not in rest:
            gap("compute", "COMPUTE without an expression")
            return [], gaps
        lhs, _, rhs = rest.partition("=")
        targets = _split_operands(lhs)
        if not targets:
            gap("compute", "COMPUTE without a target")
            return [], gaps
        return [
            Stmt(kind="compute", line=line, text=raw[:160],
                 attrs={"targets": targets, "expression": rhs.strip()})
        ], gaps

    # ── ADD / SUBTRACT / MULTIPLY / DIVIDE ─────────────────────────────────
    if word in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"):
        giving_index = _mask_literals(raw).upper().find(" GIVING ")
        body = raw
        giving = None
        if giving_index != -1:
            body = raw[:giving_index]
            giving = _split_operands(raw[giving_index + len(" GIVING "):])
        keyword_map = {
            "ADD": ("ADD", "TO"),
            "SUBTRACT": ("SUBTRACT", "FROM"),
            "MULTIPLY": ("MULTIPLY", "BY"),
            "DIVIDE": ("DIVIDE", "INTO"),
        }
        _, connector = keyword_map[word]
        tail = body[len(word):].strip()
        index = _mask_literals(tail).upper().find(" " + connector + " ")
        if index == -1:
            gap(word.lower(), f"{word} without a {connector} phrase")
            return [], gaps
        operands = _split_operands(tail[:index])
        receivers = _split_operands(tail[index + len(connector) + 1:])
        return [
            Stmt(
                kind="arithmetic",
                line=line,
                text=raw[:160],
                attrs={
                    "op": word,
                    "operands": operands,
                    "receivers": receivers,
                    "giving": giving,
                },
            )
        ], gaps

    # ── ADD is also a bare verb when it starts with ADD ────────────────────

    # ── I/O ────────────────────────────────────────────────────────────────
    if word == "OPEN":
        rest = raw[len("OPEN"):].strip()
        segments = split_on_keywords(rest, ("INPUT", "OUTPUT", "I-O", "EXTEND"))
        entries: list[dict[str, str]] = []
        for index, (keyword, segment) in enumerate(segments):
            mode = keyword or ("INPUT" if index == 0 else "INPUT")
            for name in _split_operands(segment):
                entries.append({"mode": mode, "file": name})
        if not entries:
            gap("open", "OPEN without an operand")
        return [
            Stmt(kind="open", line=line, text=raw[:160], attrs={"entries": entries})
        ], gaps

    if word == "CLOSE":
        names = _split_operands(raw[len("CLOSE"):])
        if not names:
            gap("close", "CLOSE without an operand")
        return [
            Stmt(kind="close", line=line, text=raw[:160], attrs={"files": names})
        ], gaps

    if word == "WRITE":
        return [
            Stmt(kind="write", line=line, text=raw[:160],
                 attrs=_split_write(raw[len("WRITE"):].strip()))
        ], gaps

    if word == "REWRITE":
        return [
            Stmt(kind="rewrite", line=line, text=raw[:160],
                 attrs=_split_write(raw[len("REWRITE"):].strip()) | {"rewrite": True})
        ], gaps

    if word == "READ":
        return _parse_read(raw, line, gap)

    # ── DISPLAY ────────────────────────────────────────────────────────────
    if word == "DISPLAY":
        operands = _split_operands(raw[len("DISPLAY"):])
        return [
            Stmt(kind="display", line=line, text=raw[:160], attrs={"operands": operands})
        ], gaps

    # ── CALL ───────────────────────────────────────────────────────────────
    if word == "CALL":
        rest = raw[len("CALL"):].strip()
        parts = rest.split(None, 1)
        target = parts[0].strip() if parts else ""
        using: list[str] = []
        if len(parts) > 1:
            tail = parts[1]
            using_match = re.search(
                r"(?<![A-Z0-9\-])USING(?![A-Z0-9\-])", _mask_literals(tail).upper()
            )
            if using_match:
                using = _split_operands(tail[using_match.end():])
            else:
                gap("call", "CALL form other than USING is not supported")
        return [
            Stmt(kind="call", line=line, text=raw[:160],
                 attrs={"target": target, "using": using})
        ], gaps

    simple_stmts, simple_gaps = _parse_simple(word, raw, line)
    gaps.extend(simple_gaps)
    return simple_stmts, gaps


def _split_write(text: str) -> dict[str, Any]:
    """Parse ``<record> [FROM <source>]`` for WRITE/REWRITE."""
    text = text.strip()
    upper = _mask_literals(text).upper()
    from_index = upper.find(" FROM ")
    if from_index == -1:
        return {"record": text, "from": None}
    return {
        "record": text[:from_index].strip(),
        "from": text[from_index + len(" FROM "):].strip(),
    }


def _parse_read(raw: str, line: int, gap) -> tuple[list[Stmt], list[UnsupportedConstruct]]:
    """Parse READ with its AT END / NOT AT END / INVALID KEY phrases."""
    gaps: list[UnsupportedConstruct] = []
    rest = raw[len("READ"):].strip()
    # The header ends where the first AT END / NOT AT END / INVALID KEY /
    # END-READ phrase begins; everything from there on is the body.
    segments = split_on_keywords(
        rest, ("AT END", "NOT AT END", "INVALID KEY", "END-READ")
    )
    header = segments[0][1]
    body = rest[len(segments[0][1]):]
    stop = _condition_extent(_mask_literals(header).upper(), 0)
    header = header[:stop].strip()

    attributes: dict[str, Any] = {"file": "", "into": None, "key": None}
    header_masked = _mask_literals(header).upper()
    into_index = header_masked.find(" INTO ")
    if into_index != -1:
        attributes["into"] = header[into_index + len(" INTO "):].strip()
        header = header[:into_index].strip()
        header_masked = _mask_literals(header).upper()
    key_index = header_masked.find(" KEY IS ")
    if key_index != -1:
        attributes["key"] = header[key_index + len(" KEY IS "):].strip()
        header = header[:key_index].strip()
    attributes["file"] = header.strip().split()[0] if header.strip() else ""

    at_end: list[dict[str, Any]] = []
    not_at_end: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for keyword, segment in split_on_keywords(
        body, ("AT END", "NOT AT END", "INVALID KEY", "END-READ")
    ):
        if keyword == "AT END":
            stmts, seg_gaps = _parse_block(segment, line)
            gaps.extend(seg_gaps)
            at_end = [s.as_dict() for s in stmts]
        elif keyword == "NOT AT END":
            stmts, seg_gaps = _parse_block(segment, line)
            gaps.extend(seg_gaps)
            not_at_end = [s.as_dict() for s in stmts]
        elif keyword == "INVALID KEY":
            stmts, seg_gaps = _parse_block(segment, line)
            gaps.extend(seg_gaps)
            invalid = [s.as_dict() for s in stmts]
    attributes["at_end"] = at_end
    attributes["not_at_end"] = not_at_end
    attributes["invalid_key"] = invalid
    if not attributes["file"]:
        gap("read", "READ without a file name")
    return [Stmt(kind="read", line=line, text=raw[:160], attrs=attributes)], gaps


# ── Simple verbs ────────────────────────────────────────────────────────
_SIMPLE_VERBS = {
    "CONTINUE": "continue",
    "EXIT": "exit",
    "GOBACK": "goback",
    "STOP": "stop",
    "INITIALIZE": "initialize",
    "SET": "set",
}


_PARAGRAPH_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,30}\.$")


#: A paragraph label must not be a COBOL verb. ``EXIT.`` and ``GOBACK.`` end a
#: paragraph but are statements, not labels; treating them as labels would split
#: every program into phantom paragraphs.
_NON_LABEL_WORDS = frozenset(
    {
        "EXIT", "GOBACK", "CONTINUE", "STOP", "MOVE", "IF", "ELSE", "PERFORM",
        "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "DISPLAY", "CALL",
        "OPEN", "CLOSE", "READ", "WRITE", "SET", "EVALUATE", "GO", "END",
    }
)


def _is_paragraph_label(statement: str) -> bool:
    text = statement.strip().upper()
    if not _PARAGRAPH_RE.match(text):
        return False
    label = text.rstrip(".")
    if label in _NON_LABEL_WORDS:
        return False
    # A real paragraph label is followed by a statement, never only a period.
    return not label.endswith("-")


def parse_procedure(
    text: str, *, source_format: str | None = None
) -> tuple[dict[str, list[Stmt]], list[UnsupportedConstruct]]:
    """Parse a PROCEDURE DIVISION into ``{paragraph_name: [Stmt]}``.

    Text before the first paragraph label (an implicit main line, as DAILYPOST
    uses) is stored under the key ``""``.
    """
    lines = source_lines(text, source_format=source_format)
    procedure_lines: list[tuple[int, str]] = []
    started = False
    for number, code in lines:
        if not started:
            if re.match(r"^\s*PROCEDURE\s+DIVISION", code, re.IGNORECASE):
                started = True
            continue
        procedure_lines.append((number, code))

    gaps: list[UnsupportedConstruct] = []
    paragraphs: dict[str, list[Stmt]] = {"": []}
    current = ""
    for line, statement in split_statements(procedure_lines):
        if _is_paragraph_label(statement):
            current = statement.strip().rstrip(".").upper()
            paragraphs.setdefault(current, [])
            continue
        stmts, stmt_gaps = _parse_statement(statement, line)
        paragraphs.setdefault(current, []).extend(stmts)
        gaps.extend(stmt_gaps)
    return paragraphs, gaps


def _parse_simple(word: str, raw: str, line: int):
    """Handle the remaining supported verbs and everything unsupported."""
    if word in _SIMPLE_VERBS:
        kind = _SIMPLE_VERBS[word]
        rest = raw[len(word):].strip()
        return [
            Stmt(kind=kind, line=line, text=raw[:160],
                 attrs={"operand": rest} if rest else {})
        ], []
    if word == "GO":
        return [], [
            UnsupportedConstruct(
                construct="go-to", line=line, text=raw[:160],
                reason="GO TO alters control flow the certified scope does not cover",
            )
        ]
    return [], [
        UnsupportedConstruct(
            construct=word.lower() or "unknown", line=line, text=raw[:160],
            reason="verb is outside the certified modernization subset",
        )
    ]
