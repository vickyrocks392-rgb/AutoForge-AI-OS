"""
Error normalization and classification layer for AutoForge exceptions.
"""

from __future__ import annotations
from typing import Any, Dict, Optional, Type


class ErrorObservation:
    """
    Normalized representation of an exception for observability logging/metrics.
    Does not replace or wrap domain exceptions.
    """

    def __init__(
        self,
        category: str,
        message: str,
        component: str,
        retryable: bool = False,
        cause: Optional[str] = None,
    ) -> None:
        self.category = category
        self.message = message
        self.component = component
        self.retryable = retryable
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "message": self.message,
            "component": self.component,
            "retryable": self.retryable,
            "cause": self.cause,
        }


def normalize_error(exc: Exception, component: str = "unknown") -> ErrorObservation:
    """
    Dynamically maps any exception to a normalized ErrorObservation structure.
    """
    exc_type = type(exc).__name__
    message = str(exc)
    
    # Defaults
    category = "SystemError"
    retryable = False
    cause = None

    # Inspect properties or check types dynamically to avoid hard-coded circular imports
    if hasattr(exc, "retryable"):
        retryable = bool(getattr(exc, "retryable"))
    
    if hasattr(exc, "category"):
        category = str(getattr(exc, "category"))
    
    if hasattr(exc, "cause") and getattr(exc, "cause"):
        cause = str(getattr(exc, "cause"))
    elif exc.__cause__:
        cause = str(exc.__cause__)

    # Execution package error patterns
    if "ExecutionError" in exc_type or "Subprocess" in exc_type:
        category = "ExecutionFailure"
        if "Timeout" in exc_type:
            category = "ExecutionTimeout"
            retryable = True
    # Workflow package error patterns
    elif "WorkflowError" in exc_type or "Task" in exc_type:
        category = "WorkflowFailure"
        if "Retry" in exc_type:
            retryable = True
    # AI Infrastructure package patterns
    elif "Routing" in exc_type or "Model" in exc_type or "Provider" in exc_type:
        category = "AIInfrastructureFailure"
        retryable = True  # Model calls or fallbacks are often retryable

    # If category is still generic SystemError but we have a custom type name, use it
    if category == "SystemError" and exc_type != "Exception":
        category = exc_type

    return ErrorObservation(
        category=category,
        message=message,
        component=component,
        retryable=retryable,
        cause=cause,
    )
