# RECURSIVE LEARNING — PRODUCTION

**Phase 19 FINAL — Gate 17**

---

## 1. Generation N Observes Generation N-1

`RecursiveImprovement.run_until_bounded` runs generations until it hits a bound
or cannot improve. Each generation links to its predecessor:

```python
for previous, current in zip(generations, generations[1:]):
    assert current.lineage.parent_lineage_id == previous.lineage.lineage_id
    assert current.lineage.generation == previous.lineage.generation + 1
    assert current.trace.best_score > previous.trace.best_score
```

Lineage is a real chain, not a counter. Any generation can be traced back
through its parents to the observation that started the loop.

---

## 2. Termination Is Provable, Not Hoped For

Two independent bounds, and **both** are enforced:

| Bound | Behaviour |
|---|---|
| `max_recursion_depth` | the loop stops at exactly this generation |
| `max_experiments` | the loop stops even if depth allows more |

Tested: with depth 3 the loop produces generations `[0, 1, 2]` and stops. With
depth 9 but an experiment budget of 2, the **experiment budget wins** — the
tighter bound is honoured.

A generation that cannot improve ends the loop immediately. A stage that yields
nothing ends it after one generation. There is no unbounded search.

---

## 3. Resource Governance

`ResourceGovernor` bounds experiments, recursion depth, wall-clock time, model
calls, concurrency, disk, memory and network. Exhaustion raises
`BudgetExhausted` — it never silently continues.

Critically, exhaustion **does not stop the product**: `assert_core_path()`
remains `True` even when the learning budget is spent. Learning stops; AutoForge
does not.

---

## 4. No Recursive Authority Escalation

The prohibited loop is *learning → new permission → more learning*. Two
independent refusals:

| Attempt | Result |
|---|---|
| widen capability (add `network.outbound`, `security.modify`) | `AuthorityExpansionAttempted` |
| widen scope (project → global) | `AuthorityExpansionAttempted` |

Refusal happens before any work is performed. Recursion cannot bootstrap its own
permissions, so generation N+1 has exactly the authority generation N had.

---

## 5. Verified

| Test | Proves |
|---|---|
| `test_gate36_multi_generation_learning_terminates_at_its_bound` | Linked generations, bounded termination |
| `test_gate36_recursion_stops_when_a_generation_cannot_improve` | No endless search |
| `test_gate36_recursion_cannot_exceed_its_experiment_budget` | Tighter bound wins |
| `test_gate36_recursion_never_widens_authority` | No escalation |
| `test_infinite_recursion_terminates` | A null stage still terminates |
| `test_depth_overflow_raises` | Depth overflow fails closed |
| `test_resource_exhaustion_fails_safely` | Critical path preserved |
| `test_recursive_authority_escalation_is_refused` | Capability widening refused |
| `test_recursion_widening_scope_is_refused` | Scope widening refused |