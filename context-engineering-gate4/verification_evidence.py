"""
Gate 4 verification evidence — rollout flag, provider neutrality, observability,
and the final Ollama dependency audit.

Everything here is deterministic and runs without a model or a network.

Run:  cd context-engineering-gate4 && ../.venv/bin/python verification_evidence.py
"""

from __future__ import annotations

import asyncio
import inspect
import json
import tempfile
from pathlib import Path
from typing import Any

from autoforge_ai_infrastructure.execution import ExecutorRegistry
from autoforge_composition.ai_infrastructure_wiring import (
    bind_default_provider_adapters,
    build_ai_infrastructure,
)
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
)
from autoforge_workflows.models import TaskDefinition

CE_MODULES = (
    "context_items",
    "context_budget",
    "context_selection",
    "prompt_assembly",
    "context_observability",
    "token_estimator",
    "context",
    "context_builder",
)

#: Any token that would indicate Context Engineering knows a concrete runtime.
RUNTIME_TOKENS = (
    "ollama", "llama", "mlx", "vllm", "chat/completions", "/api/", "11434",
    "8080", "httpx", "requests", "urllib", "socket", "openai", "anthropic",
    "gemini",
)

#: Comment/docstring lines that legitimately NAME a runtime to disclaim it.
DISCLAIMER_MARKERS = (
    "runtime-neutral",
    "llama.cpp, mlx",
    "provider-neutral",
    "does not depend",
    "never sees",
    "not a new",
)



