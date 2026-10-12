"""Phase 20 — Modernization Service MVP.

This package turns AutoForge's certified Legacy Modernization capability into a
customer-facing service that can take a REAL legacy workload, modernize it,
validate it deterministically, and hand it over as a professional
customer-deliverable product.

Two domains exist and never mix:

DOMAIN A -- AutoForge source/system  (``packages/``, ``apps/``, ``services/`` …)
DOMAIN B -- Customer modernization product (``Modernization Output/``)

Every customer-facing path is resolved through :mod:`boundaries`, which fails
closed: any attempt to place customer material inside Domain A, or to reach
another customer's project from within one, raises :class:`BoundaryViolation`.
"""

from __future__ import annotations

from autoforge_modernization.service.boundaries import (
    AUTOFORGE_OWNED_SOURCE_DIRS,
    CUSTOMER_OUTPUT_DIRNAME,
    BoundaryViolation,
    CustomerBoundary,
    ProjectAccessGuard,
)

__all__ = [
    "AUTOFORGE_OWNED_SOURCE_DIRS",
    "CUSTOMER_OUTPUT_DIRNAME",
    "BoundaryViolation",
    "CustomerBoundary",
    "ProjectAccessGuard",
]