"""Assemble the consolidated Gate 4 verification evidence (task §28)."""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent


def load(name: str):
    p = HERE / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pytest(pkg: str) -> str:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", f"packages/{pkg}/tests",
         "-p", "no:cacheprovider", "-q", "--no-header"],
        cwd=REPO, capture_output=True, text=True, timeout=1200,
    )
    last = [ln for ln in out.stdout.strip().splitlines() if ln.strip()]
    return last[-1] if last else "ERROR"


def main() -> int:
    det = load("preservation_results.json")
    perf = load("performance_results.json")
    ab = load("semantic_ab_results.json")
    limit = load("m6_context_limit.json")

    packages = ["execution", "runtime", "artifacts", "orchestration", "workflows",
                "kernel", "review", "observability", "persistence", "events",
                "event_platform", "connectors", "security", "ai_infrastructure",
                "modernization", "workforce", "composition"]

    regressions = {}
    for pkg in packages:
        regressions[pkg] = pytest(pkg)
        print(f"{pkg:20s} {regressions[pkg]}")

    evidence = {
        "gate": "18-L Context Compaction Gate 4",
        "verdict_inputs": {
            "deterministic_summary": det["summary"] if det else None,
            "answer_parity": ab["answer_parity"]["buckets"] if ab else None,
            "compaction_induced_regressions":
                ab["answer_parity"]["compaction_induced_regressions"] if ab else None,
            "false_compression_attributed":
                ab["false_compression_analysis"][
                    "attributed_false_compression_count"] if ab else None,
            "mean_token_reduction":
                ab["summary"]["mean_token_reduction"] if ab else None,
            "max_compaction_ms": perf["performance"]["max_compaction_ms"] if perf else None,
            "g1_resolved": perf["g1_reverification"]["g1_resolved"] if perf else None,
            "budget_pressure_classification":
                perf["budget_pressure"]["classification"] if perf else None,
        },
        "m6_runtime": {
            "model": "Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2",
            "endpoint": "http://127.0.0.1:8080/v1 (canonical local runtime port)",
            "role": "evaluation instrument only; not a production dependency",
            "context_limit_probe": limit,
        },
        "regression": regressions,
        "configuration_at_gate_close": {
            "context_engineering": "ON",
            "context_compaction": "OFF",
            "compaction_globally_enabled": False,
            "model_18j": "PROTECTED / RE-FROZEN",
            "model_18k": "PROTECTED",
            "inference_lab": "PROTECTED",
            "ollama_introduced": False,
            "committed": False,
            "pushed": False,
        },
    }

    (HERE / "verification_evidence.json").write_text(
        json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print("\nwrote verification_evidence.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
