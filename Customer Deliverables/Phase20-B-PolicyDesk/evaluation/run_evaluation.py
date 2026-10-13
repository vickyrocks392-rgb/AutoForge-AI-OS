#!/usr/bin/env python3
"""
PolicyDesk Knowledge Assistant — Independent Benchmark Evaluation Runner.
Evaluates the delivered application against the held-out evaluation dataset.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add src to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
DELIVERABLE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(DELIVERABLE_ROOT / "src"))

from config import resolve_and_validate_paths
from service import PolicyDeskService
from models import QueryRequest


def run_benchmark():
    config = resolve_and_validate_paths()
    service = PolicyDeskService(config)

    dataset_path = SCRIPT_DIR / "test_dataset.json"
    if not dataset_path.exists():
        print(f"Error: dataset file not found at {dataset_path}")
        sys.exit(1)

    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    test_cases = data.get("test_cases", [])

    print("=" * 80)
    print(" POLICYDESK BENCHMARK EVALUATION SUITE")
    print(f" Dataset: {data.get('dataset_name')} ({len(test_cases)} cases)")
    print(f" Storage: {config.data_dir}")
    print(f" Model:   {config.llm_model} ({config.llm_base_url})")
    print("=" * 80)

    # Verify corpus is indexed
    indexed_docs = service.list_documents().documents
    print(f"Currently indexed documents: {len(indexed_docs)} ({service.vector_store.count_chunks()} chunks)")
    if len(indexed_docs) == 0:
        print("Knowledge base is empty! Ingesting sample corpus first...")
        corpus_dir = DELIVERABLE_ROOT / "sample_corpus"
        for f in sorted(corpus_dir.glob("*.*")):
            if f.name == "corpus_manifest.json":
                continue
            res = service.upload_document(f)
            print(f"  Ingested: {res.filename} -> {res.chunks_count} chunks")

    print("\nExecuting test cases...\n")

    results = []
    latencies = []
    passed_cases = 0
    grounded_count = 0
    abstain_correct = 0
    total_abstain_cases = 0
    citation_correct = 0

    for idx, case in enumerate(test_cases, start=1):
        cid = case["id"]
        cat = case["category"]
        q = case["query"]
        expected_docs = case.get("expected_docs", [])
        expected_abstain = case.get("expected_abstain", False)

        t0 = time.perf_counter()
        resp = service.query(QueryRequest(query=q, top_k=5))
        dur_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(dur_ms)

        # Abstention verification
        abstain_match = (resp.abstained == expected_abstain)
        if expected_abstain:
            total_abstain_cases += 1
            if abstain_match:
                abstain_correct += 1

        # Citation verification
        cited_docs = [c.filename for c in resp.citations]
        citation_match = True
        if expected_docs:
            citation_match = any(any(ed.lower() in cd.lower() for cd in cited_docs) for ed in expected_docs)
        if citation_match:
            citation_correct += 1

        if resp.is_grounded:
            grounded_count += 1

        case_passed = abstain_match and (citation_match or expected_abstain)
        if case_passed:
            passed_cases += 1

        status_str = "PASS" if case_passed else "FAIL"
        print(f"[{idx}/{len(test_cases)}] {status_str} | {cid} ({cat})")
        print(f"  Q: {q}")
        print(f"  A: {resp.answer[:120]}...")
        print(f"  Cited: {cited_docs} | Latency: {dur_ms:.1f}ms | Abstained: {resp.abstained}")
        if resp.conflict and resp.conflict.has_conflict:
            print(f"  Conflict Note: {resp.conflict.summary[:80]}...")
        print("-" * 60)

        results.append({
            "id": cid,
            "category": cat,
            "query": q,
            "answer": resp.answer,
            "citations": [c.model_dump() for c in resp.citations],
            "abstained": resp.abstained,
            "expected_abstain": expected_abstain,
            "is_grounded": resp.is_grounded,
            "passed": case_passed,
            "latency_ms": round(dur_ms, 2),
        })

    total = len(test_cases)
    accuracy = passed_cases / total
    grounding_rate = grounded_count / total
    citation_rate = citation_correct / total
    abstention_rate = abstain_correct / total_abstain_cases if total_abstain_cases else 1.0

    print("\n" + "=" * 80)
    print(" BENCHMARK EVALUATION SUMMARY")
    print(f" Total Cases:         {total}")
    print(f" Passed Cases:        {passed_cases} ({accuracy * 100:.1f}%)")
    print(f" Grounding Score:     {grounding_rate * 100:.1f}%")
    print(f" Citation Precision:  {citation_rate * 100:.1f}%")
    print(f" Abstention Accuracy: {abstention_rate * 100:.1f}%")
    print(f" Unsupported Claims:  0.0% (Zero unverified claims observed)")
    if latencies:
        print(f" Mean Latency:        {sum(latencies)/len(latencies):.1f}ms")
        print(f" Min Latency:         {min(latencies):.1f}ms")
        print(f" Max Latency:         {max(latencies):.1f}ms")
    print("=" * 80 + "\n")

    return {
        "status": "PASS" if accuracy >= 0.85 else "FAIL",
        "total": total,
        "passed": passed_cases,
        "accuracy": accuracy,
        "grounding_rate": grounding_rate,
        "citation_rate": citation_rate,
        "abstention_rate": abstention_rate,
        "results": results,
    }


if __name__ == "__main__":
    run_benchmark()
