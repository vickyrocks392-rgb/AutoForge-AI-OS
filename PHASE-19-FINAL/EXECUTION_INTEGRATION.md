# EXECUTION INTEGRATION

**Phase 19 FINAL — Gates 1, 3, 4**

---

## 1. Where Learning Attaches

Learning resolves at exactly one point in the production path:

```
Request → Kernel → Strategic → Workflow → Execution
                                        ↓
                          ┌─────────────────────────┐
                          │ Active Learning         │
                          │ Resolution             │
                          │  (bounded read)        │
                          └─────────────────────────┘
                                        ↓
                          Learning Application
                                        ↓
                              Execution runs
                                        ↓
                          Evidence → Validation → Review → Completion
```

This is a **consumer** point, not an orchestration point. Learning reads the
active pointer and contributes parameters; the existing engine decides
everything else.

---

## 2. Required Path

Per the integration contract, the path is:

```
Request → Kernel → Strategic → Workflow → Execution
      → Active Learning Resolution → Learning Application → Execution
      → Evidence → Validation → Review → Completion
```

Learning appears twice, and only as a bounded read:
1. **Resolution** — what is active for this project/target?
2. **Application** — apply those parameters to the already-authorized step.

It creates no workflow, no task, no queue entry, and no lifecycle transition.

---

## 3. What Learning May Actually Change

The chosen target is **`prompt_strategy`** for the primary demonstration,
supported by the other seven entries in `LEARNABLE_TARGETS`.

Concretely: learning supplies a parameter set that a workflow step consumes.
It cannot:
- change which capabilities a step requests
- change an authorization decision
- widen a project or resource scope
- alter a security or guardrail verdict
- skip a validation, review, or HITL gate

---

## 4. Backward Compatibility (Gate 4)

Run the same workload twice:

| Configuration | Result |
|---|---|
| **A. learning disabled** (`store=None`) | `parameters=None`, baseline behaviour |
| **B. no learning installed** (empty store) | `parameters=None`, baseline behaviour |

Both are byte-identical from the caller's perspective. There is no third
"degraded" behaviour a caller has to handle: degradation *is* baseline.

The learning package is additive. `build_autoforge_system()` composes exactly
as before; learning simply now has a live consumer.

---

## 5. Evidence and Audit

When learning applies, the execution emits provenance into evidence/audit:

```json
{
  "learning_id": "pattern_template:default",
  "version_id": "<uuid>",
  "candidate_id": "<uuid>",
  "project_id": "<uuid>",
  "activation_state": "full",
  "kind": "pattern_template",
  "key": "default",
  "resolved_at": "<iso8601>",
  "activated_at": "<iso8601>"
}
```

So an auditor can answer "which learning version decided this execution?" from
the execution record alone.

---

## 6. Verified Behaviour

| Test | Proves |
|---|---|
| `test_learning_disabled_is_baseline` | Configuration A behaves as legacy |
| `test_no_active_learning_is_baseline` | Configuration B behaves as legacy |
| `test_authorized_learning_is_applied_with_provenance` | Real application + full provenance |
| `test_protected_targets_are_permanently_not_learnable[12]` | No authority surface is learnable |
| `test_the_resolver_exposes_no_authority` | Integration adds no capability |
| `test_learning_outage_never_stops_engineering_execution[2]` | Critical path independent |
| `test_the_complete_real_production_learning_loop` | The whole path, real components |