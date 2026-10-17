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
from autoforge_power_engines.agent.memory import AgentMemoryStore, ConversationMessage, validate_session_id
from autoforge_power_engines.agent.state_machine import AgentStateMachine, AgentExecutionState, AgentTelemetry
from autoforge_power_engines.agent.parser import RobustToolCallParser, ParseResult, ParsedToolCall
from autoforge_power_engines.agent.verifier import AgentVerifier, VerificationResult

logger = logging.getLogger("autoforge.power_engines.agent.runtime")


# ── Cancellation Token ────────────────────────────────────────────────────────

class CancellationToken:
    """Thread-safe cooperative cancellation token for agent executions."""

    def __init__(self) -> None:
        import threading
        self._event = threading.Event()
        self._reason: Optional[str] = None

    def cancel(self, reason: str = "Execution cancelled by caller") -> None:
        self._reason = reason
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> Optional[str]:
        return self._reason


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
        timeout: Optional[float] = None,
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
        timeout: Optional[float] = None,
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
        timeout: Optional[float] = None,
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

        eff_timeout = timeout if timeout is not None else self.timeout
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=eff_timeout)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return {"message": choices[0].get("message", {})}
            return {"message": {}}
        except requests.exceptions.Timeout as te:
            raise TimeoutError(f"Model generation timed out after {eff_timeout:.2f}s") from te


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
        # Validate execution limits policy strictly
        lim = spec.execution_limits
        if lim.max_iterations < 1 or lim.max_iterations > 50:
            raise ValueError(f"Invalid max_iterations ({lim.max_iterations}): must be between 1 and 50.")
        if lim.total_timeout_seconds <= 0.0 or lim.total_timeout_seconds > 600.0:
            raise ValueError(f"Invalid total_timeout_seconds ({lim.total_timeout_seconds}): must be between 0.1 and 600.0.")
        if lim.max_tool_calls_per_turn < 1 or lim.max_tool_calls_per_turn > 30:
            raise ValueError(f"Invalid max_tool_calls_per_turn ({lim.max_tool_calls_per_turn}): must be between 1 and 30.")

        self._active_cancellation_token: Optional[CancellationToken] = None

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

    def cancel(self, reason: str = "Execution cancelled by caller") -> None:
        """Cooperatively requests cancellation of any active execution."""
        if self._active_cancellation_token:
            self._active_cancellation_token.cancel(reason=reason)

    def assemble_context(self, session_id: str, current_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Assembles bounded context: system instruction, persistent memory,
        sliding turn history, and user input. (B8)

        SECURITY (SHC-01): every untrusted block is routed through the platform
        ``TrustBoundary`` so source/trust metadata is preserved and
        instruction-shaped content inside customer text, retrieved documents, and
        tool output is neutralized before the model sees it. The system prompt
        remains the only INSTRUCTION segment.
        """
        session_id = validate_session_id(session_id)
        messages: List[Dict[str, Any]] = []
        boundary = self.trust_boundary

        # Validate persistent state integrity and sanitize incomplete tool calls before assembling context
        if self.spec.memory_policy.enabled:
            self.memory.validate_state_integrity(session_id=session_id)
            self.memory.sanitize_incomplete_tool_calls(session_id=session_id)

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
        history: List[ConversationMessage] = []
        if self.spec.memory_policy.enabled:
            history = self.memory.get_messages(session_id, limit=self.spec.memory_policy.max_history_turns)
            for msg in history:
                seg = boundary.segment(
                    msg.content,
                    source=f"history:{msg.role}",
                    trust_level=(
                        TrustLevel.MODEL_OUTPUT
                        if msg.role == "assistant"
                        else (TrustLevel.EXTERNAL_TOOL_OUTPUT if msg.role == "tool" else TrustLevel.CUSTOMER_INSTRUCTION)
                    ),
                )
                turn_dict: Dict[str, Any] = {"role": msg.role, "content": seg.content}
                if msg.name:
                    turn_dict["name"] = msg.name
                if msg.tool_call_id:
                    turn_dict["tool_call_id"] = msg.tool_call_id
                if msg.tool_calls:
                    turn_dict["tool_calls"] = msg.tool_calls
                messages.append(turn_dict)

        # 3. Current user input — append only if provided and not already present at the end of history
        if current_query:
            already_recorded = bool(
                self.spec.memory_policy.enabled
                and history
                and history[-1].role == "user"
                and history[-1].content == current_query
            )
            if not already_recorded:
                user_seg = boundary.segment(
                    current_query,
                    source="customer.user_input",
                    trust_level=TrustLevel.CUSTOMER_INSTRUCTION,
                )
                messages.append({"role": "user", "content": user_seg.content})
        return messages

    def run(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AgentRunResult:
        """
        Executes a single conversational turn through the bounded agent loop.
        """
        token = cancellation_token or self._active_cancellation_token or CancellationToken()
        self._active_cancellation_token = token

        raw_sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
        sess_id = validate_session_id(raw_sid)
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        sm = AgentStateMachine(execution_id=exec_id, session_id=sess_id)

        # Immediate pre-flight cancellation check
        if token.is_cancelled:
            sm.transition_to(AgentExecutionState.CANCELLED, reason=token.reason)
            final_response_text = f"Execution cancelled before start: {token.reason}"
            if self.spec.memory_policy.enabled:
                self.memory.append_message(sess_id, ConversationMessage(role="user", content=user_input, execution_id=exec_id))
                self.memory.append_message(sess_id, ConversationMessage(role="assistant", content=final_response_text, execution_id=exec_id))
                self.memory.record_execution(
                    execution_id=exec_id,
                    session_id=sess_id,
                    status=sm.state.value,
                    iterations=0,
                    tool_calls_count=0,
                    telemetry=sm.telemetry.model_dump(),
                    completed=True,
                )
            return AgentRunResult(
                execution_id=exec_id,
                session_id=sess_id,
                final_response=final_response_text,
                status=sm.state.value,
                iterations=0,
                tool_calls_executed=0,
                repair_count=0,
                telemetry=sm.telemetry,
                tool_traces=[],
            )

        # Record initial execution run and user message in persistent state
        if self.spec.memory_policy.enabled:
            self.memory.record_execution(
                execution_id=exec_id,
                session_id=sess_id,
                status=sm.state.value,
                iterations=0,
                tool_calls_count=0,
                telemetry=sm.telemetry.model_dump(),
                completed=False,
            )
            self.memory.append_message(sess_id, ConversationMessage(role="user", content=user_input, execution_id=exec_id))

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

        # Loop and cycle trackers
        last_assistant_content: Optional[str] = None
        consecutive_identical_responses = 0
        tool_call_history: List[Tuple[str, str]] = []

        try:
            sm.transition_to(AgentExecutionState.THINKING)
            while current_iteration < max_iter:
                # 1. Cancellation check
                if token.is_cancelled:
                    sm.transition_to(AgentExecutionState.CANCELLED, reason=token.reason)
                    final_response_text = f"Execution cancelled: {token.reason}"
                    break

                # 2. Check timeout budget
                elapsed = time.time() - start_time
                remaining_budget = timeout_limit - elapsed
                if remaining_budget <= 0.0:
                    sm.transition_to(AgentExecutionState.TIMEOUT, reason=f"Execution exceeded {timeout_limit}s timeout")
                    final_response_text = f"Execution timed out after {timeout_limit} seconds."
                    break

                current_iteration += 1
                sm.telemetry.iterations = current_iteration

                # ── Model Call ───────────────────────────────────────────────
                sm.telemetry.model_call_count += 1
                model_timeout = min(self.spec.model_config_spec.timeout_seconds, remaining_budget)
                try:
                    try:
                        raw_response = self.model_provider.generate_turn(
                            messages=context_messages,
                            tools=tool_schemas if total_tool_calls < max_tools else None,
                            temperature=self.spec.model_config_spec.temperature,
                            max_tokens=self.spec.model_config_spec.max_tokens,
                            timeout=model_timeout,
                        )
                    except TypeError as te:
                        if "timeout" in str(te):
                            raw_response = self.model_provider.generate_turn(
                                messages=context_messages,
                                tools=tool_schemas if total_tool_calls < max_tools else None,
                                temperature=self.spec.model_config_spec.temperature,
                                max_tokens=self.spec.model_config_spec.max_tokens,
                            )
                        else:
                            raise
                except TimeoutError as te:
                    sm.transition_to(AgentExecutionState.TIMEOUT, reason=str(te))
                    final_response_text = f"Execution timed out during model call: {te}"
                    break

                # Post model-call cancellation check
                if token.is_cancelled:
                    sm.transition_to(AgentExecutionState.CANCELLED, reason=token.reason)
                    final_response_text = f"Execution cancelled: {token.reason}"
                    break

                # ── Tool-Call Parsing (B9) ───────────────────────────────────
                parse_result: ParseResult = RobustToolCallParser.parse(raw_response)

                if not parse_result.is_tool_call:
                    # Check for non-progress loop
                    curr_content = (parse_result.assistant_content or "").strip()
                    if curr_content and curr_content == last_assistant_content:
                        consecutive_identical_responses += 1
                        if consecutive_identical_responses >= 2:
                            sm.transition_to(
                                AgentExecutionState.FAILED,
                                reason="Non-progress loop detected: model produced repeated identical responses"
                            )
                            final_response_text = "Execution failed: model loop detected without progress."
                            break
                    else:
                        consecutive_identical_responses = 0
                        last_assistant_content = curr_content

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

                # Check tool-call cycle detection
                cycle_detected = False
                for tc in parse_result.tool_calls:
                    tc_sig = (tc.tool_name, json.dumps(tc.arguments, sort_keys=True))
                    if tool_call_history.count(tc_sig) >= 3:
                        sm.transition_to(
                            AgentExecutionState.FAILED,
                            reason=f"Tool-call cycle detected: repeated identical call to '{tc.tool_name}'"
                        )
                        final_response_text = f"Execution failed: tool-call cycle detected for tool '{tc.tool_name}'."
                        cycle_detected = True
                        break
                    tool_call_history.append(tc_sig)

                if cycle_detected:
                    break

                # Append model thought to context
                raw_msg = raw_response.get("message", {})
                assistant_msg: Dict[str, Any] = {"role": "assistant", "content": parse_result.assistant_content or ""}
                if raw_msg.get("tool_calls"):
                    assistant_msg["tool_calls"] = raw_msg["tool_calls"]
                context_messages.append(assistant_msg)

                # Persist assistant tool-call request to memory store
                if self.spec.memory_policy.enabled and raw_msg.get("tool_calls"):
                    self.memory.append_message(
                        sess_id,
                        ConversationMessage(
                            role="assistant",
                            content=parse_result.assistant_content or "",
                            tool_calls=raw_msg.get("tool_calls"),
                            execution_id=exec_id,
                        )
                    )

                # ── Process Tool Calls ───────────────────────────────────────
                for tool_call in parse_result.tool_calls:
                    # Cancellation check
                    if token.is_cancelled:
                        sm.transition_to(AgentExecutionState.CANCELLED, reason=token.reason)
                        final_response_text = f"Execution cancelled: {token.reason}"
                        break

                    # Budget checks
                    if total_tool_calls >= max_tools:
                        sm.telemetry.errors.append(f"Max tool calls limit ({max_tools}) reached.")
                        obs_err = {"error": f"Tool budget ({max_tools}) reached. No further tool calls permitted.", "status": "error"}
                        obs_dict = {
                            "role": "tool",
                            "name": tool_call.tool_name,
                            "content": json.dumps(obs_err),
                        }
                        if tool_call.call_id:
                            obs_dict["tool_call_id"] = tool_call.call_id
                        context_messages.append(obs_dict)
                        continue

                    # Deadline check before tool call
                    rem_time = timeout_limit - (time.time() - start_time)
                    if rem_time <= 0.0:
                        sm.transition_to(
                            AgentExecutionState.TIMEOUT,
                            reason=f"Execution deadline ({timeout_limit}s) expired before tool '{tool_call.tool_name}'"
                        )
                        final_response_text = f"Execution timed out before tool '{tool_call.tool_name}'."
                        break

                    sm.transition_to(AgentExecutionState.TOOL_PENDING)

                    # 1. Verify Tool Call (B11)
                    v_call = self.verifier.verify_tool_call(tool_call, repair_attempts=repair_count)
                    if not v_call.passed:
                        if v_call.requires_repair and repair_count < 1:
                            repair_count += 1
                            sm.telemetry.retry_count += 1
                            context_messages.append({"role": "user", "content": v_call.repair_prompt or "Please repair."})
                            sm.transition_to(AgentExecutionState.THINKING)
                            break
                        else:
                            obs_err = {"error": f"Tool call validation failed: {v_call.violation_code}", "details": v_call.details}
                            obs_dict = {
                                "role": "tool",
                                "name": tool_call.tool_name,
                                "content": json.dumps(obs_err),
                            }
                            if tool_call.call_id:
                                obs_dict["tool_call_id"] = tool_call.call_id
                            context_messages.append(obs_dict)
                            continue

                    # 2. Execute Tool (B4) with timeout & retry handling
                    sm.transition_to(AgentExecutionState.EXECUTING_TOOL)
                    tool_cfg = self.tool_registry.get_tool_config(tool_call.tool_name)
                    configured_tool_timeout = tool_cfg.timeout_seconds if tool_cfg else 10.0
                    effective_tool_timeout = min(configured_tool_timeout, rem_time)

                    t0 = time.perf_counter()
                    tool_result = self.tool_registry.execute_tool(
                        tool_call.tool_name,
                        tool_call.arguments,
                        allowed_tools=self.spec.allowed_tools,
                        timeout_seconds=effective_tool_timeout,
                    )
                    duration_ms = (time.perf_counter() - t0) * 1000.0

                    # Blocked authorization
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

                    # Tool Timeout check
                    if isinstance(tool_result, dict) and tool_result.get("status") == "timeout":
                        sm.telemetry.errors.append(tool_result.get("error", "Tool timeout"))
                        if (time.time() - start_time) >= timeout_limit:
                            sm.transition_to(
                                AgentExecutionState.TIMEOUT,
                                reason=f"Execution deadline ({timeout_limit}s) expired during tool '{tool_call.tool_name}'"
                            )
                            final_response_text = f"Execution timed out during tool '{tool_call.tool_name}'."
                            break

                    # Retry policy for retryable errors
                    tool_retries = 0
                    while (
                        isinstance(tool_result, dict)
                        and tool_result.get("status") == "error"
                        and not tool_result.get("blocked_by")
                        and not tool_result.get("side_effect_uncertain")
                        and self.tool_registry.is_tool_idempotent(tool_call.tool_name)
                        and tool_retries < self.spec.retry_policy.max_retries
                    ):
                        backoff = self.spec.retry_policy.backoff_seconds
                        # Check remaining budget allows retry
                        if (time.time() - start_time) + backoff >= timeout_limit:
                            break
                        if token.is_cancelled:
                            break
                        tool_retries += 1
                        sm.telemetry.retry_count += 1
                        if backoff > 0.0:
                            time.sleep(backoff)
                        rem_retry_time = timeout_limit - (time.time() - start_time)
                        if rem_retry_time <= 0.0:
                            break
                        eff_retry_to = min(configured_tool_timeout, rem_retry_time)
                        tool_result = self.tool_registry.execute_tool(
                            tool_call.tool_name,
                            tool_call.arguments,
                            allowed_tools=self.spec.allowed_tools,
                            timeout_seconds=eff_retry_to,
                        )

                    # Post tool-call cancellation check
                    if token.is_cancelled:
                        sm.transition_to(AgentExecutionState.CANCELLED, reason=token.reason)
                        final_response_text = f"Execution cancelled: {token.reason}"
                        break

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
                    obs_dict = {
                        "role": "tool",
                        "name": tool_call.tool_name,
                        "content": obs_content,
                    }
                    if tool_call.call_id:
                        obs_dict["tool_call_id"] = tool_call.call_id
                    context_messages.append(obs_dict)

                    # Persist tool observation to memory store
                    if self.spec.memory_policy.enabled:
                        self.memory.append_message(
                            sess_id,
                            ConversationMessage(
                                role="tool",
                                name=tool_call.tool_name,
                                tool_call_id=tool_call.call_id,
                                content=obs_content,
                                execution_id=exec_id,
                            )
                        )

                if sm.is_terminal():
                    break

                # Loop continues back to THINKING
                sm.transition_to(AgentExecutionState.THINKING)

            if not sm.is_terminal() and current_iteration >= max_iter:
                sm.transition_to(
                    AgentExecutionState.FAILED,
                    reason="Maximum iterations exhausted without terminal response"
                )
                final_response_text = f"Agent stopped: maximum iteration limit ({max_iter}) exhausted."

        except Exception as ex:
            logger.error(f"Runtime execution failure: {ex}", exc_info=True)
            sm.telemetry.errors.append(str(ex))
            if not sm.is_terminal():
                sm.transition_to(AgentExecutionState.FAILED, reason=str(ex))
            final_response_text = f"Execution failed: {ex}"
        finally:
            self._active_cancellation_token = None

        # Record assistant answer in persistent state
        if self.spec.memory_policy.enabled:
            try:
                self.memory.append_message(
                    sess_id,
                    ConversationMessage(role="assistant", content=final_response_text, execution_id=exec_id)
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
            except Exception as storage_ex:
                logger.error(f"Persistence write failure in finalization: {storage_ex}", exc_info=True)
                sm.telemetry.errors.append(f"Persistence error: {storage_ex}")
                if not sm.is_terminal():
                    sm.transition_to(AgentExecutionState.FAILED, reason=f"Storage write error: {storage_ex}")
                raise RuntimeError(f"Storage write error: {storage_ex}") from storage_ex

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
