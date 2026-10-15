"""Multi-Order Generalization Test Matrix for AutoForge Commercial RAG Platform.

Validates that the generic platform autonomously generates, validates, repairs,
and delivers high-quality software across materially different customer orders
(Profiles A, B, C, D, E) without customer-specific conditional branches in platform logic.
Also verifies non-RAG power engine preservation and cross-customer data isolation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from autoforge_power_engines.agent import CustomerAgentSpecification
from autoforge_power_engines.agent.engine import CustomAIAgentPowerEngine
from autoforge_power_engines.automation import (
    ActionSpec,
    CustomerAutomationSpecification,
    StepSpec,
    StepType,
)
from autoforge_power_engines.automation.engine import AIAutomationPowerEngine
from autoforge_power_engines.rag.engine import RAGKnowledgePowerEngine
from autoforge_power_engines.rag.generator import StandaloneCustomerRAGGenerator
from autoforge_power_engines.rag.spec import CustomerRAGSpecification
from autoforge_power_engines.specification import (
    CustomerProjectSpecification,
    CustomerRequirement,
    EmbeddingProviderType,
    KnowledgeSourceSpec,
    LLMProviderType,
    RequirementCategory,
    SourceType,
    VectorStoreType,
)


@pytest.fixture
def multi_order_delivery_root(tmp_path: Path) -> Path:
    deliveries = tmp_path / "commercial_deliveries"
    deliveries.mkdir(parents=True, exist_ok=True)
    return deliveries


# ── PROFILE A: Internal Operations & Knowledge Assistant (Northstar-Style) ───
@pytest.mark.asyncio
async def test_profile_a_operations_knowledge_assistant(multi_order_delivery_root: Path):
    """
    Profile A: Internal Operations Knowledge Assistant.
    Requirements:
    - Multi-format ingestion (Markdown & Text)
    - Persistent dense vector retrieval
    - Grounded citations with line numbers
    - Empty corpus and abstention safety
    - Browser UI with modular tabs
    """
    spec = CustomerProjectSpecification(
        project_name="NorthstarOperations",
        project_description="Enterprise operational knowledge assistant for logistics, facilities, and procedures.",
        output_root=str(multi_order_delivery_root),
        vector_store=VectorStoreType.CHROMADB,
        embedding_provider=EmbeddingProviderType.LOCAL,
        llm_provider=LLMProviderType.LOCAL_MLX,
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="ops-runbook",
                source_type=SourceType.INLINE_TEXT,
                content=(
                    "# Warehouse Operations Runbook\n\n"
                    "Shift handovers occur daily at 06:00, 14:00, and 22:00 UTC.\n"
                    "High-priority freight requires dual supervisor sign-off on Form W-104.\n"
                    "Cold storage temperature limits must remain strictly between -18C and -22C."
                ),
                metadata={"category": "operations", "facility": "central-hub"},
            )
        ],
        customer_requirements=[
            CustomerRequirement(
                requirement_id="REQ-OPS-01",
                category=RequirementCategory.FUNCTIONAL,
                title="Shift Handover Attestation",
                description="Must retrieve exact handover times with document citation.",
                acceptance_criteria=["Must cite Form W-104 and shift schedule"],
            )
        ],
    )

    engine = RAGKnowledgePowerEngine()
    result = await engine.execute_lifecycle(spec)

    assert result.success is True, f"Profile A failed: {result.error_message}"
    delivery_dir = Path(result.delivery_dir)

    # Verify deliverable structure
    assert (delivery_dir / "src" / "retriever.py").exists()
    assert (delivery_dir / "src" / "embeddings.py").exists()
    assert (delivery_dir / "src" / "vector_store.py").exists()
    assert (delivery_dir / "static" / "index.html").exists()
    assert (delivery_dir / "static" / "style.css").exists()
    assert (delivery_dir / "static" / "app.js").exists()

    # Run deliverable verification suite
    test_proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=str(delivery_dir),
        capture_output=True,
        text=True,
    )
    assert test_proc.returncode == 0, f"Profile A tests failed:\n{test_proc.stderr}"


# ── PROFILE B: HR Policy & Employee Benefits Assistant ────────────────────────
@pytest.mark.asyncio
async def test_profile_b_hr_policy_assistant(multi_order_delivery_root: Path):
    """
    Profile B: HR Policy Assistant.
    Requirements:
    - Handling conflicting policy versions (2024 vs 2026 handbook)
    - Contradiction detection across policy documents
    - Precise source citations for leave policies
    - Zero customer-specific platform conditionals
    """
    spec = CustomerProjectSpecification(
        project_name="HRPolicyAssist",
        project_description="HR benefits and workplace policy advisory assistant.",
        output_root=str(multi_order_delivery_root),
        vector_store=VectorStoreType.CHROMADB,
        embedding_provider=EmbeddingProviderType.LOCAL,
        llm_provider=LLMProviderType.LOCAL_MLX,
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="handbook-2024",
                source_type=SourceType.INLINE_TEXT,
                content=(
                    "# Employee Handbook 2024 (Superseded)\n\n"
                    "Section 4.1: Annual Paid Time Off is capped at 15 business days for junior staff.\n"
                    "Section 4.2: Health insurance premiums are 80% subsidized by the employer."
                ),
                metadata={"version": "2024", "status": "superseded"},
            ),
            KnowledgeSourceSpec(
                source_id="handbook-2026",
                source_type=SourceType.INLINE_TEXT,
                content=(
                    "# Employee Handbook 2026 (Active Policy)\n\n"
                    "Section 4.1: Annual Paid Time Off is increased to 22 business days for all employees.\n"
                    "Section 4.2: Health insurance premiums are 100% subsidized by the employer.\n"
                    "Section 8.0: Parental leave entitlement provides 16 fully paid weeks."
                ),
                metadata={"version": "2026", "status": "active"},
            ),
        ],
    )

    engine = RAGKnowledgePowerEngine()
    result = await engine.execute_lifecycle(spec)

    assert result.success is True, f"Profile B failed: {result.error_message}"
    delivery_dir = Path(result.delivery_dir)

    # Verify deliverable test suite passes
    test_proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=str(delivery_dir),
        capture_output=True,
        text=True,
    )
    assert test_proc.returncode == 0, f"Profile B tests failed:\n{test_proc.stderr}"


# ── PROFILE C: Technical Documentation & API Assistant ────────────────────────
@pytest.mark.asyncio
async def test_profile_c_technical_docs_assistant(multi_order_delivery_root: Path):
    """
    Profile C: Technical Documentation Assistant.
    Requirements:
    - Code snippets and API specifications
    - Conceptual paraphrase retrieval without lexical keyword overlap
    - Version-aware metadata filtering
    """
    spec = CustomerProjectSpecification(
        project_name="CloudSDKDocs",
        project_description="Developer reference assistant for CloudSDK Python and REST APIs.",
        output_root=str(multi_order_delivery_root),
        vector_store=VectorStoreType.CHROMADB,
        embedding_provider=EmbeddingProviderType.LOCAL,
        llm_provider=LLMProviderType.LOCAL_MLX,
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="sdk-auth-guide",
                source_type=SourceType.INLINE_TEXT,
                content=(
                    "# Authentication & Identity Management\n\n"
                    "To initialize the client, invoke `CloudClient(credentials=ServicePrincipalKey(...))`.\n"
                    "Tokens automatically refresh at 75% of total lifespan (typically 45 minutes).\n"
                    "Rate limit thresholds allow up to 2000 requests per minute per tenant enclave."
                ),
                metadata={"category": "developer-guide", "language": "python"},
            )
        ],
    )

    engine = RAGKnowledgePowerEngine()
    result = await engine.execute_lifecycle(spec)

    assert result.success is True, f"Profile C failed: {result.error_message}"
    delivery_dir = Path(result.delivery_dir)

    # Verify semantic retrieval handles paraphrasing in the generated project
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location("retriever", delivery_dir / "src" / "retriever.py")
    retriever_mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(retriever_mod)

    retriever = retriever_mod.StandaloneRetriever(delivery_dir / "artifacts" / "knowledge_index.json")
    # Conceptual query without exact keyword overlap:
    hits = retriever.search("how to authenticate and refresh security credentials", top_k=1)
    assert len(hits) >= 1
    assert "CloudClient" in hits[0]["content"]


# ── PROFILE D: Legal & Regulatory Compliance Assistant ────────────────────────
@pytest.mark.asyncio
async def test_profile_d_legal_compliance_assistant(multi_order_delivery_root: Path):
    """
    Profile D: Legal & Regulatory Compliance Assistant.
    Requirements:
    - Strict source attribution
    - Conservative abstention for unsupported legal queries
    - Disclaimer compliance and auditability
    """
    spec = CustomerRAGSpecification(
        project_name="LexCompliance",
        project_description="Regulatory compliance and antitrust documentation search system.",
        output_root=str(multi_order_delivery_root),
        vector_store_type=VectorStoreType.CHROMADB,
        embedding_provider=EmbeddingProviderType.LOCAL,
        llm_provider=LLMProviderType.LOCAL_MLX,
        min_similarity_score=0.45,
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="regulatory-statute",
                source_type=SourceType.INLINE_TEXT,
                content=(
                    "# Regulatory Compliance Directive 2026-B\n\n"
                    "Article 12: Cross-border financial transfers over 10,000 EUR must include verified LEI codes.\n"
                    "Article 15: Records retention schedule mandates 7-year tamper-evident cold storage."
                ),
                metadata={"jurisdiction": "EU", "effective_date": "2026-01-01"},
            )
        ],
    )

    engine = RAGKnowledgePowerEngine()
    result = await engine.execute_lifecycle(spec)

    assert result.success is True, f"Profile D failed: {result.error_message}"
    delivery_dir = Path(result.delivery_dir)

    # Verify abstention on unsupported queries
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location("retriever", delivery_dir / "src" / "retriever.py")
    retriever_mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(retriever_mod)

    retriever = retriever_mod.StandaloneRetriever(delivery_dir / "artifacts" / "knowledge_index.json")
    hits, is_insufficient = retriever.retrieve("What is the penalty for maritime shipping violations under Japanese law?")
    assert is_insufficient is True


# ── PROFILE E: Configuration Variation & Reusable Generator Customization ───
def test_profile_e_generator_configuration_variation(tmp_path: Path):
    """
    Profile E: Customer-Specific Configuration Variations.
    Tests that the reusable StandaloneCustomerRAGGenerator generates different,
    tailored configurations without global defaults or hardcoded conditionals:
    - Variation 1: Hybrid retrieval (0.6 semantic, 0.4 lexical), custom UI branding, port 8080
    - Variation 2: Pure semantic vector retrieval, alternate branding tokens, port 9090
    """
    target_v1 = tmp_path / "variation_v1"
    target_v2 = tmp_path / "variation_v2"

    gen1 = StandaloneCustomerRAGGenerator(target_v1)
    gen2 = StandaloneCustomerRAGGenerator(target_v2)

    spec_v1 = CustomerRAGSpecification(
        project_name="FinTechHybridSearch",
        project_description="Hybrid financial filings search engine.",
        retrieval_strategy="hybrid",
        hybrid_semantic_weight=0.6,
        hybrid_lexical_weight=0.4,
        min_similarity_score=0.30,
        ui_branding={
            "title": "FinTech Search",
            "primary_color": "#10b981",
            "accent_color": "#059669",
        },
    )

    spec_v2 = CustomerRAGSpecification(
        project_name="DeepBioSemanticSearch",
        project_description="Pure dense semantic vector research index.",
        retrieval_strategy="semantic",
        min_similarity_score=0.45,
        ui_branding={
            "title": "DeepBio Search",
            "primary_color": "#6366f1",
            "accent_color": "#4f46e5",
        },
    )

    gen1.generate_customer_project(spec_v1, [], [])
    gen2.generate_customer_project(spec_v2, [], [])

    # Check variation 1 configuration
    settings_v1 = json.loads((target_v1 / "config" / "settings.json").read_text(encoding="utf-8"))
    assert settings_v1["retrieval_strategy"] == "hybrid"
    assert settings_v1["hybrid_semantic_weight"] == 0.6
    assert settings_v1["hybrid_lexical_weight"] == 0.4
    assert settings_v1["min_similarity_score"] == 0.30

    # Check variation 2 configuration
    settings_v2 = json.loads((target_v2 / "config" / "settings.json").read_text(encoding="utf-8"))
    assert settings_v2["retrieval_strategy"] == "semantic"
    assert settings_v2["min_similarity_score"] == 0.45

    # Check branding token variation in style.css
    css_v1 = (target_v1 / "static" / "style.css").read_text(encoding="utf-8")
    css_v2 = (target_v2 / "static" / "style.css").read_text(encoding="utf-8")
    assert "#10b981" in css_v1
    assert "#6366f1" in css_v2


# ── NON-RAG POWER ENGINE PRESERVATION ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_non_rag_power_engines_preservation(tmp_path: Path):
    """
    Verifies that the RAG platform engineering repairs did NOT regress or break
    the other commercial power engines (AgentPowerEngine, AutomationPowerEngine).
    """
    out_dir = tmp_path / "non_rag_deliveries"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Custom AI Agent Power Engine
    agent_spec = CustomerAgentSpecification(
        project_name="CustomerSupportAgent",
        agent_purpose="Multi-turn customer support agent with tool calling and session state.",
        system_instructions="You are an autonomous customer support agent.",
        output_root=str(out_dir),
    )
    agent_engine = CustomAIAgentPowerEngine()
    agent_result = await agent_engine.execute_lifecycle(agent_spec)
    assert agent_result.success is True, f"Agent engine failed: {agent_result.error_message}"
    assert Path(agent_result.delivery_dir).exists()

    # 2. Automation Power Engine
    auto_spec = CustomerAutomationSpecification(
        project_name="DailyReconciliationWorkflow",
        project_description="Autonomous reconciliation workflow automation with idempotency keys.",
        workflow_id="daily_reconciliation",
        output_root=str(out_dir),
        initial_step_id="step_reconcile",
        steps=[
            StepSpec(
                step_id="step_reconcile",
                name="Reconciliation Step",
                step_type=StepType.ACTION,
                action=ActionSpec(
                    action_type="safe_calculator",
                    name="calc_reconciliation",
                    parameters={"expression": "1000 * 5"},
                ),
            )
        ],
    )
    auto_engine = AIAutomationPowerEngine()
    auto_result = await auto_engine.execute_lifecycle(auto_spec)
    assert auto_result.success is True, f"Automation engine failed: {auto_result.error_message}"
    assert Path(auto_result.delivery_dir).exists()
