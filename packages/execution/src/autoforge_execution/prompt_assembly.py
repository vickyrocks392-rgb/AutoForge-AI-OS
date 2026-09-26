"""
Canonical Prompt Assembly — the single provider-neutral prompt constructor.

Gate 2 §4. This is the **only** place prompt text is formatted. Engines must not
build prompt strings themselves; that is what removed the scattered-formatting
problem in Gate 1.

Provider neutrality is structural rather than aspirational: the output is the
``{"role", "content"}`` shape that ``BaseProviderAdapter.normalize_messages``
already consumes, so **no provider adapter change is required** and no
provider-specific format can leak into this layer.

Determinism: fixed section order, and within each section the canonical rank order
from :mod:`autoforge_execution.context_items`. Identical inputs therefore produce a
byte-identical message list.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    sort_context_items,
)

#: Gate 2 §4.2 — fixed section order. System first so stable material forms a
#: contiguous prefix, which is what makes cacheability metadata meaningful.
SECTION_ORDER: tuple[ContextCategory, ...] = (
    ContextCategory.SYSTEM,
    ContextCategory.PROJECT,
    ContextCategory.TASK,
    ContextCategory.DEPENDENCY,
    ContextCategory.EVIDENCE,
    ContextCategory.DECISION,
    ContextCategory.VERIFICATION,
    ContextCategory.EXECUTION,
    ContextCategory.TOOL,
    ContextCategory.RUNTIME_STATE,
    ContextCategory.GIT,
    ContextCategory.TEST_OUTPUT,
)

_SECTION_HEADINGS: dict[ContextCategory, str] = {
    ContextCategory.SYSTEM: "System Instructions",
    ContextCategory.PROJECT: "Project Context",
    ContextCategory.TASK: "Task",
    ContextCategory.DEPENDENCY: "Dependency Context",
    ContextCategory.EVIDENCE: "Evidence",
    ContextCategory.DECISION: "Decisions",
    ContextCategory.VERIFICATION: "Verification Context",
    ContextCategory.EXECUTION: "Execution Context",
    ContextCategory.TOOL: "Tool Context",
    ContextCategory.RUNTIME_STATE: "Runtime State",
    ContextCategory.GIT: "Git State",
    ContextCategory.TEST_OUTPUT: "Test Output",
}

SYSTEM_ROLE_CATEGORIES = frozenset({ContextCategory.SYSTEM})


def _render_section(category: ContextCategory, items: Sequence[ContextItem]) -> str:
    """Render one section as a heading plus attributed item blocks.

    Each block carries its provenance reference so a reader (human or model) can see
    where the information came from. That is the visible half of Gate 2 §5
    provenance; the machine-readable half lives in the observability record.
    """
    heading = _SECTION_HEADINGS.get(category, category.value.replace("_", " ").title())
    lines = [f"## {heading}"]
    for item in items:
        lines.append(f"### [{item.source.describe()}] {item.context_id}")
        if item.required:
            lines.append("requirement: mandatory")
        for reason in item.required_for:
            lines.append(f"required_for: {reason}")
        lines.append(item.content)
    return "\n".join(lines)


def build_messages(
    items: Iterable[ContextItem],
    *,
    task_name: str = "",
    include_sections: bool = True,
) -> list[dict[str, str]]:
    """Build the canonical provider-neutral message list.

    Returns a list of ``{"role": "system"|"user", "content": str}`` dicts — exactly
    the shape ``BaseProviderAdapter.normalize_messages`` already handles. No
    provider-specific formatting appears here or is assumed here.

    Gate 4 fix: the input is put into canonical rank order here, rather than
    trusting the caller to have done it. ``select_context`` already returns
    sorted items, so this changes nothing on the canonical path — but the
    constructor previously rendered items in whatever order it was handed, so a
    caller passing the same set in a different order got a different prompt.
    That made this function's output order-dependent, which is exactly what a
    *canonical* constructor must not be.
    """
    ordered = sort_context_items(items)
    system_parts: list[str] = []
    user_parts: list[str] = []

    for category in SECTION_ORDER:
        section_items = [i for i in ordered if i.category is category]
        if not section_items:
            continue
        rendered = _render_section(category, section_items)
        if category in SYSTEM_ROLE_CATEGORIES:
            system_parts.append(rendered)
        else:
            user_parts.append(rendered)

    if not include_sections:
        # Minimal form: just the task objective, for callers that already supply
        # their own framing and only need the selected context body.
        return [{"role": "user", "content": task_name}] if task_name else []

    messages: list[dict[str, str]] = []
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    user_body = "\n\n".join(user_parts)
    if task_name:
        header = f"# Task: {task_name}"
        user_body = f"{header}\n\n{user_body}" if user_body else header
    messages.append({"role": "user", "content": user_body})
    return messages


def stable_prefix_items(items: Iterable[ContextItem]) -> list[ContextItem]:
    """Items marked as stable/cache-eligible (Gate 2 §7).

    This is a *local* classification used for ordering and observability only. It
    asserts nothing about provider-side caching, and no cache-control directive is
    emitted by this layer.
    """
    return [
        i
        for i in items
        if i.cacheability.value in {"stable_system", "stable_project"}
    ]
