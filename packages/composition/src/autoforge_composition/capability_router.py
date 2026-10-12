"""
DEF-18LE-A: Canonical capability routing for the Commercial Power Engines.

Why this module exists
----------------------
18-LD proved (by AST import analysis and by driving the real composed system)
that the canonical O-2 path could not reach ANY of the five Commercial Power
Engines: ``external_importing_packages`` was ``{}`` for both engine packages and
every loop executed through the generic ``ExecutionEngine``.

18-LD also proved the two facts that make a *small* repair possible:

1. ``Request.configuration`` already survives into ``ProjectState.configuration``
   and already reaches ``execute_loop`` (the ``language``/``framework`` keys do).
   So capability identity needs **no new abstraction**.
2. Four of the five engines already share one uniform contract --
   ``PowerEngine.execute_lifecycle(spec) -> PowerEngineResult`` -- and
   ``execute_loop`` already returns the dict ``handle_loop_completion`` consumes.
   So the *invocation* and *return* edges already exist.

Only two edges were genuinely missing: **identify** and **route**. This module
supplies exactly those, and nothing else.

Contract
--------
``capability`` is read from the SAME channel the rest of the configuration uses
(``Request.configuration``), so it is durable, inspectable and deterministic::

    Request.configuration["capability"] =
        "rag_knowledge" | "custom_ai_agent" | "ai_automation"
        | "code_migration" | "legacy_modernization"

Resolution order (first match wins), all deterministic -- no model is consulted:

    loop["input_data"]["capability"]       (set by the Workflow Engine adapter)
 → Request.configuration["capability"]     (durable project configuration)

If no capability is present the caller MUST fall through to the generic
``ExecutionEngine``; that behaviour is unchanged and is covered by tests.

Engine contracts are ADAPTED HERE, never modified. Legacy Modernization is
adapted from its synchronous, reconnaissance-driven ``ModernizationPipeline.run``
to the same awaitable shape, via a thread so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("autoforge.composition.capability_router")

__all__ = [
    "CAPABILITY_RAG",
    "CAPABILITY_AGENT",
    "CAPABILITY_AUTOMATION",
    "CAPABILITY_MIGRATION",
    "CAPABILITY_MODERNIZATION",
    "CANONICAL_CAPABILITIES",
    "normalize_capability",
    "read_capability",
    "CommercialCapabilityRouter",
    "RoutedExecution",
    "UnknownCapabilityError",
    "build_default_router",
]

# ── Canonical capability identifiers ─────────────────────────────────────────
# Names are repository-native: they match the 18-LR/18-LD evidence keys and the
# engine package/class names, so no new vocabulary is invented.

CAPABILITY_RAG = "rag_knowledge"
CAPABILITY_AGENT = "custom_ai_agent"
CAPABILITY_AUTOMATION = "ai_automation"
CAPABILITY_MIGRATION = "code_migration"
CAPABILITY_MODERNIZATION = "legacy_modernization"

CANONICAL_CAPABILITIES = (
    CAPABILITY_RAG,
    CAPABILITY_AGENT,
    CAPABILITY_AUTOMATION,
    CAPABILITY_MIGRATION,
    CAPABILITY_MODERNIZATION,
)

#: Accepted aliases. The gate brief names the offerings in prose
#: ("RAG", "AGENT", "AUTOMATION", "MIGRATION", "MODERNIZATION"); these map that
#: vocabulary onto the canonical values so a requester is never blocked on naming.
_ALIASES = {
    "rag": CAPABILITY_RAG,
    "rag_pipeline": CAPABILITY_RAG,
    "knowledge": CAPABILITY_RAG,
    "agent": CAPABILITY_AGENT,
    "ai_agent": CAPABILITY_AGENT,
    "custom_agent": CAPABILITY_AGENT,
    "automation": CAPABILITY_AUTOMATION,
    "ai_automation_pipeline": CAPABILITY_AUTOMATION,
    "migration": CAPABILITY_MIGRATION,
    "code_migration_refactoring": CAPABILITY_MIGRATION,
    "modernization": CAPABILITY_MODERNIZATION,
    "legacy_modernization_pipeline": CAPABILITY_MODERNIZATION,
}


def normalize_capability(value: Any) -> Optional[str]:
    """Return the canonical capability identifier, or ``None``.

    Unknown values return ``None`` so the caller can fail closed explicitly
    rather than silently falling back to the generic engine (which would
    recreate BLOCKER A invisibly).
    """
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    if text in CANONICAL_CAPABILITIES:
        return text
    return _ALIASES.get(text)


def read_capability(
    loop_input: Optional[Dict[str, Any]],
    project_configuration: Optional[Dict[str, Any]],
) -> "tuple[Optional[str], Optional[str]]":
    """Resolve the capability identity.

    Returns ``(capability, source)``. ``source`` is ``"loop_input"``,
    ``"project_configuration"`` or ``None`` -- it exists so the decision is
    inspectable in evidence, which DECISION A requires.
    """
    if isinstance(loop_input, dict):
        loop = loop_input.get("loop")
        if isinstance(loop, dict):
            data = loop.get("input_data")
            if isinstance(data, dict):
                cap = normalize_capability(data.get("capability"))
                if cap:
                    return cap, "loop_input"
    if isinstance(project_configuration, dict):
        nested = project_configuration.get("configuration")
        for source in (nested, project_configuration):
            if isinstance(source, dict):
                cap = normalize_capability(source.get("capability"))
                if cap:
                    return cap, "project_configuration"
    return None, None


class UnknownCapabilityError(LookupError):
    """Raised when a capability is declared that no engine provides.

    Fail-closed by design: silently falling back to the generic engine would
    recreate BLOCKER A without any signal.
    """


def _base_spec_kwargs(
    project_id: str,
    request_text: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Common ``CustomerProjectSpecification`` fields for any of its subclasses.

    Every Commercial Power Engine's specification derives from
    ``CustomerProjectSpecification`` (``specification.py``), so one builder
    serves all of them and the engines themselves stay unmodified.
    """
    custom = dict(config.get("custom_parameters") or {})
    custom.setdefault("project_id", project_id)
    if request_text:
        custom.setdefault("request_text", request_text)

    return {
        "project_name": str(config.get("project_name") or project_id)[:80],
        "project_description": (
            str(request_text or "") or "AutoForge commercial delivery"
        ),
        "desired_assistant_behavior": str(
            config.get("assistant_behavior")
            or config.get("desired_assistant_behavior")
            or "Accurate, source-grounded answers with precise citations."
        ),
        "output_root": config.get("output_root"),
        "model_preference": config.get("model_preference"),
        "require_ui": bool(config.get("require_ui", False)),
        "require_api": bool(config.get("require_api", True)),
        "require_auth": bool(config.get("require_auth", False)),
        "knowledge_sources": list(config.get("knowledge_sources") or []),
        "custom_parameters": custom,
    }


