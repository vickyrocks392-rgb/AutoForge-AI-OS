"""Structured transformation context for production modernization.

Builds a deterministic, provenance-aware context payload that the LLM
transformation engine consumes.  The context carries *structured evidence* —
never just an arbitrary source file:

* source code + source SHA256 + artifact identity
* parsed/semantic representation (constructs, control flow, data flow)
* dependency relationships (CALL / COPYBOOK / SQL / CICS / VSAM / BMS / JCL)
* business requirements and modernization plan references
* target architecture and target-language knowledge
* project conventions
* retrieved RAG evidence (with identities and scores)
* verification constraints

The prompt builder is deterministic: identical inputs produce an identical
``prompt_context_id`` (SHA-256 of the canonical context digest), which makes
each LLM request reproducible/auditable.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Semantic model snapshot
# ---------------------------------------------------------------------------


class SemanticField(BaseModel):
    name: str
    level: int | None = None
    data_type: str = ""
    pic: str = ""
    value: str = ""


class SemanticMethod(BaseModel):
    name: str
    kind: str = "paragraph"
    perform_targets: list[str] = Field(default_factory=list)
    control_flow_nodes: int = 0
    references: list[str] = Field(default_factory=list)


class SemanticDependency(BaseModel):
    kind: str  # CALL / COPYBOOK / SQL / CICS / VSAM / BMS / JCL / FILE
    target: str
    detail: str = ""


class SemanticModelSnapshot(BaseModel):
    """Normalized semantic understanding of one legacy artifact."""

    semantic_constructs: int = 0
    control_flow_nodes: int = 0
    data_flow_edges: int = 0
    dependency_edges: int = 0
    methods: list[SemanticMethod] = Field(default_factory=list)
    fields: list[SemanticField] = Field(default_factory=list)
    dependencies: list[SemanticDependency] = Field(default_factory=list)
    sql_tables: list[str] = Field(default_factory=list)
    unresolved_semantics: list[str] = Field(default_factory=list)

    @property
    def complexity_score(self) -> float:
        return float(
            self.semantic_constructs
            + self.control_flow_nodes
            + len(self.dependencies) * 0.5
        )


def semantic_snapshot_from_analysis(analysis: dict[str, Any]) -> SemanticModelSnapshot:
    """Normalize an analysis record's ``semantic`` dict into a snapshot.

    Analysis dicts are produced by the existing analyzers
    (COBOL/JCL/SQL/BMS semantic extraction).  Missing keys degrade gracefully.
    """
    semantic = (analysis or {}).get("semantic") or {}
    if not isinstance(semantic, dict):
        semantic = {}
    methods: list[SemanticMethod] = []
    for para in semantic.get("paragraphs") or []:
        if isinstance(para, dict):
            methods.append(
                SemanticMethod(
                    name=str(para.get("name", "UNKNOWN")),
                    kind=para.get("kind", "paragraph"),
                    perform_targets=list(para.get("perform_targets") or []),
                    control_flow_nodes=int(para.get("ifs") or 0)
                    + int(para.get("evaluates") or 0)
                    + int(para.get("loops") or 0),
                    references=list(para.get("calls") or []),
                )
            )
    fields: list[SemanticField] = []
    for item in semantic.get("data_items") or semantic.get("fields") or []:
        if isinstance(item, dict):
            fields.append(
                SemanticField(
                    name=str(item.get("name", "UNKNOWN")),
                    level=item.get("level"),
                    data_type=item.get("java_type", item.get("type", "")),
                    pic=item.get("pic", ""),
                    value=item.get("value", ""),
                )
            )
    dependencies: list[SemanticDependency] = []
    for call in semantic.get("external_calls") or semantic.get("calls") or []:
        if isinstance(call, dict):
            dependencies.append(
                SemanticDependency(
                    kind=call.get("kind", "CALL"), target=str(call.get("name", ""))
                )
            )
        else:
            dependencies.append(SemanticDependency(kind="CALL", target=str(call)))
    for cpy in semantic.get("copybooks") or []:
        if isinstance(cpy, dict):
            dependencies.append(
                SemanticDependency(kind="COPYBOOK", target=str(cpy.get("name", "")))
            )
        else:
            dependencies.append(SemanticDependency(kind="COPYBOOK", target=str(cpy)))
    if semantic.get("cics_detected", False):
        dependencies.append(SemanticDependency(kind="CICS", target="CICS_API"))
    for tab in semantic.get("tables") or semantic.get("sql_tables") or []:
        dependencies.append(SemanticDependency(kind="SQL", target=str(tab)))

    unresolved: list[str] = []
    gaps = semantic.get("gaps") or [] if isinstance(semantic, dict) else []
    for gap in gaps:
        if isinstance(gap, str):
            unresolved.append(gap)
        elif isinstance(gap, dict):
            unresolved.append(str(gap.get("description", gap)))
    if semantic.get("cics_detected", False):
        unresolved.append("CICS transactional semantics require adapter mapping")

    constructs = int(
        len(methods)
        + len(fields)
        + sum(m.control_flow_nodes for m in methods)
        + sum(1 for d in dependencies if d.kind in ("CALL", "CICS", "SQL"))
    )
    return SemanticModelSnapshot(
        semantic_constructs=constructs,
        control_flow_nodes=sum(m.control_flow_nodes for m in methods),
        data_flow_edges=sum(len(m.references) for m in methods),
        dependency_edges=len(dependencies),
        methods=methods,
        fields=fields[:200],
        dependencies=dependencies,
        sql_tables=list(semantic.get("tables") or semantic.get("sql_tables") or []),
        unresolved_semantics=[u for u in set(unresolved) if u],
    )


# ---------------------------------------------------------------------------
# Context models
# ---------------------------------------------------------------------------


class RAGEvidenceBlock(BaseModel):
    """One retrieved RAG evidence block used in an LLM transformation."""

    evidence_id: str
    query: str
    source_id: str = ""
    path: str = ""
    score: float = 0.0
    content: str = ""
    injected: bool = True


class TransformationInputs(BaseModel):
    """Structured evidence describing the artifact being transformed."""

    source_artifact_id: str
    source_path: str = ""
    source_sha256: str
    source_technology: str
    source_language_version: str = ""
    source_text: str = ""  # bounded at assembly time
    source_loc: int = 0
    semantic_snapshot: SemanticModelSnapshot = Field(
        default_factory=SemanticModelSnapshot
    )

    analysis_identity: str = ""
    dependency_identity: str = ""
    requirements_identity: str = ""
    modernization_plan_ref: str = ""

    unit_id: str = ""
    project_id: str = ""
    job_id: str = ""

    business_context: str = ""
    target_architecture: str = ""
    verification_constraints: list[str] = Field(default_factory=list)


class TransformationPrompt(BaseModel):
    """The deterministic, provenance-aware prompt sent to an inference worker."""

    prompt_context_id: str
    system_prompt: str
    user_context: str
    assembled_at: datetime = Field(default_factory=_utc_now)
    token_estimate: int = 0
    context_digest: str = ""

    def to_text(self) -> str:
        return f"{self.system_prompt}\n\n{self.user_context}"


class TransformationContextAssembler:
    """Assemble a deterministic, provenance-aware LLM transformation prompt.

    The same inputs always yield the same ``prompt_context_id`` (the SHA-256
    of the canonical context digest), so every transformation request is
    reproducible/auditable.
    """

    def __init__(
        self,
        *,
        max_source_chars: int = 12000,
        max_semantic_methods: int = 60,
        max_dependencies: int = 80,
        max_rag_chars: int = 6000,
    ) -> None:
        self._max_source_chars = max_source_chars
        self._max_semantic_methods = max_semantic_methods
        self._max_dependencies = max_dependencies
        self._max_rag_chars = max_rag_chars

    def assemble(
        self,
        inputs: TransformationInputs,
        target_knowledge: Any,
        rag_evidence: list[RAGEvidenceBlock] | None = None,
    ) -> TransformationPrompt:
        """Build the full prompt from structured evidence."""
        snapshot = inputs.semantic_snapshot
        project_text = ""
        if target_knowledge is not None and getattr(
            target_knowledge, "project", None
        ) is not None:
            project_text = target_knowledge.project.to_context_text()
        digest_components = {
            "source_sha256": inputs.source_sha256,
            "source_technology": inputs.source_technology,
            "target_technology": getattr(target_knowledge, "name", "unknown"),
            "semantic_constructs": snapshot.semantic_constructs,
            "control_flow_nodes": snapshot.control_flow_nodes,
            "dependency_edges": snapshot.dependency_edges,
            "unresolved_semantics": snapshot.unresolved_semantics,
            "requirements_identity": inputs.requirements_identity,
            "modernization_plan_ref": inputs.modernization_plan_ref,
            "analysis_identity": inputs.analysis_identity,
            "project_conventions": project_text,
            "verification_constraints": inputs.verification_constraints,
        }
        context_digest = _sha256(
            json.dumps(digest_components, sort_keys=True, default=str)
        )
        prompt_context_id = _sha256(context_digest + "::autoforge-transformation")

        system_prompt = self._build_system_prompt(
            inputs.source_technology, target_knowledge
        )
        user_context = self._build_user_context(
            inputs, target_knowledge, rag_evidence or []
        )
        token_estimate = max(1, len(system_prompt) // 4) + max(
            1, len(user_context) // 4
        )
        return TransformationPrompt(
            prompt_context_id=prompt_context_id,
            system_prompt=system_prompt,
            user_context=user_context,
            token_estimate=token_estimate,
            context_digest=context_digest,
        )

    def _build_system_prompt(self, source_tech: str, target_knowledge: Any) -> str:
        tgt_name = getattr(target_knowledge, "name", "unknown")
        tgt_lang = getattr(
            getattr(target_knowledge, "language", None), "language", "unknown"
        )
        tgt_framework = getattr(
            getattr(target_knowledge, "framework", None), "framework", ""
        )
        return (
            "You are the AutoForge modernization transformation engine.\n"
            f"Source technology: {source_tech}\n"
            f"Target technology: {tgt_name} ({tgt_lang}"
            + (f" + {tgt_framework}" if tgt_framework else "")
            + ")\n"
            "You TRANSFORM legacy code into valid, production-oriented target code.\n"
            "Constraints:\n"
            "- Use ONLY the evidence provided in the context. Never invent semantics.\n"
            "- Preserve business behavior. Never elide logic silently.\n"
            "- When a legacy construct cannot be mapped safely, say so and mark it "
            "as an unresolved ambiguity (do NOT fabricate an implementation).\n"
            "- Emit code in a fenced code block prefixed with the language identifier.\n"
            "- If you cannot produce a faithful transformation, report BLOCKED with reasons.\n"
            "You must answer with a strict JSON object matching the requested schema."
        )

    def _build_user_context(
        self,
        inputs: TransformationInputs,
        target_knowledge: Any,
        rag_evidence: list[RAGEvidenceBlock],
    ) -> str:
        snapshot = inputs.semantic_snapshot
        blocks: list[str] = []
        blocks.append(
            "[TRANSFORMATION CONTEXT] id=%s\n"
            "unit_id=%s  artifact=%s  source_sha256=%s\n"
            "source_technology=%s  source_loc=%d\n"
            "analysis_identity=%s  requirements=%s  plan=%s"
            % (
                inputs.source_artifact_id,
                inputs.unit_id,
                inputs.source_path,
                inputs.source_sha256,
                inputs.source_technology,
                inputs.source_loc,
                inputs.analysis_identity or "NOT_USED",
                inputs.requirements_identity or "NOT_USED",
                inputs.modernization_plan_ref or "NOT_USED",
            )
        )
        blocks.append(
            "[SEMANTIC MODEL SUMMARY]\n"
            "constructs=%d control_flow_nodes=%d data_flow_edges=%d "
            "dependency_edges=%d methods=%d fields=%d"
            % (
                snapshot.semantic_constructs,
                snapshot.control_flow_nodes,
                snapshot.data_flow_edges,
                snapshot.dependency_edges,
                len(snapshot.methods),
                len(snapshot.fields),
            )
        )
        if snapshot.unresolved_semantics:
            blocks.append(
                "[UNRESOLVED SEMANTICS]\n" + "\n".join(
                    f"- {u}" for u in snapshot.unresolved_semantics
                )
            )
        if snapshot.methods:
            lines = []
            for method in snapshot.methods[: self._max_semantic_methods]:
                targets = ", ".join(method.perform_targets[:8]) or "-"
                notes = f"perform=[{targets}]" if method.perform_targets else ""
                lines.append(
                    f"- {method.kind} {method.name} "
                    f"(control_nodes={method.control_flow_nodes} {notes})".rstrip()
                )
            blocks.append("[METHODS / PARAGRAPHS]\n" + "\n".join(lines))
        if snapshot.fields:
            sample = snapshot.fields[:60]
            blocks.append(
                "[DATA ITEMS]\n"
                + "\n".join(
                    f"- {f.name} (level={f.level}, type={f.data_type or f.pic})"
                    for f in sample
                )
            )
        if snapshot.dependencies:
            dep_lines = []
            for dep in snapshot.dependencies[: self._max_dependencies]:
                dep_lines.append(f"- {dep.kind} {dep.target}")
            blocks.append("[DEPENDENCIES]\n" + "\n".join(dep_lines))
        if inputs.business_context:
            blocks.append("[BUSINESS CONTEXT]\n" + inputs.business_context[:2000])
        if inputs.target_architecture:
            blocks.append(
                "[TARGET ARCHITECTURE]\n" + inputs.target_architecture[:2000]
            )
        if target_knowledge is not None:
            blocks.append(target_knowledge.to_context_text())
        if inputs.verification_constraints:
            blocks.append(
                "[VERIFICATION CONSTRAINTS]\n"
                + "\n".join(f"- {c}" for c in inputs.verification_constraints)
            )
        if inputs.source_text:
            src = inputs.source_text[: self._max_source_chars]
            truncated = len(src) < len(inputs.source_text)
            blocks.append(
                "[SOURCE CODE]\n" + src + ("\n...[truncated]" if truncated else "")
            )
        injected = [ev for ev in rag_evidence if ev.injected]
        if injected:
            rag_blocks = []
            for ev in injected[:8]:
                rag_blocks.append(
                    "[RETRIEVED EVIDENCE] id=%s source=%s path=%s score=%.4f\n%s"
                    % (
                        ev.evidence_id,
                        ev.source_id,
                        ev.path,
                        ev.score,
                        ev.content[:1200],
                    )
                )
            blocks.append("[RAG EVIDENCE]\n" + "\n\n".join(rag_blocks))
        else:
            blocks.append("[RAG EVIDENCE]\nNOT_USED")
        return "\n\n".join(blocks)


__all__ = [
    "SemanticField",
    "SemanticMethod",
    "SemanticDependency",
    "SemanticModelSnapshot",
    "semantic_snapshot_from_analysis",
    "RAGEvidenceBlock",
    "TransformationInputs",
    "TransformationPrompt",
    "TransformationContextAssembler",
]