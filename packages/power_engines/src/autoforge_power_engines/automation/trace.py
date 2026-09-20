"""Observable Execution Tracing & Audit Trail Generator (18-COMMERCIAL-C)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.automation.verifier import VerificationResult
from autoforge_power_engines.automation.state_machine import StateTransitionRecord

logger = logging.getLogger("autoforge.power_engines.automation.trace")


SENSITIVE_KEY_PATTERNS = [
    re.compile(r"pass(word)?", re.I),
    re.compile(r"secret", re.I),
    re.compile(r"token", re.I),
    re.compile(r"auth(orization)?", re.I),
    re.compile(r"api[_-]?key", re.I),
    re.compile(r"private[_-]?key", re.I),
    re.compile(r"signature", re.I),
]


def mask_sensitive_data(obj: Any) -> Any:
    """Recursively masks passwords, tokens, API keys, and authorization headers."""
    if isinstance(obj, dict):
        masked = {}
        for k, v in obj.items():
            if any(pat.search(str(k)) for pat in SENSITIVE_KEY_PATTERNS):
                masked[k] = "[MASKED]"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(obj, list):
        return [mask_sensitive_data(item) for item in obj]
    elif isinstance(obj, str):
        # Mask embedded Bearer tokens or secret patterns
        if "Bearer " in obj:
            return re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [MASKED]", obj)
        return obj
    return obj


class StepExecutionTrace(BaseModel):
    """Audit record for an individual step execution."""
    step_id: str
    step_type: str
    action_name: Optional[str] = None
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    duration_ms: float = 0.0
    status: str = "PENDING"
    retry_count: int = 0
    repaired: bool = False
    inputs_sanitized: Dict[str, Any] = Field(default_factory=dict)
    outputs_sanitized: Dict[str, Any] = Field(default_factory=dict)
    state_transitions: List[StateTransitionRecord] = Field(default_factory=list)
    verification_result: Optional[VerificationResult] = None
    error_message: Optional[str] = None


class ExecutionTrace(BaseModel):
    """Full end-to-end execution audit trace for a workflow run."""
    execution_id: str
    workflow_id: str
    workflow_version: str
    trigger_name: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    total_duration_ms: float = 0.0
    final_status: str = "RUNNING"
    step_traces: List[StepExecutionTrace] = Field(default_factory=list)
    final_outputs: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None

    def get_step_trace(self, step_id: str) -> Optional[StepExecutionTrace]:
        for st in self.step_traces:
            if st.step_id == step_id:
                return st
        return None

    def finalize(self, status: str, outputs: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        self.final_status = status
        self.completed_at = datetime.now(timezone.utc).isoformat()
        if self.started_at:
            t0 = datetime.fromisoformat(self.started_at)
            t1 = datetime.fromisoformat(self.completed_at)
            self.total_duration_ms = (t1 - t0).total_seconds() * 1000.0
        if outputs:
            self.final_outputs = mask_sensitive_data(outputs)
        if error:
            self.error_message = error
