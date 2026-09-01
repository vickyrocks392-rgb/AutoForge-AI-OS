# PHASE 18-E — Real Testing / Evaluation / Diagnosis / Repair

## Objective

Implement the complete production repair cycle within the existing EngineeringLoop, reusing all Phase 10/18-C infrastructure without duplication.

## Core Production Cycle

```
execute
→ evaluate
→ if failure:
   diagnose
   → retrieve scoped 18-D knowledge
   → generate repair plan
   → apply real code changes
   → re-execute
   → re-evaluate
→ bounded retry / final failure
```

## Mandatory Requirements

1. Diagnosis must reference actual failure evidence.
2. Repair must produce real file changes.
3. Before applying an edit, verify the expected target content/version still matches; never blindly overwrite files.
4. After repair, actually re-run the relevant execution/evaluation.
5. Repair success must be determined by real deterministic evaluation evidence.
6. RAG evidence used for repair must come from the real 18-D local Qdrant path and remain properly scoped.
7. Track diagnosis → repair → re-execution provenance across attempts.
8. Preserve bounded retry behavior.
9. A failed diagnosis/repair must never fabricate PASS.
10. No cloud/paid infrastructure. Everything must remain free/local/offline-capable.
11. No weakening or deleting existing tests.
12. Do NOT modify `architecture/ROADMAP.md`.
13. Do NOT implement 18-F or later phases.
14. Do NOT start Phase 19.

## Confidence Semantics

Real confidence requires empirical evidence. We define:

- **Confidence** (0.0-1.0): Estimated reliability of diagnosis/repair based on available evidence
- **Evidence-based**: Evidence count, RAG retrieval scores, pattern matches
- **Not statistical calibration**: We do NOT claim statistical calibration merely because an LLM returns a number

Clear semantics:
- 0.0-0.3: Low confidence — insufficient evidence, generic diagnosis
- 0.3-0.6: Medium confidence — some evidence, partial match
- 0.6-0.85: High confidence — strong evidence, clear root cause
- 0.85-1.0: Very high confidence — exact match, deterministic evidence

## Implementation Order

1. Extend diagnosis/repair models only where required.
2. Integrate the bounded repair cycle.
3. Integrate real 18-D evidence into repair.
4. Implement safe deterministic repair application.
5. Re-execute and re-evaluate.
6. Add provenance.
7. Add focused 18-E tests.
8. Add real end-to-end diagnosis → repair → validation test.
9. Run 18-C + 18-D regression tests.
10. Run adversarial/failure tests.

## STOP CONDITION

Implement and test the complete 18-E functionality, but DO NOT commit.

## Required Proof

Create tests proving:

```
real failure
→ real diagnosis
→ real RAG retrieval
→ real repair
→ actual file mutation
→ real re-execution
→ deterministic evaluation PASS
```

Also test:

- repair target mismatch
- empty repair
- invalid repair
- diagnosis failure
- RAG unavailable
- repeated repair failure
- retry bound
- provenance chain
- FAILED worker retry
- no-knowledge path
- existing 18-C regression
- existing 18-D regression
