"""G.3 Transformation Strategies - Real bounded transformation implementations."""
from __future__ import annotations
import re
from typing import Callable

# ── Helpers ────────────────────────────────────────────────────────────────────


def _indent(lines: list[str], by: int = 4) -> list[str]:
    """Add indentation to each non-empty line."""
    pad = " " * by
    return [pad + l if l.strip() else l for l in lines]

def _unescape_cobol_name(name: str) -> str:
    """Convert COBOL names (hyphenated) to valid Java identifiers."""
    return name.replace('-', '_').replace('$', '_').upper()


def _java_safe_name(name: str) -> str:
    """
    Convert a COBOL paragraph name to a valid Java identifier.

    Java identifiers must start with a letter, $, or _. COBOL allows names
    starting with a digit (e.g., '0000-MAIN'). We prefix with 'p_' to
    preserve information without producing invalid Java.
    """
    safe = name.replace('-', '_').replace('$', '_').lower()
    if not safe or not (safe[0].isalpha() or safe[0] == '_'):
        safe = "p_" + safe
    return safe


def _cobol_type_from_pic(pic: str) -> tuple[str, str]:
    """
    Map a COBOL PIC clause to a Java type and initializer.
    Returns (java_type, default_value).
    """
    pic = pic.upper().strip()
    if pic.startswith('X') or pic.startswith('X('):
        return "String", '""'
    if pic.startswith('9') or pic.startswith('9('):
        digits = re.sub(r'[^9V]', '', pic.upper())
        if 'V' in pic.upper():
            return "BigDecimal", "BigDecimal.ZERO"
        if 'S' in pic.upper():
            return "long", "0L"
        if len(digits) > 9:
            return "BigDecimal", "BigDecimal.ZERO"
        if len(digits) > 5:
            return "long", "0L"
        return "int", "0"
    if pic.startswith('S9'):
        return "long", "0L"
    if 'COMP' in pic or 'BINARY' in pic:
        return "int", "0"
    if 'COMP-3' in pic or 'PACKED' in pic:
        return "BigDecimal", "BigDecimal.ZERO"
    return "String", '""'


# ── COBOL extraction helpers (used by _cobol_to_java) ───────────────────────


def _cobol_extract_program(lines: list[str]) -> str:
    """Return PROGRAM-ID from COBOL source lines."""
    prog_id = "CobolProgram"
    for line in lines:
        m = re.search(r'\bPROGRAM-ID\.?\s*\.?\s*([A-Z0-9][A-Z0-9-]*)', line, re.IGNORECASE)
        if m:
            prog_id = m.group(1).upper()
            break
    return prog_id


def _cobol_extract_ws(lines: list[str]) -> list[dict]:
    """
    Extract WORKING-STORAGE fields with PIC, VALUE, REDEFINES.

    Returns list of dicts: {level, name, pic, java_type, value, redefines}.
    """
    fields: list[dict] = []
    in_ws = False
    for line in lines:
        ls = line.strip()
        if not ls or (len(ls) > 6 and ls[6:7] in ('*', '/', 'D', 'd')):
            continue
        if re.search(r'\bWORKING-STORAGE\b', ls, re.IGNORECASE):
            in_ws = True
            continue
        if re.search(r'\bPROCEDURE\s+DIVISION\b', ls, re.IGNORECASE):
            in_ws = False
            continue
        if not in_ws:
            continue
        m = re.match(
            r'\s*(0?\d|77|88)\s+([A-Z0-9-]+)(\s+REDEFINES\s+([A-Z0-9-]+))?(\s+PIC\s+(\S+))?(\s+VALUE\s+(\S+))?',
            ls, re.IGNORECASE,
        )
        if m:
            level = m.group(1)
            name = _unescape_cobol_name(m.group(2))
            redefines = m.group(4)
            pic = (m.group(6) or "").upper().rstrip('.')
            value = (m.group(8) or "").rstrip('.')
            java_type, _ = _cobol_type_from_pic(pic) if pic else ("String", '""')
            fields.append({
                "level": level,
                "name": name,
                "pic": pic,
                "java_type": java_type,
                "value": value,
                "redefines": redefines,
            })
    return fields


