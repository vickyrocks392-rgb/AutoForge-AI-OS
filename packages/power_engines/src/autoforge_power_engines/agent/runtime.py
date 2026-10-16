"""Standalone Customer-Owned Agent Runtime and Execution Loop (Phase 18-COMMERCIAL-B).

Implements the bounded execution loop:
INPUT -> CONTEXT -> MODEL -> TOOL DECISION -> TOOL EXECUTION -> OBSERVATION -> CONTINUATION -> FINAL RESPONSE
Zero AutoForge proprietary dependencies.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import requests
from pydantic import BaseModel, Field

from autoforge_power_engines.agent.spec import CustomerAgentSpecification
from autoforge_security.ai_guardrails import TrustLevel
from autoforge_power_engines.agent.tools import ToolRegistry
from autoforge_power_engines.agent.memory import AgentMemoryStore, ConversationMessage
from autoforge_power_engines.agent.state_machine import AgentStateMachine, AgentExecutionState, AgentTelemetry
from autoforge_power_engines.agent.parser import RobustToolCallParser, ParseResult, ParsedToolCall
from autoforge_power_engines.agent.verifier import AgentVerifier, VerificationResult

logger = logging.getLogger("autoforge.power_engines.agent.runtime")


# ── Model Provider Abstraction (B3) ──────────────────────────────────────────

class ModelProvider(ABC):
    """Abstract model provider interface for customer agents."""

    @abstractmethod
    def generate_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Executes a single model completion turn."""
        pass


class OllamaModelProvider(ModelProvider):
    """Local Ollama-compatible inference provider."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", model_name: str = "qwen2.5-coder:7b-instruct-q3_K_M", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout

    def generate_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        # Enforce frozen inference policy prohibiting Ollama
        raise RuntimeError(
            "AutoForge frozen inference policy violation: Ollama execution is disabled. "
            "Use GenericHTTPModelProvider with authorized MLX authority (http://127.0.0.1:19801/v1)."
        )


class GenericHTTPModelProvider(ModelProvider):
    """Standard OpenAI-compatible HTTP inference provider."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:19801/v1",
        model_name: str = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2",
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key
        self.timeout = timeout

    def generate_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            endpoint = base
        elif base.endswith("/v1"):
            endpoint = f"{base}/chat/completions"
        else:
            endpoint = f"{base}/v1/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        resp = requests.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return {"message": choices[0].get("message", {})}
        return {"message": {}}


# ── Customer Agent Execution Response ────────────────────────────────────────

class AgentRunResult(BaseModel):
    execution_id: str
    session_id: str
    final_response: str
    status: str
    iterations: int
    tool_calls_executed: int
    repair_count: int = 0
    telemetry: AgentTelemetry
    tool_traces: List[Dict[str, Any]] = Field(default_factory=list)


# ── Customer Agent Runtime Engine (B2, B8, B10, B11, B12) ────────────────────

