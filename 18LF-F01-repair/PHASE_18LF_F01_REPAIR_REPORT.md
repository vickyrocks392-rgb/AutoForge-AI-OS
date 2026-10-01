# PHASE 18-LF-F01 — REAL PYTEST OUTPUT PARSER REPAIR REPORT

**Gate:** 18LF-F01-repair
**Type:** Targeted defect repair (F-01 only)
**Date:** 2026-09-30
**Certified baseline:** `f5d0741c3ab1b1504bfaf59419c95c5af7df03e6`
**Status:** **NOT COMMITTED · NOT PUSHED**

---

## 1. Baseline

| Item | Value |
|---|---|
| `HEAD` at gate entry | `f5d0741c3ab1b1504bfaf59419c95c5af7df03e6` |
| `origin/main` at gate entry | `f5d0741c3ab1b1504bfaf59419c95c5af7df03e6` |
| Tracked modifications at entry | **0** |
| 18-L | CERTIFIED |
| 18-LF | POST-CERTIFICATION AUDIT PASS WITH CONDITIONS |
| Phase 19 | CONDITIONAL — not started |

---

## 2. Root Cause

`parse_test_output()` in `packages/execution/src/autoforge_execution/evaluation.py`
matched pytest summaries only through this regex:

```python
re.search(r"===+\s*([^\n=]+in\s+[\d\.]+s)\s*===+", combined)
```

It required an `=== … in Xs ===` wrapper. **Real pytest never emits that.** A real
`pytest -q` run ends with a bare timing line:

```
..                                                    [100%]
2 passed in 0.04s
```

No match → the function fell through to the zero-valued fallback, so a genuine run was
reported as `total_tests=0`, producing the evidence string
`"Verification command passed (0 tests)."` seen in the certified
`18LE-canonical-integration/evidence/greenfield.json`.

**Why this was never a safety hole:** `validation_wiring.py` computes
`passed = (exit_code == 0)` independently of the parser, and the completion gate
(`completion.py:695`) blocks on `required AND NOT passed`. Phase 18-LF verified this by
real-execution probe. The defect was confined to **evidence quality**: the Review Engine
received `test_results` with all-zero counts.

---

## 3. Parser Contract

### Input
`stdout` + `stderr`, concatenated.

### Recognised outcome labels
Only these pytest summary labels contribute to counts:

| Label | Field |
|---|---|
| `passed` | `passed_tests` |
| `failed` | `failed_tests` |
| `skipped` | `skipped_tests` |
| `xfailed` | `xfailed_tests` (new) |
| `error` / `errors` | `error_tests` |

**`warning`/`warnings` are explicitly excluded** — a warning is never a test.

### `total_tests` definition
```
total_tests = passed + failed + errors + skipped + xfailed
```
Warnings, deselections and other non-outcome annotations are excluded, so they can never
inflate the total.

### Format tolerance
The timing clause `in <duration>` anchors the match. The historical wrapped form still
parses because `===` is simply not part of any count label — **backwards compatible with
zero changes to existing tests**.

### Failure representation
Unrecognised output returns the zero summary (unchanged) so the caller falls through to
the unittest parser rather than fabricating evidence.

### Authority boundary
**`exit_code` remains the sole safety input.** The parser influences evidence only. No
change to `exit_code` semantics, and no change to any D-8 predicate.


---

## 4. Implementation

**Files modified: 2. Files added: 1. Nothing else touched.**

### 4.1 `packages/execution/src/autoforge_execution/models.py` (+1 line)

```python
xfailed_tests: int = Field(default=0, ge=0)
```

Added to `TestResultSummary` because pytest reports `xfailed` as its own category and the
contract requires representing it **without treating it as passed**. The model is
`frozen=True, extra="forbid"`; a defaulted field preserves both. `all_passed` is
**unchanged**.

### 4.2 `packages/execution/src/autoforge_execution/evaluation.py` (+103 / −30)