def _cobol_extract_files(lines: list[str]) -> list[dict]:
    """Extract SELECT ... ASSIGN TO ... file declarations."""
    files: list[dict] = []
    for line in lines:
        ls = line.strip()
        if not ls or (len(ls) > 6 and ls[6:7] in ('*', '/', 'D', 'd')):
            continue
        m = re.search(r'\bSELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+TO\s+([\w-]+)', ls, re.IGNORECASE)
        if m:
            files.append({
                "name": _unescape_cobol_name(m.group(1)),
                "external": m.group(2),
            })
    return files


def _cobol_extract_copybooks(lines: list[str]) -> list[str]:
    return list({
        m.group(2).rstrip('.')
        for line in lines
        for m in [re.search(r'\bCOPY\s+([\'"]?)([\w.-]+)\1', line, re.IGNORECASE)]
        if m
    })


_PARAGRAPH_RESERVED = {
    "IF", "ELSE", "END-IF", "THEN", "EVALUATE", "WHEN", "END-EVALUATE",
    "PERFORM", "END-PERFORM", "CALL", "END-CALL", "UNTIL", "VARYING",
    "TIMES", "THRU", "THROUGH", "WITH", "TEST", "AFTER", "BEFORE",
    "CONTINUE", "STOP", "RUN", "GOBACK", "EXIT", "GO", "TO",
    "PROGRAM-ID", "AUTHOR", "INSTALLATION", "DATE-WRITTEN",
    "DATE-MODIFIED", "SECURITY", "REMARKS", "FUNCTION",
    "IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE",
    "DIVISION", "SECTION", "FD", "SD", "RD",
    "WORKING-STORAGE", "LINKAGE", "FILE", "REPORT",
    "PICTURE", "PIC", "REDEFINES", "VALUE", "OCCURS", "INDEXED",
    "OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "DELETE", "START",
    "DISPLAY", "ACCEPT", "MOVE", "COMPUTE", "ADD", "SUBTRACT",
    "MULTIPLY", "DIVIDE", "STRING", "UNSTRING", "INSPECT",
    "SEARCH", "SET", "INITIALIZE", "VALIDATE",
    "EXEC", "SQL", "CICS", "END", "OF", "IN", "IS", "ARE",
    "ON", "SIZE", "ERROR", "EXCEPTION", "NOT", "INVALID",
    "AT", "END-OF-PAGE", "END-OF-FILE", "TALLYING", "REPLACING",
    "CONVERTING", "USING", "FROM", "BY", "REFERENCE",
    "INTO", "DELIMITED", "POINTER", "ALL", "LEADING", "TRAILING",
}


def _cobol_extract_paragraphs(lines: list[str]) -> list[dict]:
    """
    Extract paragraph definitions and approximate body content.
    Returns list of dicts: {name, body_lines, perform_targets, calls, moves, ifs, evaluates}.
    """
    paragraphs: list[dict] = []
    current: dict | None = None
    for line in lines:
        ls = line.strip()
        if not ls or (len(ls) > 6 and ls[6:7] in ('*', '/', 'D', 'd')):
            continue
        m = re.match(r'^([A-Z0-9][A-Z0-9-]*)\s*\.', ls)
        if m and len(m.group(1)) < 32 and m.group(1).upper() not in _PARAGRAPH_RESERVED:
            if current:
                paragraphs.append(current)
            original = m.group(1)
            current = {
                "name": _unescape_cobol_name(original),
                "java_name": _java_safe_name(original),
                "perform_targets": [],
                "calls": [],
                "moves": [],
                "ifs": 0,
                "performs": 0,
                "evaluates": 0,
            }
            continue
        if current is None:
            continue
        for pm in re.finditer(
            r'\bPERFORM\s+([A-Z0-9-]+)(?:\s+(?:THRU|THROUGH)\s+([A-Z0-9-]+))?',
            ls, re.IGNORECASE,
        ):
            current["perform_targets"].append(
                _java_safe_name(_unescape_cobol_name(pm.group(1)))
            )
            current["performs"] += 1
        for cm in re.finditer(r'\bCALL\s+[\'"]?([A-Z0-9-]+)', ls, re.IGNORECASE):
            current["calls"].append(cm.group(1))
        for mm in re.finditer(
            r'\bMOVE\s+([A-Z0-9-]+)\s+TO\s+([A-Z0-9-]+)',
            ls, re.IGNORECASE,
        ):
            current["moves"].append(
                (_unescape_cobol_name(mm.group(1)),
                 _unescape_cobol_name(mm.group(2)))
            )
        if re.search(r'\bIF\b', ls, re.IGNORECASE):
            current["ifs"] += 1
        if re.search(r'\bEVALUATE\b', ls, re.IGNORECASE):
            current["evaluates"] += 1
    if current:
        paragraphs.append(current)
    return paragraphs
    if current:
        paragraphs.append(current)
    return paragraphs


