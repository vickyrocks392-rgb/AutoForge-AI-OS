"""Gate 4 evidence extractor — summarise ab_results.json for the report."""
import json
from pathlib import Path

data = json.loads(Path(__file__).with_name("ab_results.json").read_text())

print("=== MSC record at the largest corpus scale ===")
row = next(
    r
    for r in data["per_task"]
    if r["distractor_items_in_full_context"] == 20
)
rec = row["arm_B_context_engineering"]["msc_record"]
print(f"task: {row['task']}")
for k, v in rec.items():
    print(f"  {k}: {v}")

print()
print("=== Per-scale headline ===")
for scale, block in data["summary_by_scale"].items():
    a = block["arm_A_full_context"]
    b = block["arm_B_context_engineering"]
    d = block["delta"]
    print(
        f"distractors={scale:>2} | "
        f"tok A={a['mean_prompt_tokens']:>6.1f} B={b['mean_prompt_tokens']:>6.1f} "
        f"({d['prompt_tokens_pct']:>6.2f}%) | "
        f"prefill A={a['mean_prompt_ms']:>6.2f} B={b['mean_prompt_ms']:>6.2f} "
        f"({d['prompt_ms_pct']:>6.2f}%) | "
        f"recall A={a['mean_required_recall']:.3f} B={b['mean_required_recall']:.3f} "
        f"(d={d['required_recall_delta']:+.3f}) | "
        f"leaks A={a['mean_distractor_leaks']:.2f} B={b['mean_distractor_leaks']:.2f}"
    )

print()
print("=== Per-task required-fact recall (identical across arms?) ===")
for r in data["per_task"]:
    a = r["arm_A_full_context"]["score"]
    b = r["arm_B_context_engineering"]["score"]
    print(
        f"scale={r['distractor_items_in_full_context']:>2} {r['task']:<14} "
        f"A={a['required_recall']:.2f} missing={a['missing_facts']} | "
        f"B={b['required_recall']:.2f} missing={b['missing_facts']}"
    )

print()
print("=== Sample answers (Arm B, MSC) ===")
r0 = data["per_task"][0]
print("TASK:", r0["task"])
print("A:", r0["arm_A_full_context"]["answer"][:300].replace("\n", " "))
print("B:", r0["arm_B_context_engineering"]["answer"][:300].replace("\n", " "))
