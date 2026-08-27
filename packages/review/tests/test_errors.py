"""Test Review Platform error taxonomy (Section 28).

Verifies that:
- All review exceptions inherit from ReviewError
- Error codes and details dictionaries are preserved
- Representation formatting is clean and informative
"""

from __future__ import annotations

from autoforge_review.errors import (
    ReviewAiUnavailableError,
    ReviewError,
    ReviewLoopError,
    ReviewNotRunError,
    ReviewPolicyRejectedError,
    ReviewValidationError,
)


def test_review_error_hierarchy_and_details() -> None:
    """All custom review errors have appropriate codes and detail preservation."""
    err = ReviewValidationError("Missing required field", details={"field": "evidence"})
    assert isinstance(err, ReviewError)
    assert isinstance(err, Exception)
    assert err.code == "REVIEW_VALIDATION_ERROR"
    assert err.details == {"field": "evidence"}
    assert "Missing required field" in str(err)
    assert repr(err) == "ReviewValidationError(message='Missing required field', code='REVIEW_VALIDATION_ERROR')"


def test_all_error_types_instantiate() -> None:
    """Verify all error classes in the taxonomy instantiate correctly."""
    errors = [
        ReviewError("base error"),
        ReviewValidationError("validation failed"),
        ReviewPolicyRejectedError("policy rejected"),
        ReviewNotRunError("review not executed"),
        ReviewAiUnavailableError("ai provider missing"),
        ReviewLoopError("loop max reached"),
    ]
    for e in errors:
        assert isinstance(e, ReviewError)
        assert e.code.startswith("REVIEW_")
        assert len(e.message) > 0