# ── COBOL Technology Detection ─────────────────────────────────────────────────


_TECH_PATTERNS = {
    "CICS": [
        r"\bEXEC CICS\b",
        r"\bDFHCEPU1\b",
        r"\bDFHPCRQ1\b",
    ],
    "BMS": [
        r"\bEXEC BMS\b",
        r"\bDFHMDI\b",
        r"\bDFHMDF\b",
        r"\bDFHMSU\b",
    ],
    "DB2": [
        r"\bEXEC SQL\b",
        r"\bDSNTIAR\b",
        r"\bDSNHLI\b",
        r"DSN\s*\(",
    ],
    "VSAM": [
        r"\bEXEC\s+AMS\b",
        r"\bIDCAMS\b",
        r"\bVSAM\b",
        r"\bKSDS\b",
        r"\bESDS\b",
        r"\bRRDS\b",
    ],
    "IMS": [
        r"\bEXEC\s+IMS\b",
        r"\bPCB\b",
        r"\bPSB\b",
        r"\bDLI\b",
    ],
    "SQL": [
        r"\bSELECT\b.*\bFROM\b",
        r"\bINSERT\b.*\bINTO\b",
        r"\bUPDATE\b.*\bSET\b",
        r"\bDELETE\b.*\bFROM\b",
    ],
}


def _cobol_extract_technologies(lines: list[str]) -> list[str]:
    """
    Detect special COBOL technologies present in source.

    Returns a list of detected technology names (e.g. ["DB2", "SQL", "VSAM"]).
    """
    content = "\n".join(lines).upper()
    detected = []
    for tech, patterns in _TECH_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                detected.append(tech)
                break
    return detected


# ── COBOL Dependency Graph ─────────────────────────────────────────────────────


def _cobol_extract_calls(lines: list[str]) -> list[str]:
    """
    Extract all external program calls from COBOL PROCEDURE DIVISION.

    Returns a deduplicated list of called program names.
    """
    content = "\n".join(lines)
    return list({
        m.group(1).strip("'\"").upper()
        for m in re.finditer(r"\bCALL\s+['\"]?([A-Z0-9-]+)['\"]?", content, re.IGNORECASE)
        if m
    })


# ── COBOL Refactor (Area B cleanup) ──────────────────────────────────────────


def _cobol_refactor(content: str, dialect: str | None = None) -> str:
    lines = content.split('\n')
    result_lines = []
    for line in lines:
        line_stripped = line.rstrip()
        if not line_stripped:
            result_lines.append(line_stripped)
            continue
        indicator = line[6:7] if len(line) > 6 else ' '
        if indicator in ('*', '/'):
            result_lines.append(line_stripped)
        elif indicator == '-':
            if result_lines:
                result_lines[-1] = result_lines[-1].rstrip() + line_stripped[7:].strip()
        elif indicator == 'D':
            result_lines.append('*DEBUG* ' + line_stripped[7:].strip())
        elif len(line_stripped) >= 8 and line_stripped[7:8] not in (' ', '*', '/', 'D', '-'):
            result_lines.append(line_stripped)
        else:
            result_lines.append(line_stripped)
    cleaned = []
    prev_blank = False
    for l in result_lines:
        blank = not l.strip()
        if blank and prev_blank:
            continue
        cleaned.append(l)
        prev_blank = blank
    return '\n'.join(cleaned)

