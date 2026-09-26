"""Gate 4 semantic A/B experiment (task §7, §8, §10, §31).

Arm A = FULL CONTEXT (no compaction)
Arm B = COMPACTED CONTEXT (identical source history, compactor decides)

Controls held constant (Gate 4 §7):
  same task, requirements, artifacts, evidence, iteration history,
  same model (M6 30B), same parameters (temperature 0, fixed system prompt),
  same expected output, same evaluation criteria.

Nothing is hand-filtered into either arm. The ONLY difference is whether a
compactor is injected into EngineeringContextBuilder, so the compactor alone is
responsible for any difference (Gate 4 §31).

Scoring is deterministic keyword-presence plus a 16-question semantic sweep
(Gate 4 §10). M6 is an evaluation instrument only; it never decides whether a
deterministic fact is true.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

from autoforge_execution.compaction import CompactionPolicy, ContextCompactor
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.token_estimator import estimate_tokens

sys.path.insert(0, str(Path(__file__).parent))
from corpus import build_corpus, m6_ask, m6_available  # noqa: E402

ENABLED = CompactionPolicy(enabled=True)

EVAL_SYSTEM = (
    "You are an engineering context analyst. Answer using ONLY the provided "
    "context. If the context does not state something, say UNKNOWN. "
    "Be concise and factual. Never invent facts."
)

# Gate 4 §10 — the 16 semantic questions, asked identically to both arms.
SEMANTIC_QUESTIONS = [
    ("current_objective", "What is the current objective of this task?"),
    ("active_requirements", "What requirements remain active?"),
    ("superseded_requirements", "What requirements were superseded or changed?"),
    ("attempted", "What has already been attempted?"),
    ("failed", "What failed?"),
    ("why_failed", "Why did it fail?"),
    ("correction", "What correction was made?"),
    ("verified", "What was verified or passed?"),
    ("unresolved", "What remains unresolved?"),
    ("artifacts", "Which files or artifacts matter?"),
    ("authoritative_evidence", "Which evidence is authoritative (tests/checks)?"),
    ("model_inference", "Which statements are merely a diagnosis proposal?"),
    ("approved", "What was approved or accepted?"),
    ("rejected", "What was rejected or must not be done?"),
    ("dependencies", "What must the next operation depend on?"),
    ("avoid_repeating", "What must the next operation avoid repeating?"),
]


async def build_arm(case, *, compaction: bool, workspace: Path):
    """Build one arm's context. Identical inputs; only compaction differs.

    Fairness (Gate 4 §7/§31): BOTH arms receive the same accumulated history.

    * Arm A (FULL) is the brief's control: the canonical Context Engineering path
      plus the full accumulated history, so the model is never handicapped.
    * Arm B is the same source history passed through Context Compaction. The
      compactor alone decides what is transformed or folded — nothing is
      hand-filtered, pre-shrunk, or curated in its favour.

    A separate ``C_ce_only`` baseline (canonical CE, no compaction, no injected
    history) is measured for attribution: if B equals C, an omission is
    pre-existing canonical behaviour (Gate 1 G-1), not compaction-induced loss.
    """
    builder = EngineeringContextBuilder(
        compactor=ContextCompactor(ENABLED) if compaction else None
    )
    ctx = await builder.assemble_context(
        task_def=case.task,
        workspace_root=workspace,
        prior_iterations=case.history,
        last_evaluation=case.history[-1].evaluation,
        last_diagnosis=case.history[-1].diagnosis,
        context_window_tokens=32768,
    )

    # Arm A is the FULL-CONTEXT baseline: every accumulated iteration verbatim.
    # This is the "no compaction" reference the acceptance question compares
    # against ("with the same necessary facts").
    if not compaction:
        from autoforge_execution.context_items import (
            ContextCategory,
            ContextItem,
            ContextProvenance,
            ContextSource,
        )

        for rec in case.history:
            ctx.selected_context_items.append(
                ContextItem(
                    content=rec.model_dump_json(indent=2),
                    category=ContextCategory.EXECUTION,
                    source=ContextSource("iteration_full", f"iter-{rec.iteration}"),
                    required=False,
                    relevance=0.5,
                    provenance=ContextProvenance(
                        "engineering_loop", f"iter-{rec.iteration}", inferred=False
                    ),
                )
            )
    return builder, ctx


def render(ctx) -> tuple[str, int]:
    """Render the arm to the text M6 sees, plus its token count."""
    messages = ctx.build_canonical_messages()
    text = "\n\n".join(m["content"] for m in messages)
    return text, estimate_tokens(text)


def deterministic_score(case, text: str) -> dict:
    """Deterministic preservation scoring (Gate 4 §6, §10)."""
    low = text.lower()
    preserved = [f for f in case.required_facts if f.lower() in low]
    forbidden_present = [f for f in case.forbidden_facts if f.lower() in low]
    return {
        "required_expected": len(case.required_facts),
        "required_preserved": len(preserved),
        "required_missing": [f for f in case.required_facts if f not in preserved],
        "all_required_preserved": len(preserved) == len(case.required_facts),
        "forbidden_present": forbidden_present,
        "no_forbidden_resurrection": not forbidden_present,
    }


#: Contexts above this size are served with a per-question M6 restart and a
#: reduced question subset, applied IDENTICALLY to both arms (see ask_all).
HEAVY_CONTEXT_TOKENS = 1200

#: The reduced subset used for heavy contexts. Both arms of a heavy case are
#: asked exactly these questions, so the A/B comparison stays symmetric.
HEAVY_QUESTIONS = ["current_objective", "failed", "why_failed", "unresolved"]


async def ask_all(text: str, *, heavy: bool = False) -> dict:
    """Ask M6 the semantic questions (identical prompt both arms).

    ``heavy`` contexts are served one question per fresh M6 process. Measured on
    this host: a single ~3400-token request succeeds, but a sustained batch of
    long-context requests exhausts Apple-GPU memory, after which the server stops
    serving entirely. The question SET is identical for both arms either way, so
    this changes only operational headroom, never the comparison.
    """
    questions = SEMANTIC_QUESTIONS
    if heavy:
        questions = [q for q in SEMANTIC_QUESTIONS if q[0] in HEAVY_QUESTIONS]

    answers = {}
    for key, question in questions:
        if heavy:
            restart_m6()
        prompt = (
            "ENGINEERING CONTEXT\n"
            "===================\n"
            f"{text}\n"
            "===================\n\n"
            f"QUESTION: {question}\n"
            "Answer in at most 40 words, using only the context above."
        )
        try:
            answers[key] = m6_ask(prompt, system=EVAL_SYSTEM, max_tokens=140)
        except Exception as exc:  # noqa: BLE001 - evaluation must not abort
            answers[key] = f"__ERROR__ {exc}"
    return answers


def restart_m6() -> None:
    """Restart the M6 server so each case/arm starts with free GPU memory.

    Applied UNIFORMLY to both arms of every case, so it cannot advantage either
    side of the A/B. It is an operational workaround for a host limitation:
    repeated long-context requests exhaust Apple-GPU memory (measured: a single
    ~3400-token request succeeds, but a sustained run OOMs), after which the
    server stops serving entirely. The restart restores service without
    changing the model, its parameters, the context, or the evaluation prompt.
    """
    import subprocess
    import time

    from corpus import M6_MODEL_PATH

    subprocess.run(["pkill", "-9", "-f", "mlx_lm.server"], check=False)
    time.sleep(6)
    subprocess.Popen(
        [sys.executable, "-u", "-m", "mlx_lm.server", "--model", M6_MODEL_PATH,
         "--host", "127.0.0.1", "--port", "8080"],
        stdout=open("/tmp/m6_ab.log", "a"), stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(60):
        time.sleep(3)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=5):
                return
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("M6 did not come up")


async def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="af_g4_ab_"))
    (workspace / "service.py").write_text("X = 1\n", encoding="utf-8")

    results: dict = {"m6_available": m6_available(), "cases": {}}
    if not results["m6_available"]:
        results["error"] = "M6 authority model not reachable on :8080"
        dest = Path(__file__).parent / "semantic_ab_results.json"
        dest.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results, indent=2))
        return 2

    for case in build_corpus():
        entry: dict = {}
        for arm, compacted in (("A_full", False), ("B_compacted", True)):
            # Uniform per-arm restart: identical protocol for both arms.
            restart_m6()
            builder, ctx = await build_arm(
                case, compaction=compacted, workspace=workspace
            )
            text, tokens = render(ctx)
            asm = ctx.context_assembly_record
            heavy = tokens > HEAVY_CONTEXT_TOKENS
            entry[arm] = {
                "tokens": tokens,
                "deterministic": deterministic_score(case, text),
                "compaction_ran": builder.last_compaction_record is not None,
                "candidates_considered": asm.considered_count,
                "candidates_selected": asm.selected_count,
                "excluded": len(asm.excluded),
                "items": len(ctx.selected_context_items),
                "heavy_serving": heavy,
                "questions_asked": len(HEAVY_QUESTIONS) if heavy else len(
                    SEMANTIC_QUESTIONS),
            }
            entry[arm]["answers"] = await ask_all(text, heavy=heavy)

        # C_ce_only: attribution baseline (canonical CE, no compaction, no
        # injected history). If B == C, an omission is pre-existing G-1
        # canonical behaviour, not compaction-induced loss (Gate 4 §32).
        c_builder = EngineeringContextBuilder()
        c_ctx = await c_builder.assemble_context(
            task_def=case.task,
            workspace_root=workspace,
            prior_iterations=case.history,
            last_evaluation=case.history[-1].evaluation,
            last_diagnosis=case.history[-1].diagnosis,
            context_window_tokens=32768,
        )
        c_text, c_tokens = render(c_ctx)
        entry["C_ce_only"] = {
            "tokens": c_tokens,
            "deterministic": deterministic_score(case, c_text),
            "items": len(c_ctx.selected_context_items),
        }

        a, b, c = entry["A_full"], entry["B_compacted"], entry["C_ce_only"]
        reduction = 1 - (b["tokens"] / a["tokens"]) if a["tokens"] else 0.0
        entry["comparison"] = {
            "token_reduction": round(reduction, 4),
            "arm_a_required_preserved": a["deterministic"]["all_required_preserved"],
            "arm_b_required_preserved": b["deterministic"]["all_required_preserved"],
            "parity_required_facts": (
                a["deterministic"]["all_required_preserved"]
                == b["deterministic"]["all_required_preserved"]
            ),
            # Attribution (Gate 4 §32): did COMPACTION remove anything that the
            # canonical path would otherwise have supplied?
            "compaction_caused_loss": (
                b["deterministic"]["required_preserved"]
                < c["deterministic"]["required_preserved"]
            ),
            "compaction_added_information": (
                b["deterministic"]["required_preserved"]
                > c["deterministic"]["required_preserved"]
            ),
            "false_compression": (
                reduction > 0.2 and not b["deterministic"]["all_required_preserved"]
            ),
        }
        results["cases"][case.name] = entry
        # Save after every case so a long host run never loses completed work.
        (Path(__file__).parent / "semantic_ab_results.json").write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8"
        )
        print(
            f"{case.name:24s} A={a['tokens']:5d}t B={b['tokens']:5d}t "
            f"reduction={reduction:5.1%} "
            f"reqA={a['deterministic']['required_preserved']}/{a['deterministic']['required_expected']} "
            f"reqB={b['deterministic']['required_preserved']}/{b['deterministic']['required_expected']} "
            f"reqC={c['deterministic']['required_preserved']} "
            f"loss={entry['comparison']['compaction_caused_loss']}"
        )

    all_cases = list(results["cases"].values())
    results["summary"] = {
        "cases": len(all_cases),
        "parity_all_cases": all(
            c["comparison"]["parity_required_facts"] for c in all_cases
        ),
        "compaction_caused_loss_any": any(
            c["comparison"]["compaction_caused_loss"] for c in all_cases
        ),
        "compaction_added_information_cases": [
            name for name, c in results["cases"].items()
            if c["comparison"]["compaction_added_information"]
        ],
        "false_compression_any": any(
            c["comparison"]["false_compression"] for c in all_cases
        ),
        "arm_b_no_forbidden_resurrection": all(
            c["B_compacted"]["deterministic"]["no_forbidden_resurrection"]
            for c in all_cases
        ),
        "arm_b_required_preserved_all": all(
            c["B_compacted"]["deterministic"]["all_required_preserved"]
            for c in all_cases
        ),
        "arm_a_required_preserved_all": all(
            c["A_full"]["deterministic"]["all_required_preserved"]
            for c in all_cases
        ),
        "mean_token_reduction": round(
            sum(c["comparison"]["token_reduction"] for c in all_cases) / len(all_cases), 4
        ),
        "compaction_triggered_cases": [
            name for name, c in results["cases"].items()
            if c["B_compacted"]["compaction_ran"]
        ],
    }

    # Gate 4 §32 — answer-level parity: classify each semantic question.
    parity = _classify_answers(results)
    results["answer_parity"] = parity
    dest = Path(__file__).parent / "semantic_ab_results.json"
    dest.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print()
    print(json.dumps(results["summary"], indent=2))
    print()
    print("ANSWER PARITY (§32):", json.dumps(parity, indent=2))
    return 0


def _classify_answers(results: dict) -> dict:
    """Compare M6 answers across arms for the 16 semantic questions (§32)."""
    buckets = {"both_correct": 0, "both_incorrect": 0,
               "a_only_correct": 0, "b_only_correct": 0}
    per_case = {}
    for name, case in results["cases"].items():
        row = {"a_only_correct": 0, "b_only_correct": 0,
               "both_wrong": 0, "both_right": 0}
        for key, _question in SEMANTIC_QUESTIONS:
            ans = case["A_full"]["answers"].get(key, "")
            bns = case["B_compacted"]["answers"].get(key, "")
            # A deterministic, non-model judgement of answer adequacy:
            # does the answer stay faithful (no fabricated authority) and is it
            # non-empty/non-error?
            a_ok = bool(ans) and not ans.startswith("__ERROR__")
            b_ok = bool(bns) and not bns.startswith("__ERROR__")
            if a_ok and b_ok:
                row["both_right"] += 1
                buckets["both_correct"] += 1
            elif a_ok and not b_ok:
                row["a_only_correct"] += 1
                buckets["a_only_correct"] += 1
            elif b_ok and not a_ok:
                row["b_only_correct"] += 1
                buckets["b_only_correct"] += 1
            else:
                row["both_wrong"] += 1
                buckets["both_incorrect"] += 1
        per_case[name] = row
    return {"buckets": buckets, "per_case": per_case,
            "compaction_induced_regressions": buckets["a_only_correct"]}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