class RoutedExecution:
    """The result of a routed commercial execution.

    Normalises both engine shapes into ONE payload so the O-2 loop-completion
    path sees a single contract. ``verification_scorecard`` is carried verbatim
    from the engine: DECISION B layer 2 requires the engine's OWN deterministic
    verification to reach canonical validation/review/completion, not to be
    replaced by a second authority.
    """

    __slots__ = (
        "capability", "engine_class", "success", "status",
        "delivery_dir", "stages_executed", "repair_count",
        "verification_scorecard", "summary_report", "error_message",
    )

    def __init__(
        self,
        capability: str,
        engine_class: str,
        success: bool,
        status: str,
        delivery_dir: Optional[str] = None,
        stages_executed: Optional[List[str]] = None,
        repair_count: int = 0,
        verification_scorecard: Optional[Dict[str, Any]] = None,
        summary_report: str = "",
        error_message: Optional[str] = None,
    ) -> None:
        self.capability = capability
        self.engine_class = engine_class
        self.success = success
        self.status = status
        self.delivery_dir = delivery_dir
        self.stages_executed = list(stages_executed or [])
        self.repair_count = repair_count
        self.verification_scorecard = dict(verification_scorecard or {})
        self.summary_report = summary_report
        self.error_message = error_message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "engine_class": self.engine_class,
            "success": self.success,
            "status": self.status,
            "delivery_dir": self.delivery_dir,
            "stages_executed": self.stages_executed,
            "repair_count": self.repair_count,
            "verification_scorecard": self.verification_scorecard,
            "summary_report": self.summary_report,
            "error_message": self.error_message,
        }


