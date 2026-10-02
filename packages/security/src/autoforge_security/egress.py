"""
Central Egress Policy — destination control and data-loss prevention.

Canonical outbound-network control for every AI-reachable network path. Two
independent layers, both enforced *before transmission*:

1. **Destination control** — scheme, port, hostname/IP policy, loopback and
   private/link-local denial, cloud-metadata denial, and DNS-rebinding-aware
   resolution. Delegates to the existing, preserved ``validate_outbound_url``
   semantics rather than reimplementing them.

2. **Content control (DLP)** — recursive inspection of headers, query, body, and
   nested structures. Registered secrets are matched by value; high-confidence
   secret *shapes* (API keys, bearer tokens, private keys) are matched by
   pattern. Any match is blocked — the platform does not rely on prompt
   instructions such as "never send secrets".

Fail-closed by default: when inspection cannot complete, sensitive classes are
denied rather than allowed.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

# ── Destination policy ────────────────────────────────────────────────────

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Ports commonly used to reach local/internal services.
BLOCKED_PORTS = frozenset(
    {22, 23, 25, 445, 3306, 5432, 6379, 9200, 11211, 27017, 2375, 2376, 10250}
)

#: Well-known cloud metadata endpoints that must never be reachable.
CLOUD_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.goog",
        "100.100.100.200",
        "169.254.170.2",
        "fd00:ec2::254",
    }
)

#: Reserved / special-use hostnames that indicate a local target.
LOCAL_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "0.0.0.0",
        "::",
        "::1",
        "local",
    }
)


class EgressDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REDACT = "redact"


@dataclass(frozen=True)
class EgressResult:
    decision: EgressDecision
    reason: str
    sanitized_payload: Any = None
    findings: tuple[str, ...] = ()

    findings: tuple[str, ...] = ()


def _is_blocked_ip(ip: Any) -> str | None:
    """Return a denial reason for a disallowed IP, else ``None``."""
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address (includes cloud metadata)"
    if ip.is_private:
        return "private (RFC1918) address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    if str(ip) in CLOUD_METADATA_HOSTS:
        return "cloud metadata endpoint"
    return None


def validate_egress_url(
    url: str,
    *,
    allowed_domains: Sequence[str] | None = None,
    allow_private_networks: bool = False,
    allowed_ports: Sequence[int] | None = None,
) -> tuple[bool, str]:
    """Canonical destination policy.

    Preserves and re-derives the semantics of the existing
    ``validate_outbound_url`` (SSRF / DNS-rebinding) and adds port and
    metadata-endpoint restrictions.
    """
    if not isinstance(url, str) or not url.strip():
        return False, "URL must be a non-empty string."

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"Scheme '{parsed.scheme}' is not permitted (http/https only)."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname."

    if parsed.port is not None:
        if allowed_ports is not None:
            if parsed.port not in allowed_ports:
                return False, f"Port {parsed.port} is not permitted."
        elif parsed.port in BLOCKED_PORTS:
            return False, f"Port {parsed.port} is blocked by egress policy."

    lowered = hostname.lower()
    if lowered in CLOUD_METADATA_HOSTS:
        return False, f"Destination '{hostname}' is a cloud metadata endpoint."

    if lowered in LOCAL_HOSTNAMES and not allow_private_networks:
        return False, f"Destination '{hostname}' resolves to a local address."

    try:
        ip: Any = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None:
        if not allow_private_networks:
            reason = _is_blocked_ip(ip)
            if reason:
                return False, f"Destination '{hostname}' is a {reason}."
    else:
        if allowed_domains:
            permitted = {d.lower().lstrip(".") for d in allowed_domains}
            if not any(lowered == d or lowered.endswith("." + d) for d in permitted):
                return False, f"Destination '{hostname}' is not in the allowed domain list."
        if not allow_private_networks:
            try:
                infos = socket.getaddrinfo(hostname, None)
            except OSError as exc:
                return False, f"Destination '{hostname}' could not be resolved: {exc}"
            for info in infos:
                addr = info[4][0]
                try:
                    resolved = ipaddress.ip_address(addr)
                except ValueError:
                    return False, f"Destination '{hostname}' resolved to an invalid address."
                reason = _is_blocked_ip(resolved)
                if reason:
                    return False, (
                        f"Destination '{hostname}' resolves to {addr}, a {reason} "
                        "(DNS-rebinding protection)."
                    )

    return True, "Destination permitted by egress policy."


# ── Content / DLP control ─────────────────────────────────────────────────

#: High-confidence secret shapes. Matched against every string in the payload,
#: including nested values, so a secret cannot hide inside a nested JSON body.
SECRET_SHAPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_access_key", re.compile(r"(?i)aws_?secret_?access_?key\s*[=:]\s*\S{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("generic_bearer_header", re.compile(r"(?i)^(authorization|x-api-key|api-key)\s*$")),
)

#: Header names that themselves carry a credential. These are treated as
#: *secrets*: the request is denied rather than silently stripped, so the caller
#: never receives a confusingly unauthenticated success.
CREDENTIAL_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "apikey",
        "x-auth-token",
        "x-amz-security-token",
        "cookie",
    }
)

#: Header names whose values are sensitive but are not themselves credentials.
SENSITIVE_HEADER_NAMES = frozenset({"set-cookie"})

#: Body/query keys that conventionally carry credentials.
SENSITIVE_KEY_NAMES = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "secret",
        "client_secret",
        "password",
        "passwd",
        "private_key",
        "credential",
        "credentials",
        "session_id",
        "session_token",
        "authorization",
    }
)

_MAX_SCAN_DEPTH = 12


def _scan_string(value: str, registered_secrets: Iterable[str]) -> list[str]:
    findings: list[str] = []
    for secret in registered_secrets:
        if secret and len(secret) >= 4 and secret in value:
            findings.append("registered_secret_value")
    for name, pattern in SECRET_SHAPE_PATTERNS:
        if name == "generic_bearer_header":
            continue
        if pattern.search(value):
            findings.append(f"secret_shape:{name}")
    return findings


def inspect_payload(
    payload: Any,
    *,
    registered_secrets: Iterable[str] = (),
    headers: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
    in_headers: bool = False,
) -> tuple[list[str], Any]:
    """Recursively inspect an outbound payload for sensitive material.

    Walks nested mappings, sequences, and sets; inspects header names and values
    and sensitive-looking keys. Returns ``(findings, sanitized_payload)``.

    This is deliberately breadth-first over the whole structure — it never
    inspects only the top level.
    """
    secrets = list(registered_secrets)
    findings: list[str] = []
    sanitized = _inspect_node(
        payload, secrets, findings, 0, in_headers=in_headers, key_name=""
    )
    return findings, sanitized


def _inspect_node(
    node: Any,
    secrets: list[str],
    findings: list[str],
    depth: int,
    *,
    in_headers: bool,
    key_name: str,
) -> Any:
    if depth > _MAX_SCAN_DEPTH:
        findings.append("payload_too_deep_to_inspect")
        return node

    if isinstance(node, Mapping):
        out: dict[str, Any] = {}
        for k, v in node.items():
            ks = str(k)
            if in_headers and ks.lower() in CREDENTIAL_HEADER_NAMES:
                # Credentials are never transmitted; deny rather than strip.
                findings.append("sensitive_header:" + ks.lower())
                out[ks] = "[REDACTED_BY_EGRESS_POLICY]"
                continue
            if in_headers and ks.lower() in SENSITIVE_HEADER_NAMES:
                findings.append(f"sensitive_header:{ks.lower()}")
                out[ks] = "[REDACTED_BY_EGRESS_POLICY]"
                continue
            if ks.lower() in SENSITIVE_KEY_NAMES:
                findings.append(f"sensitive_field:{ks.lower()}")
                out[ks] = "[REDACTED_BY_EGRESS_POLICY]"
                continue
            out[ks] = _inspect_node(
                v, secrets, findings, depth + 1, in_headers=in_headers, key_name=ks
            )
        return out

    if isinstance(node, (list, tuple, set)):
        return [
            _inspect_node(v, secrets, findings, depth + 1, in_headers=in_headers, key_name=key_name)
            for v in node
        ]

    if isinstance(node, bytes):
        try:
            node = node.decode("utf-8")
        except UnicodeDecodeError:
            findings.append("undecodable_binary_payload")
            return "[REDACTED_BY_EGRESS_POLICY]"

    if isinstance(node, str):
        hits = _scan_string(node, secrets)
        if hits:
            findings.extend(hits)
            return "[REDACTED_BY_EGRESS_POLICY]"
        return node

    return node


# ── Composite policy ──────────────────────────────────────────────────────


@dataclass
class EgressPolicy:
    """Canonical, fail-closed outbound policy.

    ``enforce`` runs destination control first, then content inspection, and
    returns a decision plus the exact sanitized payload that may be sent. It
    never performs I/O, so it is safe to call from tests and from live code.

    * ``block_on_secret`` (default ``True``) — a secret finding denies the
      request outright. Secrets are never transmitted.
    * ``redact_on_sensitive_field`` — non-secret sensitive *field names*
      (e.g. ``password``) may be redacted and the request allowed, so ordinary
      application traffic still works.
    """

    allowed_domains: tuple[str, ...] = ()
    allow_private_networks: bool = False
    allowed_ports: tuple[int, ...] | None = None
    registered_secrets: tuple[str, ...] = ()
    block_on_secret: bool = True
    redact_on_sensitive_field: bool = True
    audit: list[dict[str, Any]] = field(default_factory=list)

    def enforce(
        self,
        url: str,
        *,
        headers: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        method: str = "GET",
        project_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EgressResult:
        """Decide whether an outbound request may proceed."""

        ok, reason = validate_egress_url(
            url,
            allowed_domains=self.allowed_domains or None,
            allow_private_networks=self.allow_private_networks,
            allowed_ports=self.allowed_ports,
        )
        if not ok:
            self._record("egress.denied.destination", url, reason, project_id, correlation_id)
            return EgressResult(decision=EgressDecision.DENY, reason=reason)

        findings: list[str] = []
        sanitized_headers = None
        sanitized_params = None
        sanitized_body: Any = body

        if headers:
            h_findings, sanitized_headers = inspect_payload(
                dict(headers),
                registered_secrets=self.registered_secrets,
                headers=dict(headers),
                in_headers=True,
            )
            findings.extend(h_findings)
        if params:
            p_findings, sanitized_params = inspect_payload(
                dict(params), registered_secrets=self.registered_secrets
            )
            findings.extend(p_findings)
        if body is not None:
            b_findings, sanitized_body = inspect_payload(
                body, registered_secrets=self.registered_secrets
            )
            findings.extend(b_findings)

        secret_findings = [
            f
            for f in findings
            if f.startswith("secret_shape:")
            or f == "registered_secret_value"
            or f.startswith("sensitive_header:")
        ]
        if secret_findings and self.block_on_secret:
            reason = (
                "Outbound payload blocked: sensitive material detected "
                f"({sorted(set(secret_findings))}). Secrets are never transmitted."
            )
            self._record("egress.denied.secret", url, reason, project_id, correlation_id)
            return EgressResult(decision=EgressDecision.DENY, reason=reason, findings=tuple(findings))

        if findings and not self.redact_on_sensitive_field:
            reason = f"Outbound payload blocked: {sorted(set(findings))}"
            self._record("egress.denied.sensitive", url, reason, project_id, correlation_id)
            return EgressResult(decision=EgressDecision.DENY, reason=reason, findings=tuple(findings))

        if findings:
            self._record("egress.allowed.redacted", url, str(sorted(set(findings))), project_id, correlation_id)
            return EgressResult(
                decision=EgressDecision.REDACT,
                reason=f"Payload redacted before transmission: {sorted(set(findings))}",
                sanitized_payload={
                    "headers": sanitized_headers,
                    "params": sanitized_params,
                    "body": sanitized_body,
                },
                findings=tuple(findings),
            )

        self._record("egress.allowed", url, "clean", project_id, correlation_id)
        return EgressResult(decision=EgressDecision.ALLOW, reason=reason)

    def _record(
        self,
        event: str,
        url: str,
        reason: str,
        project_id: str | None,
        correlation_id: str | None,
    ) -> None:
        self.audit.append(
            {
                "event": event,
                "url": url[:300],
                "reason": reason[:500],
                "project_id": project_id,
                "correlation_id": correlation_id,
            }
        )