def _jcl_to_workflow_config(content: str, tech: str | None = None) -> str:
    """
    Convert JCL to an Apache Airflow DAG-style YAML workflow config.

    Handles:
    - JOB cards (//JOBNAME JOB ...)
    - EXEC statements (//STEPNAME EXEC PGM=...)
    - DD dataset references (//DDNAME DD DSN=...)
    - INCLUDE/PROC references
    - COND parameters
    """
    lines = content.split('\n')
    # Find job card
    job_name = "BATCH_JOB"
    for line in lines:
        m = re.match(r'//(\S+)\s+JOB\b(.*)', line.strip(), re.IGNORECASE)
        if m:
            job_name = m.group(1)
            break

    steps: list[dict] = []
    datasets: list[dict] = []
    current_step: dict | None = None

    for line in lines:
        ls = line.strip()
        if not ls or ls.startswith('//*'):
            continue
        # Step start
        m_step = re.match(r'//(\S+)\s+EXEC\s+(.*)', ls, re.IGNORECASE)
        if m_step:
            if current_step:
                steps.append(current_step)
            params = m_step.group(2).strip()
            pgm_match = re.search(r'PGM=([\w.$#@]+)', params, re.IGNORECASE)
            current_step = {
                "name": m_step.group(1),
                "program": pgm_match.group(1) if pgm_match else "UNKNOWN",
                "params": params,
                "datasets": [],
            }
            continue
        # DD under step
        m_dd = re.match(r'//(\S+)\s+DD\s+(.*)', ls, re.IGNORECASE)
        if m_dd and current_step:
            dd_content = m_dd.group(2).strip()
            ds_match = re.search(r'DSN=([\w$.@#]+)', dd_content, re.IGNORECASE)
            disp_match = re.search(r'DISP=\((\S+?)\)', dd_content, re.IGNORECASE)
            ds_name = ds_match.group(1) if ds_match else "DATASET"
            entry = {
                "ddname": m_dd.group(1),
                "dsn": ds_name,
                "disposition": disp_match.group(1) if disp_match else "MOD",
            }
            current_step["datasets"].append(entry)
            datasets.append(entry)
            continue
        # INCLUDE / JCLLIB
        if 'JCLLIB' in ls.upper() or 'INCLUDE' in ls.upper():
            if current_step:
                current_step.setdefault("includes", []).append(ls)
        # COND
        m_cond = re.search(r'COND\s*=\(([^)]+)\)', ls, re.IGNORECASE)
        if m_cond and current_step:
            current_step["condition"] = m_cond.group(1)

    if current_step:
        steps.append(current_step)

    # Render as YAML
    out: list[str] = []
    out.append(f"# Auto-generated from JCL job: {job_name}")
    out.append(f"# Steps: {len(steps)}, Datasets: {len(datasets)}")
    out.append(f"# Verification: JCL is bounded — review COND, GDG, and IDCAMS before production.")
    out.append("dag:")
    out.append(f"  dag_id: {job_name.lower()}")
    out.append("  schedule_interval: '@daily'")
    out.append("  start_date: 2024-01-01")
    out.append("  catchup: false")
    out.append("  default_args:")
    out.append("    owner: autoforge-modernization")
    out.append("    retries: 0")
    out.append("tasks:")
    for s in steps:
        out.append(f"  - task_id: {s['name'].lower()}")
        out.append(f"    program: {s['program']}")
        if s.get("params"):
            out.append(f"    params: |")
            out.append(f"      {s['params']}")
        if s.get("condition"):
            out.append(f"    condition: \"{s['condition']}\"")
        if s["datasets"]:
            out.append("    datasets:")
            for d in s["datasets"]:
                out.append(f"      - ddname: {d['ddname']}")
                out.append(f"        dsn: {d['dsn']}")
                out.append(f"        disposition: {d['disposition']}")
    out.append("datasets:")
    seen = set()
    for d in datasets:
        if d["dsn"] in seen:
            continue
        seen.add(d["dsn"])
        out.append(f"  - name: {d['dsn']}")
        out.append(f"    type: sequential  # assume sequential; GDG/VSAM require migration")
    return '\n'.join(out)

def _properties_refactor(content: str, tech: str) -> str:
    lines = content.split('\n')
    result = [f"# Refactored from {tech} configuration"]
    for line in lines:
        ls = line.strip()
        if not ls or ls.startswith('#'):
            result.append(ls)
            continue
        result.append(ls)
    return '\n'.join(result)

def _unsupported_transform(content: str, tech: str) -> str:
    raise NotImplementedError(
        f"Transformation of {tech} is not supported. "
        "Set transformation_type to BLOCKED and use REWRITE for partial approaches. "
        "This transformation requires specialist tooling and human review."
    )

