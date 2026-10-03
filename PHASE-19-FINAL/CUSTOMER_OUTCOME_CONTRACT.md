# CUSTOMER OUTCOME CONTRACT

**Phase 19 FINAL — Gates 11, 12**

---

## 1. The Problem Being Closed

19B-3 listed PI-8 as NOT_APPLICABLE because *trustworthy customer-outcome
instrumentation did not yet exist*. Inventing one would have created a reward
signal with no trustworthy source — exactly the reward-hacking hazard the phase
exists to prevent.

So Phase 19 FINAL did two things, in order:

1. **Identified the authoritative outcome sources AutoForge already produces.**
2. **Measured PI-8 from those real events**, with no fabrication.

---

## 2. The Authoritative Outcome Sources

Every source is an outcome AutoForge **already records during normal
operation**. `test_the_outcome_sources_name_real_autoforge_producers` asserts
each named method exists on the real `DashboardManager`.

| `OutcomeSource` | Real producer |
|---|---|
| `execution_success` | `DashboardManager.record_execution_completed` / `record_execution_failed` |
| `worker_success` | `DashboardManager.record_worker_completed(success=...)` |
| `deterministic_validation_pass` | `CompletionModule`'s deterministic-validation gate (`completion.py:694`) — the project's own tests, actually executed |
| `review_accepted` | `DashboardManager.record_review_completed(passed=...)` |
| `artifact_published` | `DashboardManager.record_artifact_published` |
| `task_completed` | `DashboardManager.record_task_completed` |
| `model_call_success` | `DashboardManager.record_model_call(success=...)` |

These are read from AutoForge's existing observability read models. Nothing is
synthesised, and no new channel was built.

---

## 3. What the Contract Requires

The authoritative 19A contract (`phase19/REGRESSION_PROTECTION.md` §2) defines
PI-8 as **Customer outcomes**, class **DEFERRED**. Every measurement preserves
everything that contract needs:

| Requirement | Field |
|---|---|
| population | `population_size` |
| baseline | `arm == "baseline"` |
| treatment | `arm == "learning_enabled"` |
| outcome definition | `outcome_definition` |
| numerator | `numerator` |
| denominator | `denominator` |
| quality metadata | `quality_metadata` (successful, failed, coverage) |
| evidence references | `evidence_refs` |
| time window | `window_start`, `window_end` |
| project | `project_id` |
| learning version | `learning_version_id` |

`outcome_rate` is **derived**, never supplied.

---

## 4. Rules That Make Fabrication Impossible

These are enforced by the type, not by review:

1. **No fabricated denominator.** `denominator > 0` is required. An empty
   population raises `OutcomePopulationEmpty`, never "0.0 means success".
2. **No inflated numerator.** `numerator <= denominator`.
3. **No evidence-free measurement.** `evidence_refs` must be non-empty — a
   measurement with no evidence cannot be constructed at all.
4. **No zero-as-success fallback.** There is no code path that produces a
   passing measurement from absent data.
5. **No default population.** Nothing is imputed to fill a gap.
6. **No synthetic reward.** PI-8 is measured independently of the reward
   mechanism; a reward cannot be invented to satisfy it.

---

## 5. NOT_APPLICABLE Is a First-Class Outcome

When a workload genuinely has no authoritative outcome data, PI-8 is
**NOT_APPLICABLE with an explicit reason**:

```
PI-8 is NOT_APPLICABLE for project <id> on source execution_success:
no authoritative outcome events were produced by either arm; AutoForge
recorded no execution, validation, review or artifact outcomes to measure
```

This is raised, not defaulted. A caller cannot mistake "no data" for "all
passing".

---

## 6. The Result

PI-8 is measured on real populations — see `PI8_FINAL_MEASUREMENT.md` for the
reproducible report. In short: the certification includes **at least one real
AutoForge workload** for which PI-8 is genuinely measurable, measured on
outcome events AutoForge actually produced.