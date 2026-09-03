"""Dependency graph for COBOL/JCL/COPYBOOK/SQL (Phase 18-G.3).

Directed multigraph of CALL/COPY/EXEC_PGM/EXEC_PROC/DD_DSN/SQL_TABLE/PERFORM edges.
Provides topological sort (Kahn) and cycle detection (Tarjan SCC).
"""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now(): return datetime.now(timezone.utc)


class EdgeKind(str, Enum):
    CALL = "call"; COPY = "copy"; EXEC_PGM = "exec_pgm"
    EXEC_PROC = "exec_proc"; DD_DSN = "dd_dsn"; SQL_TABLE = "sql_table"
    PERFORM = "perform"; TRANSACTION = "transaction"


@dataclass
class GraphNode:
    name: str; kind: str = "module"; attrs: dict = field(default_factory=dict)
    def __hash__(self): return hash((self.name, self.kind))
    def __eq__(self, other): return self.name == other.name and self.kind == other.kind


@dataclass
class GraphEdge:
    src: GraphNode; dst: GraphNode; kind: EdgeKind
    line: int = 0; attrs: dict = field(default_factory=dict)


class DependencyGraph:
    def __init__(self):
        self.nodes = {}; self.edges = []
        self._adj = defaultdict(list); self._in_degree = defaultdict(int)

    def node(self, name, kind="module", **attrs):
        if not name: return None
        name = str(name).strip().upper()
        if not name: return None
        key = (name, kind)
        if key not in self.nodes:
            self.nodes[key] = GraphNode(name=name, kind=kind, attrs=attrs)
        return self.nodes[key]

    def edge(self, src, dst, kind, line=0, **attrs):
        if not src or not dst: return None
        e = GraphEdge(src=src, dst=dst, kind=kind, line=line, attrs=attrs)
        self.edges.append(e)
        self._adj[src].append((dst, e))
        self._in_degree[dst] += 1
        return e

    def topological_sort(self):
        from collections import deque
        in_deg = defaultdict(int)
        for e in self.edges: in_deg[e.dst] += 1
        q = deque([n for n in self.nodes.values() if in_deg[n] == 0])
        out = []
        while q:
            n = q.popleft(); out.append(n)
            for child, _e in self._adj.get(n, []):
                in_deg[child] -= 1
                if in_deg[child] == 0: q.append(child)
        if len(out) != len(self.nodes):
            rem = [n for n in self.nodes.values() if in_deg.get(n, 0) > 0]
            raise ValueError(f"cycle: {[(n.name, n.kind) for n in rem]}")
        return out

    def cycles(self):
        index = {}; lowlink = {}; on_stack = {}; stack = []; idx = [0]; sccs = []
        for v in list(self.nodes.values()):
            if v not in index:
                self._sc(v, index, lowlink, on_stack, stack, idx, sccs)
        return [s for s in sccs if len(s) > 1]

    def _sc(self, v, index, lowlink, on_stack, stack, idx, sccs):
        index[v] = idx[0]; lowlink[v] = idx[0]; idx[0] += 1
        stack.append(v); on_stack[v] = True
        for w, _e in self._adj.get(v, []):
            if w not in index:
                self._sc(w, index, lowlink, on_stack, stack, idx, sccs)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w):
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop(); on_stack[w] = False; scc.append(w)
                if w == v: break
            sccs.append(scc)

    def summary(self):
        kinds = set(n.kind for n in self.nodes.values())
        return {
            "node_count": len(self.nodes), "edge_count": len(self.edges),
            "nodes_by_kind": {k: sum(1 for n in self.nodes.values() if n.kind == k) for k in kinds},
            "edges_by_kind": {k: sum(1 for e in self.edges if e.kind == k) for k in EdgeKind},
            "cycles": [[(n.name, n.kind) for n in s] for s in self.cycles()],
        }

    def to_dict(self):
        return {
            "nodes": [{"name": n.name, "kind": n.kind, "attrs": n.attrs} for n in self.nodes.values()],
            "edges": [{"src": e.src.name, "dst": e.dst.name, "kind": e.kind.value, "line": e.line} for e in self.edges],
        }

"""Convenience builders for graph population from parser outputs."""


def build_from_cobol(program_id, cobol_summary, graph):
    if not program_id: return
    prog = graph.node(program_id, kind="COBOL")
    for c in (cobol_summary.get("copybooks") or []):
        cb = graph.node(c, kind="COPYBOOK")
        graph.edge(prog, cb, EdgeKind.COPY)
    for c in (cobol_summary.get("external_calls") or []):
        target = graph.node(c, kind="COBOL")
        graph.edge(prog, target, EdgeKind.CALL)
    for p in (cobol_summary.get("performed_targets") or []):
        tgt = graph.node(p, kind="PARAGRAPH")
        graph.edge(prog, tgt, EdgeKind.PERFORM)
    return prog


def build_from_jcl(jcl_summary, graph):
    job = graph.node(jcl_summary.get("job_name", "JOB"), kind="JCL")
    for s in jcl_summary.get("steps", []):
        step = graph.node(s.get("name", "STEP"), kind="JCL_STEP")
        graph.edge(job, step, EdgeKind.EXEC_PGM, line=s.get("line", 0))
        if "program" in s:
            pgm = graph.node(s["program"], kind="COBOL")
            graph.edge(step, pgm, EdgeKind.CALL, line=s.get("line", 0))
        elif "proc" in s:
            proc = graph.node(s["proc"], kind="PROC")
            graph.edge(step, proc, EdgeKind.EXEC_PROC, line=s.get("line", 0))
    for d in jcl_summary.get("datasets", []):
        ds = graph.node(d, kind="DATASET")
        graph.edge(job, ds, EdgeKind.DD_DSN)
    for p in jcl_summary.get("proc_libs", []):
        pl = graph.node(p, kind="PROC_LIB")
        graph.edge(job, pl, EdgeKind.EXEC_PROC)
    return job


def build_from_sql(sql_summary, graph):
    for t in sql_summary.get("tables", []): graph.node(t, kind="SQL_TABLE")
    for v in sql_summary.get("views", []): graph.node(v, kind="SQL_VIEW")
    for i in sql_summary.get("indexes", []): graph.node(i, kind="SQL_INDEX")


__all__ = ["DependencyGraph", "GraphNode", "GraphEdge", "EdgeKind", "build_from_cobol", "build_from_jcl", "build_from_sql"]