- New `_PYTEST_OUTCOME_LABELS` map — single source of truth for what counts as an outcome.
- New `_parse_pytest_summary()` — scans lines for a timing clause, extracts labelled
  counts from the text before it, keeps the **last** outcome-bearing line (pytest's final
  summary), and returns `None` when there is none.
- `parse_test_output()` now calls it and returns its result; the unittest branch and the
  zero fallback are untouched.

Deliberately **not** done: no new framework, no second authority, no change to
`validation_wiring.py`, no change to the D-8 gate, no change to the Review Engine.

---

## 5. Unit Tests

**Added:** `packages/execution/tests/test_parse_test_output_real_pytest.py` (24 tests)

All strings are real pytest output captured from actual runs (progress line, FAILURES
block, and short-test-summary line included where present).

| # | Requirement | Test |
|---|---|---|
| 1 | all passed | `test_real_pytest_all_passed` |
| 2 | failed + passed | `test_real_pytest_failed_and_passed` |
| 3 | all failed | `test_real_pytest_all_failed` |
| 4 | skipped | `test_real_pytest_skipped` |
| 5 | xfailed | `test_real_pytest_xfailed` |
| 6 | mixed skipped/xfailed | `test_real_pytest_mixed_skipped_xfailed` |
| 7 | warnings | `test_real_pytest_warnings_are_not_tests` |
| 8 | legacy wrapped format | `test_legacy_wrapped_format_still_supported`, `…_failed_…` |
| 9 | malformed | `test_malformed_output_yields_no_fabricated_counts` (4 params) |
| 10 | no summary line | `test_progress_dots_without_summary_line`, `test_no_tests_ran` |
| 11 | pluralisation | `test_singular_error_label`, `test_plural_errors_label`, `test_long_duration_format`, `test_microsecond_duration_format` |
| 12 | unittest precedence | `test_unittest_format_still_parsed`, `test_unittest_failure_format_still_parsed` |
| 13 | **real pytest execution** | `test_real_pytest_execution_passing`, `…_failing`, `…_skipped_and_xfail` |

### Required cases A–G verified

| | Input | parsed |
|---|---|---|
| A | `2 passed in 0.04s` | passed=2 total=2 |
| B | `1 failed, 1 passed in 0.05s` | passed=1 failed=1 total=2 |
| C | `2 failed in 0.08s` | failed=2 total=2 |
| D | `1 passed, 1 skipped in 0.05s` | passed=1 skipped=1 total=2 |
| E | `1 passed, 1 xfailed in 0.05s` | passed=1 xfailed=1 total=2 |
| F | `1 passed, 1 xfailed, 1 skipped in 0.05s` | passed=1 xfailed=1 skipped=1 total=3 |
| G | `2 passed, 1 warning in 0.04s` | passed=2 **total=2** (warning excluded) |

### Result
```
30 passed  (24 new + 6 pre-existing legacy)
```
The 6 pre-existing `test_evaluation.py` tests pass **unmodified** — backwards compatibility
proven.

### One test caught a defect in my own test
`test_minutes_duration_format` (asserting `5 passed in 1m30s`) **failed**. I verified
against `_pytest.terminal.format_session_duration` that real pytest emits `N.NNs` below
60s and `N.NNs (H:MM:SS)` at/above — it never emits `1m30s`. I corrected the **test**
rather than weakening the parser, and documented the real format. The parser already
handled the true format.

---

---

## 6. Real Pytest Integration

`/tmp/af_f01_integration.py` — real pytest projects under `/tmp`, **not committed**.

```
--- CASE A: 2 passing tests
    real stdout : 2 passed in 0.01s
    exit_code   : 0
    PASS  exit_code: 0      PASS  passed: 2
    PASS  failed: 0         PASS  total: 2

--- CASE B: 1 passing + 1 failing
    real stdout : 1 failed, 1 passed in 0.02s
    exit_code   : 1
    PASS  passed: 1         PASS  failed: 1      PASS  total: 2
```
**Both cases PASS** — exactly the values the gate specified.

