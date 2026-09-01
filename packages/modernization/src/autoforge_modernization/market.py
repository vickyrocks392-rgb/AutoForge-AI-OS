"""
Market Benchmark and Estimate Models.

Establishes models for market benchmarks. The base contract is:
- Do NOT reduce project value to LOC * fixed price
- Support multiple inputs: LOC, technology, complexity, geography, risk, etc.
- Represent low / typical / high market ranges
- Distinguish first-party, industry benchmark, consultancy claim, market rate, inference
- These are estimates, not guaranteed quotes

Reuses:
- sizing: LOCMetrics
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BenchmarkType(str, Enum):
    """Type of benchmark source."""

    FIRST_PARTY_PRICING = "first_party_pricing"
    """Pricing from AutoForge itself (e.g., published rate)."""

    INDUSTRY_BENCHMARK = "industry_benchmark"
    """Public industry benchmark (e.g., ISBSG, QSM)."""

    CONSULTANCY_CLAIM = "consultancy_claim"
    """Published consultancy claim."""

    MARKET_RATE = "market_rate"
    """Observed market rate (e.g., freelancer platform data)."""

    INFERENCE = "inference"
    """Inferred from related data; not a direct measurement."""

    OTHER = "other"


class PricingModel(str, Enum):
    """How the benchmark is priced."""

    FIXED_PRICE = "fixed_price"
    TIME_AND_MATERIALS = "time_and_materials"
    PER_LOC = "per_loc"
    PER_FUNCTION_POINT = "per_function_point"
    PER_USER_STORY = "per_user_story"
    RETAINER = "retainer"
    VALUE_BASED = "value_based"


class ProjectComplexity(str, Enum):
    """Overall project complexity."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    HIGHLY_COMPLEX = "highly_complex"


class Geography(str, Enum):
    """Market geography."""

    NORTH_AMERICA = "north_america"
    EUROPE = "europe"
    ASIA_PACIFIC = "asia_pacific"
    LATIN_AMERICA = "latin_america"
    MIDDLE_EAST_AFRICA = "middle_east_africa"
    GLOBAL_BLENDED = "global_blended"


class MarketBenchmark(BaseModel):
    """
    A market benchmark reference for modernization pricing.

    Distinguishes first-party pricing, industry benchmarks, consultancy
    claims, market rates, and inferences. Each has a source URL and
    retrieval date.
    """

    benchmark_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Range
    low_value_usd: float = 0.0
    typical_value_usd: float = 0.0
    high_value_usd: float = 0.0

    # Methodology
    methodology: str = ""
    benchmark_type: BenchmarkType = BenchmarkType.OTHER
    pricing_model: PricingModel = PricingModel.TIME_AND_MATERIALS
    unit: str = "USD"  # The currency unit

    # Source
    source: str = ""
    source_url: str = ""
    retrieval_date: datetime | None = None
    geography: Geography = Geography.GLOBAL_BLENDED
    scope: str = ""

    # Confidence
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""

    def is_market_data(self) -> bool:
        return self.benchmark_type in (
            BenchmarkType.INDUSTRY_BENCHMARK,
            BenchmarkType.MARKET_RATE,
            BenchmarkType.CONSULTANCY_CLAIM,
            BenchmarkType.FIRST_PARTY_PRICING,
        )


class MarketInputs(BaseModel):
    """
    All inputs that influence a market estimate.

    Captures the multi-dimensional nature of modernization pricing.
    """

    # Size
    total_loc: int = 0
    technology: str = ""
    framework: str = ""
    primary_language: str = ""

    # Strategy
    migration_strategy: str = ""
    architecture_complexity: ProjectComplexity = ProjectComplexity.MODERATE

    # Workload
    integration_count: int = 0
    database_complexity: ProjectComplexity = ProjectComplexity.MODERATE
    data_migration_volume_gb: float = 0.0

    # Quality
    testing_burden_score: float = 1.0  # Multiplier
    specialist_skills_required: list[str] = Field(default_factory=list)

    # Market
    geography: Geography = Geography.GLOBAL_BLENDED

    # Project
    estimated_duration_months: float = 0.0
    risk_score: float = 0.5  # 0-1


class MarketEstimate(BaseModel):
    """
    A market estimate for a modernization project.

    Contains a low/typical/high range based on market benchmarks.
    These are ESTIMATES, not guaranteed customer quotes.
    """

    estimate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str

    inputs: MarketInputs = Field(default_factory=MarketInputs)

    # Range
    low_value_usd: float = 0.0
    typical_value_usd: float = 0.0
    high_value_usd: float = 0.0

    # Breakdown
    cost_drivers: dict[str, float] = Field(default_factory=dict)

    # Benchmarks used
    benchmark_ids: list[str] = Field(default_factory=list)

    # Confidence
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    is_disclaimer_required: bool = True  # Always disclaimer

    # Methodology
    methodology: str = "multi_factor_blended"
    computed_at: datetime = Field(default_factory=_utc_now)
    notes: str = ""

    def is_only_estimate(self) -> bool:
        """This is ALWAYS only an estimate, not a quote."""
        return True
