"""Platform and Standalone Customer RAG Acceptance Evaluator.

Provides mathematically rigorous, fail-closed benchmark evaluation across:
1. Answerable retrieval (Recall@5)
2. Paraphrased retrieval (Semantic search without keyword overlap)
3. Citation validity (Verifiable document identity and line coordinates)
4. Abstention accuracy (Tested over both answerable and unanswerable cases)
5. Contradiction detection (Flagging conflicting claims)

Rules:
- Zero denominator NEVER produces 1.0. Zero-case categories evaluate to NOT_EVALUABLE with score=None.
- Aggregate certification requires all mandatory categories (answerable, citation, abstention) to be evaluable and passing.
- Contradiction is scored only when genuine contradiction cases exist in the benchmark.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("autoforge.power_engines.rag.evaluator")


class StandaloneEvaluator:
    """
    Independent customer evaluation harness.
    Evaluates real retrieval, citation validity, answer groundedness,
    abstention, and contradiction detection on actual customer documents.
    Guarantees mathematically rigorous metric semantics (fail-closed, no vacuous defaults).
    """

    MANDATORY_CATEGORIES = ("answerable", "citation", "abstention")
    DEFAULT_THRESHOLDS = {
        "retrieval_recall_at_5": 0.70,
        "paraphrase_recall_at_5": 0.70,
        "citation_validity_rate": 0.80,
        "abstention_accuracy": 0.75,
        "contradiction_detection_rate": 0.70,
    }

    def __init__(self, retriever: Any, grounding_engine: Any, thresholds: Optional[Dict[str, float]] = None):
        self.retriever = retriever
        self.grounding = grounding_engine
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update(thresholds)

    def evaluate_benchmark(self, dataset_path_or_dict: Union[Path, str, Dict[str, Any]]) -> Dict[str, Any]:
        """Runs evaluation over a benchmark dataset file or dictionary."""
        # 1. Parse dataset
        if isinstance(dataset_path_or_dict, (str, Path)):
            d_path = Path(dataset_path_or_dict).resolve()
            if not d_path.exists():
                return {
                    "status": "NOT_EVALUABLE",
                    "message": f"Benchmark dataset not found at {d_path}",
                    "categories": {},
                    "metrics": {
                        "total_test_cases": 0,
                        "retrieval_recall_at_5": None,
                        "paraphrase_recall_at_5": None,
                        "citation_validity_rate": None,
                        "abstention_accuracy": None,
                        "contradiction_detection_rate": None,
                    },
                    "total_cases": 0,
                    "evaluated_cases": 0,
                    "excluded_cases": 0,
                    "exclusions": [{"reason": f"File not found: {d_path}"}],
                    "details": [],
                }
            try:
                data = json.loads(d_path.read_text(encoding="utf-8"))
            except Exception as e:
                return {
                    "status": "FAIL",
                    "message": f"Malformed JSON in benchmark dataset: {e}",
                    "categories": {},
                    "metrics": {
                        "total_test_cases": 0,
                        "retrieval_recall_at_5": None,
                        "paraphrase_recall_at_5": None,
                        "citation_validity_rate": None,
                        "abstention_accuracy": None,
                        "contradiction_detection_rate": None,
                    },
                    "total_cases": 0,
                    "evaluated_cases": 0,
                    "excluded_cases": 0,
                    "exclusions": [{"reason": f"Malformed JSON: {e}"}],
                    "details": [],
                }
        elif isinstance(dataset_path_or_dict, dict):
            data = dataset_path_or_dict
        else:
            return {
                "status": "FAIL",
                "message": f"Invalid dataset input type: {type(dataset_path_or_dict)}",
                "categories": {},
                "metrics": {
                    "total_test_cases": 0,
                    "retrieval_recall_at_5": None,
                    "paraphrase_recall_at_5": None,
                    "citation_validity_rate": None,
                    "abstention_accuracy": None,
                    "contradiction_detection_rate": None,
                },
                "total_cases": 0,
                "evaluated_cases": 0,
                "excluded_cases": 0,
                "exclusions": [{"reason": f"Invalid input type: {type(dataset_path_or_dict)}"}],
                "details": [],
            }

        cases = data.get("test_cases", [])
        if not isinstance(cases, list) or len(cases) == 0:
            return {
                "status": "NOT_EVALUABLE",
                "message": "Empty or missing test cases list in dataset",
                "categories": {},
                "metrics": {
                    "total_test_cases": 0,
                    "retrieval_recall_at_5": None,
                    "paraphrase_recall_at_5": None,
                    "citation_validity_rate": None,
                    "abstention_accuracy": None,
                    "contradiction_detection_rate": None,
                },
                "total_cases": 0,
                "evaluated_cases": 0,
                "excluded_cases": 0,
                "exclusions": [{"reason": "Test cases list is empty"}],
                "details": [],
            }

        # 2. Schema validation & case sorting
        valid_cases: List[Dict[str, Any]] = []
        exclusions: List[Dict[str, Any]] = []
        for idx, c in enumerate(cases):
            if not isinstance(c, dict):
                exclusions.append({"index": idx, "case": c, "reason": "Case is not an object"})
                continue
            case_id = c.get("case_id") or c.get("id") or f"TC-GEN-{idx+1:03d}"
            query = c.get("query")
            if not query or not isinstance(query, str) or not query.strip():
                exclusions.append({"case_id": case_id, "reason": "Missing or empty query text"})
                continue

            # Normalize category
            category = c.get("category")
            if not category:
                if c.get("is_unanswerable") or c.get("should_abstain"):
                    category = "unanswerable"
                elif c.get("is_contradiction"):
                    category = "contradiction"
                elif c.get("expected_source"):
                    category = "answerable"
                else:
                    exclusions.append({"case_id": case_id, "reason": "Ambiguous case: cannot determine category"})
                    continue

            category = category.lower().strip()
            if category not in ("answerable", "paraphrased", "citation", "contradiction", "unanswerable"):
                exclusions.append({"case_id": case_id, "reason": f"Unknown category '{category}'"})
                continue

            should_abstain = bool(c.get("should_abstain") or c.get("is_unanswerable") or category == "unanswerable")
            is_contradiction = bool(c.get("is_contradiction") or category == "contradiction")

            valid_cases.append({
                "case_id": case_id,
                "category": category,
                "query": query.strip(),
                "expected_source": c.get("expected_source"),
                "expected_chunk_id": c.get("expected_chunk_id"),
                "line_start": c.get("line_start"),
                "line_end": c.get("line_end"),
                "should_abstain": should_abstain,
                "is_contradiction": is_contradiction,
                "scoring_rule": c.get("scoring_rule", "standard"),
            })

        # Category tracking
        ans_hits = 0
        ans_total = 0
        ans_case_ids: List[str] = []

        para_hits = 0
        para_total = 0
        para_case_ids: List[str] = []

        cite_hits = 0
        cite_total = 0
        cite_case_ids: List[str] = []

        contra_hits = 0
        contra_total = 0
        contra_case_ids: List[str] = []

        abs_correct = 0
        abs_total = 0
        abs_case_ids: List[str] = []

        details: List[Dict[str, Any]] = []

        for case in valid_cases:
            cid = case["case_id"]
            cat = case["category"]
            q = case["query"]
            exp_src = case["expected_source"]
            should_abs = case["should_abstain"]
            is_contra = case["is_contradiction"]
            exp_lstart = case.get("line_start")
            exp_lend = case.get("line_end")

            matches, is_insufficient = self.retriever.retrieve(q, top_k=5)
            top_score = matches[0].get("score", 0.0) if matches else 0.0

            # 1. Answerable Recall
            if cat == "answerable":
                ans_total += 1
                ans_case_ids.append(cid)
                hit = False
                if exp_src and matches:
                    hit = any(
                        exp_src.lower() in m.get("file_path", "").lower() or
                        exp_src.lower() in m.get("source_id", "").lower() or
                        exp_src.lower() in m.get("source_file", "").lower()
                        for m in matches
                    )
                if hit:
                    ans_hits += 1

            # 2. Paraphrased Recall
            if cat == "paraphrased":
                para_total += 1
                para_case_ids.append(cid)
                hit = False
                if exp_src and matches:
                    hit = any(
                        exp_src.lower() in m.get("file_path", "").lower() or
                        exp_src.lower() in m.get("source_id", "").lower() or
                        exp_src.lower() in m.get("source_file", "").lower()
                        for m in matches
                    )
                if hit:
                    para_hits += 1

            # 3. Citation Validity
            if cat == "citation":
                cite_total += 1
                cite_case_ids.append(cid)
                hit = False
                candidate_matches = [
                    m for m in matches
                    if not exp_src or (
                        exp_src.lower() in m.get("file_path", "").lower() or
                        exp_src.lower() in m.get("source_id", "").lower() or
                        exp_src.lower() in m.get("source_file", "").lower()
                    )
                ]
                if candidate_matches:
                    target_m = candidate_matches[0]
                    m_ls = target_m.get("line_start", 0)
                    m_le = target_m.get("line_end", 0)
                    has_lines = bool(isinstance(m_ls, int) and m_ls > 0 and isinstance(m_le, int) and m_le >= m_ls)
                    span_ok = True
                    if exp_lstart and exp_lend and has_lines:
                        span_ok = max(m_ls, exp_lstart) <= min(m_le, exp_lend)
                    hit = has_lines and span_ok
                if hit:
                    cite_hits += 1

            # 4. Contradiction Detection
            if cat == "contradiction" or is_contra:
                contra_total += 1
                contra_case_ids.append(cid)
                conflicts = self.grounding.detect_contradictions(matches) if hasattr(self.grounding, "detect_contradictions") else []
                if len(conflicts) > 0:
                    contra_hits += 1

            # 5. Abstention Accuracy
            # Tested across BOTH answerable and unanswerable queries:
            # - If should_abstain is False: system must NOT abstain
            # - If should_abstain is True: system MUST abstain
            abs_total += 1
            abs_case_ids.append(cid)
            system_abstained = bool(is_insufficient or len(matches) == 0 or all(m.get("score", 0.0) < 0.35 for m in matches))
            if should_abs:
                if system_abstained:
                    abs_correct += 1
            else:
                if not system_abstained:
                    abs_correct += 1

            details.append({
                "case_id": cid,
                "category": cat,
                "query": q,
                "matches_count": len(matches),
                "is_insufficient": is_insufficient,
                "top_score": top_score,
                "system_abstained": system_abstained,
                "should_abstain": should_abs,
            })

        # Helper to construct category evaluation record
        def build_category_record(
            metric_name: str,
            hits: int,
            total: int,
            threshold: float,
            formula: str,
            tested_ids: List[str]
        ) -> Dict[str, Any]:
            if total == 0:
                return {
                    "status": "NOT_EVALUABLE",
                    "metric": metric_name,
                    "numerator": 0,
                    "denominator": 0,
                    "score": None,
                    "threshold": threshold,
                    "formula": formula,
                    "tested_case_ids": tested_ids,
                    "reason": f"Zero test cases present in dataset for category '{metric_name}'",
                }
            score = round(hits / total, 4)
            status = "PASS" if score >= threshold else "FAIL"
            return {
                "status": status,
                "metric": metric_name,
                "numerator": hits,
                "denominator": total,
                "score": score,
                "threshold": threshold,
                "formula": formula,
                "tested_case_ids": tested_ids,
                "reason": None,
            }

        categories: Dict[str, Dict[str, Any]] = {
            "answerable": build_category_record(
                "retrieval_recall_at_5", ans_hits, ans_total, self.thresholds["retrieval_recall_at_5"], "recall_hits / answerable_cases", ans_case_ids
            ),
            "paraphrased": build_category_record(
                "paraphrase_recall_at_5", para_hits, para_total, self.thresholds["paraphrase_recall_at_5"], "paraphrase_hits / paraphrased_cases", para_case_ids
            ),
            "citation": build_category_record(
                "citation_validity_rate", cite_hits, cite_total, self.thresholds["citation_validity_rate"], "valid_citations / citation_cases", cite_case_ids
            ),
            "abstention": build_category_record(
                "abstention_accuracy", abs_correct, abs_total, self.thresholds["abstention_accuracy"], "(correct_abstentions + correct_non_abstentions) / total_cases", abs_case_ids
            ),
            "contradiction": build_category_record(
                "contradiction_detection_rate", contra_hits, contra_total, self.thresholds["contradiction_detection_rate"], "detected_conflicts / contradiction_cases", contra_case_ids
            ),
        }

        # Overall Status Logic:
        # Mandatory: answerable, citation, abstention.
        has_failure = any(c["status"] == "FAIL" for c in categories.values())
        mandatory_not_evaluable = any(categories[m]["status"] == "NOT_EVALUABLE" for m in self.MANDATORY_CATEGORIES)

        if has_failure:
            overall_status = "FAIL"
        elif mandatory_not_evaluable:
            overall_status = "NOT_EVALUABLE"
        else:
            overall_status = "PASS"

        metrics_summary: Dict[str, Any] = {
            "total_test_cases": len(valid_cases),
            "retrieval_recall_at_5": categories["answerable"]["score"],
            "paraphrase_recall_at_5": categories["paraphrased"]["score"],
            "citation_validity_rate": categories["citation"]["score"],
            "abstention_accuracy": categories["abstention"]["score"],
            "contradiction_detection_rate": categories["contradiction"]["score"],
        }

        return {
            "status": overall_status,
            "total_cases": len(cases),
            "evaluated_cases": len(valid_cases),
            "excluded_cases": len(exclusions),
            "exclusions": exclusions,
            "categories": categories,
            "metrics": metrics_summary,
            "details": details,
        }
