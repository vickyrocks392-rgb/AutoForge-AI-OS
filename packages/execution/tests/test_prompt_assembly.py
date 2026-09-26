"""Prompt assembly tests — the single canonical, provider-neutral path (18-L Gate 3).

Covers Gate 2 section 4 (deterministic, ordered, provider-neutral construction),
section 7 (cacheability metadata without provider claims), section 9 provenance
attribution, and section 12 provider neutrality.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from autoforge_execution.context_items import (
    ContextCacheability,
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
)
from autoforge_execution.prompt_assembly import build_messages, stable_prefix_items

CORE_MODULES = [
    "context_items.py",
    "context_budget.py",
    "context_selection.py",
    "context_observability.py",
    "prompt_assembly.py",
    "token_estimator.py",
]


def make_item(
    content: str,
    category: ContextCategory,
    ref: str = "s",
    *,
    required: bool = False,
    cacheability: ContextCacheability = ContextCacheability.TASK_DYNAMIC,
) -> ContextItem:
    return ContextItem(
        content=content,
        category=category,
        source=ContextSource(category.value, ref),
        required=required,
        required_for=("task_objective",) if required else (),
        cacheability=cacheability,
        provenance=ContextProvenance(
            acquired_from=category.value, source_ref=ref, provider="test"
        ),
    )


# --- Test 10: deterministic message structure ------------------------------


def test_messages_are_provider_neutral_role_content_pairs():
    items = [make_item("body", ContextCategory.TASK, required=True)]
    for message in build_messages(items, task_name="t"):
        assert set(message.keys()) == {"role", "content"}
        assert message["role"] in {"system", "user"}
        assert isinstance(message["content"], str)


def test_identical_inputs_produce_identical_messages():
    items = [
        make_item("a", ContextCategory.TASK, "1"),
        make_item("b", ContextCategory.EVIDENCE, "2"),
    ]
    first = build_messages(items, task_name="task")
    for _ in range(9):
        assert build_messages(items, task_name="task") == first


def test_input_order_does_not_change_output():
    a = make_item("a", ContextCategory.TASK, "1")
    b = make_item("b", ContextCategory.EVIDENCE, "2")
    assert build_messages([a, b], task_name="t") == build_messages([b, a], task_name="t")


def test_section_order_is_system_then_user():
    items = [
        make_item("sys", ContextCategory.SYSTEM, "s", cacheability=ContextCacheability.STABLE_SYSTEM),
        make_item("task", ContextCategory.TASK, "t", required=True),
    ]
    messages = build_messages(items, task_name="named")
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "System Instructions" in messages[0]["content"]
    assert "named" in messages[-1]["content"]


def test_category_ordering_is_fixed():
    items = [
        make_item("evidence text", ContextCategory.EVIDENCE, "e"),
        make_item("system text", ContextCategory.SYSTEM, "s"),
        make_item("task text", ContextCategory.TASK, "t", required=True),
    ]
    user = build_messages(items, task_name="x")[-1]["content"]
    assert user.index("## Task") < user.index("## Evidence")
    assert "## System Instructions" not in user  # system is its own message


def test_empty_selection_yields_empty_user_body():
    messages = build_messages([], task_name="only-name")
    assert len(messages) == 1
    assert messages[0]["content"] == "# Task: only-name"


# --- Test 9: provenance attribution in the prompt -------------------------


def test_prompt_is_attributable():
    item = make_item("secret body", ContextCategory.EVIDENCE, "kb-42")
    user = build_messages([item], task_name="t")[-1]["content"]
    assert "kb-42" in user
    assert item.context_id in user


def test_mandatory_items_are_marked_in_prompt():
    item = make_item("must have", ContextCategory.TASK, "t", required=True)
    user = build_messages([item], task_name="t")[-1]["content"]
    assert "requirement: mandatory" in user


# --- Test 11: cacheability metadata ---------------------------------------


def test_stable_prefix_items_identified_without_provider_claims():
    stable = make_item(
        "system rules", ContextCategory.SYSTEM, "s",
        cacheability=ContextCacheability.STABLE_SYSTEM,
    )
    dynamic = make_item("task", ContextCategory.TASK, "t", required=True)
    assert [i.context_id for i in stable_prefix_items([stable, dynamic])] == [stable.context_id]


def test_no_provider_cache_directive_is_emitted():
    items = [
        make_item(
            "stable", ContextCategory.SYSTEM, "s",
            cacheability=ContextCacheability.STABLE_SYSTEM,
        )
    ]
    blob = str(build_messages(items, task_name="t"))
    for forbidden in ("cache_control", "cache_prompt", "cached_tokens", "ephemeral"):
        assert forbidden not in blob


# --- Test 12: provider neutrality -----------------------------------------


def test_core_modules_contain_no_provider_specific_identifiers():
    root = Path(__file__).resolve().parents[1] / "src" / "autoforge_execution"
    forbidden = [
        "ollama",
        "openai",
        "anthropic",
        "llama_cpp",
        "llama-server",
        "vllm",
        "together.ai",
        "bedrock",
        "vertex",
    ]
    for name in CORE_MODULES:
        text = (root / name).read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{name} leaks provider-specific token {token!r}"


def test_prompt_assembly_emits_no_provider_imports():
    source = inspect.getsource(__import__(
        "autoforge_execution.prompt_assembly", fromlist=["x"]
    ))
    for token in ("import requests", "import httpx", "openai", "ollama"):
        assert token not in source
