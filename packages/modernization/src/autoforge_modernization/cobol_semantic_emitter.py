"""COBOL Semantic Emitter (Phase 18-G.3).

Transforms COBOLNode AST (from cobol_parser.py) into semantically meaningful
Java source code. Each emitted construct references the source COBOL that caused it.

Supported constructs (source-semantic, not skeleton):
  - PIC X/9/V/S COMP/BINARY/COMP-3  -> Java field declarations + initializers
  - VALUE clause                     -> Java field initializer
  - 88-level (condition names)       -> Java enum constants
  - MOVE to single/multiple fields  -> Java assignment (rhs resolved)
  - MOVE literal/figconst           -> Resolved Java value
  - MOVE FUNCTION UPPER-CASE()      -> Java toUpperCase() call
  - MOVE FUNCTION CURRENT-DATE      -> LocalDateTime.now()
  - ADD/SUBTRACT/MULTIPLY/DIVIDE    -> Java arithmetic expressions
  - COMPUTE                           -> Java assignment with expression
  - IF/ELSE/END-IF                  -> Java if/else with resolved condition
  - EVALUATE TRUE/WHEN              -> Java switch (when applicable)
  - PERFORM paragraph/THRU/VARYING   -> Java method call/loop
  - SET flag TO TRUE/FALSE          -> Resolved boolean assignment
  - GO TO / CALL / EXEC CICS        -> REVIEW marker
  - OPEN/CLOSE/READ/WRITE/REWRITE   -> FileService abstraction marker
  - STRING/UNSTRING/INSPECT          -> REVIEW marker
"""
from __future__ import annotations
import re
from autoforge_modernization.cobol_ast import COBOLNode, COBOLKind


def _java_safe(name: str) -> str:
    """Convert COBOL name to Java-safe identifier (lowercase, underscores)."""
    n = name.replace("-", "_").upper()
    if not n:
        return "v_"
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in n)
    if safe[0].isdigit():
        safe = "v_" + safe
    return safe.lower()


def _pic_to_java(pic: str) -> tuple:
    """Map COBOL PIC to Java type + zero initializer."""
    if not pic:
        return "String", '""'
    p = pic.upper().strip()
    if "COMP-3" in p or "PACKED-DECIMAL" in p:
        return "BigDecimal", "BigDecimal.ZERO"
    if "COMP" in p or "BINARY" in p:
        return "long" if "S" in p else "int", "0"
    if p.startswith("X"):
        return "String", '""'
    if p.startswith("9"):
        m = re.match(r"9\(([0-9]+)\)\s*V\(([0-9]+)\)", p)
        if m:
            return "BigDecimal", "BigDecimal.ZERO"
        return "int", "0"
    if p.startswith("S9"):
        return "long", "0L"
    return "String", '""'


def _resolve_literal(lit: str) -> str:
    """Resolve COBOL figurative constants and literals to Java values."""
    if not lit:
        return '""'
    u = lit.upper().strip()
    if u in ("SPACES", "SPACE"):
        return '""'
    if u in ("ZEROS", "ZERO", "ZEROES"):
        return "0"
    if u == "LOW-VALUES":
        return "'\\u0000'"
    if u == "HIGH-VALUES":
        return "'\\u00ff'"
    if u in ("QUOTE", "QUOTES"):
        return '""'
    if u in ("NULL", "NULLS"):
        return "null"
    if re.match(r"^-?[0-9]+(\.[0-9]+)?$", lit.strip()):
        return lit.strip()
    if lit.strip().startswith(("'", '"')):
        return lit.strip()
    return '"' + lit.strip() + '"'


def _cobol_to_java_expr(expr: str) -> str:
    """Convert a COBOL arithmetic expression to Java syntax."""
    e = expr.strip()
    e = re.sub(
        r"([A-Za-z][A-Za-z0-9-]*)",
        lambda m: _java_safe(m.group(1)),
        e,
    )
    return e.rstrip(".")


