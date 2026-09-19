"""Continuous Risk Detection and Safety Governance for Power Engines."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("autoforge.power_engines.risk")


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskClassification(str, Enum):
    SAFE_AUTONOMOUS = "safe_autonomous"
    DESTRUCTIVE_FILESYSTEM = "destructive_filesystem"
    UNAUTHORIZED_NETWORK = "unauthorized_network"
    CREDENTIAL_ACCESS = "credential_access"
    PRODUCTION_DEPLOYMENT = "production_deployment"
    DATA_EXFILTRATION = "data_exfiltration"
    IRREVERSIBLE_ACTION = "irreversible_action"


class RiskAssessment(BaseModel):
    """Assessment of whether an engineering action requires human approval."""
    is_safe: bool = True
    approval_required: bool = False
    risk_level: RiskLevel = RiskLevel.NONE
    classification: RiskClassification = RiskClassification.SAFE_AUTONOMOUS
    reasons: List[str] = Field(default_factory=list)
    proposed_action: Optional[str] = None
    remediation_options: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PowerEngineRiskEvaluator:
    """
    Evaluates risk boundaries across the 11-stage lifecycle.
    Enforces 'Autonomy by Default, Human Intervention by Exception'.
    Routine engineering steps (compilation, testing, parsing, code generation,
    local repair) are fully autonomous.
    """

    def __init__(self, high_risk_targets: Optional[List[str]] = None):
        self.high_risk_targets = set(high_risk_targets or [
            "/etc", "/usr", "/System", "production-db", "live-aws", "prod-cluster"
        ])

    def assess_stage_action(
        self,
        stage_name: str,
        action: str,
        target_path: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        """
        Evaluates whether a stage action is safe for autonomous execution.
        """
        ctx = context or {}
        
        # 1. Target path check: Writing to system root or outside sandbox
        if target_path:
            for forbidden in self.high_risk_targets:
                if target_path.startswith(forbidden):
                    return RiskAssessment(
                        is_safe=False,
                        approval_required=True,
                        risk_level=RiskLevel.CRITICAL,
                        classification=RiskClassification.DESTRUCTIVE_FILESYSTEM,
                        reasons=[f"Target path '{target_path}' points into protected system directory '{forbidden}'."],
                        proposed_action=f"{stage_name}: {action}",
                        remediation_options=["Redirect output to sandboxed customer delivery folder", "Abort operation"]
                    )

        # 2. Credential extraction check
        if "export_secret" in action or ctx.get("accesses_raw_credentials"):
            return RiskAssessment(
                is_safe=False,
                approval_required=True,
                risk_level=RiskLevel.HIGH,
                classification=RiskClassification.CREDENTIAL_ACCESS,
                reasons=["Operation attempts to access or export private credentials."],
                proposed_action=f"{stage_name}: {action}",
                remediation_options=["Use mock credentials", "Request operator token sign-off"]
            )

        # 3. Live production deployment check
        if "deploy_to_production" in action or ctx.get("target_environment") == "production":
            return RiskAssessment(
                is_safe=False,
                approval_required=True,
                risk_level=RiskLevel.HIGH,
                classification=RiskClassification.PRODUCTION_DEPLOYMENT,
                reasons=["Action targets external production environment."],
                proposed_action=f"{stage_name}: {action}",
                remediation_options=["Deploy to local sandbox output", "Operator manual confirmation"]
            )

        # Routine autonomous operations: parsing, chunking, indexing, generation, verification, repair
        return RiskAssessment(
            is_safe=True,
            approval_required=False,
            risk_level=RiskLevel.NONE,
            classification=RiskClassification.SAFE_AUTONOMOUS,
            reasons=[f"Autonomous execution permitted for stage '{stage_name}' action '{action}'."]
        )
