"""Controlled Transformation Pipeline Engine (18-COMMERCIAL-D).

Executes bounded, atomic transformations per unit:
parse → understand → construct semantic representation → plan transformation
→ generate target → normalize → record before/after state & lineage.
Prefers deterministic synthesis and bounds AI semantic assistance.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.migration.plan import TransformationUnit, TransformationUnitType
from autoforge_power_engines.migration.strategy import MigrationStrategyRegistry, MigrationStrategy


class TransformationRecord(BaseModel):
    """Execution evidence for a single unit transformation."""
    unit_id: str
    source_file: str
    target_file: str
    before_sha256: str
    after_sha256: str
    transformation_type: TransformationUnitType
    strategy_id: str
    duration_ms: float
    success: bool
    error_message: Optional[str] = None
    lineage_metadata: Dict[str, Any] = Field(default_factory=dict)


class TransformationPipeline:
    """
    Coordinates atomic source-to-target transformation across units.
    """

    def __init__(
        self,
        source_root: Path,
        working_dir: Path,
        target_dir: Path,
    ):
        self.source_root = Path(source_root).resolve()
        self.working_dir = Path(working_dir).resolve()
        self.target_dir = Path(target_dir).resolve()

    def transform_unit(
        self,
        unit: TransformationUnit,
        context: Dict[str, Any],
    ) -> TransformationRecord:
        """Applies transformation to a single unit."""
        start_time = time.perf_counter()
        source_abs = (self.source_root / unit.source_path).resolve()
        target_abs = (self.target_dir / unit.target_path).resolve()
        target_abs.parent.mkdir(parents=True, exist_ok=True)

        before_sha = ""
        after_sha = ""

        # Handle EXCLUDED
        if unit.transformation_type == TransformationUnitType.EXCLUDED:
            dur = (time.perf_counter() - start_time) * 1000.0
            return TransformationRecord(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_file=unit.target_path,
                before_sha256=unit.source_sha256,
                after_sha256=unit.source_sha256,
                transformation_type=unit.transformation_type,
                strategy_id="none_excluded",
                duration_ms=dur,
                success=True,
                lineage_metadata={"status": "excluded_by_policy"},
            )

        # Handle COPY_AS_IS
        if unit.transformation_type == TransformationUnitType.COPY_AS_IS:
            try:
                content_bytes = source_abs.read_bytes()
                before_sha = hashlib.sha256(content_bytes).hexdigest()
                target_abs.write_bytes(content_bytes)
                after_sha = before_sha
                dur = (time.perf_counter() - start_time) * 1000.0
                return TransformationRecord(
                    unit_id=unit.unit_id,
                    source_file=unit.source_path,
                    target_file=unit.target_path,
                    before_sha256=before_sha,
                    after_sha256=after_sha,
                    transformation_type=unit.transformation_type,
                    strategy_id="copy_as_is",
                    duration_ms=dur,
                    success=True,
                )
            except Exception as ex:
                dur = (time.perf_counter() - start_time) * 1000.0
                return TransformationRecord(
                    unit_id=unit.unit_id,
                    source_file=unit.source_path,
                    target_file=unit.target_path,
                    before_sha256=before_sha,
                    after_sha256="",
                    transformation_type=unit.transformation_type,
                    strategy_id="copy_as_is",
                    duration_ms=dur,
                    success=False,
                    error_message=str(ex),
                )

        # Active transformation using strategy
        strategy = MigrationStrategyRegistry.find_strategy(
            source_language=unit.source_language or "",
            target_language=unit.target_language,
        )

        if not strategy:
            dur = (time.perf_counter() - start_time) * 1000.0
            return TransformationRecord(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_file=unit.target_path,
                before_sha256=unit.source_sha256,
                after_sha256="",
                transformation_type=unit.transformation_type,
                strategy_id="unsupported",
                duration_ms=dur,
                success=False,
                error_message=f"No transformation strategy found for {unit.source_language} -> {unit.target_language}",
            )

        try:
            source_text = source_abs.read_text(encoding="utf-8", errors="replace")
            before_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

            # Execute transform
            transformed_code = strategy.transform(unit, source_text, context)
            target_abs.write_text(transformed_code, encoding="utf-8")
            after_sha = hashlib.sha256(transformed_code.encode("utf-8")).hexdigest()

            # Generate complementary tests
            generated_tests = strategy.generate_tests(unit, transformed_code, context)
            for tpath, tcode in generated_tests.items():
                full_test_path = (self.target_dir / tpath).resolve()
                full_test_path.parent.mkdir(parents=True, exist_ok=True)
                full_test_path.write_text(tcode, encoding="utf-8")

            dur = (time.perf_counter() - start_time) * 1000.0
            return TransformationRecord(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_file=unit.target_path,
                before_sha256=before_sha,
                after_sha256=after_sha,
                transformation_type=unit.transformation_type,
                strategy_id=strategy.strategy_id(),
                duration_ms=dur,
                success=True,
                lineage_metadata={
                    "source_bytes": len(source_text),
                    "target_bytes": len(transformed_code),
                    "generated_tests_count": len(generated_tests),
                }
            )
        except Exception as ex:
            dur = (time.perf_counter() - start_time) * 1000.0
            return TransformationRecord(
                unit_id=unit.unit_id,
                source_file=unit.source_path,
                target_file=unit.target_path,
                before_sha256=before_sha,
                after_sha256="",
                transformation_type=unit.transformation_type,
                strategy_id=strategy.strategy_id() if strategy else "unknown",
                duration_ms=dur,
                success=False,
                error_message=f"Transformation failure: {ex}",
            )
