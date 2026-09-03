"""G.3 LLM In
        }tegration - Semantic Reasoning via AutoForge AI Infrastructure."""
from __future__ import annotations
import logging, time, uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from autoforge_ai_infrastructure.execution import ExecutionRequest

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LLMWorkloadMetrics(BaseModel):
    total_files: int = 0
    total_LOC: int = 0
    deterministic_files: int = 0
    deterministic_LOC: int = 0
    parser_files: int = 0
    parser_LOC: int = 0
    LLM_analyzed_files: int = 0
    LLM_analyzed_LOC: int = 0
    LLM_calls: int = 0
    LLM_tokens_in: int = 0
    LLM_tokens_out: int = 0
    LLM_latency_ms: float = 0.0
    parallel_LLM_calls: int = 0
    serial_LLM_calls: int = 0
    critical_path_duration_ms: float = 0.0
    total_compute_time_ms: float = 0.0
    wall_clock_time_ms: float = 0.0
    RAG_calls: int = 0
    RAG_latency_ms: float = 0.0

    @property
    def semantic_coverage(self) -> float:
        return self.LLM_analyzed_files / self.total_files if self.total_files else 0.0

    @property
    def deterministic_coverage(self) -> float:
        return self.deterministic_files / self.total_files if self.total_files else 0.0

    @property
    def LLM_wall_clock_contribution(self) -> float:
        return self.LLM_latency_ms / self.wall_clock_time_ms if self.wall_clock_time_ms else 0.0


class LLMTaskKind:
    BUSINESS_RULE_INTERPRETATION = "business_rule_interpretation"
    LEGACY_BEHAVIOR_INTERPRETATION = "legacy_behavior_interpretation"
    ARCHITECTURE_SYNTHESIS = "architecture_synthesis"
    TARGET_MAPPING = "target_mapping"
    MODERNIZATION_STRATEGY = "modernization_strategy"
    TRANSFORMATION_GENERATION = "transformation_generation"
    TRANSFORMATION_EXPLANATION = "transformation_explanation"
    VERSION_INTERPRETATION = "version_interpretation"
    UNKNOWN_TECHNOLOGY = "unknown_technology"
    CODE_TRANSLATION = "code_translation"


class LLMConclusionRecord(BaseModel):
    conclusion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_kind: str
    timestamp: datetime = Field(default_factory=_utc_now)
    task_description: str = ""
    input_evidence_refs: list = Field(default_factory=list)
    input_content_preview: str = ""
    model: str = ""
    provider: str = ""
    inference_latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    conclusion: str = ""
    confidence: float = 0.0
    derived_claims: list = Field(default_factory=list)
    provenance_claim: str = "llm_inferred"
    is_fabricated: bool = False
    is_blocked: bool = False

    def is_reliable(self, min_confidence: float = 0.5) -> bool:
        return (
            self.confidence >= min_confidence
            and self.model != ""
            and self.conclusion != ""
            and not self.is_fabricated
            and not self.is_blocked
        )


def check_ollama_health(base_url: str = "http://127.0.0.1:11434", timeout: float = 5.0) -> dict:
    """Check if Ollama is reachable."""
    try:
        import json as _j
        import urllib.request as _ur
        req = _ur.Request(f"{base_url}/api/tags", method="GET")
        with _ur.urlopen(req, timeout=timeout) as r:
            d = _j.loads(r.read().decode())
            return {
                "available": True,
                "base_url": base_url,
                "models": [m.get("name", "?") for m in d.get("models", [])],
                "ok": True,
            }
    except Exception as e:
        return {
            "available": False,
            "base_url": base_url,
            "error": str(e),
            "ok": False,
            "models": [],
        }


