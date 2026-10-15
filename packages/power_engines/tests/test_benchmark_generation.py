"""Tests for Generic Benchmark Generation and Generated Evaluator Execution (Gate 2 & 5)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from autoforge_power_engines.packaging import CustomerProjectPackager
from autoforge_power_engines.rag.generator import StandaloneCustomerRAGGenerator
from autoforge_power_engines.rag.ingestion import KnowledgeChunkRecord, ProcessedDocument
from autoforge_power_engines.specification import CustomerProjectSpecification


class TestBenchmarkGeneration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_benchmark_gen_"))
        self.packager = CustomerProjectPackager(self.temp_dir)
        self.generator = StandaloneCustomerRAGGenerator(self.packager)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_benchmark_generation_empty_corpus(self):
        """When no chunks are provided, generator marks non-evaluable categories and includes unanswerables."""
        spec = CustomerProjectSpecification(
            project_name="EmptyCorpusTest",
            project_description="Test with empty initial corpus",
        )
        self.generator.generate_customer_project(spec, documents=[], chunks=[])

        benchmark_file = self.temp_dir / "evaluation" / "benchmark_dataset.json"
        self.assertTrue(benchmark_file.exists())
        data = json.loads(benchmark_file.read_text(encoding="utf-8"))

        self.assertFalse(data["corpus_available_at_generation"])
        self.assertIn("unanswerable", data["categories_evaluable"])
        self.assertIn("answerable", data["categories_not_evaluable"])
        self.assertIn("contradiction", data["categories_not_evaluable"])
        self.assertIn("citation", data["categories_not_evaluable"])

        # All test cases in dataset must be unanswerable
        cases = data["test_cases"]
        self.assertGreaterEqual(len(cases), 2)
        for c in cases:
            self.assertEqual(c["category"], "unanswerable")
            self.assertTrue(c["should_abstain"])

    def test_benchmark_generation_with_real_chunks(self):
        """When chunks are provided, generator extracts answerable, paraphrased, and citation cases."""
        spec = CustomerProjectSpecification(
            project_name="RealCorpusTest",
            project_description="Test with real knowledge chunks",
        )
        chunks = [
            KnowledgeChunkRecord(
                chunk_id="chunk-001",
                source_id="doc-ops",
                file_path="operations_manual.txt",
                document_type="text",
                language="en",
                chunk_index=0,
                content="Standard maintenance inspections must be conducted every morning before dispatch. Tire pressure and braking systems require mandatory supervisor signoff.",
                line_start=1,
                line_end=4,
                content_hash="abc123hash",
            ),
            KnowledgeChunkRecord(
                chunk_id="chunk-002",
                source_id="doc-travel",
                file_path="travel_guidelines.md",
                document_type="markdown",
                language="en",
                chunk_index=0,
                content="Domestic travel meal per diem is capped at $75 per day. Lodging expenses in tier-1 metropolitan cities must not exceed $250 per night.",
                line_start=10,
                line_end=16,
                content_hash="def456hash",
            ),
        ]
        docs = [
            ProcessedDocument(
                source_id="doc-ops",
                file_path="operations_manual.txt",
                document_type="text",
                language="en",
                size_bytes=len(chunks[0].content),
                content_hash="hash1",
                chunks_count=1,
            ),
            ProcessedDocument(
                source_id="doc-travel",
                file_path="travel_guidelines.md",
                document_type="markdown",
                language="en",
                size_bytes=len(chunks[1].content),
                content_hash="hash2",
                chunks_count=1,
            ),
        ]

        self.generator.generate_customer_project(spec, documents=docs, chunks=chunks)

        benchmark_file = self.temp_dir / "evaluation" / "benchmark_dataset.json"
        self.assertTrue(benchmark_file.exists())
        data = json.loads(benchmark_file.read_text(encoding="utf-8"))

        self.assertTrue(data["corpus_available_at_generation"])
        self.assertIn("answerable", data["categories_evaluable"])
        self.assertIn("paraphrased", data["categories_evaluable"])
        self.assertIn("citation", data["categories_evaluable"])
        self.assertIn("unanswerable", data["categories_evaluable"])
        # No conflicting statements -> contradiction must be NOT_EVALUABLE
        self.assertIn("contradiction", data["categories_not_evaluable"])

        cases = data["test_cases"]
        categories_found = {c["category"] for c in cases}
        self.assertIn("answerable", categories_found)
        self.assertIn("paraphrased", categories_found)
        self.assertIn("citation", categories_found)
        self.assertIn("unanswerable", categories_found)
        # Contradiction NOT fabricated
        self.assertNotIn("contradiction", categories_found)

        # Verify citation cases have valid line coordinates matching chunk
        cite_cases = [c for c in cases if c["category"] == "citation"]
        self.assertGreater(len(cite_cases), 0)
        for cc in cite_cases:
            self.assertIsNotNone(cc.get("expected_source"))
            self.assertGreater(cc.get("line_start", 0), 0)
            self.assertGreaterEqual(cc.get("line_end", 0), cc.get("line_start", 0))

    def test_benchmark_generation_with_conflicting_chunks(self):
        """When chunks actually contain contradictions, contradiction test cases are generated."""
        spec = CustomerProjectSpecification(
            project_name="ConflictTest",
            project_description="Test with conflicting chunks",
        )
        chunks = [
            KnowledgeChunkRecord(
                chunk_id="c1",
                source_id="doc1",
                file_path="policy_north.txt",
                document_type="text",
                language="en",
                chunk_index=0,
                content="Standard client discount limit is 12% without VP signoff under current policy.",
                line_start=1,
                line_end=3,
                content_hash="h1",
            ),
            KnowledgeChunkRecord(
                chunk_id="c2",
                source_id="doc2",
                file_path="policy_south.txt",
                document_type="text",
                language="en",
                chunk_index=0,
                content="Standard client discount limit is 28% without VP signoff under current policy.",
                line_start=1,
                line_end=3,
                content_hash="h2",
            ),
        ]
        self.generator.generate_customer_project(spec, documents=[], chunks=chunks)

        benchmark_file = self.temp_dir / "evaluation" / "benchmark_dataset.json"
        data = json.loads(benchmark_file.read_text(encoding="utf-8"))
        self.assertIn("contradiction", data["categories_evaluable"])

        contra_cases = [c for c in data["test_cases"] if c["category"] == "contradiction"]
        self.assertGreater(len(contra_cases), 0)
        self.assertTrue(contra_cases[0]["is_contradiction"])

    def test_generated_deliverable_evaluator_execution(self):
        """Generated deliverable's tests/test_evaluation_harness.py runs and passes cleanly."""
        spec = CustomerProjectSpecification(
            project_name="DeliverableEvalHarnessTest",
            project_description="Test that generated evaluation harness executes cleanly",
        )
        self.generator.generate_customer_project(spec, documents=[], chunks=[])

        import subprocess
        import sys
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(self.temp_dir / "tests"), "-p", "test_evaluation_harness.py"],
            cwd=str(self.temp_dir),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Generated test failed: {res.stderr}\n{res.stdout}")


if __name__ == "__main__":
    unittest.main()