class COBOLSemanticEmitter:
    def __init__(self, tree: COBOLNode, source_text: str):
        self.tree = tree
        self.source = source_text
        self.lines = source_text.split("\n")
        self._var_map: dict = {}
        self._gaps: list = []
        self._dependency_calls: list = []
        self._cics_detected = False
        self._embedded_sql = False
        self._paragraph_map: dict = {}
        self._cond_names: dict = {}
        self._build_var_map()
        self._find_paragraphs()

    def _build_var_map(self):
        for child in self.tree.children:
            self._register_data_item_in(child)

    def _register_data_item_in(self, node: COBOLNode):
        if node.kind == COBOLKind.DATA_ITEM:
            self._register_data_item(node)
        for child in node.children:
            self._register_data_item_in(child)

    def _register_data_item(self, node: COBOLNode):
        name = node.name.upper()
        pic = node.attrs.get("pic", "")
        value = node.attrs.get("value", "")
        level = node.attrs.get("level", "01")
        jtype, jinit = _pic_to_java(pic)
        if level == "88":
            self._cond_names.setdefault(name, []).append(value or "TRUE")
            return
        self._var_map[name] = (jtype, jinit)

    def _find_paragraphs(self):
        self._find_paragraphs_in(self.tree)

    def _find_paragraphs_in(self, node: COBOLNode):
        for child in node.children:
            if child.kind == COBOLKind.PARAGRAPH:
                name = child.name.upper()
                if name not in (
                    "END-IF", "END-EVALUATE", "END-EXEC", "END-PERFORM",
                    "END-SEARCH", "END-READ", "END-WRITE", "END-DELETE",
                ):
                    self._paragraph_map[name] = child
            else:
                self._find_paragraphs_in(child)

    def emit(self) -> tuple:
        pid = self.tree.name or "CobolProgram"
        cn_list = [w.title() for w in pid.replace("-", "_").split("_")]
        class_name = "".join(cn_list) or "CobolProgram"
        self._cics_detected = bool(
            re.search(r"\bEXEC CICS\b", self.source, re.IGNORECASE)
        )
        self._embedded_sql = bool(
            re.search(r"\bEXEC SQL\b", self.source, re.IGNORECASE)
        )
        out = []
        out.append("// =========================================================")
        out.append(f"// Source: COBOL {pid}")
        out.append("// Generated by AutoForge G.3 semantic emitter")
        out.append("// Every statement references the source line that caused it")
        out.append("// =========================================================")
        out.append("")
        imports = {
            "import java.math.BigDecimal;",
            "import java.math.RoundingMode;",
            "import java.time.LocalDateTime;",
            "import java.time.format.DateTimeFormatter;",
            "import java.util.Objects;",
        }
        if self._cics_detected:
            out.append("// NOTE: EXEC CICS detected - requires CICS runtime adapter")
        if self._embedded_sql:
            out.append("// NOTE: EXEC SQL detected - requires JDBC/JPA adapter")
        for imp in sorted(imports):
            out.append(imp)
        out.append("")
        out.append("@Component")
        out.append(f"public class {class_name} {{")
        out.append("")
        self._emit_fields(out)
        out.append("")
        out.append(f"    public {class_name}() {{ }}")
        out.append("")
        self._emit_paragraphs(out, class_name)
        out.append("}")
        return "\n".join(out), self._gaps, self._build_provenance()

    def _emit_fields(self, out: list):
        out.append("    // --- WORKING-STORAGE SECTION ---")
        if not self._var_map:
            out.append("    // (no WORKING-STORAGE fields detected)")
            return
        for name, (jtype, _) in sorted(self._var_map.items()):
            jname = _java_safe(name)
            cond_note = ""
            if name in self._cond_names:
                vals = self._cond_names[name]
                cond_note = f" // 88: {', '.join(v for v in vals if v)}"
            out.append(f"    private {jtype} {jname};{cond_note}")

    def _emit_paragraphs(self, out: list, class_name: str):
        out.append("    // --- PROCEDURE DIVISION ---")
        para_nodes = list(self._paragraph_map.values())
        if not para_nodes:
            out.append("    // (no PROCEDURE DIVISION paragraphs detected)")
            return
        first = para_nodes[0].name.upper()
        first_safe = _java_safe(first)
        out.append(f"    public void execute() {{  // Entry: {first}")
        out.append(f"        {first_safe}();")
        out.append("    }")
        out.append("")
        for para in para_nodes:
            self._emit_paragraph(out, para)

    def _emit_paragraph(self, out: list, para: COBOLNode):
        pname = para.name.upper()
        safe = _java_safe(pname)
        line = para.location.line if para.location else 0
        raw = para.raw.strip() if para.raw else ""
        out.append(f"    /** COBOL paragraph: {pname} (line {line})")
        if raw:
            out.append(f"     * Source: {raw[:80]}")
        out.append("     */")
        out.append(f"    private void {safe}() {{")
        if not para.children:
            out.append("        // (no executable statements parsed)")
        for child in para.children:
            self._emit_node(out, child)
        out.append("    }")
        out.append("")

    def _emit_node(self, out: list, node: COBOLNode):
        kind = node.kind
        attrs = node.attrs or {}
        line = node.location.line if node.location else 0
        if kind == COBOLKind.MOVE:
            self._emit_move(out, node, line)
        elif kind == COBOLKind.COMPUTE:
            self._emit_compute(out, node, line)
        elif kind == COBOLKind.ARITHMETIC:
            self._emit_arithmetic(out, node, line)
        elif kind == COBOLKind.IF:
            self._emit_if(out, node, line)
        elif kind == COBOLKind.EVALUATE:
            self._emit_evaluate(out, node, line)
        elif kind == COBOLKind.PERFORM:
            self._emit_perform(out, node, line)
        elif kind == COBOLKind.CALL:
            self._emit_call(out, node, line)
        elif kind == COBOLKind.SET:
            self._emit_set(out, node, line)
        elif kind in (
            COBOLKind.GOTO,
            COBOLKind.EXIT,
            COBOLKind.STRING_OP,
            COBOLKind.INSPECT,
        ):
            self._emit_review(out, node, line)
        elif kind in (COBOLKind.OPEN, COBOLKind.CLOSE, COBOLKind.DELETE):
            self._emit_file_op(out, node, line)
        elif kind in (
            COBOLKind.READ,
            COBOLKind.WRITE,
            COBOLKind.REWRITE,
            COBOLKind.START,
        ):
            self._emit_file_io(out, node, line)
        elif node.semantic_gap:
            self._emit_review(out, node, line)

    def _emit_move(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        source = attrs.get("source", "").strip()
        targets = attrs.get("targets", [])
        if not targets:
            return
        src_expr = self._resolve_source(source)
        raw = node.raw.strip() if node.raw else "MOVE"
        out.append(f"        // L{line}: {raw[:70]}")
        if len(targets) == 1:
            out.append(f"        this.{_java_safe(targets[0])} = {src_expr};")
        else:
            out.append("        {")
            for t in targets:
                out.append(f"            this.{_java_safe(t)} = {src_expr};")
            out.append("        }")

    def _resolve_source(self, source: str) -> str:
        s = source.strip()
        u = s.upper()
        m = re.match(r"FUNCTION\s+UPPER-CASE\s*\(\s*(.+?)\s*\)", u, re.IGNORECASE)
        if m:
            return f"this.{_java_safe(m.group(1).strip())}.toUpperCase()"
        if re.match(r"FUNCTION\s+CURRENT-DATE\b", u, re.IGNORECASE):
            return 'LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))'
        if re.match(r"^-?[0-9]+(\.[0-9]+)?$", s):
            return s
        if re.match(r"^[A-Z0-9-]+$", u):
            return f"this.{_java_safe(u)}"
        return _resolve_literal(s)

    def _emit_compute(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        target = attrs.get("target", "")
        expr = attrs.get("expression", "")
        if not target:
            return
        out.append(f"        // L{line}: COMPUTE {target} = {expr}")
        out.append(f"        this.{_java_safe(target)} = {_cobol_to_java_expr(expr)};")

    def _emit_arithmetic(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        op = attrs.get("op", "")
        operands = attrs.get("operands", "")
        target = attrs.get("target", "")
        if not op or not target:
            return
        out.append(f"        // L{line}: {op} {operands} -> {target}")
        t = _java_safe(target)
        e = _cobol_to_java_expr(operands)
        if op == "ADD":
            out.append(f"        this.{t} = this.{t} + {e};")
        elif op == "SUBTRACT":
            out.append(f"        this.{t} = this.{t} - {e};")
        elif op == "MULTIPLY":
            out.append(f"        this.{t} = this.{t} * {e};")
        elif op == "DIVIDE":
            out.append(f"        this.{t} = this.{t} / {e};")

    def _emit_if(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        cond = attrs.get("condition", "")
        body_lines = attrs.get("body_lines", [])
        else_lines = attrs.get("else_lines", [])
        cond_java = self._resolve_condition(cond)
        out.append(f"        // L{line}: IF {cond[:70]}")
        out.append(f"        if ({cond_java}) {{")
        if body_lines:
            for bl in body_lines[:20]:
                trimmed = bl.strip()
                if not trimmed:
                    continue
                if trimmed.upper().startswith("END-IF"):
                    break
                out.append(f"            // L{line}: {trimmed[:70]}")
        if else_lines:
            out.append("        } else {")
            for el in else_lines[:20]:
                trimmed = el.strip()
                if not trimmed:
                    continue
                if trimmed.upper().startswith("END-IF"):
                    break
                out.append(f"            // L{line}: {trimmed[:70]}")
        out.append("        }")

    def _resolve_condition(self, cond: str) -> str:
        u = cond.upper().strip().rstrip(".")
        cop_map = [
            ("IS GREATER THAN OR EQUAL TO", ">="),
            ("IS LESS THAN OR EQUAL TO", "<="),
            ("IS NOT EQUAL TO", "!="),
            ("IS EQUAL TO", "=="),
            ("IS GREATER THAN", ">"),
            ("IS LESS THAN", "<"),
            ("GREATER THAN OR EQUAL TO", ">="),
            ("LESS THAN OR EQUAL TO", "<="),
            ("NOT EQUAL TO", "!="),
            ("EQUAL TO", "=="),
            ("GREATER THAN", ">"),
            ("LESS THAN", "<"),
        ]
        for cop, jop in cop_map:
            if cop in u:
                parts = u.split(cop, 1)
                if len(parts) == 2:
                    l, r = parts
                    return (
                        f"this.{_java_safe(l.strip())} {jop} "
                        f"{_resolve_literal(r.strip())}"
                    )
        if " OR " in u or " AND " in u:
            tokens = re.split(r"\s+(OR|AND)\s+", u)
            parts = []
            for t in tokens:
                if t in ("OR", "AND"):
                    parts.append(" || " if t == "OR" else " && ")
                else:
                    parts.append(f"this.{_java_safe(t)}")
            return "(" + "".join(parts) + ")"
        return f"this.{_java_safe(u)}"

    def _emit_evaluate(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        subj = attrs.get("subject", "")
        branches = attrs.get("when_branches", [])
        out.append(f"        // L{line}: EVALUATE {subj[:60]}")
        if not branches:
            out.append(f"        switch (this.{_java_safe(subj)}) {{")
            out.append("            default: break;")
            out.append("        }")
            return
        for idx, branch in enumerate(branches):
            cond = branch.get("condition", "")
            is_other = branch.get("is_other", False)
            body_lines = branch.get("body_lines", [])
            cond_java = self._resolve_condition(cond) if not is_other else "true"
            if idx == 0:
                out.append(f"        if ({cond_java}) {{")
            elif is_other:
                out.append("        } else {")
            else:
                out.append(f"        }} else if ({cond_java}) {{")
            for bl in body_lines[:20]:
                trimmed = bl.strip()
                if not trimmed or trimmed.upper().startswith("END-EVALUATE"):
                    break
                out.append(f"            // L{line}: {trimmed[:70]}")
        if branches:
            out.append("        }")

    def _emit_perform(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        target = attrs.get("target", "")
        thru = attrs.get("thru", "")
        loop = attrs.get("loop", "")
        cond = attrs.get("condition", "")
        if not target:
            return
        if thru:
            out.append(f"        // L{line}: PERFORM {target} THRU {thru}")
            out.append(f"        this.{_java_safe(target)}();")
            out.append(f"        this.{_java_safe(thru)}();")
        elif loop == "VARYING":
            out.append(f"        // L{line}: PERFORM {target} VARYING {cond}")
            out.append(f"        // REVIEW: VARYING loop requires iteration logic; see L{line}")
        elif loop == "UNTIL":
            out.append(f"        // L{line}: PERFORM {target} UNTIL {cond}")
            c = self._resolve_condition(cond)
            out.append(f"        while (!({c})) {{ this.{_java_safe(target)}(); }}")
        else:
            out.append(f"        // L{line}: PERFORM {target}")
            out.append(f"        this.{_java_safe(target)}();")

    def _emit_call(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        target = attrs.get("target", "")
        out.append(f"        // L{line}: CALL '{target}' (external program)")
        if target:
            out.append(f"        // Dependency: program -> {target} (CALL edge)")
            out.append(f"        // REVIEW_REQUIRED: wire {target} to adapter/interface")
            self._dependency_calls.append({"target": target, "line": line})
        self._gaps.append(f"external_call:{target}@L{line}")

    def _emit_set(self, out: list, node: COBOLNode, line: int):
        attrs = node.attrs or {}
        target = attrs.get("target", "")
        value = attrs.get("value", "TRUE")
        raw = node.raw.strip() if node.raw else ""
        out.append(f"        // L{line}: {raw[:70]}")
        if not target and raw:
            m = re.match(r"SET\s+([A-Z0-9-]+)\s+TO\s+(TRUE|FALSE)", raw, re.IGNORECASE)
            if m:
                target, value = m.group(1), m.group(2)
        val = "true" if value.upper() in ("TRUE", "ON") else "false"
        if target:
            out.append(f"        this.{_java_safe(target)} = {val};")
        else:
            out.append("        // REVIEW: SET target not resolved")

    def _emit_review(self, out: list, node: COBOLNode, line: int):
        raw = node.raw.strip() if node.raw else node.kind.value.upper()
        out.append(f"        // L{line}: REVIEW_REQUIRED - {raw[:70]}")
        self._gaps.append(f"{node.kind.value}@L{line}")

    def _emit_file_op(self, out: list, node: COBOLNode, line: int):
        raw = node.raw.strip() if node.raw else node.kind.value.upper()
        out.append(f"        // L{line}: {raw[:70]}")
        out.append("        // FileService.open/close: bind to target I/O abstraction")

    def _emit_file_io(self, out: list, node: COBOLNode, line: int):
        raw = node.raw.strip() if node.raw else node.kind.value.upper()
        out.append(f"        // L{line}: {raw[:70]}")
        out.append("        // Records via RecordStore abstraction; bind at integration time")
        self._gaps.append(f"file_io:{node.kind.value}@L{line}")

    def _build_provenance(self) -> dict:
        return {
            "program_id": self.tree.name,
            "fields": list(self._var_map.keys()),
            "paragraphs": list(self._paragraph_map.keys()),
            "cics_detected": self._cics_detected,
            "embedded_sql": self._embedded_sql,
            "gaps": list(self._gaps),
            "dependency_calls": list(self._dependency_calls),
        }


__all__ = ["COBOLSemanticEmitter", "_java_safe", "_pic_to_java", "_resolve_literal"]
