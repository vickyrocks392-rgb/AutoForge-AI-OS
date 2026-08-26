"""Security primitives for connector boundaries.

Phase 8 rules enforced here:

- Secrets live in dedicated wrapper objects whose ``repr``/``str`` are
  redacted, so accidental logging/interpolation cannot leak them.
- Any message destined for logs/events/errors can be scrubbed of known
  secrets with :func:`redact`.
- The platform introduces NO new secret store; the composition root injects
  credentials already resolved from its own configuration.
"""

from __future__ import annotations

from typing import Iterable


class SecretValue:
    """Wraps a credential value; string conversions are redacted.

    Intentionally NOT a pydantic model: pydantic serialization could echo
    the wrapped value into artifacts. ``value`` is exposed as a private-ish
    attribute used only by the transport boundary that must place it in a
    header at request time.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("SecretValue requires a non-empty string")
        self._value = value

    @property
    def value(self) -> str:
        """The raw credential — use ONLY at the outbound transport seam."""
        return self._value

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "SecretValue(***)"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretValue):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)


def redact(message: str, secrets: Iterable[SecretValue | str]) -> str:
    """Return ``message`` with every occurrence of any secret replaced."""
    result = message
    for secret in secrets:
        raw = secret.value if isinstance(secret, SecretValue) else str(secret)
        if raw:
            result = result.replace(raw, "***")
    return result
