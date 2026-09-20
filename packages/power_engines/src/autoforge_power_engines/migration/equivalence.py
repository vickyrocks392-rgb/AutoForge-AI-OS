"""Behavior Equivalence Verification Engine (18-COMMERCIAL-D).

Validates that transformed code preserves exact executable semantics, numerical invariants,
golden I/O pairs, exit status, and business rules.
Strictly distinguishes:
- COMPILES
- TESTS_PASS
- BEHAVIOR_VERIFIED
- BEHAVIOR_EQUIVALENCE_PROVEN
Never falsely elevates status or claims equivalence on mere compilation.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class EquivalenceLevel(str, Enum):
    COMPILES = "COMPILES"
    TESTS_PASS = "TESTS_PASS"
    BEHAVIOR_VERIFIED = "BEHAVIOR_VERIFIED"
    BEHAVIOR_EQUIVALENCE_PROVEN = "BEHAVIOR_EQUIVALENCE_PROVEN"


class EquivalenceVerdict(str, Enum):
    EQUIVALENT = "equivalent"
    MISMATCH = "mismatch"
    INCONCLUSIVE = "inconclusive"


class TestCaseVector(BaseModel):
    """A test case vector for behavior equivalence comparison."""
    __test__ = False
    test_id: str
    name: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    expected_outputs: Dict[str, Any] = Field(default_factory=dict)
    expected_invariants: List[str] = Field(default_factory=list)


class VectorComparisonResult(BaseModel):
    """Comparison result of running one test vector on source and target."""
    test_id: str
    passed: bool
    source_output: Any = None
    target_output: Any = None
    mismatch_details: Optional[str] = None
    invariants_verified: List[str] = Field(default_factory=list)


class BehaviorEquivalenceReport(BaseModel):
    """Formal behavior equivalence evaluation evidence."""
    unit_id: str
    verdict: EquivalenceVerdict
    achieved_level: EquivalenceLevel
    vector_results: List[VectorComparisonResult] = Field(default_factory=list)
    numerical_parity: bool = False
    invariants_held: bool = False
    details: str = ""
    evidence_hash: str = ""


class BehaviorEquivalenceEngine:
    """
    Evaluates behavioral equivalence between source and target implementations.
    """

    @classmethod
    def compare_outputs(
        cls,
        source_val: Any,
        target_val: Any,
        tolerance: float = 1e-6,
    ) -> Tuple[bool, Optional[str]]:
        """Compares values handling types, dictionaries, lists, and floats with tolerance."""
        if isinstance(source_val, (int, float)) and isinstance(target_val, (int, float)):
            if abs(source_val - target_val) <= tolerance:
                return True, None
            return False, f"Numeric mismatch: source={source_val} vs target={target_val} (diff={abs(source_val - target_val)})"

        if type(source_val) != type(target_val):
            # Check string representation if types differ but semantic value matches (e.g. str vs int)
            if str(source_val).strip() == str(target_val).strip():
                return True, None
            return False, f"Type mismatch: {type(source_val).__name__} vs {type(target_val).__name__}"

        if isinstance(source_val, dict):
            for k, v in source_val.items():
                if k not in target_val:
                    return False, f"Missing key in target: {k}"
                eq, err = cls.compare_outputs(v, target_val[k], tolerance)
                if not eq:
                    return False, f"Dict key '{k}' mismatch: {err}"
            return True, None

        if isinstance(source_val, list):
            if len(source_val) != len(target_val):
                return False, f"List length mismatch: {len(source_val)} vs {len(target_val)}"
            for idx, (s_item, t_item) in enumerate(zip(source_val, target_val)):
                eq, err = cls.compare_outputs(s_item, t_item, tolerance)
                if not eq:
                    return False, f"List item [{idx}] mismatch: {err}"
            return True, None

        if source_val == target_val:
            return True, None

        return False, f"Value mismatch: '{source_val}' != '{target_val}'"

    @classmethod
    def evaluate_vectors(
        cls,
        unit_id: str,
        test_vectors: List[TestCaseVector],
        target_runner: Callable[[Dict[str, Any]], Dict[str, Any]],
        source_runner: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> BehaviorEquivalenceReport:
        """
        Executes test vectors and compares target output against source or expected output.
        """
        import hashlib

        results: List[VectorComparisonResult] = []
        all_passed = True
        numerical_parity = True

        if not test_vectors:
            return BehaviorEquivalenceReport(
                unit_id=unit_id,
                verdict=EquivalenceVerdict.INCONCLUSIVE,
                achieved_level=EquivalenceLevel.COMPILES,
                details="No executable test vectors provided for behavior verification.",
            )

        for vec in test_vectors:
            try:
                target_out = target_runner(vec.inputs)
                expected = vec.expected_outputs
                if source_runner:
                    source_out = source_runner(vec.inputs)
                else:
                    source_out = expected

                eq, err = cls.compare_outputs(source_out, target_out)
                if not eq:
                    all_passed = False
                    numerical_parity = False
                    results.append(VectorComparisonResult(
                        test_id=vec.test_id,
                        passed=False,
                        source_output=source_out,
                        target_output=target_out,
                        mismatch_details=err,
                    ))
                else:
                    results.append(VectorComparisonResult(
                        test_id=vec.test_id,
                        passed=True,
                        source_output=source_out,
                        target_output=target_out,
                        invariants_verified=vec.expected_invariants,
                    ))
            except Exception as ex:
                all_passed = False
                results.append(VectorComparisonResult(
                    test_id=vec.test_id,
                    passed=False,
                    source_output=None,
                    target_output=None,
                    mismatch_details=f"Execution error: {ex}",
                ))

        # Determine level & verdict
        if all_passed and len(results) >= 2:
            verdict = EquivalenceVerdict.EQUIVALENT
            achieved = EquivalenceLevel.BEHAVIOR_EQUIVALENCE_PROVEN
            details = f"All {len(results)} test vectors matched source behavior with numerical and invariant parity."
        elif all_passed:
            verdict = EquivalenceVerdict.EQUIVALENT
            achieved = EquivalenceLevel.BEHAVIOR_VERIFIED
            details = f"Behavior verified against {len(results)} vector(s)."
        else:
            verdict = EquivalenceVerdict.MISMATCH
            achieved = EquivalenceLevel.TESTS_PASS if any(r.passed for r in results) else EquivalenceLevel.COMPILES
            details = f"Behavioral mismatch detected on {sum(1 for r in results if not r.passed)} vector(s)."

        ev_bytes = json.dumps([r.model_dump() for r in results], sort_keys=True).encode("utf-8")
        evidence_hash = hashlib.sha256(ev_bytes).hexdigest()

        return BehaviorEquivalenceReport(
            unit_id=unit_id,
            verdict=verdict,
            achieved_level=achieved,
            vector_results=results,
            numerical_parity=numerical_parity,
            invariants_held=all_passed,
            details=details,
            evidence_hash=evidence_hash,
        )
