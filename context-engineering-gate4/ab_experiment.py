"""
Gate 4 semantic A/B experiment — Context Engineering (MSC) vs Full Context.

Controlled comparison. ONLY the context-construction strategy differs.

Held constant:
  * same model + same provider/runtime (one llama.cpp llama-server, one GGUF)
  * same task text and same system framing
  * same temperature (0.0) and same seed (42) on every call
  * same output contract, same max_tokens
  * same tool availability (none in both arms)

Arm A (control): the pre-existing full-context path. Every gathered source is
  rendered into one undifferentiated block — no selection, no budget, no
  dependency expansion, no dedup. This is the actual legacy behaviour.

Arm B (treatment): the canonical Context Engineering / MSC path —
  EngineeringContextBuilder(enable_context_engineering=True) ->
  select_context() -> prompt_assembly.build_messages().

Scoring is DETERMINISTIC and computed from the returned text, so no judge model
is involved:
  * required_recall     - mandatory facts present in the answer
  * distractor_leaks    - irrelevant facts the answer used anyway
  * output_valid        - parseable JSON / required labels present
  * unsupported_claims  - named entities absent from the given context

Run:  cd context-engineering-gate4 && ../.venv/bin/python ab_experiment.py
"""


from __future__ import annotations

import asyncio
import json
import re
import statistics
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.context_selection import SelectionPolicy
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
)
from autoforge_workflows.models import TaskDefinition

# ---------------------------------------------------------------------------
# Controlled inference client (llama.cpp llama-server, OpenAI-compatible).
# Deliberately a *test harness* client, not a production code path.
# ---------------------------------------------------------------------------

BASE_URL = "http://127.0.0.1:18080/v1"
MODEL = "qwen2.5-coder-3b"
TEMPERATURE = 0.0
SEED = 42
MAX_TOKENS = 320
#: Repeats per (task, arm). The median is reported so a single scheduling
#: hiccup cannot masquerade as a prompt-processing win or loss.
REPEATS = 3
SYSTEM = (
    "You are a precise software engineering assistant. "
    "Answer using ONLY the information present in the provided context. "
    "If a required fact is absent, say UNKNOWN. "
    "Never invent identifiers, versions, or file paths."
)


def chat(messages: list[dict[str, str]]) -> dict[str, Any]:
    """One inference call. temperature/seed/max_tokens are pinned for both arms."""
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": messages,
            "temperature": TEMPERATURE,
            "seed": SEED,
            "max_tokens": MAX_TOKENS,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    wall_ms = (time.perf_counter() - started) * 1000.0

    timings = body.get("timings") or {}
    usage = body.get("usage") or {}
    return {
        "content": body["choices"][0]["message"]["content"],
        # Prompt-processing (prefill) cost, reported by the runtime itself.
        "prompt_ms": timings.get("prompt_ms"),
        "generation_ms": timings.get("predicted_ms"),
        "prompt_n": usage.get("prompt_tokens"),
        "completion_n": usage.get("completion_tokens"),
        "wall_ms": wall_ms,
    }


