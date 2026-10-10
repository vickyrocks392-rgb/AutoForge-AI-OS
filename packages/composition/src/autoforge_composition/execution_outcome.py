"""B2 -- Canonical ``ExecutionOutcome`` contract (Gate B2).

This module introduces ONE canonical, *representation-only* result contract for
everything that crosses the control-plane / execution-plane boundary. It is
INERT: nothing in the production path imports it yet, and no existing behaviour
is changed by its presence. Its purpose is to make the result vocabulary that
O-2 already consumes explicit, typed, and testable.

Design constraints (Gate B2)
----------------------------
* **Pure.** No I/O, no model or provider call, no artifact write, no state
  transition, no orchestration side effect. Adapters only read their input.
* **Non-mutating.** No input is ever written to; containers are copied.
* **No invention.** A field is populated only where the real source contract
  supplies it. Where the source genuinely does not carry the information, the
  field is left at its documented empty value rather than fabricated.
* **Additive only.** No existing contract is changed, wrapped, or extended.

Dependency direction
--------------------
Placed in ``autoforge_composition`` because that package already owns all
boundary adaptation (see ``capability_router``'s module docstring and ADR-002).
It imports only:

* ``autoforge_execution.models`` -- already a hard dependency of composition
  (``kernel_adapters`` and ``execution_wiring`` both import it), so no new
  dependency edge and no cycle (verified: ``autoforge_execution`` imports
  ``autoforge_composition`` in 0 files).
* ``autoforge_composition.capability_router.RoutedExecution`` -- same package.

``PowerEngineResult`` is deliberately **NOT** imported. ``capability_router``
states that engine imports are deferred inside its factories so that importing
this module does not make the engines canonical dependencies; eagerly importing
``autoforge_power_engines`` here would break that discipline. The engine result
is therefore read structurally with ``getattr``, exactly as
``CommercialCapabilityRouter._from_power_engine_result`` already does.

Exact-incompatibility notes (evidence-backed, not workarounds)
-------------------------------------------------------------
These are places where the real source contract does NOT supply what the
canonical field name suggests. They are recorded so the difference is never
mistaken for a bug in this module.

1. ``loop_result["artifacts"]`` holds ``list[dict]``, not
   ``list[ArtifactRecord]``. Both producers serialise:
   ``kernel_adapters.py:627`` ``a.model_dump(mode="json")`` and
   ``kernel_adapters.py:491-493`` ``record.model_dump(mode="json")``. The
   round-trip ``ArtifactRecord(**dumped)`` is lossless -- verified equal for
   both ``checksum`` and ``provenance`` -- so re-validation is used rather than
   fabrication. An entry that does not validate is REJECTED, never dropped.

2. ``loop_result["evaluation"]`` holds a ``str`` status, not an
   ``EvaluationResult``. Producers write ``eval_res.status.value`` at
   ``kernel_adapters.py:628`` and ``routed.status`` at ``:429``. No
   ``EvaluationResult`` object survives into the loop dictionary. Because
   constructing one would invent evidence, this adapter preserves an
   ``EvaluationResult`` when a caller genuinely supplies one and otherwise
   leaves the field ``None``. No information is lost: in the generic path the
   string is ``eval_res.status``, already carried by ``passed``; in the routed
   path the string is byte-identical to ``status``.
   ``loop_result["evaluation"]`` has ZERO readers in production (verified:
   3 writers, 0 readers).

3. ``PowerEngineResult`` has no ``status`` field. The status is derived in
   ``capability_router._from_power_engine_result`` at ``:349-356``. That
   derivation is replicated EXACTLY rather than re-invented, including
   ``success and not waiting`` for ``passed`` and the findings expression at
   ``kernel_adapters.py:430``, so the result is behaviourally identical to what
   production produces.

4. ``loop_result["engine_class"]`` at ``kernel_adapters.py:410`` is set to
   ``type(self._router).__name__`` -- the ROUTER class name, not the engine
   class name, and only on the engine-exception path. This is pre-existing
   behaviour. It is preserved verbatim and NOT corrected here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Sequence
from pydantic import BaseModel, ConfigDict, Field

from autoforge_execution.models import ArtifactRecord, EvaluationResult

from autoforge_composition.capability_router import RoutedExecution

__all__ = ["OutcomeStatus", "ExecutionOutcome"]


class OutcomeStatus(str, Enum):
    """The four lifecycle decisions O-2 already acts on.

    The values are byte-identical to the string literals compared in
    ``autoforge_kernel.orchestration.DefaultOrchestrationEngine
    .handle_loop_completion`` (:225 ``"complete"``, :236 ``"remediate"``,
    :248 ``"escalate"``, :260 ``"failed"``) and to the literals produced in
    ``kernel_adapters.execute_loop`` (:622, :634, :392, :405) and in
    ``capability_router`` (:356, :532-536). No new vocabulary is introduced.
    """

    COMPLETE = "complete"
    REMEDIATE = "remediate"
    ESCALATE = "escalate"
    FAILED = "failed"


def _coerce_status(raw: Any) -> OutcomeStatus:
    """Map an existing production status value onto ``OutcomeStatus``.

    ``OutcomeStatus`` is a closed enumeration, so an out-of-contract value
    cannot be represented without inventing a meaning. Production would
    silently fall through every branch of ``handle_loop_completion`` in that
    case; this contract rejects it loudly instead, because silently accepting
    an unrepresentable status is how a bad outcome becomes a good one.
    """
    if isinstance(raw, OutcomeStatus):
        return raw
    if isinstance(raw, str):
        try:
            return OutcomeStatus(raw)
        except ValueError:
            pass
    raise ValueError(
        f"Unrepresentable outcome status {raw!r}; expected one of "
        f"{[s.value for s in OutcomeStatus]}."
    )


def _coerce_artifacts(raw: Any) -> list[ArtifactRecord]:
    """Re-validate the serialised artifact entries a loop result carries.

    ``kernel_adapters`` emits ``list[dict]`` (``a.model_dump(mode="json")``).
    Re-validating restores the real model with no invented values. Entries that
    do not validate raise rather than being silently discarded, so no artifact
    can vanish between the execution plane and the control plane.
    """
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise TypeError(f"artifacts must be a sequence, got {type(raw).__name__}")
    out: list[ArtifactRecord] = []
    for index, entry in enumerate(raw):
        if isinstance(entry, ArtifactRecord):
            out.append(entry)
            continue
        if isinstance(entry, Mapping):
            out.append(ArtifactRecord(**dict(entry)))
            continue
        raise TypeError(
            f"artifacts[{index}] must be an ArtifactRecord or a mapping, "
            f"got {type(entry).__name__}"
        )
    return out


def _coerce_findings(raw: Any) -> list[str]:
    """Read the findings list exactly as production produced it.

    Producers write ``eval_res.failures`` (``kernel_adapters.py:629``) or
    ``[routed.error_message or "engine reported failure"]`` (``:430``) -- both
    ``list[str]``. Anything else is rejected rather than coerced.
    """
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise TypeError(
            f"findings must be a sequence of str, got {type(raw).__name__}"
        )
    out: list[str] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, str):
            raise TypeError(f"findings[{index}] must be str, got {type(entry).__name__}")
        out.append(entry)
    return out


def _optional_str(raw: Any) -> str | None:
    """Return ``raw`` when it is a string, else ``None``."""
    return raw if isinstance(raw, str) else None


class ExecutionOutcome(BaseModel):
    """Canonical normalised result of one dispatched unit of work.

    Frozen and ``extra="forbid"``, matching the convention used by every other
    value model in the Execution Platform (``ArtifactRecord``,
    ``ArtifactProvenance``, ``EvaluationResult``).

    Fields are exactly the canonical set agreed in Gate B1. Deliberately absent:
    telemetry, provenance, worker identity, delivery paths, repair counts,
    approval identifiers and summaries -- those remain authoritative in the
    durable artifact / evidence system and must not be duplicated here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: OutcomeStatus = Field(..., description="The lifecycle decision.")
    loop_type: str = Field(..., description="The engineering loop type that ran.")
    passed: bool = Field(..., description="The executor's own verdict.")
    findings: list[str] = Field(
        default_factory=list,
        description="Explicit failure reasons reported by the executor.",
    )
    routed: bool = Field(
        default=False,
        description="True when a Commercial Power Engine served this unit.",
    )
    capability: str | None = Field(
        default=None, description="Canonical capability identifier, if routed."
    )
    engine_class: str | None = Field(
        default=None, description="Engine class name, if routed."
    )
    artifacts: list[ArtifactRecord] = Field(
        default_factory=list, description="Re-validated artifacts produced."
    )
    evaluation: EvaluationResult | None = Field(
        default=None,
        description=(
            "Full deterministic evaluation, only when a real EvaluationResult "
            "was supplied. Loop dictionaries carry a status string instead; "
            "see the module docstring, note 2."
        ),
    )

    # ── Adapter 1: the O-2 loop-result dictionary ──────────────────────

    @classmethod
    def from_loop_result(cls, loop_result: Mapping[str, Any]) -> "ExecutionOutcome":
        """Normalise the dictionary ``handle_loop_completion`` receives today.

        Field-by-field evidence:

        * ``status``      -- read verbatim; producers at ``kernel_adapters.py``
          :622/:634/:392/:405 already emit exactly the four canonical literals.
          NOT derived from ``passed``: ``passed=False`` yields ``"remediate"``
          on the generic and engine-exception paths but ``"failed"`` on the
          two exception paths, so ``passed`` cannot imply a status.
        * ``loop_type``   -- read, defaulting to ``"unknown"`` to mirror
          ``handle_loop_completion``'s own default at ``orchestration.py:223``.
        * ``passed``      -- read as-is.
        * ``findings``    -- read from ``eval_res.failures`` / the routed
          expression; absent means "no findings", as production treats it.
        * ``routed``      -- present only on the routed paths (:397, :432);
          the generic path omits it and is therefore ``False``.
        * ``capability`` / ``engine_class`` -- routed paths only (:409/:410,
          :433/:435); ``None`` on the generic path, which is correct.
        * ``artifacts``   -- serialised dicts, re-validated (note 1).
        * ``evaluation``  -- string in production; preserved only if a real
          ``EvaluationResult`` is supplied (note 2).
        """
        if not isinstance(loop_result, Mapping):
            raise TypeError(
                f"loop_result must be a mapping, got {type(loop_result).__name__}"
            )
        evaluation = loop_result.get("evaluation")
        if evaluation is not None and not isinstance(evaluation, EvaluationResult):
            # A status string (or anything else) is not an EvaluationResult and
            # must not be upgraded into one. See note 2.
            evaluation = None
        return cls(
            status=_coerce_status(loop_result.get("status")),
            loop_type=str(loop_result.get("loop_type") or "unknown"),
            passed=bool(loop_result.get("passed", False)),
            findings=_coerce_findings(loop_result.get("findings")),
            routed=bool(loop_result.get("routed", False)),
            capability=_optional_str(loop_result.get("capability")),
            engine_class=_optional_str(loop_result.get("engine_class")),
            artifacts=_coerce_artifacts(loop_result.get("artifacts")),
            evaluation=evaluation,
        )

    # ── Adapter 2: ``RoutedExecution`` ─────────────────────────────────

    @classmethod
    def from_routed_execution(
        cls,
        routed: RoutedExecution,
        *,
        loop_type: str,
    ) -> "ExecutionOutcome":
        """Normalise a ``RoutedExecution`` produced by the capability router.

        ``RoutedExecution.status`` is already one of the canonical literals: it
        is set to ``"escalate"`` / ``"complete"`` / ``"remediate"`` by
        ``_from_power_engine_result`` (:356) and ``_from_pipeline_result``
        (:531-536), so it is passed through rather than re-derived.

        ``loop_type`` is required because ``RoutedExecution`` does not carry it;
        its producer (``kernel_adapters.execute_loop``) knows it from the loop
        being run. Defaulting it here would invent a value.

        ``artifacts`` stays empty and ``evaluation`` stays ``None``: neither is
        present on ``RoutedExecution``. Production creates the routed evidence
        artifact asynchronously in ``_publish_routed_evidence``; that durable
        path remains the authority and is not duplicated here.
        """
        return cls(
            status=_coerce_status(routed.status),
            loop_type=loop_type,
            passed=bool(routed.success),
            findings=(
                []
                if routed.success
                else [routed.error_message or "engine reported failure"]
            ),
            routed=True,
            capability=routed.capability,
            engine_class=routed.engine_class,
            artifacts=[],
            evaluation=None,
        )

    # ── Adapter 3: ``PowerEngineResult`` (structural, deliberately) ─────

    @classmethod
    def from_power_engine_result(
        cls,
        result: Any,
        *,
        loop_type: str,
        capability: str,
        engine_class: str,
    ) -> "ExecutionOutcome":
        """Normalise a ``PowerEngineResult`` structurally.

        ``PowerEngineResult`` (``power_engines/base.py:90-101``) has no
        ``status`` field, so the decision is reproduced EXACTLY as
        ``CommercialCapabilityRouter._from_power_engine_result`` computes it
        (``capability_router.py:348-356``)::

            stages  = list(result.stages_executed or [])
            waiting = any("WAITING_FOR_HUMAN_APPROVAL" in str(s) for s in stages)
            success = bool(result.success)
            status  = "escalate" if waiting else ("complete" if success else "remediate")

        and ``passed`` is ``success and not waiting`` exactly as the router's
        ``RoutedExecution(success=success and not waiting, ...)`` does at :353,
        with the findings expression copied from ``kernel_adapters.py:430``.

        ``loop_type``, ``capability`` and ``engine_class`` are required because
        the engine result carries none of them; the router supplies all three
        from the invocation site.

        ``WAITING_FOR_HUMAN_APPROVAL`` is a real, existing
        ``PowerEngineLifecycleStage`` member (``power_engines/base.py:52``,
        set at :186/:192), which is why its presence is the ESCALATE signal.
        """
        stages = list(getattr(result, "stages_executed", None) or [])
        waiting = any("WAITING_FOR_HUMAN_APPROVAL" in str(s) for s in stages)
        success = bool(getattr(result, "success", False))
        if waiting:
            status = OutcomeStatus.ESCALATE
        elif success:
            status = OutcomeStatus.COMPLETE
        else:
            status = OutcomeStatus.REMEDIATE
        passed = success and not waiting
        error_message = getattr(result, "error_message", None)
        return cls(
            status=status,
            loop_type=loop_type,
            passed=passed,
            findings=[] if passed else [error_message or "engine reported failure"],
            routed=True,
            capability=capability,
            engine_class=engine_class,
            artifacts=[],
            evaluation=None,
        )

    # ── Adapter 4: ``PipelineResult`` (structural, engine 5) ───────────

    @classmethod
    def from_pipeline_result(
        cls,
        result: Any,
        *,
        loop_type: str,
        capability: str = "legacy_modernization",
        engine_class: str = "ModernizationPipeline",
    ) -> "ExecutionOutcome":
        """Normalise a ``PipelineResult`` (engine 5, ModernizationPipeline) structurally.

        Extracts status and metrics without eagerly importing
        ``autoforge_modernization``:
          * ``raw_status == 'blocked'`` -> ``ESCALATE``
          * ``complete`` and not ``error`` and ``failed_units == 0`` -> ``COMPLETE``
          * otherwise -> ``REMEDIATE``
        matching ``CommercialCapabilityRouter._from_pipeline_result``.
        """
        raw_status = getattr(result, "status", "")
        status_value = str(getattr(raw_status, "value", raw_status) or "")
        waves = list(getattr(result, "wave_results", []) or [])
        failed_units = sum(int(getattr(w, "units_failed", 0) or 0) for w in waves)
        error = getattr(result, "error_message", None)
        complete = status_value == "complete"

        if status_value == "blocked":
            status = OutcomeStatus.ESCALATE
        elif complete and not error and failed_units == 0:
            status = OutcomeStatus.COMPLETE
        else:
            status = OutcomeStatus.REMEDIATE

        passed = status is OutcomeStatus.COMPLETE
        findings = [] if passed else [error or "pipeline reported incomplete/failed units"]
        return cls(
            status=status,
            loop_type=loop_type,
            passed=passed,
            findings=findings,
            routed=True,
            capability=capability,
            engine_class=engine_class,
            artifacts=[],
            evaluation=None,
        )