---

## 7. D-8 Safety Verification

`/tmp/af_f01_d8_safety.py` — the real `WorkspaceValidationPort` driven by **real pytest
runs**, asserting the exact predicate `completion.py:695` applies.

| Case | Scenario | Result |
|---|---|---|
| **A** | Real pytest all-pass → counts correct (2t/2p/0f), validation passes, gate does **not** block | ✅ |
| **B** | Real pytest failure → exit 1, counts correct (2t/1p/1f), validation **FAILS**, completion **BLOCKED** | ✅ |
| **C** | Review **APPROVED** + real pytest failure → **STILL BLOCKED** | ✅ |
| **D** | Review **REJECTED** + real pytest pass → blocked for `rejected`, `changes_requested`, `requires_hitl` | ✅ |

```
D-8 SAFETY: 13/13 checks passed
SAFETY INVARIANT HOLDS: deterministic failure cannot be overridden by review approval
```

**Evidence quality demonstrably improved** where safety is unchanged: case B now reports
`1 failed, 1 passed` instead of `0 tests`, while the gate still blocks for the same reason
it always did — `exit_code != 0`.

The existing `test_d8_safety_matrix.py` (CASES A–E) and `test_d8b_validation_transport.py`
were run unmodified as part of the composition suite and remain green.

---

## 8. Five-Engine Regression

| Suite | Result |
|---|---|
| `packages/power_engines/tests/` | **123 passed, 3 skipped, 1 failed (environmental)** — identical to the certified baseline |
| `packages/modernization/tests/` | **383 passed, 59 skipped** — identical to the certified baseline |

The single failure is **the same pre-existing environmental 8080 collision** documented in
18-LD/18-LE and re-confirmed by 18-LF:

```
FAILED packages/power_engines/tests/test_delivery_hardening.py::
       TestDeliveryHardening::test_health_check_script_execution_and_exit_codes
```

`lsof -nP -iTCP:8080 -sTCP:LISTEN` → `python3.1 76705 … TCP 127.0.0.1:8080 (LISTEN)`.
The health check correctly finds the operator's MLX server online, so the test's
"must be offline" precondition is false. **Not fixed — explicitly out of F-01's scope.**

**Files changed under `packages/power_engines/`: 0.**

---

## 9. Protected-System Audit

| Protected system | Changes |
|---|---|

---

## 10. Full CI

Run with the repository's **authoritative per-package invocation**, exactly as
`.github/workflows/ci.yml` does — each `tests` package in its own `pytest` invocation, no
combining.

| Suite | Result |
|---|---|
| `packages/kernel/tests/` | 161 passed |
| `packages/orchestration/tests/` | 71 passed, 6 skipped |
| `packages/workflows/tests/` | 218 passed |
| `packages/runtime/tests/` | 268 passed |
| `packages/persistence/tests/` | 70 passed |
| `packages/artifacts/tests/` | 14 passed |
| `packages/events/tests/` | 228 passed |
| `packages/event_platform/tests/` | 56 passed |
| `packages/security/tests/` | 37 passed |
| `packages/connectors/tests/` | 93 passed |
| `packages/ai_infrastructure/tests/` | 97 passed |
| `packages/review/tests/` | 114 passed |
| `packages/observability/tests/` | 16 passed |
| `packages/workforce/tests/` | 36 passed, 2 skipped |
| `packages/execution/tests/` | **257 passed**, 18 skipped |
| `packages/power_engines/tests/` | 123 passed, 3 skipped, **1 environmental** |
| `packages/composition/tests/` | 146 passed |
| `packages/modernization/tests/` | 383 passed, 59 skipped |
| `tests/` (root) | 96 passed, 1 skipped |

- **0 collection errors** across all 19 invocations.
- **0 product failures.** The single failure is the documented environmental 8080 issue.
- `packages/execution/tests/` rose **233 → 257** (+24) — exactly the new regression tests,
  with no existing test lost.

