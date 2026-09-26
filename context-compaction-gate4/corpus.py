"""Gate 4 shared harness: corpus, deterministic checks, and the M6 client.

One corpus is used for BOTH arms of the A/B experiment (Gate 4 §7/§31). The
*only* difference between arms is whether Context Compaction ran — the compactor
itself decides what is transformed. Nothing is hand-curated into Arm B.

Deterministic checks are the primary instrument (Gate 4 §6). M6 is used only where
deterministic comparison cannot answer the question (Gate 4 §8).
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
)
from autoforge_execution.models import (
    DeterministicCheckResult,
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition

# ── M6 30B authority model (Gate 4 §3) ─────────────────────────────────────
# An EVALUATION INSTRUMENT ONLY. It never decides deterministic truth, never
# overrides test evidence or persisted state, and is not a production dependency.
M6_MODEL_PATH = (
    "/Users/kalachanddash/.autoforge-lab/step13_7/models/qwen3_coder_30b_dwq_v2"
)
M6_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"


def m6_available() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=5) as r:
            return M6_MODEL_PATH in r.read().decode("utf-8")
    except Exception:
        return False


def m6_ask(prompt: str, *, system: str, max_tokens: int = 200) -> str:
    """Ask M6 a question. Fixed temperature 0, fixed system prompt (Gate 4 §8)."""
    body = json.dumps(
        {
            "model": M6_MODEL_PATH,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        M6_ENDPOINT, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


@dataclass
class CorpusCase:
    """One evaluation cell: a task plus the history accumulated while doing it."""

    name: str
    task: TaskDefinition
    history: list[LoopIterationRecord]
    extra_context: list[dict[str, Any]] = field(default_factory=list)
    required_facts: list[str] = field(default_factory=list)
    forbidden_facts: list[str] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)


def _diag(i: int, root: str, fix: str) -> DiagnosisReport:
    return DiagnosisReport(
        root_cause=root,
        failure_mechanism=f"iteration {i}: mechanism observed in the failing run",
        affected_files=[f"src/retry_{i}.py"],
        suggested_fix=fix,
        confidence_score=0.8,
    )


def build_corpus() -> list[CorpusCase]:
    """Construct the A–J corpus from real AutoForge concepts (Gate 4 §9)."""
    cases: list[CorpusCase] = []
    wf = uuid.UUID("aaaaaaaa-1111-5111-8111-aaaaaaaaaaaa")

    def task(tid: str, name: str, desc: str) -> TaskDefinition:
        return TaskDefinition(
            task_id=tid, name=name, task_type="coding",
            description=desc, input_data={},
        )

    # A — simple iteration history ---------------------------------------
    cases.append(CorpusCase(
        name="A_simple_history",
        task=task("t-A", "Implement token bucket rate limiter",
                  "Implement a token bucket limiter with burst capacity."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="add TokenBucket class",
                changed_files=["src/bucket.py"], passed=False,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.FAILED,
                    failures=["test_burst::FAILED expected 10 got 1"]),
                diagnosis=_diag(1, "bucket not refilling", "add refill on consume"),
            ),
            LoopIterationRecord(
                iteration=2, action_plan="add refill on consume",
                changed_files=["src/bucket.py"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
        ],
        required_facts=["add refill on consume", "bucket not refilling"],
        questions=[{"q": "What was the root cause found in the failing iteration?",
                    "must_include": ["refill"]}],
    ))

    # B — failed then corrected ------------------------------------------
    cases.append(CorpusCase(
        name="B_failed_then_corrected",
        task=task("t-B", "Repair retry backoff",
                  "The backoff helper returns the wrong delay sequence."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="clamp the delay",
                changed_files=["src/retry.py"], passed=False,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.FAILED,
                    failures=["test_sequence FAILED expected [1,2,4,8] got [1,2,4,4]"]),
                diagnosis=_diag(1, "clamp overrides doubling on the last step",
                                "remove the clamp"),
            ),
            LoopIterationRecord(
                iteration=2, action_plan="remove the clamp",
                changed_files=["src/retry.py"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
        ],
        required_facts=["clamp overrides doubling", "remove the clamp"],
        questions=[{"q": "Why did the first attempt fail, and what corrected it?",
                    "must_include": ["clamp"]}],
    ))

    # C — conflicting evidence: model conclusion vs deterministic check ----
    cases.append(CorpusCase(
        name="C_conflicting_evidence",
        task=task("t-C", "Fix the parser off-by-one",
                  "The parser drops the last token."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="adjust the slice bound",
                changed_files=["src/parser.py"], passed=False,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.FAILED,
                    failures=["test_last_token::FAILED expected 3 got 2"],
                    deterministic_checks=[DeterministicCheckResult(
                        check_name="test_last_token", passed=False,
                        message="deterministic check failed: expected 3 got 2")],
                ),
                diagnosis=_diag(1, "slice bound excludes the final token",
                                "use an inclusive upper bound"),
            ),
        ],
        required_facts=["slice bound excludes the final token",
                        "test_last_token::FAILED"],
        questions=[{"q": "Did verification pass or fail? State the authoritative evidence.",
                    "must_include": ["fail"]}],
    ))

    # D — requirement change ----------------------------------------------
    cases.append(CorpusCase(
        name="D_requirement_change",
        task=task("t-D", "Build the export API",
                  "Originally: export CSV only. Later changed to: CSV and JSON."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="implement CSV exporter only",
                changed_files=["src/export.py"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
            LoopIterationRecord(
                iteration=2,
                action_plan="add JSON exporter per updated requirement",
                changed_files=["src/export.py"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
        ],
        required_facts=["add JSON exporter per updated requirement"],
        questions=[{"q": "What is the CURRENT export requirement?",
                    "must_include": ["JSON"]}],
    ))

    # E — rejected decision (must NOT be resurrected as available) ---------
    rejected = ContextItem(
        content="DECISION REJECTED: do NOT use Redis for the rate limiter; "
                "the reviewer rejected the Redis proposal.",
        category=ContextCategory.DECISION,
        source=ContextSource("approval", "gate-reject-1"),
        required=True,
        relevance=1.0,
        provenance=ContextProvenance("approval_store", "gate-reject-1"),
    )
    cases.append(CorpusCase(
        name="E_rejected_decision",
        task=task("t-E", "Choose a rate limiter backend",
                  "Pick a backend for the rate limiter."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="implement a Redis-backed limiter",
                changed_files=["src/limiter_redis.py"], passed=False,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.FAILED,
                    failures=["ops review: Redis rejected, in-memory limiter required"]),
                diagnosis=_diag(1, "Redis backend was rejected by the reviewer",
                                "implement an in-memory token bucket instead"),
            ),
            LoopIterationRecord(
                iteration=2, action_plan="implement in-memory token bucket",
                changed_files=["src/limiter.py"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
        ],
        extra_context=[rejected],
        required_facts=["in-memory token bucket", "in-memory limiter required"],
        forbidden_facts=["implement a Redis-backed limiter"],
        questions=[{"q": "Which backend was approved, and what must not be used?",
                    "must_include": ["in-memory"]}],
    ))

    # F — unresolved blocker ---------------------------------------------
    cases.append(CorpusCase(
        name="F_unresolved_blocker",
        task=task("t-F", "Migrate the legacy schema",
                  "Migrate the legacy orders schema to the new format."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="read the legacy table",
                changed_files=[], passed=False,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.FAILED,
                    failures=["BLOCKER: legacy table is encrypted; no read key available"]),
                diagnosis=_diag(1, "legacy table encrypted, read key unavailable",
                                "UNRESOLVED - request the read key from the DBA"),
            ),
            LoopIterationRecord(
                iteration=2, action_plan="attempt migration anyway",
                changed_files=["migrate.py"], passed=False,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.FAILED,
                    failures=["BLOCKER: still no read key; migration aborted"]),
                diagnosis=_diag(2, "read key still missing",
                                "UNRESOLVED - still blocked on the DBA read key"),
            ),
        ],
        required_facts=["read key", "BLOCKER"],
        questions=[{"q": "What remains unresolved right now?",
                    "must_include": ["read key"]}],
    ))

    # G — artifact dependency --------------------------------------------
    cases.append(CorpusCase(
        name="G_artifact_dependency",
        task=task("t-G", "Consume the generated client library",
                  "Wire the generated client into the service."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="generate the client library artifact",
                changed_files=["gen/client.py"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
            LoopIterationRecord(
                iteration=2,
                action_plan="import the generated client into the service",
                changed_files=["src/service.py"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
        ],
        required_facts=["gen/client.py", "import the generated client"],
        questions=[{"q": "Which artifact does the next step depend on?",
                    "must_include": ["client"]}],
    ))

    # H — recovery sequence ----------------------------------------------
    cases.append(CorpusCase(
        name="H_recovery",
        task=task("t-H", "Recover the interrupted deployment",
                  "Resume the deployment that was interrupted mid-apply."),
        history=[
            LoopIterationRecord(
                iteration=1, action_plan="apply the deployment manifest",
                changed_files=["deploy.yaml"], passed=False,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.FAILED,
                    failures=["process killed during apply; manifest half-applied"]),
                diagnosis=_diag(1, "interrupted mid-apply",
                                "roll back then re-apply cleanly"),
            ),
            LoopIterationRecord(
                iteration=2, action_plan="roll back the half-applied manifest",
                changed_files=["deploy.yaml"], passed=True,
                evaluation=EvaluationResult(
                    status=EvaluationStatus.PASSED, failures=[]),
            ),
        ],
        required_facts=["roll back", "half-applied"],
        questions=[{"q": "What recovery action was taken after the interruption?",
                    "must_include": ["roll back"]}],
    ))

    # I — long history (compaction pressure) -----------------------------
    long_history = [
        LoopIterationRecord(
            iteration=i,
            action_plan=f"iteration {i}: investigate flaky connection pool timeout",
            changed_files=[f"src/pool_{i}.py"],
            passed=(i == 12),
            evaluation=EvaluationResult(
                status=EvaluationStatus.PASSED if i == 12 else EvaluationStatus.FAILED,
                failures=[] if i == 12 else
                [f"test_pool_timeout::FAILED at iteration {i}"],
            ),
            diagnosis=_diag(i, f"pool sizing trial {i}",
                            f"step {i}: adjust pool_max_connections"),
        )
        for i in range(1, 13)
    ]
    cases.append(CorpusCase(
        name="I_long_history",
        task=task("t-I", "Fix the connection pool timeout",
                  "The connection pool times out under load."),
        history=long_history,
        required_facts=["pool_max_connections", "test_pool_timeout"],
        questions=[{"q": "How many iterations were completed?",
                    "must_include": ["12"]}],
    ))

    # J — redundant history (compression without semantic loss) ----------
    redundant = [
        LoopIterationRecord(
            iteration=i,
            action_plan="re-run the identical flake check on the connection pool",
            changed_files=[], passed=False,
            evaluation=EvaluationResult(
                status=EvaluationStatus.FAILED,
                failures=["IDENTICAL OBSERVATION: pool timeout persists, "
                           "unchanged from the previous run"],
            ),
            diagnosis=_diag(i, "pool timeout persists (repeated identical observation)",
                            "no new information this iteration"),
        )
        for i in range(1, 9)
    ]
    cases.append(CorpusCase(
        name="J_redundant_history",
        task=task("t-J", "Diagnose the persistent pool timeout",
                  "The pool timeout persists across identical runs."),
        history=redundant,
        required_facts=["IDENTICAL OBSERVATION", "pool timeout persists"],
        questions=[{"q": "What observation keeps repeating?",
                    "must_include": ["pool timeout persists"]}],
    ))

    return cases


# APPEND-CORPUS
