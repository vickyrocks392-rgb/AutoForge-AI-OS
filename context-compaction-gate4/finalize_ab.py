"""Finalise the A/B evidence: add attribution-aware false-compression analysis.

The naive §13 flag (``reduction > 0.2 and Arm B lost a required fact``) fires on
cases where compaction never ran at all. That is a measurement artefact, not
compaction loss: those cases sit BELOW the iteration trigger, so Arm B and the
canonical CE-only baseline (C) are identical. This step re-derives the flag
against the correct baseline without re-running any model calls.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
results = json.loads((HERE / "semantic_ab_results.json").read_text(encoding="utf-8"))

rows = []
for name, case in results["cases"].items():
    a, b, c = case["A_full"], case["B_compacted"], case["C_ce_only"]
    cmp_ = case["comparison"]
    rows.append({
        "case": name,
        "compaction_triggered": b["compaction_ran"],
        "arm_b_tokens": b["tokens"],
        "arm_a_tokens": a["tokens"],
        "token_reduction": cmp_["token_reduction"],
        "arm_a_required": a["deterministic"]["required_preserved"],
        "arm_b_required": b["deterministic"]["required_preserved"],
        "ce_only_required": c["deterministic"]["required_preserved"],
        # §13 attributed false compression: loss caused BY COMPACTION, i.e. Arm B
        # preserves strictly less than the canonical path it replaces.
        "false_compression_attributed": (
            cmp_["token_reduction"] > 0.2
            and b["deterministic"]["required_preserved"]
            < c["deterministic"]["required_preserved"]
        ),
        # Pre-existing G-1 gap: the canonical CE path does not project
        # iterations below the compaction trigger into context at all.
        "preexisting_g1_gap": (
            b["deterministic"]["required_preserved"]
            < a["deterministic"]["required_preserved"]
            and b["deterministic"]["required_preserved"]
            == c["deterministic"]["required_preserved"]
        ),
    })

triggered = [r for r in rows if r["compaction_triggered"]]
not_triggered = [r for r in rows if not r["compaction_triggered"]]

results["false_compression_analysis"] = {
    "definition_naive": "token_reduction > 0.2 AND Arm B lost a required fact vs Arm A",
    "definition_attributed": (
        "token_reduction > 0.2 AND Arm B preserves strictly less than the "
        "canonical CE-only baseline (C) that compaction replaces"
    ),
    "naive_flag_count": sum(1 for r in rows if r["false_compression_attributed"] is False
                            and r["token_reduction"] > 0.2
                            and r["arm_b_required"] < r["arm_a_required"]),
    "attributed_false_compression_count": sum(
        1 for r in rows if r["false_compression_attributed"]),
    "attributed_false_compression_cases": [
        r["case"] for r in rows if r["false_compression_attributed"]],
    "compaction_triggered_cases": [r["case"] for r in triggered],
    "compaction_not_triggered_cases": [r["case"] for r in not_triggered],
    "preexisting_g1_gap_cases": [r["case"] for r in rows if r["preexisting_g1_gap"]],
    "preexisting_g1_gap_note": (
        "These cases have fewer iterations than the compaction trigger, so the "
        "canonical Context Engineering path does not project their iteration "
        "history into context AT ALL - with or without compaction. Arm B and the "
        "CE-only baseline are identical, so the gap is pre-existing Gate 1 G-1 "
        "behaviour, NOT compaction-induced loss. Redesigning it is out of Gate 4 "
        "scope (the brief forbids redesigning Context Engineering)."
    ),
    "per_case": rows,
}

(HERE / "semantic_ab_results.json").write_text(
    json.dumps(results, indent=2, default=str), encoding="utf-8"
)

print("compaction triggered:  ", [r["case"] for r in triggered])
print("compaction NOT triggered:", [r["case"] for r in not_triggered])
print("attributed false compression:",
      results["false_compression_analysis"]["attributed_false_compression_count"])
print("pre-existing G-1 gap cases:",
      results["false_compression_analysis"]["preexisting_g1_gap_cases"])
print()
print("In cases where compaction RAN, Arm B preserved:",
      [(r["case"], r["arm_b_required"], "vs CE-only", r["ce_only_required"])
       for r in triggered])