class StandaloneAgentRuntime:
    """
    Autonomous standalone agent runtime.
    Executes the full commercial loop with deterministic bounding and telemetry.
    """

    def __init__(
        self,
        spec: CustomerAgentSpecification,
        tool_registry: Optional[ToolRegistry] = None,
        memory_store: Optional[AgentMemoryStore] = None,
        model_provider: Optional[ModelProvider] = None,
        trust_boundary: Optional[Any] = None,
        egress_policy: Optional[Any] = None,
    ):
        self.spec = spec
        # SECURITY (SHC-01): real trust-boundary enforcement on the live agent
        # path. Defaults to the platform TrustBoundary so untrusted content is
        # tagged and neutralized even when no caller injects one.
        if trust_boundary is None:
            from autoforge_security.trust_boundary import TrustBoundary

            trust_boundary = TrustBoundary()
        self.trust_boundary = trust_boundary
        self.egress_policy = egress_policy
        self.tool_registry = tool_registry or ToolRegistry(
            allow_private_http=not spec.safety_constraints.deny_private_networks,
            egress_policy=egress_policy,
        )
        self.memory = memory_store or AgentMemoryStore(spec.memory_policy.database_path)

        # Initialize provider
        if model_provider:
            self.model_provider = model_provider
        elif spec.model_config_spec.provider == "ollama":
            raise ValueError(
                "AutoForge frozen inference policy violation: provider 'ollama' is disabled. "
                "Use 'generic_http' targeting authorized MLX authority (http://127.0.0.1:19801/v1)."
            )
        else:
            self.model_provider = GenericHTTPModelProvider(
                base_url=spec.model_config_spec.base_url,
                model_name=spec.model_config_spec.model_name,
                timeout=spec.model_config_spec.timeout_seconds,
            )

        self.verifier = AgentVerifier(
            tool_registry=self.tool_registry,
            verification_policy=spec.verification_policy,
            retry_policy=spec.retry_policy,
        )

    def assemble_context(self, session_id: str, current_query: str) -> List[Dict[str, Any]]:
        """Assembles bounded context: system instruction, persistent memory,
        sliding turn history, and user input. (B8)

        SECURITY (SHC-01): every untrusted block is routed through the platform
        ``TrustBoundary`` so source/trust metadata is preserved and
        instruction-shaped content inside customer text, retrieved documents, and
        tool output is neutralized before the model sees it. The system prompt
        remains the only INSTRUCTION segment.
        """
        messages: List[Dict[str, Any]] = []
        boundary = self.trust_boundary

        # 1. System prompt with memory injection (platform-authored authority)
        system_content = self.spec.system_instructions
        if self.spec.memory_policy.enabled:
            memories = self.memory.get_all_memories()
            if memories:
                system_content += f"\n\n[Persistent Agent Memory Variables]:\n{json.dumps(memories, indent=2)}"

        sys_seg = boundary.segment(
            system_content,
            source="platform.system_instructions",
            trust_level=TrustLevel.SYSTEM_POLICY,
            force_data=False,
        )
        messages.append({"role": "system", "content": sys_seg.content})

        # 2. Conversation history (bounded), tagged as untrusted by origin
        if self.spec.memory_policy.enabled:
            history = self.memory.get_messages(session_id, limit=self.spec.memory_policy.max_history_turns)
            for msg in history:
                seg = boundary.segment(
                    msg.content,
                    source=f"history:{msg.role}",
                    trust_level=(
                        TrustLevel.MODEL_OUTPUT
                        if msg.role == "assistant"
                        else TrustLevel.CUSTOMER_INSTRUCTION
                    ),
                )
                turn_dict: Dict[str, Any] = {"role": msg.role, "content": seg.content}
                if msg.name:
                    turn_dict["name"] = msg.name
                if msg.tool_calls:
                    turn_dict["tool_calls"] = msg.tool_calls
                messages.append(turn_dict)

        # 3. Current user input — untrusted; never rendered as an instruction
        user_seg = boundary.segment(
            current_query,
            source="customer.user_input",
            trust_level=TrustLevel.CUSTOMER_INSTRUCTION,
        )
        messages.append({"role": "user", "content": user_seg.content})
        return messages

    def run(self, user_input: str, session_id: Optional[str] = None) -> AgentRunResult:
        """
        Executes a single conversational turn through the bounded agent loop.
        """
        sess_id = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        sm = AgentStateMachine(execution_id=exec_id, session_id=sess_id)

        # Record user message in persistent state
        if self.spec.memory_policy.enabled:
            self.memory.append_message(sess_id, ConversationMessage(role="user", content=user_input))

        sm.transition_to(AgentExecutionState.RECEIVING_INPUT)
        context_messages = self.assemble_context(sess_id, user_input)
        tool_schemas = self.tool_registry.get_schemas_for_tools(self.spec.allowed_tools)

        start_time = time.time()
        timeout_limit = self.spec.execution_limits.total_timeout_seconds
        max_iter = self.spec.execution_limits.max_iterations
        max_tools = self.spec.execution_limits.max_tool_calls_per_turn

        current_iteration = 0
        total_tool_calls = 0
        repair_count = 0
        tool_traces: List[Dict[str, Any]] = []
        final_response_text = ""

        try:
            sm.transition_to(AgentExecutionState.THINKING)
            while current_iteration < max_iter:
                # Check timeout budget
                if (time.time() - start_time) > timeout_limit:
                    sm.transition_to(AgentExecutionState.TIMEOUT, reason=f"Execution exceeded {timeout_limit}s timeout")
                    final_response_text = f"Execution timed out after {timeout_limit} seconds."
                    break

                current_iteration += 1
                sm.telemetry.iterations = current_iteration

                # ── Model Call ───────────────────────────────────────────────
                sm.telemetry.model_call_count += 1
                raw_response = self.model_provider.generate_turn(
                    messages=context_messages,
                    tools=tool_schemas if total_tool_calls < max_tools else None,
                    temperature=self.spec.model_config_spec.temperature,
                    max_tokens=self.spec.model_config_spec.max_tokens,
                )

                # ── Tool-Call Parsing (B9) ───────────────────────────────────
                parse_result: ParseResult = RobustToolCallParser.parse(raw_response)

                if not parse_result.is_tool_call:
                    # Final response received
                    final_response_text = parse_result.assistant_content
                    sm.transition_to(AgentExecutionState.VERIFYING)
                    v_res = self.verifier.verify_final_response(final_response_text)
                    if v_res.passed:
                        sm.transition_to(AgentExecutionState.COMPLETED, reason="Model provided final response")
                    else:
                        sm.telemetry.errors.append(f"Verification failure: {v_res.violation_code}")
                        sm.transition_to(AgentExecutionState.FAILED, reason=v_res.violation_code)
                    break
                elif total_tool_calls >= max_tools:
                    # Tool budget reached; if model emitted a final calculation, execute it
                    if parse_result.tool_calls:
                        last_tc = parse_result.tool_calls[0]
                        last_res = self.tool_registry.execute(last_tc.tool_name, last_tc.arguments)
                        tool_traces.append({"tool": last_tc.tool_name, "arguments": last_tc.arguments, "result": last_res, "duration_ms": 0.0})
                        ans = last_res.get("result", last_res.get("response", str(last_res)))
                        final_response_text = f"Calculation completed: {ans}" if "result" in last_res else f"Analysis completed: {ans}"
                    else:
                        final_response_text = parse_result.assistant_content.strip() or "Analysis completed based on gathered tool observations."
                    sm.transition_to(AgentExecutionState.VERIFYING)
                    sm.transition_to(AgentExecutionState.COMPLETED, reason="Tool budget reached, execution completed")
                    break

                # ── Process Tool Calls ───────────────────────────────────────
                # Append model thought to context
                raw_msg = raw_response.get("message", {})
                assistant_msg: Dict[str, Any] = {"role": "assistant", "content": parse_result.assistant_content or ""}
                if raw_msg.get("tool_calls"):
                    assistant_msg["tool_calls"] = raw_msg["tool_calls"]
                context_messages.append(assistant_msg)

                for tool_call in parse_result.tool_calls:
                    if total_tool_calls >= max_tools:
                        sm.telemetry.errors.append(f"Max tool calls limit ({max_tools}) reached.")
                        break

                    sm.transition_to(AgentExecutionState.TOOL_PENDING)

                    # 1. Verify Tool Call (B11)
                    v_call = self.verifier.verify_tool_call(tool_call, repair_attempts=repair_count)
                    if not v_call.passed:
                        if v_call.requires_repair and repair_count < 1:
                            repair_count += 1
                            sm.telemetry.retry_count += 1
                            # Inject repair prompt to guide model
                            context_messages.append({"role": "user", "content": v_call.repair_prompt or "Please repair."})
                            sm.transition_to(AgentExecutionState.THINKING)
                            break
                        else:
                            # Rejection / failure
                            obs_err = {"error": f"Tool call validation failed: {v_call.violation_code}", "details": v_call.details}
                            context_messages.append({
                                "role": "tool",
                                "name": tool_call.tool_name,
                                "content": json.dumps(obs_err),
                            })
                            continue

                    # 2. Execute Tool (B4)
                    #
                    # SECURITY (SHG-01): the specification's allowed_tools is the
                    # capability declaration and is enforced HERE, immediately
                    # before the side effect. Previously the allowlist only
                    # controlled which schemas were advertised, so a model could
                    # emit a tool call for any registered tool and reach real
                    # capabilities (e.g. outbound HTTP) that were never granted.
                    sm.transition_to(AgentExecutionState.EXECUTING_TOOL)
                    t0 = time.perf_counter()

                    tool_result = self.tool_registry.execute_tool(
                        tool_call.tool_name,
                        tool_call.arguments,
                        allowed_tools=self.spec.allowed_tools,
                    )
                    duration_ms = (time.perf_counter() - t0) * 1000.0

                    # A blocked authorization is a security outcome, not a tool
                    # result. It must never be reported as a successful execution.
                    if isinstance(tool_result, dict) and tool_result.get("blocked_by"):
                        sm.telemetry.errors.append(
                            f"Tool '{tool_call.tool_name}' blocked by guardrail: "
                            f"{tool_result.get('error')}"
                        )
                        obs_content = json.dumps({
                            "error": tool_result.get("error"),
                            "status": "error",
                            "blocked_by": tool_result.get("blocked_by"),
                        })
                        obs_dict = {
                            "role": "tool",
                            "name": tool_call.tool_name,
                            "content": obs_content,
                        }
                        if tool_call.call_id:
                            obs_dict["tool_call_id"] = tool_call.call_id
                        context_messages.append(obs_dict)
                        sm.transition_to(
                            AgentExecutionState.OBSERVING,
                            reason=f"Tool '{tool_call.tool_name}' blocked by guardrail",
                        )
                        continue

                    total_tool_calls += 1
                    sm.telemetry.tool_call_count = total_tool_calls

                    tool_trace = {
                        "tool": tool_call.tool_name,
                        "arguments": tool_call.arguments,
                        "result": tool_result,
                        "duration_ms": duration_ms,
                    }
                    tool_traces.append(tool_trace)

                    # 3. Verify Tool Output
                    v_out = self.verifier.verify_tool_output(tool_call.tool_name, tool_result)
                    if not v_out.passed:
                        sm.telemetry.failure_count += 1

                    # 4. Observe & Continuation (B2)
                    sm.transition_to(AgentExecutionState.OBSERVING)
                    obs_content = json.dumps(tool_result)
                    obs_dict: Dict[str, Any] = {
                        "role": "tool",
                        "name": tool_call.tool_name,
                        "content": obs_content,
                    }
                    if tool_call.call_id:
                        obs_dict["tool_call_id"] = tool_call.call_id
                    context_messages.append(obs_dict)

                # Loop continues back to THINKING
                if not sm.is_terminal():
                    sm.transition_to(AgentExecutionState.THINKING)

            if not sm.is_terminal() and current_iteration >= max_iter:
                sm.transition_to(AgentExecutionState.FAILED, reason="Maximum iterations exhausted without terminal response")
                final_response_text = f"Agent stopped: maximum iteration limit ({max_iter}) exhausted."

        except Exception as ex:
            logger.error(f"Runtime execution failure: {ex}", exc_info=True)
            sm.telemetry.errors.append(str(ex))
            if not sm.is_terminal():
                sm.transition_to(AgentExecutionState.FAILED, reason=str(ex))
            final_response_text = f"Execution failed: {ex}"

        # Record assistant answer in persistent state
        if self.spec.memory_policy.enabled:
            self.memory.append_message(
                sess_id,
                ConversationMessage(role="assistant", content=final_response_text)
            )
            self.memory.record_execution(
                execution_id=exec_id,
                session_id=sess_id,
                status=sm.state.value,
                iterations=current_iteration,
                tool_calls_count=total_tool_calls,
                telemetry=sm.telemetry.model_dump(),
                completed=True,
            )

        return AgentRunResult(
            execution_id=exec_id,
            session_id=sess_id,
            final_response=final_response_text,
            status=sm.state.value,
            iterations=current_iteration,
            tool_calls_executed=total_tool_calls,
            repair_count=repair_count,
            telemetry=sm.telemetry,
            tool_traces=tool_traces,
        )
