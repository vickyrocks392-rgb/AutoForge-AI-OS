"""
Token Estimation — provider-neutral, deterministic, injectable.

Gate 2 §3.4. No tokenizer exists in this repository and adding one would be a new
dependency, so the design defines a ``TokenEstimator`` *protocol* with one default
heuristic implementation. A real tokenizer can later be injected **without changing
selection, ordering, or budget logic** — that is the entire reason for the seam.

The default heuristic is intentionally conservative: it is calibrated to
over-estimate slightly, because under-estimation would allow a real context-window
overflow. A safety margin is applied on top (see :class:`TokenEstimator`).
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

# Rough token classes. Kept deliberately simple and dependency-free.
_CODE_SYMBOL_RE = re.compile(r"[{}()\[\];:,.<>=+\-*/%&|^~!@#$\"'`]")
_WHITESPACE_RE = re.compile(r"\s+")


@runtime_checkable
class TokenEstimator(Protocol):
    """Estimates the token cost of a piece of text.

    Implementations must be deterministic: the same text always yields the same
    count, or budget enforcement and the determinism tests become meaningless.
    """

    def estimate(self, text: str) -> int:
        """Return a non-negative estimated token count for ``text``."""
        ...


class HeuristicTokenEstimator:
    """Deterministic character/class heuristic for code-and-prose text.

    Strategy: whitespace-delimited words, plus one extra token per code punctuation
    symbol, which approximates how BPE-style vocabularies split source code. This is
    an *estimate* and is named as such everywhere it is surfaced.
    """

    #: Multiplier applied to keep the estimate conservative (Gate 2 §3.4).
    safety_margin: float = 1.10

    def __init__(self, *, safety_margin: float | None = None) -> None:
        if safety_margin is not None:
            if safety_margin < 1.0:
                raise ValueError("safety_margin must be >= 1.0 (estimates must not under-count)")
            self.safety_margin = float(safety_margin)

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        words = [w for w in _WHITESPACE_RE.split(text) if w]
        symbols = len(_CODE_SYMBOL_RE.findall(text))
        raw = len(words) + symbols
        return max(1, int(raw * self.safety_margin))


#: Process-wide default estimator.
DEFAULT_TOKEN_ESTIMATOR: TokenEstimator = HeuristicTokenEstimator()


def estimate_tokens(text: str, estimator: TokenEstimator | None = None) -> int:
    """Estimate tokens for ``text`` using ``estimator`` or the module default."""
    return (estimator or DEFAULT_TOKEN_ESTIMATOR).estimate(text)
