"""Workflow Trigger Abstraction & Security Boundaries (18-COMMERCIAL-C)."""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel

from autoforge_power_engines.automation.spec import (
    TriggerSpec,
    TriggerType,
    WebhookAuthConfig,
)

logger = logging.getLogger("autoforge.power_engines.automation.triggers")


class TriggerSecurityError(RuntimeError):
    """Raised when an unauthorized or malformed trigger request is received."""


class TriggerPayload(BaseModel):
    """Standardized trigger event payload received by the runtime."""
    trigger_name: str
    trigger_type: TriggerType
    payload: Dict[str, Any]
    headers: Dict[str, str] = {}
    source_ip: Optional[str] = None
    received_at: str = ""


class Trigger(ABC):
    """Abstract base trigger interface."""

    def __init__(self, spec: TriggerSpec):
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def trigger_type(self) -> TriggerType:
        return self.spec.trigger_type

    @abstractmethod
    def evaluate(self, context: Dict[str, Any]) -> Tuple[bool, Optional[TriggerPayload]]:
        """Evaluates whether the trigger should fire based on incoming context."""


class ManualTrigger(Trigger):
    """Explicit customer/operator invocation trigger."""

    def evaluate(self, context: Dict[str, Any]) -> Tuple[bool, Optional[TriggerPayload]]:
        inputs = context.get("inputs", {})
        payload = TriggerPayload(
            trigger_name=self.name,
            trigger_type=TriggerType.MANUAL,
            payload=inputs,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        return True, payload


class WebhookTrigger(Trigger):
    """
    HTTP Webhook Trigger with strict security boundaries:
    - Payload size enforcement
    - Content-type validation
    - Optional HMAC-SHA256 signature verification
    - Optional Bearer token validation
    - Sanitized logging
    """

    def __init__(self, spec: TriggerSpec):
        super().__init__(spec)
        self.auth_config = spec.webhook_auth

    def verify_request(
        self,
        raw_body: bytes,
        headers: Dict[str, str],
        source_ip: Optional[str] = None,
    ) -> TriggerPayload:
        """
        Validates the incoming HTTP request against security constraints.
        Raises TriggerSecurityError on violation.
        """
        # 1. Payload size check
        if len(raw_body) > self.auth_config.max_payload_bytes:
            raise TriggerSecurityError(
                f"Payload size ({len(raw_body)} bytes) exceeds configured limit of {self.auth_config.max_payload_bytes} bytes."
            )

        # 2. Content-Type check
        content_type = headers.get("content-type", "").lower()
        if "application/json" not in content_type and raw_body.strip():
            raise TriggerSecurityError(f"Unsupported content-type '{content_type}'. Expected 'application/json'.")

        # 3. Authentication Checks
        if self.auth_config.require_auth:
            # Bearer token check if configured
            if self.auth_config.expected_token:
                auth_val = headers.get(self.auth_config.auth_header_name.lower()) or headers.get(self.auth_config.auth_header_name)
                if not auth_val:
                    raise TriggerSecurityError("Missing required authorization header.")
                expected = self.auth_config.expected_token
                token_to_check = auth_val.replace("Bearer ", "").strip()
                if not hmac.compare_digest(token_to_check, expected):
                    raise TriggerSecurityError("Invalid webhook authorization token.")

            # HMAC Signature check if configured
            if self.auth_config.hmac_secret:
                sig_header = headers.get(self.auth_config.hmac_header_name.lower()) or headers.get(self.auth_config.hmac_header_name)
                if not sig_header:
                    raise TriggerSecurityError(f"Missing required HMAC signature header '{self.auth_config.hmac_header_name}'.")

                expected_sig = hmac.new(
                    self.auth_config.hmac_secret.encode("utf-8"),
                    raw_body,
                    hashlib.sha256
                ).hexdigest()

                # Support both raw hex and sha256=hex format
                received_sig = sig_header.split("=")[-1] if "=" in sig_header else sig_header
                if not hmac.compare_digest(received_sig, expected_sig):
                    raise TriggerSecurityError("HMAC signature mismatch. Webhook payload rejected.")

        # 4. Parse JSON
        try:
            parsed_json = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as e:
            raise TriggerSecurityError(f"Malformed JSON payload: {e}")

        # 5. Build sanitized payload
        sanitized_headers = {
            k: ("[MASKED]" if k.lower() in ("authorization", "x-webhook-signature", "cookie") else v)
            for k, v in headers.items()
        }

        logger.info(
            f"Webhook trigger '{self.name}' validated successfully from {source_ip or 'unknown'}. "
            f"Payload size: {len(raw_body)} bytes."
        )

        return TriggerPayload(
            trigger_name=self.name,
            trigger_type=TriggerType.WEBHOOK,
            payload=parsed_json,
            headers=sanitized_headers,
            source_ip=source_ip,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

    def evaluate(self, context: Dict[str, Any]) -> Tuple[bool, Optional[TriggerPayload]]:
        raw_body = context.get("raw_body", b"")
        headers = context.get("headers", {})
        source_ip = context.get("source_ip")
        try:
            payload = self.verify_request(raw_body, headers, source_ip)
            return True, payload
        except Exception as e:
            logger.warning(f"WebhookTrigger '{self.name}' rejected request: {e}")
            return False, None


class EventTrigger(Trigger):
    """Matches structured events by topic and key-value pattern."""

    def evaluate(self, context: Dict[str, Any]) -> Tuple[bool, Optional[TriggerPayload]]:
        event_topic = context.get("event_topic")
        event_data = context.get("event_data", {})

        if self.spec.event_topic and self.spec.event_topic != event_topic:
            return False, None

        # Pattern match on event_data
        for k, v in self.spec.event_pattern.items():
            if event_data.get(k) != v:
                return False, None

        payload = TriggerPayload(
            trigger_name=self.name,
            trigger_type=TriggerType.EVENT,
            payload=event_data,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        return True, payload


class ScheduledTrigger(Trigger):
    """
    Bounded declarative scheduler trigger.
    Defines schedule parameters (interval / cron) to be executed or simulated.
    """

    def evaluate(self, context: Dict[str, Any]) -> Tuple[bool, Optional[TriggerPayload]]:
        # In a standalone runtime or test environment, a schedule trigger evaluates
        # true when explicitly tick-stimulated or matched.
        payload = TriggerPayload(
            trigger_name=self.name,
            trigger_type=TriggerType.SCHEDULE,
            payload={
                "cron_expression": self.spec.cron_expression,
                "interval_seconds": self.spec.interval_seconds,
                "triggered_time": datetime.now(timezone.utc).isoformat(),
            },
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        return True, payload


class TriggerRegistry:
    """Registry and coordinator for workflow triggers."""

    def __init__(self):
        self._triggers: Dict[str, Trigger] = {}

    def register(self, spec: TriggerSpec) -> Trigger:
        if spec.trigger_type == TriggerType.MANUAL:
            trigger = ManualTrigger(spec)
        elif spec.trigger_type == TriggerType.WEBHOOK:
            trigger = WebhookTrigger(spec)
        elif spec.trigger_type == TriggerType.EVENT:
            trigger = EventTrigger(spec)
        elif spec.trigger_type == TriggerType.SCHEDULE:
            trigger = ScheduledTrigger(spec)
        else:
            raise ValueError(f"Unsupported trigger type: {spec.trigger_type}")

        self._triggers[spec.name] = trigger
        return trigger

    def get(self, name: str) -> Optional[Trigger]:
        return self._triggers.get(name)

    def list_triggers(self) -> List[Trigger]:
        return list(self._triggers.values())
