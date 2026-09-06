"""Generalized Technology-Neutral Semantic Query Engine for AutoForge.

Provides high-level engineering queries across the TechnologyNeutralSemanticModel
and its underlying unified SemanticGraph.

Supports querying:
- Dataset and file usage across programs and jobs
- Data flow lineage, input-output dependencies, and field mutations
- Business rule influence and referenced fields
- Job step orchestration and program execution
- Procedure call hierarchies and callers
- Unresolved references and specialist intervention points
"""

from __future__ import annotations

from typing import Any
from collections import deque

from autoforge_modernization.semantic.model import (
    DataFlowEdge,
    ResolutionStatus,
    SemanticIOKind,
    TechnologyNeutralSemanticModel,
    UnresolvedReference,
)


class SemanticQueryEngine:
    """Answers engineering questions across technology-neutral semantic models."""

    def __init__(self, model: TechnologyNeutralSemanticModel) -> None:
        self.model = model
        self.graph = model.semantic_graph

    def programs_reading_dataset(self, dataset_name: str) -> list[str]:
        """Which programs read this dataset or file?"""
        d_upper = dataset_name.upper().strip()
        readers: set[str] = set()

        # Check graph edges
        for edge in self.graph.edges:
            if edge.kind == "READS":
                dst_node = self.graph.get_node(edge.dst)
                if dst_node and (dst_node.name.upper() == d_upper or d_upper in edge.dst):
                    src_node = self.graph.get_node(edge.src)
                    if src_node and src_node.kind == "PROGRAM":
                        readers.add(src_node.name)

        # Also inspect modules directly
        for mod_name, mod in self.model.modules.items():
            if mod.module_type == "program":
                for io in mod.io_operations:
                    if io.kind in (SemanticIOKind.DATA_READ, SemanticIOKind.DATABASE_READ):
                        if io.resource_name.upper() == d_upper or d_upper in io.resource_name.upper():
                            readers.add(mod_name)

        return sorted(readers)

    def programs_writing_dataset(self, dataset_name: str) -> list[str]:
        """Which programs write to this dataset or file?"""
        d_upper = dataset_name.upper().strip()
        writers: set[str] = set()

        for edge in self.graph.edges:
            if edge.kind == "WRITES":
                dst_node = self.graph.get_node(edge.dst)
                if dst_node and (dst_node.name.upper() == d_upper or d_upper in edge.dst):
                    src_node = self.graph.get_node(edge.src)
                    if src_node and src_node.kind == "PROGRAM":
                        writers.add(src_node.name)

        for mod_name, mod in self.model.modules.items():
            if mod.module_type == "program":
                for io in mod.io_operations:
                    if io.kind in (SemanticIOKind.DATA_WRITE, SemanticIOKind.DATA_UPDATE, SemanticIOKind.DATABASE_WRITE):
                        if io.resource_name.upper() == d_upper or d_upper in io.resource_name.upper():
                            writers.add(mod_name)

        return sorted(writers)

    def fields_influencing_rule(self, rule_id_or_name: str) -> list[str]:
        """Which fields directly or indirectly influence this business rule?"""
        r_target = rule_id_or_name.upper().strip()
        fields: set[str] = set()

        # Find matching business rules
        matching_rules = []
        for r in self.model.global_business_rules:
            if r.rule_id == rule_id_or_name or r_target in r.name.upper():
                matching_rules.append(r)
        for mod in self.model.modules.values():
            for r in mod.business_rules:
                if r.rule_id == rule_id_or_name or r_target in r.name.upper() or rule_id_or_name in r.statement:
                    matching_rules.append(r)

        for rule in matching_rules:
            for f in rule.referenced_fields:
                fields.add(f)
            for pred in rule.predicates:
                if pred.left_operand and not pred.left_operand.replace(".", "").isdigit():
                    fields.add(pred.left_operand)

        # Follow upstream data flows for the identified fields
        upstream_fields: set[str] = set(fields)
        queue = deque(list(fields))
        visited = set(queue)
        while queue:
            curr = queue.popleft()
            for df in self.model.data_flows:
                if df.target.upper() == curr.upper() and df.source_kind == "FIELD":
                    if df.source not in visited:
                        visited.add(df.source)
                        upstream_fields.add(df.source)
                        queue.append(df.source)

        return sorted(upstream_fields)

    def programs_executed_by_job(self, job_name: str) -> list[str]:
        """What programs does this job execute?"""
        j_upper = job_name.upper().strip()
        programs: set[str] = set()

        job_mod = self.model.get_module(job_name) or self.model.get_module(j_upper)
        if job_mod and job_mod.module_type == "job":
            for dep in job_mod.external_dependencies:
                programs.add(dep)
            for proc in job_mod.procedures:
                for op in proc.operations:
                    if op.target:
                        programs.add(op.target)

        # Graph-based traversal
        job_node_id = f"JOB:{j_upper}"
        step_edges = self.graph.outgoing_edges(job_node_id, kind="EXECUTES")
        for se in step_edges:
            call_edges = self.graph.outgoing_edges(se.dst, kind="CALLS")
            for ce in call_edges:
                dst_node = self.graph.get_node(ce.dst)
                if dst_node:
                    programs.add(dst_node.name)

        return sorted(programs)

    def callers_of_procedure(self, proc_name: str) -> list[str]:
        """Which procedures or paragraphs call this procedure?"""
        p_upper = proc_name.upper().strip()
        callers: set[str] = set()

        for mod in self.model.modules.values():
            for proc in mod.procedures:
                if p_upper in [c.upper() for c in proc.called_procedures]:
                    callers.add(f"{mod.name}.{proc.name}" if len(self.model.modules) > 1 else proc.name)
                for op in proc.operations:
                    if op.target.upper() == p_upper:
                        callers.add(f"{mod.name}.{proc.name}" if len(self.model.modules) > 1 else proc.name)

        return sorted(callers)


    def writers_of_field(self, field_name: str) -> list[str]:
        """Where is this field written or mutated?"""
        f_upper = field_name.upper().strip()
        writers: set[str] = set()

        for mod in self.model.modules.values():
            for proc in mod.procedures:
                for op in proc.operations:
                    if f_upper in [m.upper() for m in op.mutated_fields] or op.target.upper() == f_upper:
                        writers.add(f"{mod.name}.{proc.name}")
            for df in mod.data_flows:
                if df.target.upper() == f_upper:
                    writers.add(f"{mod.name}.{df.procedure_name or 'FLOW'}")

        for df in self.model.data_flows:
            if df.target.upper() == f_upper:
                writers.add(df.procedure_name or "GLOBAL_DATA_FLOW")

        return sorted(writers)

    def outputs_dependent_on_input(self, input_name: str) -> list[str]:
        """Which outputs and fields depend on this input or source field?"""
        i_upper = input_name.upper().strip()
        dependents: set[str] = set()

        # Forward reachability through data flows
        queue = deque([i_upper])
        visited = {i_upper}

        while queue:
            curr = queue.popleft()
            for df in self.model.data_flows:
                if df.source.upper() == curr:
                    tgt = df.target.upper()
                    dependents.add(tgt)
                    if tgt not in visited:
                        visited.add(tgt)
                        queue.append(tgt)

        return sorted(dependents)

    def unresolved_dependencies(self) -> list[UnresolvedReference]:
        """Which unresolved dependencies or references remain in the model?"""
        unresolved = list(self.model.unresolved_references)

        # Also inspect graph edges marked UNRESOLVED
        for edge in self.graph.edges:
            if edge.resolution_status in (ResolutionStatus.UNRESOLVED, ResolutionStatus.SPECIALIST_REQUIRED):
                src_n = self.graph.get_node(edge.src)
                dst_n = self.graph.get_node(edge.dst)
                src_name = src_n.name if src_n else edge.src
                dst_name = dst_n.name if dst_n else edge.dst
                if not any(u.target_name == dst_name for u in unresolved):
                    unresolved.append(
                        UnresolvedReference(
                            source_module=src_name,
                            target_name=dst_name,
                            reference_kind=edge.kind,
                            reason=f"Edge '{edge.kind}' marked {edge.resolution_status.value}",
                            confidence=0.0,
                            provenance=edge.provenance,
                        )
                    )

        return unresolved

    def get_call_graph(self) -> dict[str, list[str]]:
        """Return adjacency list of caller -> callee relationships."""
        adj: dict[str, set[str]] = {}
        for edge in self.graph.edges:
            if edge.kind in ("CALLS", "EXECUTES", "TRANSFERS_TO"):
                src_n = self.graph.get_node(edge.src)
                dst_n = self.graph.get_node(edge.dst)
                src_name = src_n.name if src_n else edge.src
                dst_name = dst_n.name if dst_n else edge.dst
                adj.setdefault(src_name, set()).add(dst_name)
        return {k: sorted(v) for k, v in adj.items()}

    def get_data_lineage(self, field_or_dataset: str) -> list[DataFlowEdge]:
        """Return the complete data lineage trail starting from or arriving at a symbol."""
        s_upper = field_or_dataset.upper().strip()
        return [
            df for df in self.model.data_flows
            if df.source.upper() == s_upper or df.target.upper() == s_upper
        ]