class G3TransformationStrategies:

    @staticmethod
    def get_strategy(source_technology: str, transformation_type: str) -> Callable[[str], str]:
        source_upper = source_technology.upper()
        tt_lower = transformation_type.lower()
        if source_upper == "COBOL":
            if tt_lower == "transpilation":
                return _cobol_to_java
            if tt_lower == "refactor":
                return _cobol_refactor
            return _unsupported_transform
        if source_upper in ("JCL", "JOB_CONTROL_LANGUAGE"):
            if tt_lower in ("reconfiguration", "rewrite"):
                return _jcl_to_workflow_config
            return _unsupported_transform
        if source_upper in ("SHELL", "BASH", "KSH", "ZSH"):
            if tt_lower == "reconfiguration":
                return lambda c, _tech=None: "# Refactored shell\n" + c
            return _unsupported_transform
        if source_upper in ("PROPERTIES", "XML", "YAML", "JSON"):
            if tt_lower in ("reconfiguration", "refactor"):
                return lambda c, tech=None: _properties_refactor(c, tech or source_upper)
            return _unsupported_transform
        if source_upper in ("SQL", "PL_SQL", "TRANSACT_SQL", "MYSQL_SQL"):
            if tt_lower in ("reconfiguration", "refactor"):
                return lambda c, tech=None: _properties_refactor(c, tech or source_upper)
            return _unsupported_transform
        if source_upper in ("ASSEMBLER", "ASM", "HLASM", "ASM370"):
            if tt_lower == "refactor":
                return lambda c, tech=None: _properties_refactor(c, tech or source_upper)
            return _unsupported_transform
        for blocked in ("RPG", "PLI", "PL1", "PL_I", "BMS", "MAP", "CICS",
                        "CICS_BMS", "DB2", "VSAM", "IMS", "IDMS",
                        "WEBSPHERE", "WEBLOGIC"):
            if source_upper == blocked:
                return _unsupported_transform
        return _unsupported_transform

    @staticmethod
    def is_supported(source_technology: str, transformation_type: str) -> bool:
        try:
            strat = G3TransformationStrategies.get_strategy(source_technology, transformation_type)
            return strat is not None and strat != _unsupported_transform
        except NotImplementedError:
            return False

    @staticmethod
    def supported_types_for(technology: str) -> list[str]:
        supported = []
        for tt in ["refactor", "rewrite", "reconfiguration", "transpilation", "extraction"]:
            if G3TransformationStrategies.is_supported(technology, tt):
                supported.append(tt)
        return supported if supported else ["blocked"]

