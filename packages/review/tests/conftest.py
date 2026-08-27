"""Shared fixtures for autoforge_review tests."""

from __future__ import annotations

import pytest

from autoforge_review.engine import ReviewEngine
from autoforge_review.policies import ReviewPolicy, default_review_policy


@pytest.fixture
def engine() -> ReviewEngine:
    return ReviewEngine()


@pytest.fixture
def policy() -> ReviewPolicy:
    return default_review_policy()
