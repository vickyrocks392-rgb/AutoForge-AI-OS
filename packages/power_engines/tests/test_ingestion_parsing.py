"""Tests for Multi-Format Ingestion Pipeline & Parsing (PDF, MD, Code, Structured)."""

import pytest
from pathlib import Path
from autoforge_power_engines.rag.ingestion import RAGIngestionPipeline
from autoforge_power_engines.specification import CustomerProjectSpecification, KnowledgeSourceSpec, SourceType


def test_markdown_and_python_ingestion(tmp_path):
    # Setup fixtures
    docs_dir = tmp_path / "knowledge"
    docs_dir.mkdir()

    md_file = docs_dir / "guide.md"
    md_file.write_text(
        "# Platform Guide\nPlatform overview section.\n\n## Setup\nRun the command to initialize.\n",
        encoding="utf-8"
    )

    py_file = docs_dir / "service.py"
    py_file.write_text(
        "class AuthService:\n    def authenticate(self, user: str) -> bool:\n        return user == 'admin'\n",
        encoding="utf-8"
    )

    spec = CustomerProjectSpecification(
        project_name="TestIngest",
        project_description="Test ingestion",
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="guide-doc",
                source_type=SourceType.DOCUMENT,
                path=str(md_file),
            ),
            KnowledgeSourceSpec(
                source_id="code-doc",
                source_type=SourceType.SOURCE_CODE,
                path=str(py_file),
            ),
        ],
    )

    pipeline = RAGIngestionPipeline()
    docs, chunks = pipeline.process_spec_sources(spec, "test_proj")

    assert len(docs) == 2
    assert len(chunks) >= 2

    # Verify metadata preservation
    chunk_types = {c.document_type for c in chunks}
    assert "markdown" in chunk_types
    assert "python_source" in chunk_types

    for c in chunks:
        assert c.chunk_id
        assert c.content_hash
        assert c.metadata.get("project_id") == "test_proj"


def test_structured_json_and_yaml_ingestion(tmp_path):
    conf_dir = tmp_path / "configs"
    conf_dir.mkdir()

    json_file = conf_dir / "app_config.json"
    json_file.write_text('{"environment": "staging", "cluster_nodes": 4, "timeout": 30}', encoding="utf-8")

    yaml_file = conf_dir / "deployment.yaml"
    yaml_file.write_text("apiVersion: v1\nkind: Pod\nmetadata:\n  name: worker\n", encoding="utf-8")

    spec = CustomerProjectSpecification(
        project_name="StructuredTest",
        project_description="Test structured formats",
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="json-src",
                source_type=SourceType.STRUCTURED,
                path=str(json_file),
            ),
            KnowledgeSourceSpec(
                source_id="yaml-src",
                source_type=SourceType.STRUCTURED,
                path=str(yaml_file),
            ),
        ],
    )

    pipeline = RAGIngestionPipeline()
    docs, chunks = pipeline.process_spec_sources(spec, "test_proj")

    assert len(docs) == 2
    types = {d.document_type for d in docs}
    assert "json_document" in types
    assert "yaml_document" in types


def test_pdf_ingestion_with_real_pdf(tmp_path):
    # Generate a real PDF file using reportlab
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "sample_manual.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.drawString(100, 750, "AutoForge Commercial RAG Platform Manual")
    c.drawString(100, 720, "This is page 1 describing cloud architecture.")
    c.showPage()
    c.drawString(100, 750, "Chapter 2: Configuration and API Credentials")
    c.drawString(100, 720, "Ensure all endpoints are verified before deployment.")
    c.save()

    spec = CustomerProjectSpecification(
        project_name="PDFTest",
        project_description="Test PDF parser",
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="manual-pdf",
                source_type=SourceType.DOCUMENT,
                path=str(pdf_path),
            ),
        ],
    )

    pipeline = RAGIngestionPipeline()
    docs, chunks = pipeline.process_spec_sources(spec, "test_proj")

    assert len(docs) == 1
    assert docs[0].document_type == "pdf_document"
    assert len(chunks) >= 1

    extracted_text = " ".join(c.content for c in chunks)
    assert "AutoForge Commercial RAG" in extracted_text
    assert "Chapter 2" in extracted_text
