"""Extractors converting technology-specific analyzer findings into TechnologyNeutralSemanticModel."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from autoforge_modernization.analyzers.base import AnalysisResult, FindingKind
from autoforge_modernization.analyzers.cobol import COBOLAnalyzer
from autoforge_modernization.analyzers.jcl import JCLAnalyzer
from autoforge_modernization.semantic.model import (
    SemanticBusinessRule,
    SemanticDataType,
    SemanticField,
    SemanticModule,
    SemanticOperation,
    SemanticOperationKind,
    SemanticProcedure,
    SourceProvenance,
    TechnologyNeutralSemanticModel,
    UnsupportedSemanticConstruct,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _map_pic_to_datatype(pic: str) -> SemanticDataType:
    pic_upper = pic.upper()
    if "X" in pic_upper or "A" in pic_upper:
        return SemanticDataType.STRING
    if "9" in pic_upper:
        if "V" in pic_upper or "." in pic_upper or "COMP-3" in pic_upper:
            return SemanticDataType.DECIMAL
        return SemanticDataType.INTEGER
    return SemanticDataType.STRING


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
        analysis = self.cobol_analyzer.analyze(content, file_path)
        sha = _sha256(content)

        # Extract program name
        m = re.search(r"\bPROGRAM-ID\.?\s*\.?\s*([A-Z0-9-]+)", content, re.IGNORECASE)
        if m:
            prog_name = m.group(1).upper()
        else:
            prog_name = Path(file_path).stem.upper()

        # Extract fields
        fields: list[SemanticField] = []
        for finding in analysis.findings:
            if finding.kind == FindingKind.DATA_DECLARATION:
                pic = finding.detail.get("pic", "")
                val = finding.detail.get("value")
                if not pic and finding.evidence:
                    ev_line = finding.evidence[0]
                    m_p = re.search(r"\bPIC\s+([^\s.]+)", ev_line, re.IGNORECASE)
                    if m_p:
                        pic = m_p.group(1)
                    m_v = re.search(r"\bVALUE\s+([^\s.]+)", ev_line, re.IGNORECASE)
                    if m_v:
                        val = m_v.group(1)
                dt = _map_pic_to_datatype(pic)
                fields.append(
                    SemanticField(
                        name=finding.name,
                        data_type=dt,
                        original_type_descriptor=pic,
                        level=finding.detail.get("level"),
                        default_value=val,
                        provenance=SourceProvenance(
                            source_file=file_path,
                            source_sha256=sha,
                            original_construct=finding.description,
                        ),
                    )
                )

        # Extract procedures (paragraphs)
        procedures: list[SemanticProcedure] = []
        calls_found: list[str] = []
        unsupported: list[UnsupportedSemanticConstruct] = []

        for finding in analysis.findings:
            if finding.kind == FindingKind.PARAGRAPH:
                proc_name = finding.name
                procedures.append(
                    SemanticProcedure(
                        name=proc_name,
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
        # Content regex fallback for CALL statements
        for m_call in re.finditer(r"\bCALL\s+['\"]([A-Z0-9-]+)['\"]", content, re.IGNORECASE):
            c_name = m_call.group(1).upper()
            if c_name not in calls_found:
                calls_found.append(c_name)

        # Extract COPYbook relationships
        copybooks_found: list[str] = []
        for m_cpy in re.finditer(r"\bCOPY\s+([A-Z0-9_-]+)", content, re.IGNORECASE):
            cpy_name = m_cpy.group(1).upper()
            if cpy_name not in copybooks_found:
                copybooks_found.append(cpy_name)
            if cpy_name not in calls_found:
                calls_found.append(f"COPYBOOK:{cpy_name}")

        # Extract operations inside procedures / paragraphs
        for proc in procedures:
            # Look for PERFORM, READ, WRITE, MOVE in content associated with paragraph
            p_pattern = re.compile(rf"\b{re.escape(proc.name)}\.\s*(.*?)(?=\n\s*[A-Z0-9-]+\.|\Z)", re.DOTALL | re.IGNORECASE)
            m_p = p_pattern.search(content)
            if m_p:
                body = m_p.group(1)
                for line in body.splitlines():
                    s_ln = line.strip().upper()
                    if s_ln.startswith("PERFORM "):
                        words = s_ln.split()
                        if len(words) > 1:
                            target_proc = words[1].rstrip(".")
                            if target_proc not in ("UNTIL", "VARYING", "WITH", "TEST", "AFTER", "BEFORE", "THRU", "THROUGH"):
                                proc.called_procedures.append(target_proc)
                                proc.operations.append(
                                    SemanticOperation(
                                        kind=SemanticOperationKind.CALL,
                                        description=f"PERFORM {target_proc}",
                                        target=target_proc,
                                    )
                                )
                    elif s_ln.startswith("READ "):
                        file_tgt = s_ln.split()[1].rstrip(".")
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.IO_READ,
                                description=f"READ {file_tgt}",
                                target=file_tgt,
                            )
                        )
                    elif s_ln.startswith("WRITE "):
                        rec_tgt = s_ln.split()[1].rstrip(".")
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.IO_WRITE,
                                description=f"WRITE {rec_tgt}",
                                target=rec_tgt,
                            )
                        )
                    elif s_ln.startswith("MOVE "):
                        proc.operations.append(
                            SemanticOperation(
                                kind=SemanticOperationKind.ASSIGNMENT,
                                description=s_ln.rstrip("."),
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

        # Extract business rules
        rules: list[SemanticBusinessRule] = []
        rule_findings = [f for f in analysis.findings if f.kind == FindingKind.BUSINESS_RULE]
        for idx, rf in enumerate(rule_findings):
            stmt = rf.description or rf.name or rf.detail.get("rule_type", "business rule")
            rules.append(
                SemanticBusinessRule(
                    name=f"Rule_{prog_name}_{idx + 1}",
                    statement=stmt,
                    conditions=[rf.name],
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        original_construct=stmt,
                    ),
                )
            )

        # Also extract IF statements as business logic rules
        for idx, m_if in enumerate(re.finditer(r"\bIF\s+([^.\n]+)", content, re.IGNORECASE)):
            cond = m_if.group(1).strip()
            # Filter out COBOL structural keywords and noise
            if cond.upper() in ("END-IF", "EXIT", "CONTINUE"):
                continue
            rules.append(
                SemanticBusinessRule(
                    name=f"Rule_{prog_name}_IF_{idx + 1}",
                    statement=f"IF {cond}",
                    conditions=[cond],
                    provenance=SourceProvenance(
                        source_file=file_path,
                        source_sha256=sha,
                        original_construct=f"IF {cond}",
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
            procedures=procedures,
            external_dependencies=list(set(calls_found)),
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

        for finding in analysis.findings:
            if finding.kind == FindingKind.JCL_STEP:
                pgm = finding.detail.get("program", finding.name)
                deps.append(pgm)
                procedures.append(
                    SemanticProcedure(
                        name=finding.name,
                        kind="step",
                        operations=[
                            SemanticOperation(
                                kind=SemanticOperationKind.CALL,
                                description=f"EXEC PGM={pgm}",
                                target=pgm,
                            )
                        ],
                        called_procedures=[pgm],
                    )
                )

        return SemanticModule(
            name=job_name,
            module_type="job",
            source_technology="JCL",
            source_file_path=file_path,
            source_sha256=sha,
            procedures=procedures,
            external_dependencies=list(set(deps)),
            provenance=SourceProvenance(
                source_file=file_path,
                source_sha256=sha,
                original_construct=f"JCL Job {job_name}",
            ),
        )