class CommercialCapabilityRouter:
    """Maps a canonical capability identifier to its existing engine.

    This is the *only* new architectural object in the repair, and it lives in
    the composition package, which already owns all wiring (ADR-002 compliant).
    Engines are constructed lazily and injected, so importing this module does
    not by itself make the engines canonical dependencies.
    """

    def __init__(
        self,
        *,
        engine_factories: Optional[Dict[str, Callable[[], Any]]] = None,
        modernization_runner: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._engine_factories: Dict[str, Callable[[], Any]] = dict(
            engine_factories or {}
        )
        self._modernization_runner = modernization_runner
        self._instances: Dict[str, Any] = {}

    # ── registration ────────────────────────────────────────────────────────

    def register(self, capability: str, factory: Callable[[], Any]) -> None:
        canonical = normalize_capability(capability)
        if not canonical:
            raise UnknownCapabilityError(f"Unknown capability: {capability!r}")
        self._engine_factories[canonical] = factory

    def register_modernization(self, runner: Callable[..., Any]) -> None:
        """Register the Legacy Modernization entry point.

        It is a *callable taking a reconnaissance output* rather than a
        ``PowerEngine`` subclass, because it genuinely has a different contract.
        Adapting it here is what avoids modifying the engine.
        """
        self._modernization_runner = runner

    @property
    def capabilities(self) -> List[str]:
        return sorted(self._engine_factories)

    def supports(self, capability: Optional[str]) -> bool:
        canonical = normalize_capability(capability) if capability else None
        if canonical == CAPABILITY_MODERNIZATION:
            return self._modernization_runner is not None
        return bool(canonical) and canonical in self._engine_factories

    # ── invocation ───────────────────────────────────────────────────────────

    async def invoke(
        self,
        capability: str,
        *,
        project_id: str,
        request_text: str,
        project_configuration: Optional[Dict[str, Any]] = None,
        auto_approve_safe_risks: bool = True,
    ) -> RoutedExecution:
        """Invoke the engine that owns ``capability`` through its own contract."""
        canonical = normalize_capability(capability)
        if not canonical:
            raise UnknownCapabilityError(f"Unknown capability: {capability!r}")

        configuration = dict(project_configuration or {})

        if canonical == CAPABILITY_MODERNIZATION:
            return await self._invoke_modernization(
                canonical, project_id=project_id, request_text=request_text,
                project_configuration=configuration,
            )

        factory = self._engine_factories.get(canonical)
        if factory is None:
            raise UnknownCapabilityError(
                f"No Commercial Power Engine is registered for {canonical!r}. "
                f"Registered: {self.capabilities or 'none'}"
            )

        engine = self._instances.get(canonical)
        if engine is None:
            engine = factory()
            self._instances[canonical] = engine

        spec = self._build_specification(
            canonical, project_id=project_id, request_text=request_text,
            project_configuration=configuration,
        )
        result = await engine.execute_lifecycle(
            spec, auto_approve_safe_risks=auto_approve_safe_risks
        )
        return self._from_power_engine_result(canonical, engine, result)

    @staticmethod
    def _from_power_engine_result(
        capability: str, engine: Any, result: Any
    ) -> RoutedExecution:
        """Normalise a ``PowerEngineResult`` (engines 1-4)."""
        stages = list(getattr(result, "stages_executed", []) or [])
        waiting = any("WAITING_FOR_HUMAN_APPROVAL" in str(s) for s in stages)
        success = bool(getattr(result, "success", False))
        return RoutedExecution(
            capability=capability,
            engine_class=type(engine).__name__,
            success=success and not waiting,
            # Map onto the O-2 vocabulary consumed by handle_loop_completion.
            status=("escalate" if waiting else ("complete" if success else "remediate")),
            delivery_dir=getattr(result, "delivery_dir", None),
            stages_executed=stages,
            repair_count=int(getattr(result, "repair_count", 0) or 0),
            # DECISION B layer 2: the engine's own deterministic evidence travels
            # to canonical validation/review/completion.
            verification_scorecard=dict(
                getattr(result, "verification_scorecard", {}) or {}
            ),
            summary_report=str(getattr(result, "summary_report", "") or ""),
            error_message=getattr(result, "error_message", None),
        )

    # ── specification construction (boundary adaptation only) ───────────────

    #: Capability -> specification builder. Engines that accept the base
    #: ``CustomerProjectSpecification`` (RAG, Agent) use the default builder.
    _SPEC_BUILDERS: Dict[str, Callable[..., Any]] = {}

    @staticmethod
    def _build_specification(
        capability: str,
        *,
        project_id: str,
        request_text: str,
        project_configuration: Dict[str, Any],
    ) -> Any:
        """Build the engine's own specification object.

        Pure boundary adaptation. Four of the five engines accept the base
        ``CustomerProjectSpecification``; the Automation and Migration engines
        require their own typed subclasses and deliberately REJECT a base spec
        (their ``_resolve_spec`` raises on a type mismatch). Building the typed
        spec here is what lets those engines be routed WITHOUT modifying them.

        Values come from the requester-declared configuration; nothing is
        invented and the request text is never rewritten.
        """
        builder = CommercialCapabilityRouter._SPEC_BUILDERS.get(
            capability, CommercialCapabilityRouter._build_base_spec
        )
        return builder(project_id, request_text, project_configuration)

    @staticmethod
    def _build_base_spec(
        project_id: str, request_text: str, config: Dict[str, Any]
    ) -> Any:
        """The base ``CustomerProjectSpecification`` (RAG; Agent also accepts it)."""
        from autoforge_power_engines.specification import CustomerProjectSpecification
        return CustomerProjectSpecification(
            **_base_spec_kwargs(project_id, request_text, config)
        )

    @staticmethod
    def _build_automation_spec(
        project_id: str, request_text: str, config: Dict[str, Any]
    ) -> Any:
        """``CustomerAutomationSpecification`` — requires a non-empty step graph."""
        from autoforge_power_engines.automation.spec import (
            CustomerAutomationSpecification,
            StepSpec,
            StepType,
        )
        steps = config.get("automation_steps")
        if not steps:
            # A minimal, well-formed single-step workflow. This mirrors the
            # engine's own documented minimum (INTAKE requires >=1 step and a
            # valid workflow_id) and is deterministic; a requester may supply a
            # richer graph through ``automation_steps`` instead.
            steps = [
                {
                    "step_id": "process",
                    "name": "Process input",
                    "step_type": StepType.ACTION.value,
                    "action": {
                        "action_type": "safe_calculator",
                        "name": "safe_calculator",
                        "description": "Default registered safe action.",
                        "parameters": {"expression": "1+1"},
                    },
                }
            ]
        kwargs = _base_spec_kwargs(project_id, request_text, config)
        return CustomerAutomationSpecification(
            **kwargs,
            workflow_id=str(config.get("workflow_id") or "business_process_v1"),
            initial_step_id=str(steps[0].get("step_id") or "process"),
            steps=[StepSpec(**s) for s in steps],
        )

    @staticmethod
    def _build_migration_spec(
        project_id: str, request_text: str, config: Dict[str, Any]
    ) -> Any:
        """``CustomerMigrationSpecification`` — needs real source + target."""
        from autoforge_power_engines.migration.spec import CustomerMigrationSpecification
        kwargs = _base_spec_kwargs(project_id, request_text, config)
        return CustomerMigrationSpecification(
            **kwargs,
            migration_id=str(config.get("migration_id") or f"mig-{project_id}"),
            source_path=(
                config.get("migration_source_path")
                or config.get("legacy_source_root")
                or config.get("source_root")
            ),
            source_languages=list(
                config.get("source_languages") or ["python"]
            ),
            target_language=str(config.get("target_language") or "python"),
            migration_objective=str(
                config.get("migration_objective")
                or request_text
                or "Modernize the customer codebase",
            ),
        )

    # ── Legacy Modernization adaptation ─────────────────────────────────────

    async def _invoke_modernization(
        self,
        capability: str,
        *,
        project_id: str,
        request_text: str,
        project_configuration: Dict[str, Any],
    ) -> RoutedExecution:
        """Invoke the certified ``ModernizationPipeline`` through its own contract.

        18-LR proved this engine is REAL and certified (G.3) and that its defect
        was in the pipeline that *feeds* it. Three obligations are honoured:

        * **Real reconnaissance.** The adapter never synthesises a placeholder --
          that would reintroduce B-2 through a new door. If no real source root
          is declared, this fails explicitly.
        * **No event-loop blocking.** ``run`` is synchronous, so it runs in a thread.
        * **Normalised result.** Its ``PipelineResult`` maps onto ``RoutedExecution``.
        """
        if self._modernization_runner is None:
            raise UnknownCapabilityError(
                "No Legacy Modernization runner is registered."
            )

        source_root = (
            project_configuration.get("legacy_source_root")
            or project_configuration.get("source_root")
        )
        if not source_root:
            raise ValueError(
                "legacy_modernization requires a real legacy source root "
                "('legacy_source_root'); refusing to synthesise a placeholder."
            )

        from autoforge_modernization.reconnaissance.engine import run_reconnaissance

        reconnaissance = run_reconnaissance(str(source_root))
        result = await asyncio.to_thread(
            self._modernization_runner,
            project_id=project_id,
            job_id=f"{capability}-{project_id}",
            reconnaissance_output=reconnaissance,
            project_configuration=project_configuration,
        )
        return self._from_pipeline_result(capability, result)

    @staticmethod
    def _from_pipeline_result(capability: str, result: Any) -> RoutedExecution:
        """Normalise a ``PipelineResult`` (engine 5) onto ``RoutedExecution``."""
        raw_status = getattr(result, "status", "")
        status_value = str(getattr(raw_status, "value", raw_status) or "")
        records = list(getattr(result, "transformation_records", []) or [])
        waves = list(getattr(result, "wave_results", []) or [])
        transformed = sum(int(getattr(w, "units_transformed", 0) or 0) for w in waves)
        failed_units = sum(int(getattr(w, "units_failed", 0) or 0) for w in waves)
        error = getattr(result, "error_message", None)
        complete = status_value == "complete"

        if status_value == "blocked":
            loop_status = "escalate"
        elif complete and not error:
            loop_status = "complete"
        else:
            loop_status = "remediate"

        # DECISION B layer 2 for engine 5: the engine's own deterministic
        # evidence is its transformation/gate record, carried verbatim.
        scorecard = {
            "pipeline_status": status_value,
            "transformation_records": len(records),
            "units_transformed": transformed,
            "units_failed": failed_units,
            "wave_count": len(waves),
            "analysis_present": getattr(result, "analysis_report", None) is not None,
            "gate_decisions": len(getattr(result, "gate_decisions", []) or []),
            "real_source": True,
        }
        if hasattr(result, "verification_scorecard") and result.verification_scorecard:
            scorecard.update(result.verification_scorecard)

        delivery_dir = getattr(result, "delivery_dir", None)
        repair_count = int(getattr(result, "repair_count", 0))
        stages_executed = list(getattr(result, "stages_executed", [f"modernization:{status_value}"]))
        summary = getattr(result, "summary_report", f"Modernized {transformed} unit(s) from real legacy source.")

        return RoutedExecution(
            capability=capability,
            engine_class="ModernizationPipeline",
            success=complete and not error and failed_units == 0,
            status=loop_status,
            delivery_dir=delivery_dir,
            stages_executed=stages_executed,
            repair_count=repair_count,
            verification_scorecard=scorecard,
            summary_report=summary,
            error_message=error,
        )


def build_default_router(
    *,
    event_publisher: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> CommercialCapabilityRouter:
    """Construct the router bound to all five real Commercial Power Engines.

    This is the ONLY place the canonical O-2 path becomes dependent on
    ``autoforge_power_engines`` and ``autoforge_modernization`` -- the edge
    18-LD proved was absent (``external_importing_packages == {}``). It lives in
    the composition package because the composition root owns all wiring
    (ADR-002).

    Engine imports are deferred inside the factories, so merely importing the
    composition package does not eagerly pull in the engine packages.
    """

    def _sink() -> Any | None:
        return event_publisher

    def _rag() -> Any:
        from autoforge_power_engines.rag.engine import RAGKnowledgePowerEngine
        return RAGKnowledgePowerEngine(event_sink=_sink())

    def _agent() -> Any:
        from autoforge_power_engines.agent.engine import CustomAIAgentPowerEngine
        return CustomAIAgentPowerEngine(event_sink=_sink())

    def _automation() -> Any:
        from autoforge_power_engines.automation.engine import AIAutomationPowerEngine
        return AIAutomationPowerEngine(event_sink=_sink())

    def _migration() -> Any:
        from autoforge_power_engines.migration.engine import CodeMigrationPowerEngine
        return CodeMigrationPowerEngine(event_sink=_sink())

    def _modernization(**kwargs: Any) -> Any:
        # The certified engine keeps its own constructor and ``run`` signature;
        # the router supplies only what ``run`` requires.
        from autoforge_modernization.pipeline import ModernizationPipeline
        return ModernizationPipeline().run(**kwargs)

    router = CommercialCapabilityRouter()
    # The Automation and Migration engines reject a base specification by design
    # (their ``_resolve_spec`` raises on a type mismatch), so their typed specs
    # are built at the routing boundary. The engines are NOT modified.
    CommercialCapabilityRouter._SPEC_BUILDERS.update({
        CAPABILITY_AUTOMATION: CommercialCapabilityRouter._build_automation_spec,
        CAPABILITY_MIGRATION: CommercialCapabilityRouter._build_migration_spec,
    })
    router.register(CAPABILITY_RAG, _rag)
    router.register(CAPABILITY_AGENT, _agent)
    router.register(CAPABILITY_AUTOMATION, _automation)
    router.register(CAPABILITY_MIGRATION, _migration)
    router.register_modernization(_modernization)
    return router
