"""Extractors converting technology-specific analyzer findings into TechnologyNeutralSemanticModel."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any

from autoforge_modernization.analyzers.base import AnalysisResult, FindingKind
from autoforge_modernization.analyzers.cobol import COBOLAnalyzer
from autoforge_modernization.analyzers.jcl import JCLAnalyzer
from autoforge_modernization.jcl_semantics import JCLParser
from autoforge_modernization.cobol_parser import COBOLParser
from autoforge_modernization.cobol_copybook import CopybookResolver
from autoforge_modernization.cics_semantics import CICSParser, CICSKind
from autoforge_modernization.bms_semantics import BMSParser
from autoforge_modernization.vsam_semantics import VSAMAnalyzer
from autoforge_modernization.sql_semantics import SQLParser, SQLKind
from autoforge_modernization.semantic.model import (
    BusinessRuleAction,
    BusinessRulePredicate,
    DataFlowEdge,
    ResolutionStatus,
    SemanticBusinessRule,
    SemanticCondition,
    SemanticDataType,
    SemanticEntity,
    SemanticErrorHandling,
    SemanticField,
    SemanticGraph,
    SemanticGraphEdge,
    SemanticGraphNode,
    SemanticIOKind,
    SemanticIOOperation,
    SemanticModule,
    SemanticOperation,
    SemanticOperationKind,
    SemanticProcedure,
    SourceProvenance,
    TechnologyNeutralSemanticModel,
    UnresolvedReference,
    UnsupportedSemanticConstruct,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_pic_clause(pic: str) -> tuple[SemanticDataType, int | None, int | None, int | None, bool]:
    """Parse COBOL PIC clause into (SemanticDataType, length, precision, scale, is_signed)."""
    if not pic:
        return SemanticDataType.UNKNOWN, None, None, None, False
    p = pic.upper().strip().rstrip(".")
    is_signed = p.startswith("S") or "S" in p
    is_packed = "COMP-3" in p or "PACKED-DECIMAL" in p

    clean_p = re.sub(r"\b(COMP-\d|COMP|BINARY|PACKED-DECIMAL|DISPLAY)\b", "", p).strip().rstrip(".")


    def _expand(s: str) -> str:
        def _rep(m):
            ch = m.group(1)
            count = int(m.group(2))
            return ch * count
        return re.sub(r"([9XAZS])\((\d+)\)", _rep, s)

    expanded = _expand(clean_p)

    if "X" in expanded or "A" in expanded:
        length = len(re.findall(r"[XA]", expanded))
        return SemanticDataType.STRING, length, None, None, False

    if "9" in expanded:
        if "V" in expanded or "." in expanded or is_packed:
            parts = re.split(r"[V.]", expanded)
            int_part = len(re.findall(r"9", parts[0]))
            dec_part = len(re.findall(r"9", parts[1])) if len(parts) > 1 else 0
            prec = int_part + dec_part
            return SemanticDataType.DECIMAL, prec, prec, dec_part, is_signed
        else:
            length = len(re.findall(r"9", expanded))
            return SemanticDataType.INTEGER, length, length, 0, is_signed

    return SemanticDataType.STRING, len(clean_p), None, None, False


def _map_pic_to_datatype(pic: str) -> SemanticDataType:
    dt, _, _, _, _ = parse_pic_clause(pic)
    return dt if dt != SemanticDataType.UNKNOWN else SemanticDataType.STRING


def _clean_cobol_source(content: str) -> str:
    """Strip fixed-format comments (col 7 * or /), line comments, sequence numbers (cols 1-6 and 73-80), and inline *> comments."""
    clean_lines = []
    for line in content.splitlines():
        if len(line) >= 7 and line[6] in ("*", "/"):
            continue
        stripped = line
        if len(stripped) > 72 and stripped[72:].strip().isdigit():
            stripped = stripped[:72]
        if len(stripped) >= 7 and stripped[:6].isdigit() and stripped[6] in (" ", "-"):
            stripped = stripped[7:]
        stripped = stripped.strip()
        if not stripped or stripped.isdigit():
            continue
        if stripped.startswith(("*", "/")):
            continue
        if "*>" in stripped:
            stripped = stripped.split("*>")[0].strip()
        if stripped and not stripped.isdigit():
            clean_lines.append(stripped)
    return "\n".join(clean_lines)


def _split_cobol_statements(body: str) -> list[str]:
    """Split procedure division body into individual statements handling inline IF, THEN, and scope terminators."""
    stmt_starters = {
        "PERFORM", "READ", "WRITE", "REWRITE", "MOVE", "COMPUTE", "ADD", "SUBTRACT",
        "MULTIPLY", "DIVIDE", "STOP", "GOBACK", "EXIT", "IF", "ELSE", "END-IF",
        "EVALUATE", "WHEN", "END-EVALUATE", "OPEN", "CLOSE", "DISPLAY", "STRING",
        "UNSTRING", "INITIALIZE", "SET", "EXEC", "END-EXEC", "CONTINUE", "CALL",
        "GO", "INSPECT", "NEXT", "SEARCH", "END-SEARCH", "END-COMPUTE", "END-READ",
        "END-WRITE", "END-PERFORM"
    }
    raw_lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith(("*", "/"))]
    clean_text = " ".join(raw_lines)
    sentences = re.split(r"\.\s+(?=[A-Z0-9])|\.\s*$", clean_text)
    statements: list[str] = []
    for s in sentences:
        s_clean = s.strip().rstrip(".")
        if not s_clean:
            continue
        tokens = re.findall(r"'[^']*'|\"[^\"]*\"|\S+", s_clean)
        current_tokens = []
        for tok in tokens:
            tu = tok.upper().rstrip(".")
            if tu.startswith("END-") or tu == "ELSE":
                if current_tokens:
                    statements.append(" ".join(current_tokens))
                    current_tokens = []
                statements.append(tok)
                continue
            if tu in stmt_starters and current_tokens:
                first_tu = current_tokens[0].upper().rstrip(".")
                if first_tu == "IF" and tu == "THEN":
                    current_tokens.append(tok)
                    statements.append(" ".join(current_tokens))
                    current_tokens = []
                    continue
                statements.append(" ".join(current_tokens))
                current_tokens = [tok]
            else:
                current_tokens.append(tok)
        if current_tokens:
            statements.append(" ".join(current_tokens))
    return [st for st in statements if st.strip()]


class SemanticModelExtractor:
    """Extracts TechnologyNeutralSemanticModel from source content using registered analyzers."""

    def __init__(self) -> None:
        self.cobol_analyzer = COBOLAnalyzer()
        self.jcl_analyzer = JCLAnalyzer()

    def extract_from_cobol(
        self,
        content: str,
        file_path: str = "program.cbl",
        project_id: str = "project-default",
    ) -> SemanticModule:
        clean_content = _clean_cobol_source(content)
        analysis = self.cobol_analyzer.analyze(content, file_path)
        sha = _sha256(content)

        # Extract program name
        m = re.search(r"\bPROGRAM-ID\.?\s*\.?\s*([A-Z0-9-]+)", clean_content, re.IGNORECASE)
        if m:
            prog_name = m.group(1).upper()
        else:
            prog_name = Path(file_path).stem.upper()

        # Extract fields with deep layout semantics
        fields: list[SemanticField] = []
        entities: list[SemanticEntity] = []
        current_record_entity: SemanticEntity | None = None

        for finding in analysis.findings:
            if finding.kind == FindingKind.DATA_DECLARATION:
                pic = finding.detail.get("pic", "")
                val = finding.detail.get("value")
                redef = finding.detail.get("redefines")
                level = finding.detail.get("level")
                if not pic and finding.evidence:
                    ev_line = finding.evidence[0]
                    m_p = re.search(r"\bPIC\s+([^\s.]+)", ev_line, re.IGNORECASE)
                    if m_p:
                        pic = m_p.group(1)
                    m_v = re.search(r"\bVALUE\s+([^\s.]+)", ev_line, re.IGNORECASE)
                    if m_v:
                        val = m_v.group(1)
                    m_r = re.search(r"\bREDEFINES\s+([^\s.]+)", ev_line, re.IGNORECASE)
                    if m_r:
                        redef = m_r.group(1)

                dt, flen, prec, scale, is_signed = parse_pic_clause(pic)
                sem_field = SemanticField(
                    name=finding.name,
                    data_type=dt,
                    original_type_descriptor=pic,
                    level=level,
                    default_value=val,
                    length=flen,
                    precision=prec,
                    scale=scale,
                    is_signed=is_signed,
                    redefines=redef,
                    parent_record_name=current_record_entity.name if current_record_entity and level and level > 1 else None,
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        original_construct=finding.description,
                        confidence=1.0,
                    ),
                )
                fields.append(sem_field)

                # Group 01 record structures into SemanticEntity
                if level == 1:
                    current_record_entity = SemanticEntity(
                        name=finding.name,
                        entity_type="record",
                        fields=[sem_field],
                        source_technology="COBOL",
                        provenance=SourceProvenance(
                            source_file=file_path,
                            source_sha256=sha,
                            original_construct=f"01 {finding.name}",
                        ),
                    )
                    entities.append(current_record_entity)
                elif current_record_entity and level and level > 1:
                    current_record_entity.fields.append(sem_field)

        # Extract file declarations from FILE-CONTROL / SELECT
        io_operations: list[SemanticIOOperation] = []
        file_select_map: dict[str, str] = {}  # internal_name -> ddname/dataset
        for m_sel in re.finditer(
            r"\bSELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+TO\s+([A-Z0-9-.\$#@_]+)",
            clean_content,
            re.IGNORECASE,
        ):
            internal_file = m_sel.group(1).upper()
            assigned_to = m_sel.group(2).upper().strip(". ")
            file_select_map[internal_file] = assigned_to

            # Check for file status and access mode in surrounding block
            tail = clean_content[m_sel.end() : m_sel.end() + 300]
            m_stat = re.search(r"\bFILE\s+STATUS\s+IS\s+([A-Z0-9-]+)", tail, re.IGNORECASE)
            status_fld = m_stat.group(1).upper() if m_stat else ""
            m_org = re.search(r"\bORGANIZATION\s+IS\s+(INDEXED|SEQUENTIAL|RELATIVE)", tail, re.IGNORECASE)
            org = m_org.group(1).upper() if m_org else "SEQUENTIAL"

            io_operations.append(
                SemanticIOOperation(
                    kind=SemanticIOKind.FILE_OPEN,
                    resource_name=assigned_to,
                    resource_type="vsam" if org == "INDEXED" else "file",
                    access_mode=org.lower(),
                    status_field=status_fld,
                    original_construct=m_sel.group(0),
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        original_construct=m_sel.group(0),
                    ),
                )
            )

        # Extract procedures (paragraphs)
        procedures: list[SemanticProcedure] = []
        calls_found: list[str] = []
        data_flows: list[DataFlowEdge] = []
        error_handlers: list[SemanticErrorHandling] = []
        unsupported: list[UnsupportedSemanticConstruct] = []

        for finding in analysis.findings:
            if finding.kind == FindingKind.PARAGRAPH:
                procedures.append(
                    SemanticProcedure(
                        name=finding.name,
                        kind="paragraph",
                        provenance=SourceProvenance(
                            source_file=file_path,
                            source_sha256=sha,
                            original_construct=finding.description,
                        ),
                    )
                )
            elif finding.kind == FindingKind.PROCEDURE_CALL and "CALL:" in finding.name:
                tgt = finding.detail.get("target") or finding.name.replace("CALL:", "").strip()
                if tgt and tgt not in calls_found:
                    calls_found.append(tgt)

        # Content regex fallback for CALL statements
        for m_call in re.finditer(r"\bCALL\s+['\"]([A-Z0-9-]+)['\"]", clean_content, re.IGNORECASE):
            c_name = m_call.group(1).upper()
            if c_name not in calls_found:
                calls_found.append(c_name)

        # Extract COPYbook relationships
        copybooks_found: list[str] = []
        for m_cpy in re.finditer(r"\bCOPY\s+([A-Z0-9_-]+)", clean_content, re.IGNORECASE):
            cpy_name = m_cpy.group(1).upper()
            if cpy_name not in copybooks_found:
                copybooks_found.append(cpy_name)
            if f"COPYBOOK:{cpy_name}" not in calls_found:
                calls_found.append(f"COPYBOOK:{cpy_name}")

        # Extract structured operations inside procedures / paragraphs
        for proc in procedures:
            p_pattern = re.compile(
                rf"\b{re.escape(proc.name)}\.\s*(.*?)(?=\n\s*[A-Z0-9-]+\.|\Z)",
                re.DOTALL | re.IGNORECASE,
            )
            m_p = p_pattern.search(clean_content)
            if not m_p:
                continue
            body = m_p.group(1)
            assembled_statements = _split_cobol_statements(body)

            for line in assembled_statements:
                s_ln = line.strip().upper()
                if not s_ln:
                    continue

                # PERFORM target [THRU thru] [UNTIL / VARYING cond]
                if s_ln.startswith("PERFORM "):
                    m_perf = re.search(
                        r"^PERFORM\s+([A-Z0-9-]+)(?:\s+THRU\s+([A-Z0-9-]+))?(?:\s+(UNTIL|VARYING)\s+(.+))?",
                        s_ln,
                        re.IGNORECASE,
                    )
                    if m_perf:
                        target_proc = m_perf.group(1)
                        thru_proc = m_perf.group(2)
                        loop_kind = m_perf.group(3)
                        loop_expr = m_perf.group(4)
                        if target_proc not in ("UNTIL", "VARYING", "WITH", "TEST", "AFTER", "BEFORE", "THRU", "THROUGH"):
                            proc.called_procedures.append(target_proc)
                            if thru_proc:
                                proc.called_procedures.append(thru_proc)
                            loop_cond = SemanticCondition(expression=loop_expr.strip()) if loop_expr else None
                            proc.operations.append(
                                SemanticOperation(
                                    kind=SemanticOperationKind.LOOP if loop_kind else SemanticOperationKind.CALL,
                                    description=s_ln.rstrip("."),
                                    target=target_proc,
                                    parameters=[thru_proc] if thru_proc else [],
                                    loop_kind=loop_kind,
                                    loop_condition=loop_cond,
                                    provenance=SourceProvenance(
                                        source_file=file_path,
                                        source_sha256=sha,
                                        original_construct=s_ln,
                                    ),
                                )
                            )

                # READ file
                elif s_ln.startswith("READ "):
                    words = s_ln.split()
                    if len(words) > 1:
                        file_tgt = words[1].rstrip(".")
                        dsn = file_select_map.get(file_tgt, file_tgt)
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.IO_READ,
                                description=f"READ {file_tgt}",
                                target=dsn,
                            )
                        )
                        io_operations.append(
                            SemanticIOOperation(
                                kind=SemanticIOKind.DATA_READ,
                                resource_name=dsn,
                                resource_type="vsam" if "VSAM" in dsn or "FILE" in file_tgt else "file",
                                target_record_or_field=file_tgt,
                                original_construct=s_ln,
                                provenance=SourceProvenance(
                                    source_file=file_path,
                                    source_sha256=sha,
                                    original_construct=s_ln,
                                ),
                            )
                        )

                # WRITE record
                elif s_ln.startswith("WRITE "):
                    words = s_ln.split()
                    if len(words) > 1:
                        rec_tgt = words[1].rstrip(".")
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.IO_WRITE,
                                description=f"WRITE {rec_tgt}",
                                target=rec_tgt,
                            )
                        )
                        io_operations.append(
                            SemanticIOOperation(
                                kind=SemanticIOKind.DATA_WRITE,
                                resource_name=rec_tgt,
                                resource_type="record",
                                target_record_or_field=rec_tgt,
                                original_construct=s_ln,
                                provenance=SourceProvenance(
                                    source_file=file_path,
                                    source_sha256=sha,
                                    original_construct=s_ln,
                                ),
                            )
                        )

                # REWRITE record
                elif s_ln.startswith("REWRITE "):
                    words = s_ln.split()
                    if len(words) > 1:
                        rec_tgt = words[1].rstrip(".")
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.IO_WRITE,
                                description=f"REWRITE {rec_tgt}",
                                target=rec_tgt,
                            )
                        )
                        io_operations.append(
                            SemanticIOOperation(
                                kind=SemanticIOKind.DATA_UPDATE,
                                resource_name=rec_tgt,
                                resource_type="record",
                                target_record_or_field=rec_tgt,
                                original_construct=s_ln,
                                provenance=SourceProvenance(
                                    source_file=file_path,
                                    source_sha256=sha,
                                    original_construct=s_ln,
                                ),
                            )
                        )

                # MOVE src TO dst(s)
                elif s_ln.startswith("MOVE "):
                    m_move = re.search(r"^MOVE\s+(.+?)\s+TO\s+(.+)$", s_ln, re.IGNORECASE)
                    if m_move:
                        src_expr = m_move.group(1).strip()
                        targets = [t.strip().rstrip(".") for t in m_move.group(2).split() if t.strip() and t.strip().upper() != "OF"]
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.ASSIGNMENT,
                                description=s_ln.rstrip("."),
                                target=targets[0] if targets else "",
                                parameters=targets[1:] if len(targets) > 1 else [],
                                referenced_fields=[src_expr] if not src_expr.replace(".", "").isdigit() and not src_expr.startswith("'") else [],
                                mutated_fields=targets,
                            )
                        )
                        for tgt in targets:
                            src_is_const = src_expr.isdigit() or src_expr.startswith("'") or src_expr in ("SPACE", "SPACES", "ZERO", "ZEROS")
                            data_flows.append(
                                DataFlowEdge(
                                    source=src_expr,
                                    source_kind="CONSTANT" if src_is_const else "FIELD",
                                    target=tgt,
                                    target_kind="FIELD",
                                    transformation_kind="ASSIGNMENT",
                                    procedure_name=proc.name,
                                    provenance=SourceProvenance(
                                        source_file=file_path,
                                        source_sha256=sha,
                                        original_construct=s_ln,
                                    ),
                                )
                            )

                # COMPUTE target = expr
                elif s_ln.startswith("COMPUTE "):
                    m_comp = re.search(r"^COMPUTE\s+([A-Z0-9-]+)\s*=\s*(.+)$", s_ln, re.IGNORECASE)
                    if m_comp:
                        tgt = m_comp.group(1).strip()
                        expr = m_comp.group(2).strip().rstrip(".")
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.COMPUTATION,
                                description=s_ln.rstrip("."),
                                target=tgt,
                                parameters=[expr],
                                mutated_fields=[tgt],
                            )
                        )
                        data_flows.append(
                            DataFlowEdge(
                                source=expr,
                                source_kind="EXPRESSION",
                                target=tgt,
                                target_kind="FIELD",
                                transformation_kind="ARITHMETIC",
                                expression=expr,
                                procedure_name=proc.name,
                                provenance=SourceProvenance(
                                    source_file=file_path,
                                    source_sha256=sha,
                                    original_construct=s_ln,
                                ),
                            )
                        )

                # ARITHMETIC: ADD, SUBTRACT, MULTIPLY, DIVIDE
                elif any(s_ln.startswith(kw) for kw in ("ADD ", "SUBTRACT ", "MULTIPLY ", "DIVIDE ")):
                    m_arith = re.search(r"^(ADD|SUBTRACT|MULTIPLY|DIVIDE)\s+(.+?)\s+(TO|FROM|BY|INTO)\s+([A-Z0-9-]+)", s_ln, re.IGNORECASE)
                    if m_arith:
                        op, src, _, tgt = m_arith.groups()
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.COMPUTATION,
                                description=s_ln.rstrip("."),
                                target=tgt,
                                parameters=[src],
                                mutated_fields=[tgt],
                            )
                        )
                        data_flows.append(
                            DataFlowEdge(
                                source=src,
                                source_kind="FIELD" if not src.replace(".", "").isdigit() else "CONSTANT",
                                target=tgt,
                                target_kind="FIELD",
                                transformation_kind="ARITHMETIC",
                                expression=f"{tgt} {op} {src}",
                                procedure_name=proc.name,
                            )
                        )

                # BRANCH: IF / ELSE / END-IF
                elif s_ln.startswith("IF "):
                    m_if = re.search(r"^IF\s+(.+?)(?:\s+THEN)?$", s_ln, re.IGNORECASE)
                    if m_if:
                        cond_expr = m_if.group(1).strip().rstrip(".")
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.BRANCH,
                                description=s_ln.rstrip("."),
                                condition=SemanticCondition(expression=cond_expr),
                                provenance=SourceProvenance(
                                    source_file=file_path,
                                    source_sha256=sha,
                                    original_construct=s_ln,
                                ),
                            )
                        )
                elif s_ln == "ELSE" or s_ln.startswith("ELSE "):
                    proc.operations.append(
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description=s_ln.rstrip("."),
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                original_construct=s_ln,
                            ),
                        )
                    )
                elif s_ln == "END-IF" or s_ln.startswith("END-IF"):
                    proc.operations.append(
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description=s_ln.rstrip("."),
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                original_construct=s_ln,
                            ),
                        )
                    )

                # BRANCH: EVALUATE / WHEN / END-EVALUATE
                elif s_ln.startswith("EVALUATE "):
                    m_ev = re.search(r"^EVALUATE\s+(.+)$", s_ln, re.IGNORECASE)
                    ev_expr = m_ev.group(1).strip().rstrip(".") if m_ev else ""
                    proc.operations.append(
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description=s_ln.rstrip("."),
                            condition=SemanticCondition(expression=ev_expr),
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                original_construct=s_ln,
                            ),
                        )
                    )
                elif s_ln.startswith("WHEN "):
                    proc.operations.append(
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description=s_ln.rstrip("."),
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                original_construct=s_ln,
                            ),
                        )
                    )

                # STOP RUN / GOBACK / EXIT PROGRAM
                elif s_ln.startswith("STOP RUN") or s_ln.startswith("GOBACK") or s_ln.startswith("EXIT PROGRAM"):
                    proc.operations.append(
                        SemanticOperation(
                            kind=SemanticOperationKind.RETURN,
                            description=s_ln.rstrip("."),
                            exit_kind="STOP_RUN" if "STOP" in s_ln else "GOBACK",
                        )
                    )

                # CALL external program / service
                elif s_ln.startswith("CALL "):
                    m_call = re.search(r"^CALL\s+['\"]?([A-Z0-9-]+)['\"]?", s_ln, re.IGNORECASE)
                    c_tgt = m_call.group(1) if m_call else ""
                    proc.operations.append(
                        SemanticOperation(
                            kind=SemanticOperationKind.EXTERNAL_SERVICE,
                            description=s_ln.rstrip("."),
                            target=c_tgt,
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                original_construct=s_ln,
                            ),
                        )
                    )

        # Detect unsupported / specialist constructs (e.g. EXEC CICS, IMS DL/I)
        if "EXEC CICS" in content.upper():
            unsupported.append(
                UnsupportedSemanticConstruct(
                    technology="CICS",
                    construct_name="EXEC CICS",
                    raw_text="EXEC CICS ... END-EXEC",
                    reason="CICS transactional and terminal control semantics require specialist adapter mapping.",
                    required_specialist="CICS Transaction Specialist",
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        original_construct="EXEC CICS block",
                    ),
                )
            )
            # Also extract CICS I/O operations and transactions
            cics_parser = CICSParser(content)
            cics_nodes = cics_parser.parse()
            for cn in cics_nodes:
                if cn.kind == CICSKind.SEND_MAP:
                    io_operations.append(
                        SemanticIOOperation(
                            kind=SemanticIOKind.TRANSACTION_OUTPUT,
                            resource_name=cn.map_name or "SCREEN_MAP",
                            resource_type="cics_map",
                            access_mode="output",
                            line_number=cn.line,
                            original_construct=cn.raw,
                        )
                    )
                elif cn.kind == CICSKind.RECEIVE_MAP:
                    io_operations.append(
                        SemanticIOOperation(
                            kind=SemanticIOKind.TRANSACTION_INPUT,
                            resource_name=cn.map_name or "SCREEN_MAP",
                            resource_type="cics_map",
                            access_mode="input",
                            line_number=cn.line,
                            original_construct=cn.raw,
                        )
                    )
                elif cn.kind in (CICSKind.LINK, CICSKind.XCTL):
                    if cn.program and cn.program not in calls_found:
                        calls_found.append(cn.program)

        if "CBLTDLI" in content.upper() or "AIBTDLI" in content.upper():
            unsupported.append(
                UnsupportedSemanticConstruct(
                    technology="IMS",
                    construct_name="DL/I CALL",
                    raw_text="CALL 'CBLTDLI' ...",
                    reason="IMS hierarchical database call requires specialist schema mapping.",
                    required_specialist="IMS Database Specialist",
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        original_construct="CALL 'CBLTDLI'",
                    ),
                )
            )

        # Extract structured business rules and error paths from parsed procedure operations
        rules: list[SemanticBusinessRule] = []
        rule_idx = 0

        for proc in procedures:
            for op_idx, op in enumerate(proc.operations):
                if op.kind == SemanticOperationKind.BRANCH and op.condition and op.condition.expression:
                    cond = op.condition.expression.strip()
                    cond_upper = cond.upper()
                    if cond_upper in ("END-IF", "EXIT", "CONTINUE"):
                        continue
                    rule_idx += 1

                    predicates: list[BusinessRulePredicate] = []
                    ref_fields: list[str] = []
                    actions: list[BusinessRuleAction] = []

                    m_pred = re.search(r"([A-Z0-9-]+)\s*(=|NOT\s*=|EQUAL\s+TO|NOT\s+EQUAL\s+TO|>|<|>=|<=)\s*(['\"][^'\"]*['\"]|\S+)", cond, re.IGNORECASE)
                    if m_pred:
                        left = m_pred.group(1).strip().upper()
                        op_str = m_pred.group(2).strip().upper()
                        right = m_pred.group(3).strip().rstrip(".")
                        ref_fields.append(left)
                        predicates.append(
                            BusinessRulePredicate(
                                left_operand=left,
                                operator="EQUALS" if op_str in ("=", "EQUAL TO") else "NOT_EQUALS" if "NOT" in op_str else op_str,
                                right_operand=right,
                            )
                        )
                    elif "EQUAL TO ZERO" in cond_upper or " = ZERO" in cond_upper:
                        f_name = cond.split()[0].upper()
                        ref_fields.append(f_name)
                        predicates.append(
                            BusinessRulePredicate(
                                left_operand=f_name,
                                operator="EQUAL_TO_ZERO",
                                right_operand="0",
                            )
                        )
                    else:
                        predicates.append(
                            BusinessRulePredicate(
                                left_operand=cond,
                                operator="EXPRESSION",
                                right_operand="",
                            )
                        )

                    # Inspect subsequent operations in the procedure for consequence actions
                    for next_op in proc.operations[op_idx + 1 : op_idx + 6]:
                        if next_op.kind == SemanticOperationKind.ASSIGNMENT and next_op.target:
                            actions.append(BusinessRuleAction(target=next_op.target, action_type="MUTATION", expression=next_op.description))
                        elif next_op.kind == SemanticOperationKind.CALL and next_op.target:
                            actions.append(BusinessRuleAction(target=next_op.target, action_type="CALL", expression="PERFORM"))
                            if "ABEND" in next_op.target.upper() or "ERROR" in next_op.target.upper():
                                error_handlers.append(
                                    SemanticErrorHandling(
                                        status_field=ref_fields[0] if ref_fields else "UNKNOWN",
                                        expected_status="00",
                                        error_condition=cond,
                                        handler_procedure=next_op.target,
                                        is_abnormal_termination=True,
                                        provenance=SourceProvenance(source_file=file_path, original_construct=cond),
                                    )
                                )
                        elif next_op.kind == SemanticOperationKind.COMPUTATION and next_op.target:
                            actions.append(BusinessRuleAction(target=next_op.target, action_type="COMPUTATION", expression=next_op.description))

                    rules.append(
                        SemanticBusinessRule(
                            name=f"Rule_{prog_name}_{proc.name}_{rule_idx}",
                            statement=f"IF {cond}",
                            conditions=[cond],
                            predicates=predicates,
                            referenced_fields=list(set(ref_fields)),
                            actions=actions,
                            confidence=0.95 if predicates else 0.8,
                            resolution_status=ResolutionStatus.RESOLVED,
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                original_construct=f"IF {cond}",
                            ),
                        )
                    )
                elif op.kind == SemanticOperationKind.COMPUTATION and op.target:
                    rule_idx += 1
                    rules.append(
                        SemanticBusinessRule(
                            name=f"Rule_{prog_name}_{proc.name}_CALC_{rule_idx}",
                            statement=op.description,
                            conditions=[],
                            predicates=[],
                            referenced_fields=op.referenced_fields,
                            actions=[BusinessRuleAction(target=op.target, action_type="COMPUTATION", expression=op.description)],
                            confidence=0.9,
                            resolution_status=ResolutionStatus.RESOLVED,
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                original_construct=op.description,
                            ),
                        )
                    )

        return SemanticModule(
            name=prog_name,
            module_type="program",
            source_technology="COBOL",
            source_file_path=file_path,
            source_sha256=sha,
            fields=fields,
            entities=entities,
            procedures=procedures,
            external_dependencies=list(set(calls_found)),
            io_operations=io_operations,
            data_flows=data_flows,
            error_handlers=error_handlers,
            unsupported_constructs=unsupported,
            business_rules=rules,
            entry_point=procedures[0].name if procedures else None,
            provenance=SourceProvenance(
                source_file=file_path,
                source_sha256=sha,
                original_construct=f"COBOL Program {prog_name}",
            ),
        )

    def extract_from_jcl(
        self,
        content: str,
        file_path: str = "job.jcl",
        project_id: str = "project-default",
    ) -> SemanticModule:
        analysis = self.jcl_analyzer.analyze(content, file_path)
        sha = _sha256(content)

        job_name = "JCL_JOB"
        for finding in analysis.findings:
            if "JOB" in finding.name:
                job_name = finding.name

        procedures: list[SemanticProcedure] = []
        deps: list[str] = []
        io_operations: list[SemanticIOOperation] = []

        parser = JCLParser(content)
        parser.parse()
        summary = parser.summary()
        if summary.get("job_name") and summary["job_name"] != "root":
            job_name = summary["job_name"]

        for s in summary.get("steps", []):
            step_name = s.get("name", "STEP")
            pgm = s.get("program") or s.get("proc") or step_name
            deps.append(pgm)
            procedures.append(
                SemanticProcedure(
                    name=step_name,
                    kind="step",
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.CALL,
                            description=f"EXEC PGM={pgm}",
                            target=pgm,
                            parameters=[s.get("parm")] if s.get("parm") else [],
                        )
                    ],
                    called_procedures=[pgm],
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        line_start=s.get("line"),
                        original_construct=f"EXEC PGM={pgm}",
                    ),
                )
            )

        for dsn in summary.get("datasets", []):
            io_operations.append(
                SemanticIOOperation(
                    kind=SemanticIOKind.DATA_READ,
                    resource_name=dsn,
                    resource_type="dataset",
                    original_construct=f"DD DSN={dsn}",
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        original_construct=f"DD DSN={dsn}",
                    ),
                )
            )

        if not job_name or job_name == "JCL_JOB":
            job_name = Path(file_path).stem.upper()

        module_name = job_name

        return SemanticModule(
            name=module_name,
            module_type="job",
            source_technology="JCL",
            source_file_path=file_path,
            source_sha256=sha,
            procedures=procedures,
            external_dependencies=list(set(deps)),
            io_operations=io_operations,
            provenance=SourceProvenance(
                source_file=file_path,
                source_sha256=sha,
                original_construct=f"JCL Job {job_name}",
            ),
        )

    def extract_from_copybook(
        self,
        content: str,
        file_path: str = "copybook.cpy",
    ) -> SemanticEntity:
        """Extract copybook data structure into a SemanticEntity."""
        member_name = Path(file_path).stem.upper()
        sha = _sha256(content)
        fields: list[SemanticField] = []

        # Find 01 level or all data lines
        for lineno, line in enumerate(content.splitlines(), 1):
            ls = line.strip()
            if not ls or ls.startswith("*") or ls.startswith("/"):
                continue
            m = re.match(
                r"^\s*(\d{1,2})\s+([A-Z0-9-]+)(?:\s+REDEFINES\s+([A-Z0-9-]+))?(?:\s+PIC\s+(\S+))?(?:\s+VALUE\s+(\S+))?",
                ls,
                re.IGNORECASE,
            )
            if m:
                lvl = int(m.group(1))
                name = m.group(2).upper()
                redef = m.group(3)
                pic = m.group(4) or ""
                val = m.group(5)

                dt, flen, prec, scale, is_signed = parse_pic_clause(pic)
                fields.append(
                    SemanticField(
                        name=name,
                        data_type=dt,
                        original_type_descriptor=pic,
                        level=lvl,
                        default_value=val,
                        length=flen,
                        precision=prec,
                        scale=scale,
                        is_signed=is_signed,
                        redefines=redef,
                        provenance=SourceProvenance(
                            source_file=file_path,
                            source_sha256=sha,
                            line_start=lineno,
                            original_construct=ls,
                        ),
                    )
                )

        return SemanticEntity(
            name=member_name,
            entity_type="copybook",
            fields=fields,
            source_technology="COPYBOOK",
            provenance=SourceProvenance(
                source_file=file_path,
                source_sha256=sha,
                original_construct=f"COPYBOOK {member_name}",
            ),
        )

    def extract_from_bms(
        self,
        content: str,
        file_path: str = "screen.bms",
    ) -> list[SemanticEntity]:
        """Extract BMS screen maps into SemanticEntity definitions."""
        parser = BMSParser(content)
        maps = parser.parse()
        entities = []
        for m in maps:
            fields = []
            for f in m.get("fields", []):
                fields.append(
                    SemanticField(
                        name=f["name"],
                        data_type=SemanticDataType.STRING,
                        length=f.get("length", 0),
                        default_value=f.get("initial"),
                        constraints=f.get("attrs", []),
                    )
                )
            entities.append(
                SemanticEntity(
                    name=m["name"],
                    entity_type="screen",
                    fields=fields,
                    source_technology="BMS",
                    provenance=SourceProvenance(source_file=file_path, original_construct=f"BMS MAP {m['name']}"),
                )
            )
        return entities

    def extract_from_sql(
        self,
        content: str,
        file_path: str = "schema.sql",
    ) -> list[SemanticEntity]:
        """Extract SQL tables and schemas into SemanticEntity definitions."""
        parser = SQLParser(content)
        tree = parser.parse()
        entities = []
        for tbl in parser._tables:
            entities.append(
                SemanticEntity(
                    name=tbl,
                    entity_type="table",
                    source_technology="DB2",
                    provenance=SourceProvenance(source_file=file_path, original_construct=f"CREATE TABLE {tbl}"),
                )
            )
        return entities

    def extract_from_python(
        self,
        content: str,
        file_path: str = "module.py",
        project_id: str = "default",
    ) -> SemanticModule:
        """Extract Python AST into TechnologyNeutral SemanticModule, procedures, and entities."""
        import ast
        mod_name = Path(file_path).stem.upper()
        sha = _sha256(content)
        procedures: list[SemanticProcedure] = []
        entities: list[SemanticEntity] = []
        deps: list[str] = []

        try:
            tree = ast.parse(content, filename=file_path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    proc_name = node.name.upper()
                    procedures.append(
                        SemanticProcedure(
                            name=proc_name,
                            description=f"Python function {node.name}",
                            operations=[
                                SemanticOperation(
                                    kind=SemanticOperationKind.COMPUTE,
                                    target=proc_name,
                                    description=f"Execute {node.name}",
                                )
                            ],
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                line_start=node.lineno,
                                line_end=getattr(node, "end_lineno", node.lineno),
                                original_construct=f"def {node.name}",
                            ),
                        )
                    )
                elif isinstance(node, ast.ClassDef):
                    ent_name = node.name.upper()
                    fields = []
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            fields.append(
                                SemanticField(
                                    name=item.target.id,
                                    data_type=SemanticDataType.STRING,
                                    provenance=SourceProvenance(
                                        source_file=file_path,
                                        source_sha256=sha,
                                        line_start=item.lineno,
                                        original_construct=item.target.id,
                                    ),
                                )
                            )
                    entities.append(
                        SemanticEntity(
                            name=ent_name,
                            entity_type="class",
                            fields=fields,
                            source_technology="PYTHON",
                            provenance=SourceProvenance(
                                source_file=file_path,
                                source_sha256=sha,
                                line_start=node.lineno,
                                line_end=getattr(node, "end_lineno", node.lineno),
                                original_construct=f"class {node.name}",
                            ),
                        )
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        deps.append(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    deps.append(node.module)
        except Exception:
            pass

        if not procedures:
            procedures.append(
                SemanticProcedure(
                    name=f"{mod_name}_EXEC",
                    description=f"Python module execution for {mod_name}",
                    operations=[],
                    provenance=SourceProvenance(source_file=file_path, source_sha256=sha),
                )
            )

        return SemanticModule(
            name=mod_name,
            source_file_path=file_path,
            source_technology="PYTHON",
            module_type="service",
            procedures=procedures,
            entities=entities,
            external_dependencies=list(set(deps)),
            provenance=SourceProvenance(source_file=file_path, source_sha256=sha),
        )


class ProjectSemanticExtractor:
    """Multi-file cross-technology semantic extractor and graph synthesizer."""

    def __init__(self, search_paths: list[str] | None = None) -> None:
        self.search_paths = search_paths or []
        self.single_extractor = SemanticModelExtractor()

    def extract_project(
        self,
        project_root: str | Path,
        file_paths: list[str | Path] | None = None,
        project_id: str = "autoforge-project",
    ) -> TechnologyNeutralSemanticModel:
        """Analyze files across a project, perform cross-file linking, and produce unified semantic model."""
        root = Path(project_root)
        model = TechnologyNeutralSemanticModel(project_id=project_id)

        # Collect files if not explicitly provided
        if file_paths is None:
            file_paths = []
            for ext in ("*.cbl", "*.CBL", "*.cob", "*.jcl", "*.JCL", "*.cpy", "*.CPY", "*.bms", "*.BMS", "*.sql", "*.ddl", "*.py"):
                file_paths.extend(root.rglob(ext))

        # Pass 1: Parse individual files into modules / entities
        copybook_entities: dict[str, SemanticEntity] = {}
        for fp in file_paths:
            p = Path(fp) if isinstance(fp, str) else fp
            if not p.is_file():
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_path = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            ext = p.suffix.lower()

            if ext in (".cbl", ".cob"):
                mod = self.single_extractor.extract_from_cobol(content, file_path=rel_path, project_id=project_id)
                model.add_module(mod)
                for ent in mod.entities:
                    model.add_entity(ent)
                for io in mod.io_operations:
                    model.add_io_operation(io)
                for df in mod.data_flows:
                    model.add_data_flow(df)
                for eh in mod.error_handlers:
                    model.error_handlers.append(eh)

            elif ext == ".jcl":
                job_mod = self.single_extractor.extract_from_jcl(content, file_path=rel_path, project_id=project_id)
                if job_mod.name in model.modules:
                    job_mod.name = f"{job_mod.name}_JOB"
                model.add_module(job_mod)
                for io in job_mod.io_operations:
                    model.add_io_operation(io)

            elif ext in (".cpy", ".copy"):
                cpy_ent = self.single_extractor.extract_from_copybook(content, file_path=rel_path)
                model.add_entity(cpy_ent)
                copybook_entities[cpy_ent.name] = cpy_ent

            elif ext == ".bms":
                bms_ents = self.single_extractor.extract_from_bms(content, file_path=rel_path)
                for be in bms_ents:
                    model.add_entity(be)

            elif ext in (".sql", ".ddl", ".dbd"):
                sql_ents = self.single_extractor.extract_from_sql(content, file_path=rel_path)
                for se in sql_ents:
                    model.add_entity(se)

            elif ext == ".py":
                py_mod = self.single_extractor.extract_from_python(content, file_path=rel_path, project_id=project_id)
                model.add_module(py_mod)
                for ent in py_mod.entities:
                    model.add_entity(ent)

        # Pass 2 & 3: Cross-File Linking & Graph Composition
        graph = model.semantic_graph

        # Add all modules as graph nodes
        for mod_name, mod in model.modules.items():
            kind = "JOB" if mod.module_type == "job" else "PROGRAM"
            graph.add_node(
                SemanticGraphNode(
                    node_id=f"{kind}:{mod_name}",
                    name=mod_name,
                    kind=kind,
                    technology=mod.source_technology,
                    provenance=mod.provenance,
                )
            )
            # Add procedures
            for proc in mod.procedures:
                proc_id = f"PROCEDURE:{mod_name}.{proc.name}"
                graph.add_node(
                    SemanticGraphNode(
                        node_id=proc_id,
                        name=proc.name,
                        kind="PROCEDURE" if kind == "PROGRAM" else "STEP",
                        technology=mod.source_technology,
                        provenance=proc.provenance,
                    )
                )
                graph.add_edge(
                    SemanticGraphEdge(
                        src=f"{kind}:{mod_name}",
                        dst=proc_id,
                        kind="DEFINES",
                    )
                )

        # Add all entities as graph nodes
        for ent_name, ent in model.entities.items():
            kind = ent.entity_type.upper()
            graph.add_node(
                SemanticGraphNode(
                    node_id=f"{kind}:{ent_name}",
                    name=ent_name,
                    kind=kind,
                    technology=ent.source_technology,
                    provenance=ent.provenance,
                )
            )

        # Cross-File Resolution
        for mod_name, mod in model.modules.items():
            if mod.module_type == "program":
                prog_node_id = f"PROGRAM:{mod_name}"

                # 1. Program -> Copybook resolution
                for dep in list(mod.external_dependencies):
                    if dep.startswith("COPYBOOK:"):
                        cpy_name = dep.replace("COPYBOOK:", "").strip().upper()
                        cpy_node_id = f"COPYBOOK:{cpy_name}"
                        if cpy_name in copybook_entities:
                            # RESOLVED copybook
                            graph.add_edge(
                                SemanticGraphEdge(
                                    src=prog_node_id,
                                    dst=cpy_node_id,
                                    kind="INCLUDES",
                                    resolution_status=ResolutionStatus.RESOLVED,
                                )
                            )
                        else:
                            # UNRESOLVED copybook
                            graph.add_edge(
                                SemanticGraphEdge(
                                    src=prog_node_id,
                                    dst=cpy_node_id,
                                    kind="INCLUDES",
                                    resolution_status=ResolutionStatus.UNRESOLVED,
                                )
                            )
                            model.add_unresolved_reference(
                                UnresolvedReference(
                                    source_module=mod_name,
                                    target_name=cpy_name,
                                    reference_kind="COPYBOOK_INCLUDE",
                                    reason=f"Copybook member '{cpy_name}' not found in project paths.",
                                    provenance=mod.provenance,
                                )
                            )

                # 2. Program -> Program CALL resolution
                for dep in mod.external_dependencies:
                    if not dep.startswith("COPYBOOK:"):
                        target_prog = dep.upper()
                        target_node_id = f"PROGRAM:{target_prog}"
                        if target_prog in model.modules:
                            # RESOLVED internal call
                            graph.add_edge(
                                SemanticGraphEdge(
                                    src=prog_node_id,
                                    dst=target_node_id,
                                    kind="CALLS",
                                    resolution_status=ResolutionStatus.RESOLVED,
                                )
                            )
                        else:
                            # Check if target is a known specialist utility (e.g. IDCAMS, IEFBR14)
                            is_sys_util = target_prog in ("IDCAMS", "IEFBR14", "SORT", "SYNCSORT", "DFSRRC00")
                            status = ResolutionStatus.SPECIALIST_REQUIRED if is_sys_util else ResolutionStatus.UNRESOLVED
                            graph.add_edge(
                                SemanticGraphEdge(
                                    src=prog_node_id,
                                    dst=target_node_id,
                                    kind="CALLS",
                                    resolution_status=status,
                                )
                            )
                            model.add_unresolved_reference(
                                UnresolvedReference(
                                    source_module=mod_name,
                                    target_name=target_prog,
                                    reference_kind="PROGRAM_CALL",
                                    reason=f"Called target program '{target_prog}' is external or not resolved.",
                                    provenance=mod.provenance,
                                )
                            )

                # 3. Program -> I/O & Dataset edges
                for io in mod.io_operations:
                    res_node_id = f"DATASET:{io.resource_name}"
                    if not graph.get_node(res_node_id):
                        graph.add_node(
                            SemanticGraphNode(
                                node_id=res_node_id,
                                name=io.resource_name,
                                kind="DATASET",
                                technology="VSAM" if io.resource_type == "vsam" else "FILE",
                            )
                        )
                    edge_kind = "READS" if io.kind in (SemanticIOKind.DATA_READ, SemanticIOKind.DATABASE_READ) else "WRITES"
                    graph.add_edge(
                        SemanticGraphEdge(
                            src=prog_node_id,
                            dst=res_node_id,
                            kind=edge_kind,
                            resolution_status=io.resolution_status,
                        )
                    )

            elif mod.module_type == "job":
                job_node_id = f"JOB:{mod_name}"

                # JCL Job -> Step -> Program resolution
                for proc in mod.procedures:
                    step_node_id = f"PROCEDURE:{mod_name}.{proc.name}"
                    for op in proc.operations:
                        if op.kind == SemanticOperationKind.CALL:
                            target_pgm = op.target.upper()
                            pgm_node_id = f"PROGRAM:{target_pgm}"
                            resolved = target_pgm in model.modules
                            status = ResolutionStatus.RESOLVED if resolved else (
                                ResolutionStatus.SPECIALIST_REQUIRED if target_pgm in ("IDCAMS", "IEFBR14", "SORT") else ResolutionStatus.UNRESOLVED
                            )
                            graph.add_edge(
                                SemanticGraphEdge(
                                    src=job_node_id,
                                    dst=step_node_id,
                                    kind="EXECUTES",
                                )
                            )
                            graph.add_edge(
                                SemanticGraphEdge(
                                    src=step_node_id,
                                    dst=pgm_node_id,
                                    kind="CALLS",
                                    resolution_status=status,
                                )
                            )
                            if not resolved and target_pgm not in ("IDCAMS", "IEFBR14"):
                                model.add_unresolved_reference(
                                    UnresolvedReference(
                                        source_module=mod_name,
                                        target_name=target_pgm,
                                        reference_kind="EXEC_PGM",
                                        line_number=proc.provenance.line_start if proc.provenance else None,
                                        reason=f"JCL step program '{target_pgm}' not found in project sources.",
                                        provenance=proc.provenance,
                                    )
                                )

                # JCL -> Datasets
                for io in mod.io_operations:
                    dsn_node_id = f"DATASET:{io.resource_name}"
                    if not graph.get_node(dsn_node_id):
                        graph.add_node(
                            SemanticGraphNode(
                                node_id=dsn_node_id,
                                name=io.resource_name,
                                kind="DATASET",
                                technology="JCL_DD",
                            )
                        )
                    graph.add_edge(
                        SemanticGraphEdge(
                            src=job_node_id,
                            dst=dsn_node_id,
                            kind="BINDS",
                        )
                    )

        # 4. Data-flow edges in graph
        for df in model.data_flows:
            src_node_id = f"FIELD:{df.source}"
            dst_node_id = f"FIELD:{df.target}"
            if not graph.get_node(src_node_id):
                graph.add_node(SemanticGraphNode(node_id=src_node_id, name=df.source, kind="FIELD"))
            if not graph.get_node(dst_node_id):
                graph.add_node(SemanticGraphNode(node_id=dst_node_id, name=df.target, kind="FIELD"))
            graph.add_edge(
                SemanticGraphEdge(
                    src=src_node_id,
                    dst=dst_node_id,
                    kind="FLOWS_TO",
                    attrs={"transformation": df.transformation_kind, "procedure": df.procedure_name or ""},
                    provenance=df.provenance,
                )
            )

        return model
