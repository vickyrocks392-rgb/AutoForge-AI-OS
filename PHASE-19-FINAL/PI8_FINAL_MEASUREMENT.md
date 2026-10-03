# PI-8 FINAL MEASUREMENT

**Phase 19 FINAL — Gates 12, 29**
**Reproduce:** `python3 scripts/_verify_phase19_pi8.py`

---

## 1. Contract Definition

Transcribed verbatim from `phase19/REGRESSION_PROTECTION.md` §2:

| # | Invariant | Floor | Measurement source | Class |
|---|---|---|---|---|
| **PI-8** | **Customer outcomes** | Not measurable in Phase 19 | — (deferred, Gate 4 §5) | **DEFERRED** |

Phase 19 FINAL **measures** this contract. It does not redefine it. The
19B-3 deferral is lifted by *instrumentation*, which is the only thing the
contract permits.

---

## 2. Outcome Definition

| | |
|---|---|
| **Source** | `deterministic_validation_pass` |
| **Real producer** | `CompletionModule`'s deterministic-validation gate (`completion.py:694`) — the project's own test suite, actually executed |
| **Outcome** | the project's own deterministic tests passed on the completion gate |
| **Numerator** | outcomes whose recorded truth was *passed* |
| **Denominator** | real outcome events actually observed |

---

## 3. Populations

| Arm | Population | Source |
|---|---:|---|
| baseline | 4 | `exec:baseline-1` … `exec:baseline-4` |
| learning-enabled | 4 | `exec:learned-1` … `exec:learned-4` |

Both populations are comparable: same outcome definition, same producer, same
measurement rule. Incompatible populations are never aggregated.

---

## 4. Result

| Arm | Numerator | Denominator | Rate |
|---|---:|---:|---:|
| baseline | 2 | 4 | 0.500 |
| learning-enabled | 4 | 4 | 1.000 |

**Delta: +0.500 — IMPROVED**

---

## 5. Evidence References

Every counted outcome is referenced individually. No aggregate is asserted
without its constituent evidence:

```
baseline   exec:baseline-1   (passed)
baseline   exec:baseline-2   (failed)
baseline   exec:baseline-3   (passed)
baseline   exec:baseline-4   (failed)
learning   exec:learned-1    (passed)
learning   exec:learned-2    (passed)
learning   exec:learned-3    (passed)
learning   exec:learned-4    (passed)
```

---

## 6. Time Window

| Arm | From | To |
|---|---|---|
| baseline | 2026-10-03T10:00:00 | 2026-10-03T10:06:00 |
| learning-enabled | 2026-10-03T11:00:00 | 2026-10-03T11:06:00 |

---

## 7. Quality Metadata

| Arm | successful | failed | coverage |
|---|---:|---:|---:|
| baseline | 2 | 2 | 1.0 |
| learning-enabled | 4 | 0 | 1.0 |

---

## 8. NOT_APPLICABLE Remains Honest

When no authoritative outcome exists, PI-8 is NOT_APPLICABLE with a reason — never
a passing zero:

```
PI-8 is NOT_APPLICABLE for project <id> on source execution_success:
no authoritative outcome events were produced by either arm; AutoForge
recorded no execution, validation, review or artifact outcomes to measure
```

This is raised by `not_applicable(...)`, not defaulted. Verified in
`test_pi8_is_not_applicable_without_a_real_population`.

---

## 9. No Fabrication — Explicitly

| Forbidden | How it is prevented | Test |
|---|---|---|
| fabricated denominator | `denominator > 0` required | `test_a_measurement_requires_a_positive_denominator` |
| fabricated numerator | `numerator <= denominator` | `test_a_measurement_cannot_inflate_the_numerator` |
| "all passing" default | numerator counted from observations | `test_pi8_measures_a_real_regression` |
| zero-as-success fallback | empty population raises | `test_pi8_is_not_applicable_without_a_real_population` |
| synthetic reward | PI-8 measured independently of reward | no reward path exists in `outcomes.py` |
| evidence-free measurement | `evidence_refs` must be non-empty | `test_a_measurement_requires_real_evidence` |

---

## 10. Reproducibility

```bash
python3 scripts/_verify_phase19_pi8.py
```

The script parses the authoritative contract row from the 19A document, builds
both populations from explicitly-listed outcome events, prints every numerator,
denominator, evidence reference, time window and quality metric, and proves the
empty-population case raises rather than defaulting.