class G3LLMIntegration:
    """G.3 semantic reasoning facade backed by AutoForge AI Infrastructure."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        default_model: str = "qwen2.5-coder:7b-instruct-q3_K_M",
        timeout_seconds: float = 120.0,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        force_offline: bool = False,
    ):
        self._bu = base_url
        self._dm = default_model
        self._ts = timeout_seconds
        self._mt = max_tokens
        self._t = temperature
        self._fo = force_offline
        self._hr = None
        self._av = None
        self._cs = []
        self._m = LLMWorkloadMetrics()
        self._wc = None

    @property
    def is_available(self) -> bool:
        if self._fo:
            return False
        if self._av is None:
            self._hr = check_ollama_health(self._bu)
            self._av = bool(self._hr.get("ok", False))
        return self._av

    def health(self) -> dict:
        if self._fo:
            self._hr = {"available": False, "base_url": self._bu, "ok": False, "models": [], "error": "forced_offline"}
            self._av = False
            return self._hr
        self._hr = check_ollama_health(self._bu)
        self._av = bool(self._hr.get("ok", False))
        return self._hr

    @property
    def metrics(self) -> LLMWorkloadMetrics:
        return self._m

    @property
    def conclusions(self) -> list:
        return list(self._cs)

    def start_wall_clock(self) -> None:
        self._wc = time.perf_counter()

    def stop_wall_clock(self) -> None:
        if self._wc is not None:
            e = (time.perf_counter() - self._wc) * 1000.0
            self._m.wall_clock_time_ms += e
            self._m.total_compute_time_ms += e
            self._wc = None

    def record_deterministic_file(self, loc: int = 0) -> None:
        self._m.deterministic_files += 1
        self._m.deterministic_LOC += loc
        self._m.total_files += 1
        self._m.total_LOC += loc

    def record_parser_file(self, loc: int = 0) -> None:
        self._m.parser_files += 1
        self._m.parser_LOC += loc
        self._m.total_files += 1
        self._m.total_LOC += loc

    def record_LLM_file(self, loc: int = 0) -> None:
        self._m.LLM_analyzed_files += 1
        self._m.LLM_analyzed_LOC += loc
        self._m.total_files += 1
        self._m.total_LOC += loc

    def record_RAG(self, latency_ms: float) -> None:
        self._m.RAG_calls += 1
        self._m.RAG_latency_ms += latency_ms

    def record_serial_LLM(self) -> None:
        self._m.serial_LLM_calls += 1

    def record_parallel_LLM(self, count: int) -> None:
        self._m.parallel_LLM_calls += count

    async def interpret_business_rule(self, rt, sc, er):
        return await self._st(
            tk=LLMTaskKind.BUSINESS_RULE_INTERPRETATION,
            td=f"IBR:{rt[:100]}",
            ic=f"BR:\n{rt}\n\nSC:\n{sc[:500]}",
            er=er,
            sp=_BRP,
        )

    async def interpret_legacy_behavior(self, cs, lg, er):
        return await self._st(
            tk=LLMTaskKind.LEGACY_BEHAVIOR_INTERPRETATION,
            td=f"{lg} behavior",
            ic=f"L:{lg}\nC:\n{cs[:800]}",
            er=er,
            sp=_LBP,
        )

    async def synthesize_architecture(self, cd, dg, er):
        return await self._st(
            tk=LLMTaskKind.ARCHITECTURE_SYNTHESIS,
            td="Arch synthesis",
            ic="Comps:\n" + "\n".join(f"-{x}" for x in cd) + f"\n\nDG:\n{dg[:500]}",
            er=er,
            sp=_AP,
        )

    async def map_target_technology(self, st, sv, sp2, er):
        suffix = f" v{sv}" if sv else ""
        return await self._st(
            tk=LLMTaskKind.TARGET_MAPPING,
            td=f"Map {st}",
            ic=f"ST:{st}{suffix}\nPat:\n" + "\n".join(f"-{x}" for x in sp2),
            er=er,
            sp=_TMP,
        )

    async def generate_transformation(self, sc, st, tt, tt2, er):
        return await self._st(
            tk=LLMTaskKind.TRANSFORMATION_GENERATION,
            td=f"{st}->{tt}",
            ic=f"TT:{tt2}\nST:{st}\nTT:{tt}\n\nSC:\n{sc[:600]}",
            er=er,
            sp=_TRP,
        )

    async def explain_transformation(self, sc, tc, tt2, er):
        return await self._st(
            tk=LLMTaskKind.TRANSFORMATION_EXPLANATION,
            td=f"Explain {tt2}",
            ic=f"TT:{tt2}\n\n---SRC---\n{sc[:400]}\n\n---TGT---\n{tc[:400]}",
            er=er,
            sp=_EP,
        )

    async def interpret_unknown_technology(self, cs, ds, er):
        return await self._st(
            tk=LLMTaskKind.UNKNOWN_TECHNOLOGY,
            td="ID unk tech",
            ic="Sig:\n" + "\n".join(f"-{x}" for x in ds) + f"\n\nCS:\n{cs[:500]}",
            er=er,
            sp=_UTP,
        )

    async def interpret_version(self, vs, t, er):
        return await self._st(
            tk=LLMTaskKind.VERSION_INTERPRETATION,
            td=f"Ver {vs} {t}",
            ic=f"T:{t}\nVS:{vs}",
            er=er,
            sp=_VP,
        )

    async def translate_code(self, sc, st, tt, er):
        return await self._st(
            tk=LLMTaskKind.CODE_TRANSLATION,
            td=f"Tr {st}->{tt}",
            ic=f"S:{st}\nT:{tt}\nC:\n{sc[:800]}",
            er=er,
            sp=_CTP,
        )

    async def _st(self, *, tk, td, ic, er, sp):
        r = LLMConclusionRecord(
            task_kind=tk,
            task_description=td,
            input_evidence_refs=er,
            input_content_preview=ic[:200],
        )
        if not self.is_available:
            r.conclusion = "LLM_UNAVAILABLE"
            r.confidence = 0.0
            r.provenance_claim = "llm_unavailable"
            r.is_fabricated = True
            logger.warning("G3LLM: UNAVAILABLE task=%s", tk)
            self._cs.append(r)
            return r
        try:
            from autoforge_ai_infrastructure.adapters import OllamaProviderAdapter
            from autoforge_ai_infrastructure.execution import ExecutionRequest, ExecutionTarget
            a = OllamaProviderAdapter(
                provider_id="local-m1",
                base_url=self._bu,
                default_timeout_seconds=self._ts,
            )
            req = ExecutionRequest(
                payload={"messages": [{"role": "system", "content": sp}, {"role": "user", "content": ic}]},
                parameters={"temperature": self._t, "num_predict": self._mt},
                timeout_seconds=self._ts,
            )
            tgt = ExecutionTarget(model_id=self._dm, provider_id="local-m1")
            s = time.perf_counter()
            res = await a.execute(req, tgt)
            ms = (time.perf_counter() - s) * 1000.0
            ct = res.get("content", "")
            ti = res.get("tokens", {}).get("input_tokens", 0)
            to = res.get("tokens", {}).get("output_tokens", 0)
            st_out = res.get("structured_output")
            if st_out and isinstance(st_out, dict):
                r.conclusion = st_out.get("conclusion", ct[:500])
                r.confidence = float(st_out.get("confidence", 0.5))
                r.derived_claims = st_out.get("claims", [])
            else:
                r.conclusion = ct[:500]
                r.confidence = 0.5
                r.derived_claims = []
            r.model = self._dm
            r.provider = "local-m1"
            r.inference_latency_ms = ms
            r.tokens_in = ti
            r.tokens_out = to
            self._m.LLM_calls += 1
            self._m.LLM_latency_ms += ms
            self._m.LLM_tokens_in += ti
            self._m.LLM_tokens_out += to
        except Exception as exc:
            logger.warning("G3LLM fail %s: %s", tk, exc)
            r.conclusion = f"LLM_FAIL:{exc}"
            r.confidence = 0.0
            r.is_fabricated = True
            r.model = self._dm
            r.provider = "local-m1"
        self._cs.append(r)
        return r


_BRP = 'G3 analyst. Return strict JSON: {"c": "what rule does (1-2 sentences)", "cf": 0.0-1.0, "cl": []}. Conservative.'
_LBP = 'G3 legacy analyst. Return strict JSON: {"c": "what code does (1-2 sentences)", "cf": 0.0-1.0, "cl": []}. Conservative.'
_AP = 'G3 architect. Return strict JSON: {"c": "architectural pattern (2-3 sentences)", "cf": 0.0-1.0, "cl": []}'
_TMP = 'G3 target mapper. Known: COBOL->Java17, JCL->Airflow, CICS->SpringBoot, VSAM/DB2->PostgreSQL. Return strict JSON: {"c": "target tech", "cf": 0.0-1.0, "cl": []}'
_TRP = 'G3 transform planner. Return strict JSON: {"c": "transform desc (2-3 sentences)", "cf": 0.0-1.0, "cl": [], "tt": "refactor|rewrite|review_req|blocked", "risks": [], "tools": []}'
_EP = 'G3 explainer. Return strict JSON: {"c": "what transform does (2-3 sentences)", "cf": 0.0-1.0, "cl": []}'
_UTP = 'G3 tech ID. Return strict JSON: {"c": "tech name or UNKNOWN", "cf": 0.0-1.0, "cl": []}'
_VP = 'G3 version interpreter. Return strict JSON: {"c": "version and dialect", "cf": 0.0-1.0, "cl": []}'
_CTP = 'G3 code translator. Return strict JSON: {"c": "translation approach (2-3 sentences)", "cf": 0.0-1.0, "cl": [], "tt": "refactor|rewrite|review_req|blocked"}'
__all__ = ["G3LLMIntegration", "LLMWorkloadMetrics", "LLMConclusionRecord", "LLMTaskKind", "check_ollama_health"]
