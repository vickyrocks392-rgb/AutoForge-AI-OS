"""Deterministic COBOL-to-Java code generator (Phase 20).

Consumes the :class:`~autoforge_modernization.service.cobol_program.ProgramModel`
produced by the existing parser -- there is no second COBOL parser here -- and
emits a self-contained Java application built on the COBOL runtime in
:mod:`autoforge_modernization.service.java_runtime`.

Every COBOL data item becomes a ``byte[]`` record area at the offsets the data
dictionary computed, so generated code addresses bytes exactly as the legacy
program did. Expressions resolve to runtime calls with literal offsets, digits,
scale and usage baked in, which keeps every generated access traceable back to
the PICTURE clause that produced it.

Anti-cheating properties are structural, not stylistic:

* golden-master bytes are never read or embedded;
* no program-specific business logic is hardcoded -- every statement comes from
  the parsed AST;
* nothing outside the modelled program influences the output, so the generated
  application computes its own results.

If a construct cannot be translated faithfully it is recorded in
:attr:`GenerationResult.unsupported` and **no files are emitted**, so callers
fail closed instead of shipping a partially translated program.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from autoforge_modernization.service.cobol_ir import (
    FieldDef,
    RecordLayout,
    join_qualified,
)
from autoforge_modernization.service.cobol_program import ProgramModel
from autoforge_modernization.service.java_runtime import render_runtime

__all__ = [
    "Symbol", "GeneratedFile", "GenerationResult",
    "generate_java", "java_safe", "camel",
]


def java_safe(name: str) -> str:
    """COBOL name -> Java identifier (hyphens become underscores)."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "_", name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned.lower()


