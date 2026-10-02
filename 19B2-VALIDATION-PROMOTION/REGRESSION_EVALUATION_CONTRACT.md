# Regression Evaluation Contract (M-08)

**Gate:** 19B-2 — Gates 3 & 4
**Implementation:** `invariants.py`, `evaluation.py`
**Architecture basis:** `phase19/REGRESSION_PROTECTION.md` (19A-8), `phase19/LEARNING_REVIEW_VALIDATION.md` (19A-12)

---

## 1. The nine invariants

Transcribed verbatim from 19A-8 §2. Nothing is added, renumbered, or
reclassified, and no scoring function replaces them.

| # | Invariant | Floor | Class | Required | Evidence prefix |
|---|---|---|---|---|---|
| PI-1 | Security | ZERO regression, zero tolerance | ABSOLUTE | yes | `security` |
| PI-2 | Deterministic validation | ZERO regression | ABSOLUTE | yes | `validation` |
| PI-3 | Review acceptance | No decline beyond pre-registered tolerance | CRITICAL | yes | `review` |
| PI-4 | Completion success | No decline beyond pre-registered tolerance | CRITICAL | yes | `completion` |
| PI-5 | Correctness | No decline in pass rate | CRITICAL | yes | `correctness` |
| PI-6 | Reliability | No increase in failure or retry rate | HIGH | yes | `reliability` |
| PI-7 | Latency & resource usage | No unbounded regression | HIGH | yes | `latency` |
| PI-8 | Customer outcomes | **Not measurable in Phase 19** | DEFERRED | **no** | `customer` |
| PI-9 | Isolation & authority integrity | ZERO regression | ABSOLUTE | yes | `isolation` |

`PROTECTED_INVARIANTS` is ordered, and `EvaluationReport` validates that its
results match that exact sequence. Dropping or reordering an invariant is a
`ValidationError` (`RM-02`).

## 2. Statuses

| Status | Meaning | Blocks promotion? |
|---|---|---|
| `PASS` | Measured, and not regressed | no |
| `FAIL` | Measured, and regressed | **yes** |
| `UNAVAILABLE` | Not measured, or the evidence is unusable | **yes** |
| `NOT_APPLICABLE` | The contract defers this invariant | only PI-8 |

There is deliberately no `SKIPPED`. An invariant that cannot be evaluated
reports `UNAVAILABLE`; it never disappears from the report.

### Why PI-8 alone may be N/A

19A-8 §2 records PI-8 as *deferred — not measurable in Phase 19* (Gate 4 §5).
Gate 3 permits an `UNAVAILABLE` invariant to proceed only "unless the 19A
contract explicitly defines that invariant as safely N/A". PI-8 is the one
such definition, so it is the sole member of `NA_PERMITTED_BY_CONTRACT`
(`test_only_pi8_may_be_not_applicable`).

## 3. Fail-closed decision rule

```
promotable(candidate) =
      (all 9 invariants were evaluated)
  AND (every required invariant has status PASS)
  AND (the only non-PASS is PI-8 as NOT_APPLICABLE)
```

Equivalently, the report is promotable iff no result `blocks_promotion`. This
is enforced *twice*: by the rules, and by a `model_validator` that refuses a
report whose `promotable` flag contradicts its own results.

## 4. No trading (`RM-01`)

Each invariant is decided independently by its own rule, then combined with
AND. There is no blended score, so a large gain on one invariant can never
compensate for a loss on another:

```python
# test_security_violation_disqualifies_despite_gains_everywhere_else
candidate_metrics = healthy_metrics(security_violations=1, latency_ms=1.0)
baseline          = healthy_metrics(latency_ms=10_000.0, failure_rate=0.9, ...)
assert report.result_for(PI7).status is PASS   # the gain is recorded honestly
assert report.promotable is False               # and does not compensate
```

## 5. Evidence requirements (Gate 4)

An invariant can only be evaluated when the evidence bundle carries at least
one **authoritative** reference for its prefix, and that reference must be:

| Check | Failure result |
|---|---|
| present for the invariant's prefix | `UNAVAILABLE` |
| content-hash length 64 (well-formed) | `UNAVAILABLE` |
| free of duplicate `source_ref` with differing hashes | `UNAVAILABLE` |
| newer than `MAX_EVIDENCE_AGE_SECONDS` (30 days) | `UNAVAILABLE` |
| suffixed with the candidate's own project id | `UNAVAILABLE` |
| not `EvidenceSource.NON_AUTHORITATIVE` (Q4 / model text) | `UNAVAILABLE` |

The evidence gate runs **before** the numbers are inspected. An invariant with
unusable evidence is `UNAVAILABLE` regardless of what the metrics say.

### No fabricated evidence

`build_evidence_refs` emits a reference only for a field that is actually
present. A metric that was never measured produces nothing — it is not
represented as an empty or zero-valued payload.

## 6. Baseline pinning (`RM-03` / `RM-05`)

The baseline is hashed into the report (`baseline_hash`, SHA-256 of the
canonical baseline metrics) and `baseline_pinned` is carried on the record. A
verdict is therefore bound to the baseline it was computed against.

## 7. Error behaviour

Any internal error fails closed: `EvaluationOutcome.ERROR`, every invariant
`UNAVAILABLE`, `promotable is False` (`test_evaluator_exception_fails_closed`).

## 8. Model confidence is not an input

`RegressionEvaluator.evaluate()` accepts a baseline, candidate metrics and
evidence references. There is **no** confidence parameter, and a Q4 evidence
reference is rejected outright. This is the structural replacement for the
19A GAP-06 tautology where `confidence >= 0.90` was a branch constant.

## 9. Known limitations

* Tolerances for CRITICAL/HIGH invariants are pre-registered as zero in this
  implementation; 19A-8 RM-04's tolerance machinery is modelled (the field
  exists per invariant) but no non-zero tolerance is configured. This is
  strictly *more* conservative than the contract permits.
* PI-8 is reported `NOT_APPLICABLE` rather than measured. This is the
  contract's own deferral, not an implementation shortcut.