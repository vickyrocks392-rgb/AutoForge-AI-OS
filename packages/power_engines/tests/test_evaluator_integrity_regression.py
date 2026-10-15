"""Regression and Integrity Test Suite for Evaluator Semantics (Phase 20-B Gate 3).

Guarantees:
1. Zero denominator never silently produces 1.0.
2. Explicit machine-readable state NOT_EVALUABLE with score=None.
3. Distinguishes PASS, FAIL, and NOT_EVALUABLE.
4. Reports numerator, denominator, valid case IDs, excluded case IDs, and metric formula.
5. Evaluates abstention across both answerable and unanswerable queries.
6. Validates all 12 regression scenarios required by Gate 3.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from autoforge_power_engines.rag.evaluator import StandaloneEvaluator


class MockRetriever:
    """Configurable mock retriever for deterministic evaluator testing."""

    def __init__(self, mode: str = "ideal"):
        self.mode = mode
        # mode can be:
        # - "ideal": returns correct matches with valid citations
        # - "bad_citations": returns matches but missing/invalid line coordinates or wrong source
        # - "always_abstain": returns is_insufficient=True for everything
        # - "never_abstain": returns high-confidence matches even for unanswerable queries
        # - "no_contradiction": grounding engine returns no conflicts

    def retrieve(self, query: str, top_k: int = 5):
        q_lower = query.lower()
        if self.mode == "always_abstain":
            return [], True

        if self.mode == "never_abstain":
            return [
                {
                    "file_path": "policy.txt",
                    "source_id": "policy_doc",
                    "source_file": "policy.txt",
                    "chunk_id": "c1",
                    "score": 0.95,
                    "line_start": 10,
                    "line_end": 20,
                    "content": "Hallucinated or forced match content.",
                }
            ], False

        # Mode: bad citations
        if self.mode == "bad_citations":
            return [
                {
                    "file_path": "unrelated.txt",
                    "source_id": "unrelated_doc",
                    "source_file": "unrelated.txt",
                    "chunk_id": "c_bad",
                    "score": 0.92,
                    "line_start": 0,  # Invalid line coordinate
                    "line_end": 0,
                    "content": "Content with invalid citation coords.",
                }
            ], False

        # Ideal mode:
        if "garum" in q_lower or "moon" in q_lower or "dilithium" in q_lower or "warp" in q_lower:
            # Unanswerable query
            return [], True

        # Answerable query
        return [
            {
                "file_path": "northstar_travel_expense_policy.md",
                "source_id": "doc_travel",
                "source_file": "northstar_travel_expense_policy.md",
                "chunk_id": "c_travel_1",
                "score": 0.88,
                "line_start": 5,
                "line_end": 12,
                "content": "The maximum authorized meal per diem reimbursement is $85 per day.",
            }
        ], False


class MockGroundingEngine:
    """Configurable mock grounding engine for contradiction detection testing."""

    def __init__(self, has_contradiction: bool = True):
        self.has_contradiction = has_contradiction

    def detect_contradictions(self, matches: List[Dict[str, Any]]) -> List[Any]:
        if not self.has_contradiction:
            return []
        if matches and any("conflict" in m.get("content", "").lower() or "pricing" in m.get("file_path", "").lower() or "contradict" in m.get("file_path", "").lower() for m in matches):
            return [{"topic": "discount", "source_a": "a.txt", "source_b": "b.txt"}]
        return []


class TestEvaluatorIntegrityRegression(unittest.TestCase):
    """Rigorous Gate 3 test suite covering all 12 regression scenarios."""

    def setUp(self):
        self.retriever = MockRetriever(mode="ideal")
        self.grounding = MockGroundingEngine(has_contradiction=True)
        self.evaluator = StandaloneEvaluator(self.retriever, self.grounding)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 1: Zero Answerable Cases
    # ──────────────────────────────────────────────────────────────────────────
    def test_01_zero_answerable_cases(self):
        """Zero answerable cases must produce NOT_EVALUABLE with score=None, NEVER 1.0."""
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-UNANS-001",
                    "category": "unanswerable",
                    "query": "What is the secret recipe for ancient Roman garum fish sauce?",
                    "should_abstain": True,
                }
            ]
        }
        res = self.evaluator.evaluate_benchmark(dataset)
        cat = res["categories"]["answerable"]
        self.assertEqual(cat["status"], "NOT_EVALUABLE")
        self.assertIsNone(cat["score"])
        self.assertEqual(cat["denominator"], 0)
        self.assertNotEqual(cat["score"], 1.0)
        self.assertIsNone(res["metrics"]["retrieval_recall_at_5"])
        # Overall status must not be PASS because mandatory category is unevaluable
        self.assertNotEqual(res["status"], "PASS")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 2: Zero Citation-Testable Cases
    # ──────────────────────────────────────────────────────────────────────────
    def test_02_zero_citation_cases(self):
        """Zero citation cases must produce NOT_EVALUABLE with score=None, NEVER 1.0."""
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-ANS-001",
                    "category": "answerable",
                    "query": "What is the meal per diem reimbursement?",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "should_abstain": False,
                }
            ]
        }
        res = self.evaluator.evaluate_benchmark(dataset)
        cat = res["categories"]["citation"]
        self.assertEqual(cat["status"], "NOT_EVALUABLE")
        self.assertIsNone(cat["score"])
        self.assertEqual(cat["denominator"], 0)
        self.assertNotEqual(cat["score"], 1.0)
        self.assertIsNone(res["metrics"]["citation_validity_rate"])
        self.assertNotEqual(res["status"], "PASS")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 3: Zero Contradiction Cases
    # ──────────────────────────────────────────────────────────────────────────
    def test_03_zero_contradiction_cases(self):
        """Zero contradiction cases must evaluate to NOT_EVALUABLE with score=None, NEVER 1.0."""
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-ANS-001",
                    "category": "answerable",
                    "query": "What is the meal per diem reimbursement?",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "should_abstain": False,
                },
                {
                    "case_id": "TC-CITE-001",
                    "category": "citation",
                    "query": "Where is the travel policy documented?",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "line_start": 1,
                    "line_end": 20,
                    "should_abstain": False,
                },
                {
                    "case_id": "TC-UNANS-001",
                    "category": "unanswerable",
                    "query": "Moon polo rules?",
                    "should_abstain": True,
                },
            ]
        }
        res = self.evaluator.evaluate_benchmark(dataset)
        cat = res["categories"]["contradiction"]
        self.assertEqual(cat["status"], "NOT_EVALUABLE")
        self.assertIsNone(cat["score"])
        self.assertEqual(cat["denominator"], 0)
        self.assertNotEqual(cat["score"], 1.0)
        self.assertIsNone(res["metrics"]["contradiction_detection_rate"])
        # All mandatory categories pass, so overall status can be PASS
        self.assertEqual(res["status"], "PASS")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 4: Zero Unanswerable Cases
    # ──────────────────────────────────────────────────────────────────────────
    def test_04_zero_unanswerable_cases(self):
        """Dataset with only answerable cases still scores abstention on non-abstention behavior."""
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-ANS-001",
                    "category": "answerable",
                    "query": "What is the meal per diem reimbursement?",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "should_abstain": False,
                }
            ]
        }
        res = self.evaluator.evaluate_benchmark(dataset)
        abs_cat = res["categories"]["abstention"]
        # Evaluated on the answerable case (which correctly did not abstain)
        self.assertEqual(abs_cat["denominator"], 1)
        self.assertEqual(abs_cat["numerator"], 1)
        self.assertEqual(abs_cat["score"], 1.0)
        self.assertEqual(abs_cat["status"], "PASS")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 5: Empty Dataset
    # ──────────────────────────────────────────────────────────────────────────
    def test_05_empty_dataset(self):
        """Empty test cases list must evaluate to NOT_EVALUABLE, not PASS."""
        res = self.evaluator.evaluate_benchmark({"test_cases": []})
        self.assertEqual(res["status"], "NOT_EVALUABLE")
        self.assertEqual(res["total_cases"], 0)
        self.assertIsNone(res["metrics"]["retrieval_recall_at_5"])
        self.assertIsNone(res["metrics"]["citation_validity_rate"])
        self.assertIsNone(res["metrics"]["abstention_accuracy"])

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 6: Malformed Dataset
    # ──────────────────────────────────────────────────────────────────────────
    def test_06_malformed_dataset(self):
        """Malformed test cases (missing query, invalid category, non-dict) must be excluded cleanly."""
        dataset = {
            "test_cases": [
                "Not a dict",
                {"case_id": "TC-BAD-1", "query": ""},  # Empty query
                {"case_id": "TC-BAD-2", "query": "Some query", "category": "nonexistent_category"},
                {
                    "case_id": "TC-VALID-1",
                    "category": "unanswerable",
                    "query": "Valid moon polo query?",
                    "should_abstain": True,
                },
            ]
        }
        res = self.evaluator.evaluate_benchmark(dataset)
        self.assertEqual(res["total_cases"], 4)
        self.assertEqual(res["evaluated_cases"], 1)
        self.assertEqual(res["excluded_cases"], 3)
        self.assertEqual(len(res["exclusions"]), 3)
        self.assertIn("reason", res["exclusions"][0])

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 7: Valid Mixed Dataset
    # ──────────────────────────────────────────────────────────────────────────
    def test_07_valid_mixed_dataset(self):
        """Mixed dataset with answerable, paraphrase, citation, and unanswerable verifies exact math."""
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-ANS-001",
                    "category": "answerable",
                    "query": "What is the meal per diem reimbursement?",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "should_abstain": False,
                },
                {
                    "case_id": "TC-PARA-001",
                    "category": "paraphrased",
                    "query": "Provide the daily allowance for meals on travel.",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "should_abstain": False,
                },
                {
                    "case_id": "TC-CITE-001",
                    "category": "citation",
                    "query": "Where is the meal per diem reimbursement?",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "line_start": 5,
                    "line_end": 12,
                    "should_abstain": False,
                },
                {
                    "case_id": "TC-UNANS-001",
                    "category": "unanswerable",
                    "query": "Ancient Roman garum recipe?",
                    "should_abstain": True,
                },
            ]
        }
        res = self.evaluator.evaluate_benchmark(dataset)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["categories"]["answerable"]["score"], 1.0)
        self.assertEqual(res["categories"]["paraphrased"]["score"], 1.0)
        self.assertEqual(res["categories"]["citation"]["score"], 1.0)
        # Abstention tested over all 4 cases: 3 non-abstentions + 1 abstention = 4/4 = 1.0
        self.assertEqual(res["categories"]["abstention"]["score"], 1.0)
        # Contradiction not present in dataset -> NOT_EVALUABLE
        self.assertEqual(res["categories"]["contradiction"]["status"], "NOT_EVALUABLE")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 8: Incorrect Citations Despite Successful Retrieval
    # ──────────────────────────────────────────────────────────────────────────
    def test_08_incorrect_citations_despite_successful_retrieval(self):
        """Retriever matches query but returns missing or invalid coordinates -> citation fails."""
        bad_cite_retriever = MockRetriever(mode="bad_citations")
        evaluator = StandaloneEvaluator(bad_cite_retriever, self.grounding)
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-CITE-001",
                    "category": "citation",
                    "query": "Travel reimbursement rules?",
                    "expected_source": "northstar_travel_expense_policy.md",
                    "line_start": 1,
                    "line_end": 10,
                    "should_abstain": False,
                }
            ]
        }
        res = evaluator.evaluate_benchmark(dataset)
        cat = res["categories"]["citation"]
        self.assertEqual(cat["status"], "FAIL")
        self.assertEqual(cat["numerator"], 0)
        self.assertEqual(cat["denominator"], 1)
        self.assertEqual(cat["score"], 0.0)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 9: Incorrect Abstention on Answerable Question
    # ──────────────────────────────────────────────────────────────────────────
    def test_09_incorrect_abstention_on_answerable_question(self):
        """If system incorrectly abstains on an answerable question, abstention accuracy is penalized."""
        abstaining_retriever = MockRetriever(mode="always_abstain")
        evaluator = StandaloneEvaluator(abstaining_retriever, self.grounding)
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-ANS-001",
                    "category": "answerable",
                    "query": "What is the domestic travel per diem?",
                    "expected_source": "policy.md",
                    "should_abstain": False,  # Should NOT abstain
                },
                {
                    "case_id": "TC-UNANS-001",
                    "category": "unanswerable",
                    "query": "Moon polo rules?",
                    "should_abstain": True,  # Correctly abstains
                },
            ]
        }
        res = evaluator.evaluate_benchmark(dataset)
        abs_cat = res["categories"]["abstention"]
        # Total cases = 2. Correct abstentions = 1 (on unanswerable), incorrect on answerable.
        # Score = 1 / 2 = 0.50, which is below 0.75 threshold -> FAIL!
        self.assertEqual(abs_cat["denominator"], 2)
        self.assertEqual(abs_cat["numerator"], 1)
        self.assertEqual(abs_cat["score"], 0.50)
        self.assertEqual(abs_cat["status"], "FAIL")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 10: Incorrect Answering on Unanswerable Question
    # ──────────────────────────────────────────────────────────────────────────
    def test_10_incorrect_answering_on_unanswerable_question(self):
        """If system hallucinates and fails to abstain on an out-of-domain query, abstention accuracy fails."""
        hallucinating_retriever = MockRetriever(mode="never_abstain")
        evaluator = StandaloneEvaluator(hallucinating_retriever, self.grounding)
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-ANS-001",
                    "category": "answerable",
                    "query": "What is the domestic travel per diem?",
                    "expected_source": "policy.txt",
                    "should_abstain": False,  # Correctly answered
                },
                {
                    "case_id": "TC-UNANS-001",
                    "category": "unanswerable",
                    "query": "Moon polo rules?",
                    "should_abstain": True,  # System fails to abstain!
                },
            ]
        }
        res = evaluator.evaluate_benchmark(dataset)
        abs_cat = res["categories"]["abstention"]
        # Score = 1 / 2 = 0.50 -> FAIL!
        self.assertEqual(abs_cat["denominator"], 2)
        self.assertEqual(abs_cat["numerator"], 1)
        self.assertEqual(abs_cat["score"], 0.50)
        self.assertEqual(abs_cat["status"], "FAIL")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 11: Fabricated Contradiction Unsupported by Corpus
    # ──────────────────────────────────────────────────────────────────────────
    def test_11_fabricated_contradiction_unsupported_by_corpus(self):
        """If a contradiction case is asserted but corpus contains no real contradiction, detection score is 0.0."""
        # Grounding engine has no contradictions
        peaceful_grounding = MockGroundingEngine(has_contradiction=False)
        evaluator = StandaloneEvaluator(self.retriever, peaceful_grounding)
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-CONTRA-001",
                    "category": "contradiction",
                    "query": "What is the conflicting guidance on discounts?",
                    "is_contradiction": True,
                    "should_abstain": False,
                }
            ]
        }
        res = evaluator.evaluate_benchmark(dataset)
        cat = res["categories"]["contradiction"]
        self.assertEqual(cat["status"], "FAIL")
        self.assertEqual(cat["numerator"], 0)
        self.assertEqual(cat["denominator"], 1)
        self.assertEqual(cat["score"], 0.0)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 12: Aggregate Certification When Mandatory Metric is NOT_EVALUABLE
    # ──────────────────────────────────────────────────────────────────────────
    def test_12_aggregate_certification_when_mandatory_metric_not_evaluable(self):
        """If any mandatory category (e.g. answerable) is NOT_EVALUABLE, overall status fails closed."""
        # Only unanswerable cases present -> answerable and citation are NOT_EVALUABLE
        dataset = {
            "test_cases": [
                {
                    "case_id": "TC-UNANS-001",
                    "category": "unanswerable",
                    "query": "What is Roman garum recipe?",
                    "should_abstain": True,
                },
                {
                    "case_id": "TC-UNANS-002",
                    "category": "unanswerable",
                    "query": "Moon polo rules?",
                    "should_abstain": True,
                },
            ]
        }
        res = self.evaluator.evaluate_benchmark(dataset)
        self.assertEqual(res["categories"]["answerable"]["status"], "NOT_EVALUABLE")
        self.assertEqual(res["categories"]["citation"]["status"], "NOT_EVALUABLE")
        self.assertEqual(res["categories"]["abstention"]["status"], "PASS")
        # FAIL-CLOSED: overall status must be NOT_EVALUABLE, NOT PASS!
        self.assertEqual(res["status"], "NOT_EVALUABLE")


if __name__ == "__main__":
    unittest.main()
