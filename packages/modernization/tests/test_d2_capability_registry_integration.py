"""D2 regression tests: analyze_capability_gaps must register with TechnologyCapabilityRegistry.

These tests cover the D2 fix: analyze_capability_gaps() previously did not register
TechnologyCapability entries for discovered gaps. The fix adds calls to
self.capability_registry.register(...) so the registry is populated with honest
CapabilityState values (UNSUPPORTED/PARTIALLY_SUPPORTED/UNKNOWN).
"""
from __future__ import annotations

import pytest

from autoforge_modernization.capability_registry import (
    TechnologyCapabilityRegistry,
    CapabilityState,
    CapabilityLevel,
)
from autoforge_modernization.analysis import LegacyAnalysisEngine, TechnologyAnalysisStage1
from autoforge_modernization.knowledge import (
    TechnologyKnowledge,
    TechnologyFamily,
    KnowledgeClaim,
    ClaimKind,
    ModernizationPath,
)


class TestCapabilityGapRegistryIntegration:
    """Stage-5 gap analysis must register discovered capabilities."""

    def test_unsupported_mainframe_registered_unsupported(self):
        reg = TechnologyCapabilityRegistry()
        engine = LegacyAnalysisEngine(capability_registry=reg)
        ta = TechnologyAnalysisStage1(
            detected_name="RPG",
            is_mainframe=True,
            is_supported=False,
            modernization_paths=[],
            confidence=0.5,
            evidence_refs=["file:rpg.rpgle"],
        )
        ta.knowledge_entry = TechnologyKnowledge(
            technology_name="rpg",
            family=TechnologyFamily.MAINFRAME_LANGUAGE,
            description="RPG",
            claims=[
                KnowledgeClaim(
                    kind=ClaimKind.KNOWLEDGE_BASE,
                    statement="not natively supported",
                    confidence=0.8,
                    source="knowledge",
                ),
            ],
        )
        gaps = engine.analyze_capability_gaps([ta])
        assert len(gaps) >= 1
        assert len(reg.capabilities) >= 1
        cap = reg.get("RPG")
        assert cap is not None
        assert cap.state == CapabilityState.UNSUPPORTED
        assert cap.level == CapabilityLevel.DETECT

    def test_supported_mainframe_with_unsupported_claim_is_partially_supported(self):
        """A mainframe tech marked supported but with an 'unsupported' claim is PARTIALLY_SUPPORTED."""
        reg = TechnologyCapabilityRegistry()
        engine = LegacyAnalysisEngine(capability_registry=reg)
        ta = TechnologyAnalysisStage1(
            detected_name="COBOL",
            is_mainframe=True,
            is_supported=True,
            modernization_paths=[],
            confidence=0.9,
            evidence_refs=["file:cobol.cbl"],
        )
        ta.knowledge_entry = TechnologyKnowledge(
            technology_name="cobol",
            family=TechnologyFamily.MAINFRAME_LANGUAGE,
            description="COBOL",
            claims=[
                KnowledgeClaim(
                    kind=ClaimKind.KNOWLEDGE_BASE,
                    statement="unsupported by knowledge base",
                    confidence=0.7,
                    source="knowledge",
                ),
            ],
        )
        gaps = engine.analyze_capability_gaps([ta])
        assert len(gaps) >= 1
        cap = reg.get("COBOL")
        assert cap is not None
        assert cap.state == CapabilityState.PARTIALLY_SUPPORTED

    def test_unsupported_mainframe_with_paths_target_unknown_gives_unknown(self):
        """A tech with a path whose target is not in knowledge layer gets UNKNOWN."""
        reg = TechnologyCapabilityRegistry()
        engine = LegacyAnalysisEngine(capability_registry=reg)
        ta = TechnologyAnalysisStage1(
            detected_name="COBOL",
            is_mainframe=True,
            is_supported=False,
            modernization_paths=[
                ModernizationPath(
                    target_technology="java",
                    strategy="refactor",
                    target_family=TechnologyFamily.ENTERPRISE_LANGUAGE,
                    compatibility="partial",
                    description="test",
                    required_tools=[],
                    required_adapters=[],
                ),
            ],
            confidence=0.9,
            evidence_refs=[],
        )
        ta.knowledge_entry = TechnologyKnowledge(
            technology_name="cobol",
            family=TechnologyFamily.MAINFRAME_LANGUAGE,
            description="COBOL",
            claims=[],
        )
        gaps = engine.analyze_capability_gaps([ta])
        cap = reg.get("COBOL")
        assert cap is not None
        assert cap.state == CapabilityState.UNKNOWN


    def test_non_mainframe_no_gaps(self):
        reg = TechnologyCapabilityRegistry()
        engine = LegacyAnalysisEngine(capability_registry=reg)
        ta = TechnologyAnalysisStage1(
            detected_name="PYTHON",
            is_mainframe=False,
            is_supported=True,
            modernization_paths=[],
            confidence=0.9,
            evidence_refs=[],
        )
        gaps = engine.analyze_capability_gaps([ta])
        assert len(gaps) == 0
        assert len(reg.capabilities) == 0

    def test_none_registry_does_not_crash(self):
        engine = LegacyAnalysisEngine(capability_registry=None)
        ta = TechnologyAnalysisStage1(
            detected_name="RPG",
            is_mainframe=True,
            is_supported=False,
            modernization_paths=[],
            confidence=0.5,
            evidence_refs=[],
        )
        gaps = engine.analyze_capability_gaps([ta])
        assert len(gaps) >= 1
        assert gaps[0].current_state == "not_in_capability_registry"

    def test_multiple_mainframe_techs_all_registered(self):
        reg = TechnologyCapabilityRegistry()
        engine = LegacyAnalysisEngine(capability_registry=reg)

        def make_ta(name):
            t = TechnologyAnalysisStage1(
                detected_name=name,
                is_mainframe=True,
                is_supported=False,
                modernization_paths=[],
                confidence=0.5,
                evidence_refs=[],
            )
            t.knowledge_entry = TechnologyKnowledge(
                technology_name=name.lower(),
                family=TechnologyFamily.MAINFRAME_LANGUAGE,
                description=name,
                claims=[],
            )
            return t

        gaps = engine.analyze_capability_gaps(
            [make_ta("RPG"), make_ta("COBOL"), make_ta("JCL")]
        )
        assert len(gaps) >= 3
        assert len(reg.capabilities) >= 3
        assert reg.get("RPG") is not None
        assert reg.get("COBOL") is not None
        assert reg.get("JCL") is not None

    def test_unknown_target_source_gets_unknown_state(self):
        reg = TechnologyCapabilityRegistry()
        engine = LegacyAnalysisEngine(capability_registry=reg)
        ta = TechnologyAnalysisStage1(
            detected_name="COBOL",
            is_mainframe=True,
            is_supported=True,
            modernization_paths=[
                ModernizationPath(
                    target_technology="unknown_lang",
                    strategy="refactor",
                    target_family=TechnologyFamily.UNKNOWN,
                    compatibility="partial",
                    description="?",
                    required_tools=[],
                    required_adapters=[],
                ),
            ],
            confidence=0.7,
            evidence_refs=[],
        )
        ta.knowledge_entry = TechnologyKnowledge(
            technology_name="cobol",
            family=TechnologyFamily.MAINFRAME_LANGUAGE,
            description="COBOL",
            claims=[],
        )
        engine.analyze_capability_gaps([ta])
        cap = reg.get("COBOL")
        assert cap is not None
        assert cap.state == CapabilityState.UNKNOWN

    def test_gap_state_matches_registry_state(self):
        reg = TechnologyCapabilityRegistry()
        engine = LegacyAnalysisEngine(capability_registry=reg)
        ta = TechnologyAnalysisStage1(
            detected_name="RPG",
            is_mainframe=True,
            is_supported=False,
            modernization_paths=[],
            confidence=0.9,
            evidence_refs=["file:rpg.rpgle"],
        )
        ta.knowledge_entry = TechnologyKnowledge(
            technology_name="rpg",
            family=TechnologyFamily.MAINFRAME_LANGUAGE,
            description="RPG",
            claims=[
                KnowledgeClaim(
                    kind=ClaimKind.KNOWLEDGE_BASE,
                    statement="unsupported",
                    confidence=0.8,
                    source="knowledge",
                ),
            ],
        )
        gaps = engine.analyze_capability_gaps([ta])
        gap = next(g for g in gaps if g.technology == "RPG")
        cap = reg.get("RPG")
        assert gap.current_state == cap.state.value

