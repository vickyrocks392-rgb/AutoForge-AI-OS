"""18-L read-only probe: what does the production Model Router actually see?

Establishes, without modifying anything, whether the certified M6 authority
model is registered and which provider adapters are bound. Used to classify the
routing gap found during the greenfield run.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in ["events", "event_platform", "runtime", "models", "ai_infrastructure",
          "workflows", "execution", "artifacts", "review", "security",
          "connectors", "orchestration", "kernel", "composition", "workforce",
          "power_engines", "modernization", "observability", "persistence",
          "knowledge_platform"]:
    _src = _REPO / "packages" / p / "src"
    if _src.exists():
        sys.path.insert(0, str(_src))

from autoforge_composition.ai_infrastructure_wiring import build_ai_infrastructure

ai = build_ai_infrastructure(include_workforce_models=True, bind_adapters=True)

reg = ai.executor_registry
inner = getattr(reg, "_adapters", None) or getattr(reg, "_executors", None) or {}
print("BOUND PROVIDERS:", sorted(inner.keys()) if hasattr(inner, "keys") else inner)
for pid, adapter in (inner.items() if hasattr(inner, "items") else []):
    print(f"  provider={pid:<20} adapter={type(adapter).__name__} "
          f"tag_map={getattr(adapter, '_model_tag_map', None)}")

print("\nREGISTERED MODELS:")
from autoforge_ai_infrastructure.metadata import ModelQuery
for m in ai.registry.query_models(ModelQuery()):
    print(f"  model_id={m.model_id:<24} provider={m.provider_id:<20} "
          f"quality={m.quality_tier} ctx={m.context_window_tokens}")
print("\nPROVIDERS:")
for p in ai.registry.list_providers():
    print(f"  {p.provider_id:<22} {getattr(p, 'display_name', '')}")
