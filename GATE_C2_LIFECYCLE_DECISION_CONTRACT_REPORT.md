# GATE C2 — LIFECYCLE DECISION CONTRACT REPORT

Status: **PASS** (decision model only; no production authority granted)
Date (UTC): 2026-10-05
HEAD: `0d37ef5702d10546fb8db2355107d578c101700a`

## 1. Exact files changed

* NEW: `packages/composition/tests/test_lifecycle_decision_contract.py`
  (21 focused C2 tests, T1–T10).
* NOT modified: `lifecycle_decision.py` (already satisfied the contract —
  verified, not rewritten), `lifecycle_taxonomy.py` (no defect found),
  `execution_outcome.py`, O-1, O-2, O-3, Kernel, Power Engines, workers,
  Model Router, API, modernization.
* Pre-existing tree state left as-is (`M kernel_adapters.py` = C6).
  No commit, no push.

## 2. Existing lifecycle semantics inspected

* O-2 `orchestration.py:225/236/248/260` — four literals
  complete/remediate/escalate/failed. Decision table matches 1:1.
* B2 `OutcomeStatus` — byte-identical values. Reused, not duplicated.
* O-1 `models.py:104-116` — `WAITING_FOR_HITL` reachable only from RUNNING,
  non-terminal. Stage taxonomy, NOT outcome vocabulary: the decision surfaces
  human need only via `requires_human_approval=True` on ESCALATE (T3/T8).
* C1 `LifecycleContractError` — `LifecycleDecisionError` subclasses it.
* B2 carry-forwards (zero `remediation_tasks` producers; no durable approval;
  no bounded O-2 retry) documented in module docstring; contract supplies
  determinism + explicit budget as data without executing anything.

## 3. Final decision contract

`LifecycleDecision` (frozen, extra=forbid): `status: OutcomeStatus`,
`attempt`, `remediation_allowed: bool`, `requires_human_approval`
(ESCALATE only), `terminal`, `reason` (evidence-derived).
`RemediationBudget` (frozen): 1-based `attempt`, `max_attempts`;
`exhausted` / `remaining`. `decide_lifecycle(outcome, *, budget)` is pure:
no I/O, dispatch, persistence, or model call.

## 4. Decision truth table

| Outcome | Budget | Decision | terminal | remediate? | human? |
|---|---|---|---|---|---|
| COMPLETE + passed | any | COMPLETE | true | no | no |
| COMPLETE + not passed | any | raise (refuse unverified success) | — | — | — |
| ESCALATE | any | ESCALATE | true | no | YES |
| FAILED | any | FAILED | true | no | no |
| REMEDIATE | attempt < max | REMEDIATE | false | YES | no |
| REMEDIATE | attempt >= max | FAILED (fail closed) | true | no | no |

Remediation never upgrades to COMPLETE; exhaustion never auto-succeeds;
ESCALATE never carries a retry permit.

## 5. Canonical-result / determinism / unwired proofs

* T9: no OutcomeStatus/ExecutionOutcome redefinition, no new Enum;
  `LifecycleDecision.status` annotation IS `OutcomeStatus`; every member maps.
* T5+T6: identical inputs give identical decisions (incl. serialised form,
  stable across wall-clock); AST scan finds no network/model imports; full
  sweep passes with socket monkeypatched to raise.
* T10: AST proves no production file imports `lifecycle_decision`;
  importing `composition_root` does not load it; repo grep confirms.

## 6. Tests executed / results

C2 NEW file: 21 passed. B2 contract: 34 passed. Kernel: 161 passed
(incl. completion gate + O-1 quarantine). Orchestration+workflows: 319
passed, 6 skipped. Execution+ai_infra: 354 passed, 18 skipped. Workforce +
capability routing: 45 passed. Modernization (minus golden-master): 585
passed, 59 skipped. Composition (all): 224 passed, 3 failed.

## 7. O-1 / O-2 / O-3 impact

NONE. No orchestrator, Kernel, API, Power Engine, worker, router,
compaction, context, or modernization file changed. `handle_loop_completion`
untouched. No remediation/retry/HITL built. No runtime, no second authority.

## 8. Environmental failures (pre-existing, unrelated)

The 3 composition failures all raise `ModelUnavailableError` / HTTP 404
against `http://127.0.0.1:8080/v1/chat/completions` (live model endpoint
unreachable here). C2's production diff is zero.

## 9. Carry-forward for C3 / C4 / C5

* C3: REMEDIATE carries attempt+permit as data; consumer/re-execution wiring
  not built. Exhausted→FAILED decided; wiring not.
* C4: `requires_human_approval` is declarative; no approval object,
  persistence, or resume built (durable-approval gap carries forward).
* C5: retry exists only as the `RemediationBudget` value type; no wiring.

## 10. Verdict

**PASS.** STOP — not proceeding to C3.