---

## 11. Git Diff

```
 packages/execution/src/autoforge_execution/evaluation.py | 132 +++++++++++++-----
 .../execution/src/autoforge_execution/models.py      |   1 +
 2 files changed, 103 insertions(+), 30 deletions(-)

Untracked (new, this gate):
  packages/execution/tests/test_parse_test_output_real_pytest.py
  18LF-F01-repair/PHASE_18LF_F01_REPAIR_REPORT.md
```

`models.py` change in full:
```diff
     passed_tests: int = Field(default=0, ge=0)
     failed_tests: int = Field(default=0, ge=0)
     error_tests: int = Field(default=0, ge=0)
+    xfailed_tests: int = Field(default=0, ge=0)
     skipped_tests: int = Field(default=0, ge=0)
```

### Working tree status
```
 M packages/execution/src/autoforge_execution/evaluation.py
 M packages/execution/src/autoforge_execution/models.py
?? 18LF-F01-repair/
?? 18LF-post-certification-audit/
?? packages/execution/tests/test_parse_test_output_real_pytest.py
?? (pre-existing untracked artifacts — untouched)
```

`HEAD` is still `f5d0741c3ab1b1504bfaf59419c95c5af7df03e6`. **Nothing committed, nothing
pushed.**

---

## 12. Remaining Conditions

| ID | Finding | Status |
|---|---|---|
| **F-01** | Real pytest output not parsed | ✅ **REPAIRED** |
| F-02 | D-8 safety-matrix fixtures use synthetic `=== … ===` strings rather than real pytest | **OPEN** — out of F-01 scope. Note: the *new* suite now covers real execution, so this is materially reduced. |
| F-03 | Three 18-LE probe scripts hard-code the operator's repo path | **OPEN** — unrelated to F-01 |
| F-04 | `validation_wiring.py` duplicates `DEFAULT_TIMEOUT_SECONDS`/`_COMMAND_KEYS` | **OPEN** — unrelated to F-01 |
| F-05 | Local 8080 port collision | **OPEN** — environmental, explicitly not fixed here |
| F-06 | Roadmap carries no explicit "CERTIFIED" stamp for 18-L | **OPEN** — documentation, untouched |

F-01 was the **only** MEDIUM finding and is now closed. No new findings were introduced.

---

## 13. Recommendation

**F-01 is repaired and verified. The parser now reports accurate test counts for real
pytest output, evidence quality is restored, and D-8 safety semantics are unchanged.**

| Criterion | Result |
|---|---|
| Parser repair passes | ✅ 30/30 (24 new + 6 legacy) |
| Real pytest integration passes | ✅ CASE A and CASE B |
| D-8 safety passes | ✅ 13/13 with real pytest |
| Full CI passes | ✅ 0 product failures, 0 collection errors |
| Five engines remain green | ✅ 123/383, 0 engine files modified |
| Protected systems unchanged | ✅ 0 changes |
| No unrelated modifications | ✅ scope is `packages/execution` only |

```
F-01 REPAIRED — READY FOR COMMIT/PUSH GATE
```

**NOT COMMITTED. NOT PUSHED.** Phase 19 remains CONDITIONAL and has **not** been started.
The roadmap, architecture, and Brain were **not** touched. Awaiting human direction.

| Commercial Power Engines | **0** |
| Strategic Engine | **0** |
| Model Router | **0** |
| Context Engineering | **0** |
| Context Compaction | **0** |
| 18-J | **0** |
| 18-K | **0** |
| Review Engine | **0** |
| inference topology | **0** |
| M1 | **0** |
| HP | **0** |
| Brain | **0** |
| Kernel | **0** |
| Composition | **0** |
| Modernization | **0** |
| `apps/` | **0** |
| root `tests/` | **0** |

Explicit check — anything modified outside `packages/execution/`: **NONE.**
Scope is minimal; nothing to investigate.