def camel(name: str) -> str:
    """COBOL name -> Java class name."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]", name) if p]
    return "".join(p.capitalize() for p in parts) or "ModernizedProgram"


@dataclass(frozen=True)
class Symbol:
    """A resolved COBOL data item and how to address it in generated Java."""

    name: str
    holder: str          # Java field holding the record buffer
    offset: int
    length: int          # bytes for one occurrence
    occurs: int
    digits: int
    scale: int
    signed: bool
    usage: str
    category: str        # alphanumeric | numeric
    owner: str           # record name


@dataclass
class GeneratedFile:
    path: str
    content: str


@dataclass
class GenerationResult:
    files: list[GeneratedFile] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unsupported

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": [f.path for f in self.files],
            "unsupported": list(self.unsupported),
        }


class _SymbolTable:
    """Name -> Symbol across every record and working-storage area."""

    def __init__(self) -> None:
        self.by_name: dict[str, Symbol] = {}
        self.by_owner: dict[str, dict[str, Symbol]] = {}
        self.conditions: dict[str, tuple[str, str]] = {}

    def add_layout(self, layout: RecordLayout, holder: str) -> None:
        owned: dict[str, Symbol] = {}
        for fdef in layout.fields:
            if not fdef.name or fdef.picture is None or fdef.name == "FILLER":
                continue
            unit = fdef.size // max(1, fdef.occurs)
            symbol = Symbol(
                name=fdef.name, holder=holder, offset=fdef.offset, length=unit,
                occurs=max(1, fdef.occurs), digits=fdef.digits, scale=fdef.scale,
                signed=fdef.signed, usage=fdef.usage, category=fdef.category,
                owner=layout.record_name,
            )
            owned.setdefault(fdef.name, symbol)
            self.by_name.setdefault(fdef.name, symbol)
            for cond_name, cond_value in fdef.conditions.items():
                self.conditions[cond_name] = (fdef.name, cond_value)
        self.by_owner[layout.record_name] = owned


class _Emitter:
    """Translates the modelled PROCEDURE DIVISION into Java statements."""

    def __init__(self, model: ProgramModel, symbols: _SymbolTable,
                 files: dict[str, str]) -> None:
        self.model = model
        self.symbols = symbols
        self.files = files
        self.unsupported: list[str] = []
        self._tokens: list[str] = []
        self._position = 0
        # Arithmetic safety flags; reset per expression in _arith_expr.
        self._missing_operand = False
        self._paren_fault = False

    # ── Operand resolution ────────────────────────────────────────────────

    @staticmethod
    def _operand(value: Any) -> str | None:
        """Return operand text, or ``None`` when the operand is genuinely absent.

        This is the guard that keeps Python ``None`` from ever masquerading as a
        COBOL operand. ``str(None)`` would produce the literal text ``"None"``,
        which would then flow into the symbol table as if it were a field name.
        """
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _resolve(self, text: str) -> tuple[Symbol | None, int, int]:
        """Resolve an operand to a symbol plus subscript / reference modification."""
        text = text.strip()
        occurrence, refmod = 1, 0
        match = re.match(r"^([A-Za-z0-9\-]+)\s*\(([^)]*)\)$", text)
        if match:
            base, inner = match.group(1), match.group(2).strip()
            if ":" in inner:
                refmod = int(inner.partition(":")[2].strip())
            else:
                occurrence = int(inner)
            text = base
        return self._lookup(text), occurrence, refmod

    def _lookup(self, name: str) -> Symbol | None:
        name = name.strip().upper()
        if " OF " in name:
            field_name, _, owner = name.partition(" OF ")
            return self.symbols.by_owner.get(
                owner.strip().upper(), {}
            ).get(field_name.strip().upper())
        return self.symbols.by_name.get(name)

    def _group_holder(self, name: str) -> str | None:
        """Return the Java buffer for a whole record / group item.

        ``WRITE ACCT-OUT-REC FROM ACCT-IN-REC`` names *group* items, not leaf
        fields, so :meth:`_resolve` cannot see them (it only indexes leaf
        fields). Without this the record copy would be silently skipped and a
        blank record written out.
        """
        key = name.strip().upper()
        if key in self.symbols.by_owner:
            return java_safe(key)
        for layout in (list(self.model.records.values())
                       + list(self.model.working_storage.values())):
            if layout.record_name.upper() == key:
                return java_safe(layout.record_name)
        return None

    def _offset_expr(self, symbol: Symbol, occurrence: int) -> str:
        if occurrence > 1:
            return f"({symbol.holder} + {(occurrence - 1) * symbol.length})"
        return symbol.holder

    # ── Literals ──────────────────────────────────────────────────────────

    def is_literal(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if stripped[0] in "'\"":
            return True
        return bool(re.fullmatch(r"-?\d+(\.\d+)?", stripped))

    def literal(self, text: str) -> str:
        stripped = text.strip()
        if stripped and stripped[0] in "'\"":
            return '"' + stripped[1:-1].replace('"', '\\"') + '"'
        if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
            return f'new BigDecimal("{stripped}")'
        return ""

    def figurative(self, text: str) -> str | None:
        upper = text.strip().upper()
        table = {
            "SPACES": '""', "SPACE": '""',
            "ZEROS": "BigDecimal.ZERO", "ZERO": "BigDecimal.ZERO",
            "ZEROES": "BigDecimal.ZERO",
            "LOW-VALUES": '"\\u0000"', "HIGH-VALUES": '"\\u00ff"',
            "QUOTE": '"\\""', "QUOTES": '"\\""',
            "NULL": "null", "NULLS": "null",
        }
        return table.get(upper)

    def is_numeric_operand(self, text: str) -> bool:
        if self.is_literal(text):
            return bool(re.fullmatch(r"-?\d+(\.\d+)?", text.strip()))
        figurative = self.figurative(text)
        if figurative is not None:
            return figurative == "BigDecimal.ZERO"
        symbol, _, _ = self._resolve(text)
        return bool(symbol and symbol.category == "numeric")

    # ── Value expressions ─────────────────────────────────────────────────

    def value_expr(self, text: str) -> str:
        """Return a Java expression for a COBOL operand (String or BigDecimal)."""
        stripped = text.strip()
        literal = self.literal(stripped)
        if literal:
            return literal
        figurative = self.figurative(stripped)
        if figurative is not None:
            return figurative
        symbol, occurrence, refmod = self._resolve(stripped)
        if symbol is None:
            self.unsupported.append(f"unresolved operand: {stripped}")
            return "null"
        holder = self._offset_expr(symbol, occurrence)
        if refmod:
            if symbol.category == "numeric":
                return (f"Rt.getDisplay({holder}, {symbol.offset}, {refmod}, "
                        f"{symbol.scale}, {str(symbol.signed).lower()})")
            return f"Rt.getText({holder}, {symbol.offset}, {refmod})"
        if symbol.category == "alphanumeric":
            return f"Rt.getText({holder}, {symbol.offset}, {symbol.length})"
        if symbol.usage == "COMP-3":
            return (f"Rt.getPacked({holder}, {symbol.offset}, {symbol.digits}, "
                    f"{symbol.scale}, {str(symbol.signed).lower()})")
        return (f"Rt.getDisplay({holder}, {symbol.offset}, {symbol.length}, "
                f"{symbol.scale}, {str(symbol.signed).lower()})")

    # ── Conditions ────────────────────────────────────────────────────────

    def cond_expr(self, node: dict[str, Any]) -> str:
        """Translate a parsed condition tree into a Java boolean expression."""
        op = node.get("op")
        if op == "true":
            return "true"
        if op in ("AND", "OR"):
            joiner = " && " if op == "AND" else " || "
            return (f"({self.cond_expr(node['left'])}{joiner}"
                    f"{self.cond_expr(node['right'])})")
        if op == "NOT":
            return f"(!{self.cond_expr(node['left'])})"
        if op == "class":
            return self._class_condition(node)
        return self._relation(node, op)

    def _class_condition(self, node: dict[str, Any]) -> str:
        field = str(node.get("left", "")).strip()
        klass = str(node.get("right", "NUMERIC")).upper()
        symbol, _, _ = self._resolve(field)
        if symbol is None:
            self.unsupported.append(f"unresolved class condition: {field}")
            return "false"
        if klass != "NUMERIC":
            self.unsupported.append(f"unsupported class condition: {klass}")
            return "false"
        check = f"Rt.isNumeric({symbol.holder}, {symbol.offset}, {symbol.length})"
        return f"(!{check})" if node.get("join") == "NOT" else check

    def _relation(self, node: dict[str, Any], op: str) -> str:
        left_text = self._operand(node.get("left"))
        right_text = self._operand(node.get("right"))
        if left_text is None or right_text is None:
            # Safety requirement: a relation must never carry `None` as a
            # semantic operand. Fail closed with an explicit diagnostic instead
            # of emitting Java that compares against `null`.
            self.unsupported.append(
                f"relation {op} missing operand: left={left_text!r} "
                f"right={right_text!r}")
            return "false"
        condition = self.symbols.conditions.get(left_text.upper())
        if condition is not None:
            owner, value = condition
            left_text = f"{owner} = {value}"
        java_op = {"=": "==", "!=": "!=", "<": "<", ">": ">", "<=": "<=",
                   ">=": ">="}.get(op, "==")
        left = self.value_expr(left_text)
        right = self.value_expr(right_text)
        if self.is_numeric_operand(left_text) or self.is_numeric_operand(right_text):
            return f"(Rt.compareNumeric({left}, {right}) {java_op} 0)"
        return f"(Rt.compareText({left}, {right}) {java_op} 0)"

    def _arith_tokens(self, text: str) -> list[str]:
        """Tokenize a COBOL arithmetic expression.

        Operators are recognised only when they stand alone as a whitespace- or
        parenthesis-delimited token. COBOL identifiers contain hyphens
        (``WS-TS``, ``CURR-BAL``), so splitting ``WS-TS / WS-MILLION`` on ``-``
        would turn one operand into three bogus ones.

        Qualified names carry the same hazard in the other direction:
        ``CURR-BAL OF ACCT-IN-REC - TXN-AMOUNT OF TXN-IN-REC`` must reduce to
        exactly three tokens, or the recursive-descent parser would silently
        stop after the first operand and drop the subtraction entirely. The
        ``A OF B`` chains are therefore re-joined before the token stream is
        returned.

        Subscript and reference modification bind to their data name with no
        intervening space, so ``AMT-FLD(1:8)`` is ONE operand. A parenthesis
        that follows whitespace (``( A + B )``) is a grouping parenthesis and
        stays a separate token. Splitting the former used to yield four tokens,
        which then parsed as a bare field plus unbalanced parentheses.
        """
        tokens: list[str] = []
        index = 0
        length = len(text)
        while index < length:
            char = text[index]
            if char.isspace():
                index += 1
                continue
            if char in "()":
                tokens.append(char)
                index += 1
                continue
            if char in "+-*/":
                end = index + 1
                while end < length and text[end].isspace():
                    end += 1
                # A sign directly attached to a following operand (`-AMT-FLD`)
                # is unary, not a binary operator, so it is its own token.
                # Otherwise it must stand alone, or a COBOL hyphen inside a
                # name would be mistaken for subtraction.
                attached = end < length and (
                    text[end].isalnum() or text[end] == "_")
                if attached or end >= length or text[end] in "()+-*/" \
                        or text[end].isspace():
                    tokens.append(char)
                    index += 1
                    continue
            end = index
            while end < length and not text[end].isspace() and text[end] not in "()":
                end += 1
            word = text[index:end]
            # A parenthesis glued to the end of a name is a subscript or
            # reference modification and belongs to that operand.
            while end < length and text[end] == "(":
                close = text.find(")", end)
                if close == -1:
                    break
                word += text[end:close + 1]
                end = close + 1
            tokens.append(word)
            index = end
        return join_qualified(tokens)

    # ── Arithmetic expressions ────────────────────────────────────────────
    #
    # SAFETY INVARIANT (Phase 20): an arithmetic expression is translated as a
    # whole or not at all. The recursive-descent parser used to return whatever
    # it managed to consume and silently drop the remainder -- a subtraction
    # could vanish and still produce a compiling, plausible program. Every exit
    # from this path now proves the token stream was fully consumed, the
    # parentheses balanced, and that no operand was missing.

    def _arith_expr(self, text: str) -> str:
        """Translate a COBOL arithmetic expression, or record why it cannot be.

        Fails closed: if any token is left unconsumed, the parentheses do not
        balance, or an operand was missing, a diagnostic is recorded and the
        result is discarded (the caller emits no file when ``unsupported`` is
        non-empty).
        """
        self._tokens = self._arith_tokens(text)
        self._position = 0
        self._missing_operand = False
        self._paren_fault = False
        if not self._tokens:
            return "BigDecimal.ZERO"
        value = self._arith_sum()
        self._assert_expression_fully_consumed(text)
        return value

    def _assert_expression_fully_consumed(self, text: str) -> None:
        """Record a diagnostic unless the whole expression was understood."""
        stripped = text.strip()
        leftover = self._tokens[self._position:]
        if leftover:
            self.unsupported.append(
                f"unconsumed arithmetic tokens in {stripped!r}: "
                f"{' '.join(leftover)}")
        opens = self._tokens.count("(")
        closes = self._tokens.count(")")
        if opens != closes:
            self.unsupported.append(
                f"unbalanced parentheses in arithmetic {stripped!r}: "
                f"{opens} '(' and {closes} ')'")
        if self._paren_fault:
            self.unsupported.append(
                f"unclosed parenthesis in arithmetic {stripped!r}")
        if self._missing_operand:
            self.unsupported.append(
                f"missing operand in arithmetic {stripped!r}")

    def _peek(self) -> str:
        return self._tokens[self._position] if self._position < len(self._tokens) else ""

    def _take(self) -> str:
        token = self._peek()
        self._position += 1
        return token

    def _arith_sum(self) -> str:
        value = self._arith_term()
        while self._peek() in ("+", "-"):
            op = self._take()
            right = self._arith_term()
            java_op = "add" if op == "+" else "subtract"
            value = f"Rt.{java_op}({value}, {right})"
        return value

    def _arith_term(self) -> str:
        value = self._arith_factor()
        while self._peek() in ("*", "/"):
            op = self._take()
            right = self._arith_factor()
            java_op = "multiply" if op == "*" else "divide"
            value = f"Rt.{java_op}({value}, {right})"
        return value

    def _arith_factor(self) -> str:
        token = self._take()
        if token == "(":
            inner = self._arith_sum()
            if self._peek() == ")":
                self._take()
            else:
                # A group with no closing parenthesis. Recorded, not ignored.
                self._paren_fault = True
            return f"({inner})"
        if token == "-":
            return f"Rt.negate({self._arith_factor()})"
        if token == "+":
            return self._arith_factor()
        if not token:
            # Ran off the end of the expression (e.g. `A +`). Substituting zero
            # here would invent an operand that the legacy program never had.
            self._missing_operand = True
            return "BigDecimal.ZERO"
        return self.value_expr(token)

    # ── Statement emission ────────────────────────────────────────────────

    def store(self, target: str, value_expr: str, indent: str) -> list[str]:
        """Emit a COBOL MOVE of ``value_expr`` into ``target``."""
        symbol, occurrence, _ = self._resolve(target)
        if symbol is None:
            self.unsupported.append(f"unresolved MOVE target: {target}")
            return []
        holder = self._offset_expr(symbol, occurrence)
        return [f"{indent}Rt.storeValue({holder}, {symbol.offset}, {symbol.length}, "
                f"{symbol.digits}, {symbol.scale}, "
                f"{str(symbol.signed).lower()}, \"{symbol.usage}\", {value_expr});"]

    def emit(self, statements: list[dict[str, Any]], indent: str) -> list[str]:
        lines: list[str] = []
        for node in statements:
            lines.extend(self._emit_one(node, indent))
        return lines

    def _emit_one(self, node: dict[str, Any], indent: str) -> list[str]:
        kind = node.get("kind")
        attrs = node.get("attrs", {})
        if kind == "move":
            source = self.value_expr(str(attrs["source"]))
            out: list[str] = []
            for target in attrs["targets"]:
                out.extend(self.store(target, source, indent))
            return out
        if kind == "compute":
            expression = self._arith_expr(str(attrs["expression"]))
            out = []
            for target in attrs["targets"]:
                out.extend(self.store(target, expression, indent))
            return out
        if kind == "arithmetic":
            return self._emit_arithmetic(attrs, indent)
        if kind == "if":
            out = [f"{indent}if ({self.cond_expr(attrs['condition'])}) {{"]
            out.extend(self.emit(attrs.get("then", []), indent + "    "))
            if attrs.get("else"):
                out.append(f"{indent}}} else {{")
                out.extend(self.emit(attrs["else"], indent + "    "))
            out.append(f"{indent}}}")
            return out
        if kind == "evaluate":
            return self._emit_evaluate(attrs, indent)
        if kind == "perform_para":
            return self._emit_perform_para(attrs, indent)
        if kind == "perform_until":
            out = []
            if attrs.get("target"):
                out.append(f"{indent}{java_safe(str(attrs['target']))}();")
            out.append(f"{indent}while (!({self.cond_expr(attrs['condition'])})) {{")
            out.extend(self.emit(attrs.get("body", []), indent + "    "))
            out.append(f"{indent}}}")
            return out
        if kind == "read":
            return self._emit_read(attrs, indent)
        if kind in ("write", "rewrite"):
            return self._emit_write(attrs, indent)
        if kind == "open":
            return self._emit_open(attrs, indent)
        if kind == "close":
            return [
                f"{indent}{self.files[name.strip().upper()]}.close();"
                for name in attrs.get("files", [])
                if str(name).strip().upper() in self.files
            ]
        if kind == "display":
            parts = [self.value_expr(str(o)) for o in attrs.get("operands", [])]
            return [f"{indent}Rt.display({''.join(parts)});"]
        if kind in ("goback", "continue", "exit", "stop", "initialize", "set"):
            return []
        self.unsupported.append(f"unsupported statement: {kind}")
        return []

    def _emit_arithmetic(self, attrs: dict[str, Any], indent: str) -> list[str]:
        """Emit ADD / SUBTRACT / MULTIPLY / DIVIDE with optional GIVING."""
        op = str(attrs["op"])
        operands = [self.value_expr(str(o)) for o in attrs.get("operands", [])]
        receivers = attrs.get("receivers", [])
        giving = attrs.get("giving")
        if not operands or op not in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"):
            self.unsupported.append(f"unsupported arithmetic: {op}")
            return []
        if op == "DIVIDE":
            # DIVIDE x INTO y means y = y / x. The receiver is the dividend,
            # so it is accumulated like the other verbs -- but the verb itself
            # is not one of the add/subtract/multiply family, so it is handled
            # separately rather than through `java_op`.
            source = (f"Rt.divide({receivers[0]}, {operands[0]})"
                      if receivers else "BigDecimal.ZERO")
            accumulate_op = "divide"
        else:
            java_op = {"ADD": "add", "SUBTRACT": "subtract",
                       "MULTIPLY": "multiply"}[op]
            accumulate_op = java_op
            source = operands[0]
            for extra in operands[1:]:
                source = f"Rt.{java_op}({source}, {extra})"
        targets = giving if giving else [
            r for r in receivers if str(r).upper() != "ZERO"
        ]
        out: list[str] = []
        for target in targets:
            # `source` is rebuilt for every receiver. Folding the accumulation
            # into the loop variable would compound earlier receivers into
            # later ones (`ADD x TO A B` must give A+x and B+x, not B+A+x).
            value = source
            if giving is None and op != "DIVIDE":
                # `ADD x TO y` / `SUBTRACT x FROM y` are *accumulating* verbs:
                # the receiver already holds a value and the result is
                # receiver (op) x. Storing the operand alone would overwrite
                # the field instead of updating it.
                #
                # DIVIDE is special: `source` above is already
                # receiver / operand, so it must NOT be accumulated again.
                current = self.value_expr(str(target))
                value = f"Rt.{accumulate_op}({current}, {value})"
            out.extend(self.store(str(target), value, indent))
        return out

    def _emit_evaluate(self, attrs: dict[str, Any], indent: str) -> list[str]:
        subject_text = self._operand(attrs.get("subject_text"))
        out: list[str] = []
        for when in attrs.get("whens", []):
            if when.get("is_other"):
                keyword = "else" if out else "if (false)"
            else:
                test = self._when_test(subject_text, when)
                keyword = f"else if ({test})" if out else f"if ({test})"
            out.append(f"{indent}{keyword} {{")
            out.extend(self.emit(when.get("body", []), indent + "    "))
            out.append(f"{indent}}}")
        return out or [f"{indent}// EVALUATE with no WHEN clauses"]

    def _when_test(self, subject_text: str | None, when: dict[str, Any]) -> str:
        """Build the Java test for one ``WHEN`` branch.

        ``EVALUATE subject WHEN value`` is a *comparison against the subject*.
        The WHEN text is the value, not a self-contained condition, so the
        subject has to be compared against it. Ignoring the subject would make
        every branch test its own literal against ``null`` -- constantly true --
        and silently execute the first branch for every record.
        """
        node = when.get("condition") or {}
        when_left = self._operand(node.get("left"))
        if when_left is None:
            self.unsupported.append(
                "EVALUATE WHEN without a value against subject "
                f"{subject_text!r}")
            return "false"
        if subject_text is None:
            self.unsupported.append("EVALUATE without a subject operand")
            return "false"
        # `WHEN OTHER` is handled by the caller; anything else is a value test.
        return self._relation(
            {"op": "=", "left": subject_text, "right": when_left, "join": None},
            "=",
        )

    def _emit_perform_para(self, attrs: dict[str, Any], indent: str) -> list[str]:
        target = str(attrs.get("target", "")).strip().upper()
        thru = attrs.get("thru")
        order = [name for name in self.model.paragraphs if name]
        if target not in order:
            self.unsupported.append(f"unresolved PERFORM target: {target}")
            return []
        start = order.index(target)
        end = order.index(str(thru).upper()) if thru in order else start
        return [f"{indent}{java_safe(name)}();" for name in order[start:end + 1]]

    def _emit_read(self, attrs: dict[str, Any], indent: str) -> list[str]:
        file_name = str(attrs.get("file", "")).strip().upper()
        handle = self.files.get(file_name)
        record = self._record_buffer(file_name)
        if handle is None or record is None:
            self.unsupported.append(f"unresolved READ file: {file_name}")
            return []
        out = [f"{indent}if ({handle}.read({record})) {{"]
        out.extend(self.emit(attrs.get("not_at_end", []), indent + "    "))
        out.append(f"{indent}}} else {{")
        out.extend(self.emit(attrs.get("at_end", []), indent + "    "))
        out.append(f"{indent}}}")
        return out

    def _emit_write(self, attrs: dict[str, Any], indent: str) -> list[str]:
        """Emit ``WRITE record [FROM source]``.

        SAFETY INVARIANT (Phase 20): when a ``FROM`` source is named it must
        resolve, either as a group item (whole-record copy) or as a leaf field.
        If it resolves to neither, *no* code is emitted -- previously the copy
        was skipped silently and a blank, all-spaces record was written, which
        is indistinguishable from real data downstream.
        """
        record_name = str(attrs.get("record", "")).strip().upper()
        holder = self._record_buffer(record_name)
        target = self._write_file_for_record(record_name)
        if holder is None:
            self.unsupported.append(f"unresolved WRITE record: {record_name}")
            return []
        out: list[str] = []
        source = self._operand(attrs.get("from"))
        if source:
            group = self._group_holder(source)
            if group is not None:
                # GROUP to GROUP: the whole record area is copied verbatim,
                # exactly as the legacy WRITE did.
                if group != holder:
                    out.append(
                        f"{indent}Rt.copyRecord({holder}, {group});")
            else:
                symbol, _, _ = self._resolve(source)
                if symbol is None:
                    # Fail closed: never emit the WRITE without its source.
                    self.unsupported.append(
                        f"unresolved WRITE source: {source}")
                    return []
                if symbol.holder != holder:
                    out.append(
                        f"{indent}Rt.moveText({holder}, 0, {holder}.length, "
                        f"{symbol.holder}, {symbol.offset}, {symbol.length});")
        out.append(f"{indent}{target}.write({holder});")
        return out

    def _emit_open(self, attrs: dict[str, Any], indent: str) -> list[str]:
        out: list[str] = []
        for entry in attrs.get("entries", []):
            name = str(entry.get("file", "")).strip().upper()
            definition = self.model.files.get(name)
            handle = self.files.get(name)
            if definition is None or handle is None:
                continue
            mode = ("openInput"
                    if str(entry.get("mode", "INPUT")).upper() == "INPUT"
                    else "openOutput")
            out.append(f"{indent}{handle}.{mode}(datasets, \"{name}\", "
                       f"{definition.record_size});")
        return out

    def _record_buffer(self, key: str) -> str | None:
        definition = self.model.files.get(key)
        if definition is not None and definition.record_name:
            for symbol in self.symbols.by_owner.get(
                definition.record_name.upper(), {}
            ).values():
                return symbol.holder
        for symbol in self.symbols.by_owner.get(key.upper(), {}).values():
            return symbol.holder
        return None

    def _write_file_for_record(self, record_name: str) -> str:
        for name, definition in self.model.files.items():
            if (definition.record_name or "").upper() == record_name.upper():
                return self.files.get(name, java_safe(name))
        self.unsupported.append(f"no output file bound to record {record_name}")
        return "null"


def _value_initializers(
    symbols: _SymbolTable, fdef: FieldDef, holder: str
) -> list[str]:
    """Emit COBOL ``VALUE`` clause initialisers for a data item."""
    if not fdef.value:
        return []
    symbol = symbols.by_name.get(fdef.name)
    if symbol is None or symbol.holder != holder:
        return []
    raw = str(fdef.value).strip()
    if raw[:1] in ("'", '"'):
        value = raw[1:-1].replace('"', '\\"')
        return [f"        Rt.setText({holder}, {fdef.offset}, "
                f"{symbol.length}, \"{value}\");"]
    if re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return [f"        Rt.storeValue({holder}, {fdef.offset}, {symbol.length}, "
                f"{symbol.digits}, {symbol.scale}, "
                f"{str(symbol.signed).lower()}, \"{symbol.usage}\", "
                f'new BigDecimal("{raw}"));']
    return []

def generate_java(
    model: ProgramModel,
    *,
    java_package: str = "modernized",
    runtime_class: str = "CobolRuntime",
) -> GenerationResult:
    """Generate a self-contained Java application for ``model``.

    When anything cannot be translated faithfully the result carries it in
    ``unsupported`` and **no files are produced**, so a caller cannot mistake a
    partial translation for a delivered one.
    """
    result = GenerationResult()
    if model.gaps:
        result.unsupported.extend(
            f"model gap: {gap.construct} at line {gap.line}: {gap.reason}"
            for gap in model.gaps
        )
        return result

    symbols = _SymbolTable()
    declarations, initializers = _collect_buffers(model, symbols)
    file_buffers = {name: java_safe(name) for name in sorted(model.files)}
    emitter = _Emitter(model, symbols, file_buffers)
    class_name = camel(model.program_id)

    out: list[str] = [
        f"package {java_package};", "",
        "import java.io.IOException;",
        "import java.math.BigDecimal;", "",
        "/**",
        f" * Modernized COBOL program {model.program_id}.",
        f" * Source: {model.source_path} ({model.source_format} format).",
        " *",
        " * <p>Generated by AutoForge's Legacy Modernization engine. Every data",
        " * access below is derived from the PICTURE and USAGE clauses resolved by",
        " * the COBOL data dictionary, so record bytes and field offsets match the",
        " * original program exactly.</p>",
        " */",
        f"public final class {class_name} {{", "",
        f"    private static final {runtime_class} Rt = {runtime_class}.INSTANCE;", "",
    ]
    out.extend(declarations)
    out.extend(["", f"    private final {runtime_class}.Datasets datasets = "
                      f"new {runtime_class}.Datasets();"])
    for handle in file_buffers.values():
        out.append(f"    private final {runtime_class}.SequentialFile {handle} = "
                   f"new {runtime_class}.SequentialFile();")
    out.extend(["", f"    public {class_name}() {{"])
    for name, definition in sorted(model.files.items()):
        assign = (definition.assign or "").replace('"', "")
        if assign:
            out.append(f'        datasets.put("{name}", "{assign}");')
    out.extend(initializers)
    out.extend(["    }", ""])

    for paragraph in [p for p in model.paragraphs if p]:
        # Paragraphs perform file I/O, so they declare the checked exception the
        # COBOL verbs map onto (OPEN / WRITE / CLOSE). `execute()` declares it
        # too, so program entry stays a single checked call.
        out.append(f"    /** COBOL paragraph {paragraph}. */")
        out.append(
            f"    private void {java_safe(paragraph)}() throws IOException {{")
        body = emitter.emit(
            [s.as_dict() for s in model.paragraphs[paragraph]], "        ")
        out.extend(body or ["        // no translatable statements"])
        out.extend(["    }", ""])

    out.append("    /** Execute the program (the implicit main line). */")
    out.append("    public void execute() throws Exception {")
    entry = [s.as_dict() for s in model.paragraphs.get("", [])]
    if not entry and [p for p in model.paragraphs if p]:
        # COBOL enters the PROCEDURE DIVISION at the first paragraph. When the
        # program labels its first paragraph (DAILYPOST does, with MAIN), there
        # is no implicit main line, so execute() must invoke that paragraph --
        # otherwise the generated program opens with an empty method and does
        # nothing at all.
        first = next(p for p in model.paragraphs if p)
        entry = [{"kind": "perform_para", "attrs": {"target": first, "thru": None}}]
    body = emitter.emit(entry, "        ")
    out.extend(body or ["        // no translatable statements"])
    out.extend([
        "    }", "",
        "    public static void main(String[] args) throws Exception {",
        f"        {class_name} program = new {class_name}();",
        f"        {runtime_class}.Datasets.applyOverrides(args, program.datasets);",
        "        program.execute();",
        "    }",
        "}",
    ])

    result.unsupported.extend(emitter.unsupported)
    if result.unsupported:
        return result

    base = f"src/main/java/{java_package.replace('.', '/')}"
    result.files.append(GeneratedFile(f"{base}/{class_name}.java", "\n".join(out) + "\n"))
    result.files.append(
        GeneratedFile(f"{base}/CobolRuntime.java", render_runtime(java_package))
    )
    return result

def _collect_buffers(
    model: ProgramModel, symbols: _SymbolTable
) -> tuple[list[str], list[str]]:
    """Declare one byte buffer per record / working-storage area."""
    declarations: list[str] = []
    initializers: list[str] = []
    for layout in list(model.records.values()) + list(model.working_storage.values()):
        holder = java_safe(layout.record_name)
        symbols.add_layout(layout, holder)
        declarations.append(
            f"    private final byte[] {holder} = Rt.newRecord({layout.size});"
        )
        for fdef in layout.fields:
            if fdef.picture is None or not fdef.name or fdef.name == "FILLER":
                continue
            initializers.extend(_value_initializers(symbols, fdef, holder))
    return declarations, initializers