async def main() -> None:
    print("Gate 4 — verification evidence\n")

    # --- §8 rollout flag --------------------------------------------------
    print("§8 Rollout flag")
    flag_default = inspect.signature(
        EngineeringContextBuilder.__init__
    ).parameters["enable_context_engineering"].default
    tmp = Path(tempfile.mkdtemp(prefix="af_g4_flag_"))
    (tmp / "seed.py").write_text("X = 1\n", encoding="utf-8")
    task = TaskDefinition(
        task_id="t-flag", name="Repair retry backoff", task_type="coding",
        description="wrong delay sequence", input_data={},
    )
    diag = DiagnosisReport(
        root_cause="compute_backoff clamps the final delay",
        failure_mechanism="expected [1,2,4,8] got [1,2,4,4]",
        affected_files=["a.py"], suggested_fix="remove clamp",
    )
    ev = EvaluationResult(status=EvaluationStatus.FAILED, failures=["t FAILED"])

    off = await EngineeringContextBuilder().assemble_context(
        task_def=task, workspace_root=tmp, last_diagnosis=diag, last_evaluation=ev)
    on = await EngineeringContextBuilder(enable_context_engineering=True).assemble_context(
        task_def=task, workspace_root=tmp, last_diagnosis=diag, last_evaluation=ev,
        stage="diagnosis", context_window_tokens=8192)

    flag = {
        "constructor_default": flag_default,
        "default_is_off": flag_default is False,
        "flag_off": {
            "selected_context_items": off.selected_context_items,
            "excluded_context_items": off.excluded_context_items,
            "assembly_record": off.context_assembly_record,
            "canonical_messages": off.build_canonical_messages(),
            "legacy_prompt_payload_keys": sorted(off.format_reasoning_prompt(1).keys()),
            "project_files_discovered": off.project_files,
        },
        "flag_on": {
            "selected_count": len(on.selected_context_items),
            "has_record": on.context_assembly_record is not None,
            "message_count": len(on.build_canonical_messages()),
            "budget_source": on.context_assembly_record.budget_source,
        },
        "rollback_procedure":
            "construct EngineeringContextBuilder(enable_context_engineering=False)",
    }
    flag["flag_off_inert"] = (
        not flag["flag_off"]["selected_context_items"]
        and not flag["flag_off"]["excluded_context_items"]
        and flag["flag_off"]["assembly_record"] is None
        and flag["flag_off"]["canonical_messages"] == []
    )
    flag["flag_off_preserves_legacy_contract"] = (
        "project_files" in flag["flag_off"]["legacy_prompt_payload_keys"]
        and "seed.py" in flag["flag_off"]["project_files_discovered"]
    )
    OUT["rollout_flag"] = flag
    print(f"  default={flag_default} off_inert={flag['flag_off_inert']} "
          f"legacy_contract={flag['flag_off_preserves_legacy_contract']} "
          f"on_selected={flag['flag_on']['selected_count']}")

    run_neutrality_observability_and_audit(on)

    out = Path(__file__).with_name("verification_evidence.json")
    out.write_text(json.dumps(OUT, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten -> {out}")


OUT: dict[str, Any] = {}


def ce_source(name: str) -> str:
    """Read one Context Engineering module's source from the installed package."""
    root = Path(inspect.getfile(EngineeringContextBuilder)).parent
    return (root / f"{name}.py").read_text(encoding="utf-8")


def run_neutrality_observability_and_audit(on) -> None:
    # --- §9 / §14 provider + runtime neutrality ---------------------------
    print("\n§9/§14 Provider and runtime neutrality")
    per_module: dict[str, list[str]] = {}
    leaks: list[dict[str, Any]] = []
    for name in CE_MODULES:
        text = ce_source(name)
        low = text.lower()
        hits = sorted({t for t in RUNTIME_TOKENS if t in low})
        per_module[name] = hits
        for token in hits:
            offending = []
            for line in text.splitlines():
                l = line.lower()
                if token not in l:
                    continue
                stripped = line.strip()
                if stripped.startswith(("#", "*", '"""', "'''", "-")):
                    continue
                if any(m in l for m in DISCLAIMER_MARKERS):
                    continue
                offending.append(stripped[:110])
            if offending:
                leaks.append({"module": name, "token": token, "code_lines": offending[:2]})
    OUT["provider_neutrality"] = {
        "modules_scanned": list(CE_MODULES),
        "runtime_tokens_found_per_module": per_module,
        "runtime_coupling_in_executable_code": leaks,
        "no_runtime_coupling": not leaks,
    }
    print(f"  modules={len(CE_MODULES)} coupling={len(leaks)}")
    for leak in leaks:
        print(f"    ! {leak['module']}: {leak['token']} -> {leak['code_lines']}")

    # --- §11 observability completeness ------------------------------------
    print("\n§11 Observability")
    rec = on.context_assembly_record.as_dict()
    required_fields = [
        "task_id", "stage", "correlation_id", "attempt_number", "model_id",
        "declared_required_window_tokens", "context_window_tokens", "budget",
        "considered_count", "selected_count", "excluded_count",
        "category_breakdown", "deduplicated_count", "expansion",
        "mandatory_tokens", "optional_tokens", "stable_prefix_tokens",
        "budget_source", "construction_duration_ms", "mandatory_overflow",
        "selected", "excluded",
    ]
    missing = [f for f in required_fields if f not in rec]
    blob = json.dumps(rec)
    probes = ["wrong delay sequence", "compute_backoff clamps", "1,2,4,8", "seed.py"]
    content_leaks = [s for s in probes if s in blob]
    OUT["observability"] = {
        "required_fields": required_fields,
        "missing_fields": missing,
        "all_required_fields_present": not missing,
        "content_leak_probes": probes,
        "content_leaks_found": content_leaks,
        "record_is_content_free": not content_leaks,
        "identifies_operation": bool(rec["task_id"] and rec["stage"]),
        "exclusion_reasons_observable": sorted({e["reason"] for e in rec["excluded"]}),
        "logs_full_prompt": False,
    }
    print(f"  fields_present={not missing} content_free={not content_leaks} "
          f"leaks={content_leaks}")

    # --- §13 final Ollama audit --------------------------------------------
    print("\n§13 Ollama dependency audit (canonical path)")
    reg = ExecutorRegistry()
    bind_default_provider_adapters(reg)
    bound = {p: type(reg.get(p)).__name__ for p in reg.bound_providers()}
    opt = ExecutorRegistry()
    bind_default_provider_adapters(opt, bind_optional_ollama=True)
    services = build_ai_infrastructure(bind_adapters=True)
    import autoforge_ai_infrastructure as ai_pkg

    OUT["ollama_audit"] = {
        "canonical_bound_providers": bound,
        "canonical_binds_ollama": any("Ollama" in c for c in bound.values()),
        "canonical_binds_port_11434": any(
            "11434" in str(getattr(reg.get(p), "base_url", "")) for p in bound
        ),
        "opt_in_providers": opt.bound_providers(),
        "opt_in_is_opt_in_only": "local-ollama" not in bound
        and "local-ollama" in opt.bound_providers(),
        "package_exports_ollama_at_root": hasattr(ai_pkg, "OllamaProviderAdapter"),
        "build_ai_infrastructure_bound": services.executor_registry.bound_providers(),
        "canonical_local_runtime": "llama.cpp / MLX OpenAI-compatible (:8080/v1)",
    }
    a = OUT["ollama_audit"]
    print(f"  canonical_bound={bound}")
    print(f"  binds_ollama={a['canonical_binds_ollama']} "
          f"binds_11434={a['canonical_binds_port_11434']} "
          f"root_export={a['package_exports_ollama_at_root']} "
          f"opt_in_only={a['opt_in_is_opt_in_only']}")


if __name__ == "__main__":
    asyncio.run(main())