def _cobol_to_java(content: str, dialect: str | None = None) -> str:
    """
    Deep bounded COBOL -> Java transformation.
    Extracts PROGRAM-ID, WORKING-STORAGE, file declarations, COPY refs,
    and paragraphs (with PERFORM/CALL/MOVE/IF/EVALUATE references).
    Output is a syntactically valid Java skeleton.
    """
    lines = content.split('\n')
    prog_id = _cobol_extract_program(lines)
    ws_fields = _cobol_extract_ws(lines)
    file_decls = _cobol_extract_files(lines)
    paragraphs = _cobol_extract_paragraphs(lines)
    copybooks = _cobol_extract_copybooks(lines)
    class_name = ''.join(w.title() for w in prog_id.replace('-', '_').split('_')) or "CobolProgram"
    imports = {"import java.math.BigDecimal;", "import java.util.HashMap;", "import java.util.Map;"}
    if any('V' in f.get('pic', '').upper() for f in ws_fields):
        imports.add("import java.math.RoundingMode;")
    out: list[str] = []
    out.append("// =============================================================")
    out.append(f"// Transformed from COBOL: {prog_id}")
    out.append(f"//   Working-storage fields: {len(ws_fields)}")
    out.append(f"//   Paragraphs: {len(paragraphs)}")
    out.append(f"//   File declarations: {len(file_decls)}")
    cb_note = ', '.join(copybooks) if copybooks else 'none'
    out.append(f"//   COPY references: {cb_note}")
    out.append("// =============================================================")
    out.append("")
    out.append("/**")
    out.append(f" * Java equivalent of COBOL program {prog_id}.")
    out.append(" * Generated by AutoForge Modernization G.3 bounded transpiler.")
    out.append(" * REVIEW REQUIRED: semantic skeleton, not a 1:1 translation.")
    if copybooks:
        out.append(f" * Copybooks: {', '.join(copybooks)}")
    out.append(" */")
    out.append("")
    for imp in sorted(imports):
        out.append(imp)
    out.append("")
    out.append(f"public class {class_name} {{")
    out.append("")

    if file_decls:
        out.append("    // File handles (SELECT ... ASSIGN TO)")
        for f in file_decls:
            out.append(
                f"    private final Map<String, String> file_{f['name'].lower()}"
                f" = new HashMap<>(); // external: {f['external']}"
            )
        out.append("")

    if ws_fields:
        out.append("    // Working-storage fields")
        for f in ws_fields[:50]:
            parts = []
            if f.get('pic'):
                parts.append(f"PIC {f['pic']}")
            if f.get('value'):
                parts.append(f"VALUE {f['value']}")
            if f.get('redefines'):
                parts.append(f"REDEFINES {f['redefines']}")
            comment = (
                f" // level {f['level']}, " + ", ".join(parts)
                if parts else f" // level {f['level']}"
            )
            init = f.get('value', '').strip('"\'')
            if f['java_type'] == 'String':
                iv = f' = "{init}"' if init else ''
            elif f['java_type'] in ('int', 'long'):
                iv = f' = {init}' if init and init.lstrip('-').isdigit() else ''
            elif f['java_type'] == 'BigDecimal':
                iv = f' = new BigDecimal("{init}")' if init else ''
            else:
                iv = ''
            out.append(
                f"    private {f['java_type']} {f['name'].lower()}{iv};{comment}"
            )
        out.append("")
        out.append(f"    public {class_name}() {{ }}")
        out.append("")
        for f in ws_fields[:20]:
            n = f['name'].lower()
            jt = f['java_type']
            cap = f['name'].capitalize()
            out.append(f"    public {jt} get{cap}() {{ return this.{n}; }}")
            out.append(f"    public void set{cap}({jt} {n}) {{ this.{n} = {n}; }}")
        out.append("")
    return _cobol_to_java_emit_paragraphs(out, paragraphs, class_name)


def _cobol_to_java_emit_paragraphs(out, paragraphs, class_name):
    if not paragraphs:
        out.append("}")
        return '\n'.join(out)
    out.append("    // Procedure division paragraphs")
    out.append("")
    for p in paragraphs[:20]:
        out.append(f"    /** Paragraph: {p['name']}")
        if p['perform_targets']:
            tgt_str = ', '.join(sorted(set(p['perform_targets'])))
            out.append(f"     * PERFORM: {tgt_str}")
        if p['calls']:
            c_str = ', '.join(sorted(set(p['calls'])))
            out.append(f"     * CALL: {c_str}")
        if p['ifs']:
            out.append(f"     * IF statements: {p['ifs']}")
        if p['evaluates']:
            out.append(f"     * EVALUATE statements: {p['evaluates']}")
        out.append("     */")
        out.append(f"    public void {p['java_name']}() {{")
        seen: set[str] = set()
        for tgt in p['perform_targets']:
            if tgt in seen:
                continue
            seen.add(tgt)
            out.append(f"        // PERFORM {tgt}")
            out.append(f"        this.{tgt}();")
        for call in sorted(set(p['calls'])):
            out.append(f"        // CALL {call} (external - wire to adapter)")
        if p['ifs']:
            out.append(f"        // {p['ifs']} IF block(s) - see original COBOL")
        if p['evaluates']:
            out.append(f"        // {p['evaluates']} EVALUATE block(s) - see original COBOL")
        if not (p['perform_targets'] or p['calls'] or p['ifs'] or p['evaluates']):
            out.append("        // (no PERFORM/CALL detected)")
        out.append("    }")
        out.append("")
    out.append("    public static void main(String[] args) {")
    out.append(f"        {class_name} program = new {class_name}();")
    out.append(f"        program.{paragraphs[0]['java_name']}();")
    out.append("    }")
    out.append("")
    out.append("}")
    return '\n'.join(out)



__all__ = ["G3TransformationStrategies"]
