# PRODUCTION LEARNING ARCHITECTURE

**Phase 19 FINAL — Gates 1, 2, 3, 4, 23**

---

## 1. What Was Built

19B-3 shipped an overlay that was implemented and tested but **not live**. The
kernel/execution/composition path still used the baseline fallback.

Phase 19 FINAL adds `production.py::ActiveLearningResolver` — the resolver that
makes learning a real consumer of the existing AutoForge execution path.

---

## 2. Design Rule: No Second Orchestration Engine

The existing orchestration engine remains authoritative. Learning attaches at
exactly one point: **where an execution is about to be prepared**.

It does not:
- create workflows, tasks, or queues
- re-dispatch work
- schedule anything
- own any lifecycle transition

It performs one bounded read and returns either a parameter set or nothing.

---

## 3. The Resolution Chain (Gate 2)

Each step fails closed to baseline:

| Step | Check | On failure |
|---|---|---|
| 1 | Target is in `LEARNABLE_TARGETS` | baseline |
| 2 | Target is not in `PROTECTED_TARGETS` | baseline |
| 3 | Resolver is enabled (store present) | baseline |
| 4 | Active learning exists | baseline *(healthy, not a degradation)* |
| 5 | Integrity — `content_hash` present | baseline, **degraded** |
| 6 | Scope — `state.project_id == project_id` | baseline, **degraded** |
| 7 | Revoked — no `deactivation_timestamp` | baseline |
| 8 | Not expired — `activation_timestamp <= now` | baseline, **degraded** |
| 9 | Authorization — external authorizer agrees | baseline, **degraded** |
| 10 | Compatibility — `state.kind == kind` | baseline, **degraded** |
| 11 | Apply parameters + emit provenance | **applied** |

Every degraded step records its reason in `resolver.degradations`. Absent
learning records nothing — it is the normal case, not a failure.

---

## 4. The Bounded Target Set (Gate 3)

Learning may influence exactly these, and nothing else:

| Target | Nature |
|---|---|
| `planning_heuristic` | which strategy the planner prefers |
| `prompt_strategy` | how a prompt is framed |
| `context_selection_strategy` | what context is selected |
| `retrieval_strategy` | how retrieval is performed |
| `tool_selection_heuristic` | which permitted tool is chosen |
| `repair_strategy` | how a defect is repaired |
| `workflow_optimization` | how a workflow is arranged |
| `model_selection_strategy` | which *already-permitted* model is chosen |

Every one is a **content or strategy choice inside a step that is already
authorized**. None can grant a capability, widen a scope, or alter a security
decision.

Permanently protected (`PROTECTED_TARGETS`): `authorization`, `authentication`,
`credential_scope`, `ai_guardrails`, `trust_boundary`, `hitl_policy`,
`governance_policy`, `security_policy`, `audit_policy`, `rollback_mechanism`,
`learning_authority_model`, `sandbox_enforcement`.

---

## 5. No Active Learning == Legacy AutoForge (Gate 4)

This is enforced, not asserted. `ProductionResolution.is_baseline` is true —
and `parameters is None` — for **every** one of these:

| Condition | Reason recorded |
|---|---|
| learning disabled | `learning is disabled; baseline behaviour` |
| learning absent | `no active learning for this project` |
| learning expired | `active learning is not yet active` |
| learning revoked | `active learning has been revoked` |
| learning corrupted | `active learning failed integrity verification` |
| wrong project | `active learning belongs to project X, addressed from Y` |
| incompatible | `active learning kind 'k' is incompatible with 'k2'` |
| unauthorized | `authorization refused learning <id>` |
| no authorizer | `no authorizer configured; learning not applied` |
| store unavailable | `learning resolver degraded to baseline behaviour (...)` |
| protected target | `target 'x' is permanently outside learning authority` |
| undeclared target | `target 'x' is not in the declared learnable set` |

A caller cannot distinguish "learning is off" from "learning was refused": both
produce identical, parameter-free behaviour.

---

## 6. Critical-Path Independence (Gate 23)

`resolve()` **never raises**. A learning outage degrades to baseline engineering
execution rather than stopping it. Proven for:

- learning store unavailable
- resolver's store raising
- malformed active state
- authorizer raising

The learning subsystem is optional relative to the critical path. That is the
whole point of the overlay: it can be entirely absent without changing how
AutoForge works.

---

## 7. The Resolver Grants No Authority

`assert_resolver_has_no_authority()` asserts the resolver exposes **none** of:
`promote`, `activate`, `deactivate`, `rollback`, `approve`, `authorize`,
`grant`, `escalate`, `set_policy`, `write`, `save`, `commit`.

Wiring learning into production execution therefore adds a bounded *read*, not
a capability. This is what makes the integration safe to ship.

---

## 8. Provenance Emitted (Gate 3)

When learning applies, `ExecutionDecisionProvenance` carries `learning_id`,
`version_id`, `candidate_id`, `project_id`, `activation_state`, `kind`, `key`,
`resolved_at` and `activated_at` into execution evidence, so any decision can be
traced to the exact learning version that produced it.