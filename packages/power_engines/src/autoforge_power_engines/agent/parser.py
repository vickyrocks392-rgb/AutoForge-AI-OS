"""Robust Tool-Call Parsing and Argument Extraction (Phase 18-COMMERCIAL-B).

Extracts and normalizes tool requests from model outputs across multiple formats:
native tool_calls list, markdown code blocks, inline JSON, and conversational fallback.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class ParsedToolCall(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    raw_input: Optional[str] = None
    call_id: Optional[str] = None
    parse_error: Optional[str] = None

    def is_valid(self) -> bool:
        return bool(self.tool_name and self.parse_error is None)


class ParseResult(BaseModel):
    is_tool_call: bool
    tool_calls: List[ParsedToolCall] = Field(default_factory=list)
    assistant_content: str = ""
    had_malformed_syntax: bool = False


class RobustToolCallParser:
    """Parses tool calls from raw model responses resiliently."""

    @classmethod
    def parse(cls, response_payload: Dict[str, Any]) -> ParseResult:
        """
        Parses an LLM response dict into structured tool calls or conversational content.
        Supports both OpenAI-style and Ollama-style outputs.
        """
        # 1. Check for native tool_calls structure
        msg = response_payload.get("message", response_payload)
        native_calls = msg.get("tool_calls") or response_payload.get("tool_calls")
        content = msg.get("content", "") or ""

        if native_calls and isinstance(native_calls, list):
            calls: List[ParsedToolCall] = []
            for item in native_calls:
                fn = item.get("function", item)
                name = fn.get("name", "")
                args_raw = fn.get("arguments", {})
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except Exception as e:
                        args, err = cls._lenient_json_parse(args_raw)
                        if err:
                            calls.append(ParsedToolCall(tool_name=name, arguments={}, raw_input=args_raw, parse_error=err))
                            continue
                else:
                    args = args_raw or {}
                calls.append(ParsedToolCall(tool_name=name, arguments=args, call_id=item.get("id")))

            if calls:
                has_malformed = any(not c.is_valid() for c in calls)
                return ParseResult(
                    is_tool_call=True,
                    tool_calls=calls,
                    assistant_content=content,
                    had_malformed_syntax=has_malformed,
                )

        # 2. If no native tool_calls, inspect content for JSON or markdown blocks
        stripped_content = content.strip()
        if not stripped_content:
            return ParseResult(is_tool_call=False, assistant_content="")

        # Attempt to extract markdown json blocks
        block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped_content)
        json_candidate = block_match.group(1).strip() if block_match else stripped_content

        # Check if content contains JSON blocks
        if "{" in json_candidate or "[" in json_candidate:
            parsed_data, err = cls._lenient_json_parse(json_candidate)
            if parsed_data is not None:
                extracted = cls._extract_calls_from_json(parsed_data, json_candidate)
                if extracted:
                    return ParseResult(
                        is_tool_call=True,
                        tool_calls=extracted,
                        assistant_content=content,
                        had_malformed_syntax=False,
                    )

            # Multi-object / NDJSON extraction (multiple JSON objects in single output)
            multi_calls: List[ParsedToolCall] = []
            matches = re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", json_candidate)
            for m in matches:
                sub_str = m.group(0).strip()
                p_data, _ = cls._lenient_json_parse(sub_str)
                if p_data is not None:
                    ext = cls._extract_calls_from_json(p_data, sub_str)
                    multi_calls.extend(ext)
            if multi_calls:
                return ParseResult(
                    is_tool_call=True,
                    tool_calls=multi_calls,
                    assistant_content=content,
                    had_malformed_syntax=False,
                )

            if err and ("name" in json_candidate or "tool" in json_candidate):
                # Likely an intended tool call with syntax error
                return ParseResult(
                    is_tool_call=True,
                    tool_calls=[ParsedToolCall(tool_name="unknown", arguments={}, raw_input=json_candidate, parse_error=err)],
                    assistant_content=content,
                    had_malformed_syntax=True,
                )

        # 3. Not a tool call -> Regular conversational response
        return ParseResult(is_tool_call=False, assistant_content=content)

    @classmethod
    def _extract_calls_from_json(cls, data: Any, raw_str: str) -> List[ParsedToolCall]:
        calls: List[ParsedToolCall] = []
        if isinstance(data, dict):
            # Formats:
            # 1. {"name": "calculator", "arguments": {...}}
            # 2. {"tool": "calculator", "args": {...}}
            # 3. {"tool_name": "...", "parameters": {...}}
            name = data.get("name") or data.get("tool") or data.get("tool_name")
            if name and isinstance(name, str):
                args = data.get("arguments") or data.get("args") or data.get("parameters") or {}
                if isinstance(args, str):
                    parsed_sub, _ = cls._lenient_json_parse(args)
                    args = parsed_sub if isinstance(parsed_sub, dict) else {}
                calls.append(ParsedToolCall(tool_name=name, arguments=args, raw_input=raw_str))
            elif "tool_calls" in data and isinstance(data["tool_calls"], list):
                for sub in data["tool_calls"]:
                    calls.extend(cls._extract_calls_from_json(sub, raw_str))
        elif isinstance(data, list):
            for item in data:
                calls.extend(cls._extract_calls_from_json(item, raw_str))
        return calls

    @classmethod
    def _lenient_json_parse(cls, s: str) -> Tuple[Optional[Any], Optional[str]]:
        """Lenient JSON parsing attempting simple repairs."""
        cleaned = s.strip()
        try:
            return json.loads(cleaned), None
        except Exception:
            pass

        # Attempt 1: replace single quotes with double quotes
        try:
            repaired = re.sub(r"'([^']*)'", r'"\1"', cleaned)
            return json.loads(repaired), None
        except Exception:
            pass

        # Attempt 2: close missing closing brackets
        if cleaned.startswith("{") and not cleaned.endswith("}"):
            try:
                return json.loads(cleaned + "}"), None
            except Exception:
                pass
        if cleaned.startswith("[") and not cleaned.endswith("]"):
            try:
                return json.loads(cleaned + "]"), None
            except Exception:
                pass

        return None, "Malformed JSON syntax could not be parsed."
