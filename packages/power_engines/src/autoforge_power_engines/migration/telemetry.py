"""Performance Telemetry & Traceable Observability (18-COMMERCIAL-D).

Records:
1. Deterministic performance measurements:
   - Files processed, source LOC, source NLOC, target LOC
   - Transformation time, model time, build time, test time, verification time, repair time, packaging time, wall time
   - Model calls
   - Strictly separates LLM tokens/sec from migration NLOC/hour
2. End-to-end unit traceability with secret masking.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# Secret masking regex
SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|token|password|auth[_-]?token)\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END \1PRIVATE KEY-----", re.DOTALL),
]


def mask_secrets(text: str) -> str:
    """Masks tokens, secrets, and private keys from strings."""
    masked = text
    for p in SECRET_PATTERNS:
        masked = p.sub(r"\1: '***MASKED***'", masked)
    return masked


class MigrationUnitTrace(BaseModel):
    """End-to-end audit trace for a single migration unit."""
    migration_id: str
    unit_id: str
    source_file: str
    target_file: str
    stage: str
    status: str
    model_used: Optional[str] = None
    attempts: int = 1
    repair_attempts: int = 0
    verification_verdict: str = "PENDING"
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None


class PerformanceMetrics(BaseModel):
    """
    Deterministic performance metrics for the migration run.
    Explicitly separates LLM inference metrics from engineering migration throughput.
    """
    files_processed: int = 0
    source_loc: int = 0
    source_nloc: int = 0
    target_loc: int = 0

    # Timing breakdowns (in seconds)
    transformation_time_s: float = 0.0
    model_time_s: float = 0.0
    build_time_s: float = 0.0
    test_time_s: float = 0.0
    verification_time_s: float = 0.0
    repair_time_s: float = 0.0
    packaging_time_s: float = 0.0
    total_wall_time_s: float = 0.0

    # Model inference telemetry
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_tokens_per_sec: float = 0.0

    # Engineering throughput (strictly separate from tokens/sec)
    migration_nloc_per_hour: float = 0.0

    def calculate_rates(self) -> None:
        """Calculates distinct rates for LLM tokens/sec and migration NLOC/hour."""
        if self.model_time_s > 0 and (self.prompt_tokens + self.completion_tokens) > 0:
            self.llm_tokens_per_sec = (self.prompt_tokens + self.completion_tokens) / self.model_time_s

        if self.total_wall_time_s > 0 and self.source_nloc > 0:
            hours = self.total_wall_time_s / 3600.0
            self.migration_nloc_per_hour = self.source_nloc / hours


class MigrationTelemetryCollector:
    """
    Collects performance metrics and unit traces during execution.
    """

    def __init__(self, migration_id: str):
        self.migration_id = migration_id
        self.metrics = PerformanceMetrics()
        self.traces: List[MigrationUnitTrace] = []
        self._start_time: float = time.perf_counter()

    def record_trace(
        self,
        unit_id: str,
        source_file: str,
        target_file: str,
        stage: str,
        status: str,
        duration_ms: float = 0.0,
        model_used: Optional[str] = None,
        attempts: int = 1,
        repair_attempts: int = 0,
        verification_verdict: str = "PENDING",
        error_message: Optional[str] = None,
    ) -> MigrationUnitTrace:
        trace = MigrationUnitTrace(
            migration_id=self.migration_id,
            unit_id=unit_id,
            source_file=source_file,
            target_file=target_file,
            stage=stage,
            status=status,
            duration_ms=duration_ms,
            model_used=model_used,
            attempts=attempts,
            repair_attempts=repair_attempts,
            verification_verdict=verification_verdict,
            error_message=mask_secrets(error_message) if error_message else None,
        )
        self.traces.append(trace)
        return trace

    def finalize(self) -> PerformanceMetrics:
        self.metrics.total_wall_time_s = time.perf_counter() - self._start_time
        self.metrics.calculate_rates()
        return self.metrics