def chat_repeated(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Run one arm REPEATS times; return the median-timing run and all timings.

    Temperature and seed are pinned, so every repeat is the same request; the
    repeats exist purely to make the *timing* statistic trustworthy.
    """
    runs = [chat(messages) for _ in range(REPEATS)]
    runs.sort(key=lambda r: (r["prompt_ms"] if r["prompt_ms"] is not None else 1e18))
    return {
        "content": runs[0]["content"],
        "prompt_ms": statistics.median(
            [r["prompt_ms"] for r in runs if r["prompt_ms"] is not None]
        )
        if any(r["prompt_ms"] is not None for r in runs)
        else None,
        "generation_ms": statistics.median(
            [r["generation_ms"] for r in runs if r["generation_ms"] is not None]
        )
        if any(r["generation_ms"] is not None for r in runs)
        else None,
        "wall_ms": round(statistics.fmean([r["wall_ms"] for r in runs]), 2),
        "prompt_n": runs[0]["prompt_n"],
        "completion_n": runs[0]["completion_n"],
        "repeats": REPEATS,
    }



# ---------------------------------------------------------------------------
# Representative engineering tasks.
#
# Each task is a real engineering situation with:
#   * mandatory facts  - task objective + prior failure evidence. Losing any of
#                        these means the answer cannot be correct.
#   * distractor facts - true, relevant-looking, but NOT needed. Full context
#                        carries them; MSC should exclude them. Answering from
#                        them is a measurable MSC failure mode.
#   * a fixed output contract, so output validity is objectively checkable.
# ---------------------------------------------------------------------------

FAILURE = "test_retry_backoff::test_backoff_sequence_mismatch FAILED"
FAILURE_MECHANISM = "AssertionError: expected [1,2,4,8] got [1,2,4,4]"

# Irrelevant material: real, plausible engineering context that this task does
# not need. It is the honest test of "minimum sufficient" — if the model uses it,
# context selection failed to exclude it.
#
# ``corpus(scale)`` grows the *irrelevant* corpus while holding the relevant
# evidence fixed. That is the regime Context Engineering exists for: as the
# workspace and knowledge base grow, full context grows linearly and MSC does
# not. A small corpus would flatter or unfairly penalise either arm.
NOISE_SEED: list[dict[str, Any]] = [
    {"content": "Deployment note: the platform team runs redis and kafka on the cluster.", "score": 0.31},
    {"content": "Observability stack: prometheus, grafana and jaeger collect cluster metrics.", "score": 0.28},
    {"content": "Payments integration uses stripe, twilio and sendgrid webhooks.", "score": 0.26},
    {"content": "Edge proxying is handled by nginx, envoy, traefik and haproxy.", "score": 0.24},
    {"content": "Data platform uses airflow, dbt, fivetran and debezium.", "score": 0.22},
    {"content": "Storage layer is postgres; a recent migration added user_email.", "score": 0.20},
    {"content": "Search is served by elasticsearch with a kibana dashboard.", "score": 0.18},
    {"content": "Secrets live in vault and are injected by a sidecar at boot.", "score": 0.16},
    {"content": "CI runs github actions on a shared arm64 runner pool.", "score": 0.14},
    {"content": "Feature flags are evaluated by the launchdarkly relay.", "score": 0.12},
    {"content": "Object storage is minio behind an s3 gateway.", "score": 0.10},
    {"content": "Tracing is sampled at 10 percent and shipped to a collector.", "score": 0.08},
    {"content": "Backups run nightly and are retained in a glacier bucket.", "score": 0.06},
    {"content": "Blue/green deploys cut over with a weighted dns switch.", "score": 0.04},
    {"content": "Image builds are cached in a registry mirror on the lan.", "score": 0.02},
    {"content": "Alerting rules are versioned alongside service manifests.", "score": 0.01},
    {"content": "Rate limiting middleware is disabled in the staging profile.", "score": 0.01},
    {"content": "The gateway terminates tls with a wildcard certificate.", "score": 0.01},
    {"content": "Log shipping uses fluentbit with a twenty four hour buffer.", "score": 0.01},
    {"content": "Canary analysis runs hourly against the production baseline.", "score": 0.01},
]

#: The only knowledge hit the retriever surfaces to the MSC arm.
RELEVANT_CUTOFF = 0.29

#: Corpus scales exercised. ``distractors`` is how many irrelevant items the
#: *full-context* arm is forced to carry.
SCALES = (4, 12, 20)


def corpus(scale: int) -> list[dict[str, Any]]:
    """The distractor corpus at a given scale (relevant hit always first)."""
    relevant = [h for h in NOISE_SEED if h["score"] >= RELEVANT_CUTOFF]
    irrelevant = [h for h in NOISE_SEED if h["score"] < RELEVANT_CUTOFF]
    return relevant + irrelevant[: max(0, scale)]


TASK_SPECS: list[dict[str, Any]] = [
    {
        "name": "retry-backoff",
        "description": "The retry backoff helper produces a wrong delay sequence.",
        "root_cause": "compute_backoff clamps the final delay instead of doubling it",
        "failure": "test_retry_backoff::test_backoff_sequence_mismatch FAILED: expected [1,2,4,8] got [1,2,4,4]",
        "required_facts": ("compute_backoff", "1,2,4,8", "1,2,4,4"),
        "distractor_facts": ("redis", "kafka", "nginx", "envoy", "prometheus", "grafana"),
        "question": (
            'Return ONLY a JSON object with exactly these keys: "failure_cause", '
            '"affected_symbol", "expected_sequence", "actual_sequence". '
            "Use only values present in the context. Use UNKNOWN if a value is absent."
        ),
        "want_json": True,
    },
    {
        "name": "cache-ttl",
        "description": "A cache helper returns stale entries after the documented TTL.",
        "root_cause": "cache_get ignores ttl_seconds, so entries never expire",
        "failure": "test_cache_ttl::test_entry_expired FAILED: expected ttl_seconds 300, saw stale key",
        "required_facts": ("ttl_seconds", "300", "cache_get"),
        "distractor_facts": ("redis", "kafka", "postgres", "airflow", "dbt"),
        "question": (
            "Answer in exactly this format:\nCAUSE: <one sentence>\nFILE: <path>\nFIX: <one sentence>"
        ),
        "want_json": False,
    },
    {
        "name": "auth-redirect",
        "description": "Authenticated users are redirected to login after token refresh.",
        "root_cause": "the refresh handler returns 302 instead of 200 and drops the session cookie",
        "failure": "test_auth_refresh::test_session_kept FAILED: got 302 on /refresh, session lost",
        "required_facts": ("302", "session"),
        "distractor_facts": ("stripe", "twilio", "sendgrid", "prometheus"),
        "question": (
            "Answer in exactly this format:\nCAUSE: <one sentence>\nFILE: <path>\nFIX: <one sentence>"
        ),
        "want_json": False,
    },
    {
        "name": "rate-limit",
        "description": "A rate limiter never reports remaining quota to clients.",
        "root_cause": "the response builder omits X-RateLimit-Remaining so clients never see 429",
        "failure": "test_rate_limit::test_header_present FAILED: X-RateLimit-Remaining missing, expected 429 handling",
        "required_facts": ("X-RateLimit-Remaining", "429"),
        "distractor_facts": ("nginx", "envoy", "traefik", "haproxy", "datadog"),
        "question": (
            'Return ONLY a JSON object with exactly these keys: "cause", "header", "limit". '
            "Use UNKNOWN for anything absent."
        ),
        "want_json": True,
    },
    {
        "name": "schema-drift",
        "description": "A schema migration fails against the production database.",
        "root_cause": "the migration drops user_email NOT NULL before backfilling existing rows",
        "failure": "test_migration::test_user_email_present FAILED: user_email column missing, expected NOT NULL",
        "required_facts": ("user_email", "NOT NULL", "postgres"),
        "distractor_facts": ("airflow", "dbt", "fivetran", "debezium", "stripe"),
        "question": (
            "Answer in exactly this format:\nCAUSE: <one sentence>\nFILE: <path>\nFIX: <one sentence>"
        ),
        "want_json": False,
    },
]



# ---------------------------------------------------------------------------
# Arm A — the pre-existing full-context path (control).
#
# Renders every gathered source into one undifferentiated block: no selection,
# no budget, no dependency expansion, no dedup. This is the actual legacy
# behaviour, not a strawman.
# ---------------------------------------------------------------------------


def build_full_context_messages(spec: dict[str, Any], scale: int) -> list[dict[str, str]]:
    n = spec["name"]
    blocks = [
        f"## Task\nName: Repair {n}\nType: coding\nDescription: {spec['description']}",
        "## Workspace files\n"
        + "\n".join(
            [
                f"src/{n}/service.py",
                f"tests/test_{n.replace('-', '_')}.py",
                "src/shared/config.py",
                "src/shared/logging.py",
                "docs/architecture.md",
            ]
        ),
        f"## Diagnosis\nRoot cause: {spec['root_cause']}\n"
        "Mechanism: AssertionError comparing expected and actual values\n"
        f"Affected: src/{n}/service.py\n"
        "Suggested fix: Apply the targeted fix described in the evidence.",
        f"## Evaluation\nFailures: {spec['failure']}",
    ]
    for index, hit in enumerate(corpus(scale)):
        blocks.append(f"## Retrieved knowledge {index}\n{hit['content']}")
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "\n\n".join(blocks) + "\n\n## Question\n" + spec["question"],
        },
    ]


# ---------------------------------------------------------------------------
# Arm B — the canonical Context Engineering (MSC) path (treatment).
# ---------------------------------------------------------------------------


async def build_msc_messages(
    spec: dict[str, Any], workspace: Path, context_window: int, scale: int
) -> tuple[list[dict[str, str]], Any]:
    """Assemble via the canonical engine; return (messages, assembly record).

    The retriever is handed the FULL corpus, identical to what the full-context
    arm is forced to carry. Both arms therefore start from exactly the same
    candidate pool; the only difference is that this arm then runs the MSC
    selection policy. Handing this arm a pre-filtered pool would be a rigged
    experiment — the exclusion must be *decided by the engine*, not by the
    harness.
    """
    n = spec["name"]
    hits = corpus(scale)

    class _FixedRag:
        async def retrieve(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
            return [dict(h) for h in hits]

    builder = EngineeringContextBuilder(
        enable_context_engineering=True,
        # The MSC relevance floor is the policy decision under test: a knowledge
        # hit scoring below the floor is not admitted even when budget remains.
        selection_policy=SelectionPolicy(min_optional_relevance=RELEVANT_CUTOFF),
    )
    task_def = TaskDefinition(
        task_id=f"t-g4-{n}",
        name=f"Repair {n}",
        task_type="coding",
        description=spec["description"],
        input_data={},
    )
    diagnosis = DiagnosisReport(
        root_cause=spec["root_cause"],
        failure_mechanism="AssertionError comparing expected and actual values",
        affected_files=[f"src/{n}/service.py"],
        suggested_fix="Apply the targeted fix described in the evidence.",
        confidence_score=0.9,
    )
    evaluation = EvaluationResult(
        status=EvaluationStatus.FAILED, failures=[spec["failure"]]
    )

    # Seed the workspace so the real file-discovery step runs.
    (workspace / "seed.py").write_text("X = 1\n", encoding="utf-8")

    ctx = await builder.assemble_context(
        task_def=task_def,
        workspace_root=workspace,
        workflow_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        attempt_number=2,
        rag_engine=_FixedRag(),
        last_evaluation=evaluation,
        last_diagnosis=diagnosis,
        effective_model_requirements={},
        stage="diagnosis",
        context_window_tokens=context_window,
        max_output_tokens=256,
        model_id=MODEL,
    )
    assembled = ctx.build_canonical_messages(task_name=f"Repair {n}")
    # `build_canonical_messages` returns only the sections that actually have
    # content, so it may or may not start with a system message. Prepend the
    # experiment's fixed system framing and keep every assembled message.
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
    messages.extend(m for m in assembled if m["role"] != "system")
    messages.append({"role": "user", "content": spec["question"]})
    return messages, ctx.context_assembly_record


# ---------------------------------------------------------------------------
# Deterministic scoring — no model-as-judge.
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    """Whitespace-insensitive form for fact matching.

    The model legitimately renders the same fact as ``[1,2,4,8]`` or
    ``[1, 2, 4, 8]``. Matching the raw string would score a *correct* answer as
    a miss purely on formatting, which would understate both arms identically
    and hide real differences. Comparison is therefore on the whitespace-stripped
    text. Substring matching is used deliberately: these are distinctive
    identifiers and sequence literals, not common English words.
    """
    return re.sub(r"\s+", "", text).casefold()


def score(spec: dict[str, Any], answer: str, context_text: str) -> dict[str, Any]:
    low = _norm(answer)
    required = list(spec["required_facts"])
    distractors = list(spec["distractor_facts"])

    preserved = [f for f in required if _norm(f) in low]
    missing = [f for f in required if _norm(f) not in low]
    leaked = [d for d in distractors if _norm(d) in low]

    if spec["want_json"]:
        blob = re.sub(r"^```(?:json)?|```$", "", answer.strip(), flags=re.MULTILINE).strip()
        try:
            valid = isinstance(json.loads(blob), dict)
        except Exception:
            valid = False
    else:
        valid = all(
            re.search(rf"^{label}\s*:", answer, flags=re.MULTILINE | re.IGNORECASE)
            for label in ("CAUSE", "FILE", "FIX")
        )

    # Hallucination proxy without a judge model: a named technology that appears
    # in the answer but was NOT in the context the model was actually given.
    ctx_low = _norm(context_text)
    answer_techs = {t for t in distractors if _norm(t) in low}
    context_techs = {t for t in distractors if _norm(t) in ctx_low}

    return {
        "required_preserved": len(preserved),
        "required_total": len(required),
        "required_recall": round(len(preserved) / len(required), 4),
        "missing_facts": missing,
        "distractor_leaks": leaked,
        "distractor_leak_count": len(leaked),
        "output_valid": valid,
        "unsupported_claims": sorted(answer_techs - context_techs),
        "answer_chars": len(answer),
    }


def _agg(rows: list[dict[str, Any]], key: str) -> float:
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(statistics.fmean(vals), 4) if vals else 0.0


def _arm_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mean_context_chars": _agg(rows, "context_chars"),
        "mean_prompt_tokens": _agg(rows, "prompt_tokens"),
        "mean_prompt_ms": _agg(rows, "prompt_ms"),
        "mean_generation_ms": _agg(rows, "generation_ms"),
        "mean_wall_ms": _agg(rows, "wall_ms"),
        "mean_completion_tokens": _agg(rows, "completion_tokens"),
        "mean_required_recall": _agg([r["score"] for r in rows], "required_recall"),
        "mean_distractor_leaks": _agg([r["score"] for r in rows], "distractor_leak_count"),
        "output_valid_rate": round(
            sum(1 for r in rows if r["score"]["output_valid"]) / len(rows), 4
        ),
        "unsupported_claim_total": sum(len(r["score"]["unsupported_claims"]) for r in rows),
    }


async def run(context_window: int = 8192) -> dict[str, Any]:
    # Warm up the runtime so the first measured call is not paying page-in and
    # thread-pool spin-up costs that belong to neither arm.
    chat([{"role": "user", "content": "Reply with OK."}])

    tmpdir = tempfile.mkdtemp(prefix="af_g4_ab_")
    workspace = Path(tmpdir)
    results: list[dict[str, Any]] = []

    for scale in SCALES:
        for spec in TASK_SPECS:
            # --- Arm A: pre-existing full-context path -------------------
            a_messages = build_full_context_messages(spec, scale)
            a_ctx_text = "\n".join(m["content"] for m in a_messages)
            a_run = chat_repeated(a_messages)

            # --- Arm B: canonical Context Engineering / MSC path ---------
            b_messages, record = await build_msc_messages(
                spec, workspace, context_window, scale
            )
            b_ctx_text = "\n".join(m["content"] for m in b_messages)
            b_run = chat_repeated(b_messages)

            results.append(
                {
                    "task": spec["name"],
                    "distractor_items_in_full_context": scale,
                    "arm_A_full_context": {
                        "context_chars": len(a_ctx_text),
                        "prompt_tokens": a_run["prompt_n"],
                        "prompt_ms": a_run["prompt_ms"],
                        "generation_ms": a_run["generation_ms"],
                        "wall_ms": a_run["wall_ms"],
                        "completion_tokens": a_run["completion_n"],
                        "answer": a_run["content"],
                        "score": score(spec, a_run["content"], a_ctx_text),
                    },
                    "arm_B_context_engineering": {
                        "context_chars": len(b_ctx_text),
                        "prompt_tokens": b_run["prompt_n"],
                        "prompt_ms": b_run["prompt_ms"],
                        "generation_ms": b_run["generation_ms"],
                        "wall_ms": b_run["wall_ms"],
                        "completion_tokens": b_run["completion_n"],
                        "answer": b_run["content"],
                        "score": score(spec, b_run["content"], b_ctx_text),
                        "msc_record": {
                            "considered": record.considered_count,
                            "selected": record.selected_count,
                            "excluded": record.excluded_count,
                            "deduplicated": record.deduplicated_count,
                            "mandatory_tokens": record.mandatory_tokens,
                            "optional_tokens": record.optional_tokens,
                            "expansion_depth_reached": record.expansion_depth_reached,
                            "expansion_items_added": record.expansion_items_added,
                            "cacheability": [e.cacheability for e in record.selected],
                            "budget_source": record.budget_source,
                            "context_window_tokens": record.context_window_tokens,
                            "exclusion_reasons": sorted(
                            {e.reason for e in record.excluded}
                        ),
                        },
                    },
                }
            )
            print(
                f"  scale={scale:>2} task={spec['name']:<14} "
                f"A tok={a_run['prompt_n']:>4} prefill={a_run['prompt_ms']:>7.1f}ms | "
                f"B tok={b_run['prompt_n']:>4} prefill={b_run['prompt_ms']:>7.1f}ms",
                flush=True,
            )

    def summarise(scale: int | None) -> dict[str, Any]:
        rows = [
            r for r in results if scale is None or r["distractor_items_in_full_context"] == scale
        ]
        return {
            "n": len(rows),
            "arm_A_full_context": _arm_stats([r["arm_A_full_context"] for r in rows]),
            "arm_B_context_engineering": _arm_stats([r["arm_B_context_engineering"] for r in rows]),
        }

    def deltas(block: dict[str, Any]) -> dict[str, Any]:
        a, b = block["arm_A_full_context"], block["arm_B_context_engineering"]
        return {
            "prompt_tokens_pct": round(
                (b["mean_prompt_tokens"] - a["mean_prompt_tokens"]) / a["mean_prompt_tokens"] * 100, 2
            ),
            "prompt_ms_pct": round(
                (b["mean_prompt_ms"] - a["mean_prompt_ms"]) / a["mean_prompt_ms"] * 100, 2
            ),
            "required_recall_delta": round(
                b["mean_required_recall"] - a["mean_required_recall"], 4
            ),
            "distractor_leaks_delta": round(
                b["mean_distractor_leaks"] - a["mean_distractor_leaks"], 4
            ),
        }

    per_scale = {str(s): {**summarise(s), "delta": deltas(summarise(s))} for s in SCALES}
    overall = summarise(None)
    overall["delta"] = deltas(overall)

    return {
        "control": {
            "model": MODEL,
            "runtime": "llama.cpp llama-server (OpenAI-compatible /v1)",
            "temperature": TEMPERATURE,
            "seed": SEED,
            "max_tokens": MAX_TOKENS,
            "repeats_per_arm": REPEATS,
            "context_window": context_window,
            "distractor_scales": list(SCALES),
            "held_constant": [
                "model", "provider/runtime", "task", "system framing",
                "temperature", "seed", "max_tokens", "output contract",
                "tool availability (none in both arms)",
            ],
            "varied": "context construction strategy only",
        },
        "summary_overall": overall,
        "summary_by_scale": per_scale,
        "per_task": results,
    }


if __name__ == "__main__":
    print("Gate 4 semantic A/B — running (this issues real llama.cpp inferences)…")
    report = asyncio.run(run())
    out = Path(__file__).with_name("ab_results.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(json.dumps(report["summary_by_scale"], indent=2))
    print()
    print("OVERALL:")
    print(json.dumps(report["summary_overall"], indent=2))
    print(f"\nwritten -> {out}")

