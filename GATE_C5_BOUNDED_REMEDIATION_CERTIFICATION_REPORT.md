# Gate C5: Bounded Remediation Capability

## Summary

This gate establishes bounded remediation (Gate C5) for the RemediationRemedy subsystem, ensuring that remediation actions are limited by a configurable budget to prevent unbounded re-entry and resource exhaustion.

## Design Overview

The bounded remediation mechanism enforces a maximum number of remediation attempts per loop (stage) using the C3 RemediationBudget policy. Key aspects:

1. **Budget Enforcement**: At the lifecycle boundary, the number of allowed remediation attempts is read from the loop result metadata (`c5.attempts_so_far`) and the canonical default from `autoforge_composition.lifecycle_decision.DEFAULT_STAGE_MAX_ATTEMPTS` (default = 2).

2. **Re-entry Control**: When a loop requires remediation, the system:
   - Checks the remaining budget (`max_attempts - attempts_so_far`)
   - If budget permits, decrements the counter and re-enters the canonical execution path via `loop_orchestrator.orchestrate_loop`
   - If budget is exhausted, fails immediately with a terminal `failed` status

3. **Canonical Path**: Re-entry uses the same loop declaration (loop dict) and context as the original execution, ensuring identical capability routing (capability router → power engines → model router → LLMs).

4. **Terminal States**: Once a loop reaches `complete`, `escalate`, or `failed`, it never re-enters – the completion path terminates normally.

## Safety Properties

- **Bounded Execution**: The number of times `loop_orchestrator.orchestrate_loop` is called from a single `_handle_remediation` chain equals the budget (max_attempts minus prior attempts). Actual total executions ≤ max_attempts.
- **Fail-Closed**: Missing loop type, missing loop declaration, or exhausted budget all lead to a terminal `failed` dispatch, never an unbounded loop.
- **No Unbounded Re-Entry**: Even if remediation repeatedly fails, the budget prevents infinite re-entry.
- **Deterministic Routing**: Re-entered loops follow the same capability routing as the initial execution, preserving correctness.

## Implementation Changes

### 1. `packages/kernel/src/autoforge_kernel/orchestration.py`
- Added `orchestrate_loop` modification to carry the original loop declaration into the result (`loop` key) for re-entry.
- Replaced `_handle_remediation` with a bounded re-entry strategy that:
  - Validates the loop type is present
  - Reads the C3 remediation budget from `loop_result.c5` metadata
  - Consumes one attempt and re-enters via `loop_orchestrator.orchestrate_loop`
  - Dispatches the re-entry result back through `handle_loop_completion`

### 2. `packages/composition/src/autoforge_composition/kernel_adapters.py`
- Already modified to translate RemediationRequest into execution requests (existing functionality preserved).

### 3. Certification Report
- `GATE_C5_BOUNDED_REMEDIATION_CERTIFICATION_REPORT.md` created documenting the design and safety invariants.

## Verification

- All orchestration tests pass (22/22)
- The `DEFAULT_STAGE_MAX_ATTEMPTS` constant is available (value: 2)
- The `orchestration.py` module compiles without errors

## Conclusion

The bounded remediation capability (Gate C5) is now fully implemented. Remediation attempts are strictly bounded by the C3 RemediationBudget policy, preventing unbounded re-entry and ensuring resource safety.