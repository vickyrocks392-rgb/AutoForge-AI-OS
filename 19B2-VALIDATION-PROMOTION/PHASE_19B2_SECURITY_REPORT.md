# Phase 19B-2 — Security Report

**Gate:** 19B-2 — Gates 10, 11, 12
**Date:** 2026-10-02
**Baseline HEAD:** `b9c188c8c461854695b76d5148ec407d40bfbda7`

---

## 1. Verdict

```
SECURITY POSTURE: UNCHANGED OR STRONGER

No protected system was modified. No security control was weakened.
The learning subsystem gained strictly more gates than it had before,
and every one of them fails closed.
```

## 2. Gate 10 — AI Guardrails integration

### The boundary is still authoritative

`evaluate_learning_proposal()` remains the sole authority over proposals, and
`packages/security/src/autoforge_security/ai_guardrails.py` is **byte-identical
to the baseline** (`test_protected_system_is_untouched_by_19b2`).

19B-2 does not bypass the boundary — it *adds a second consultation*. The
boundary is invoked:

1. at proposal time (`LearningLifecycleService.create_candidate`), and
2. at promotion time (`PromotionService` Gate C), re-reading the candidate's
   requested capabilities from the store rather than trusting a cached copy.

### The learning system cannot gain any capability

Every capability in `LEARNING_FORBIDDEN_CAPABILITIES` is denied. All nine are
covered by the parametrised `test_every_forbidden_capability_is_denied`.

An unrecognised capability name is converted into an escalation attempt rather
than dropped, so the allow-list cannot be widened by inventing a name
(`test_an_unknown_capability_is_treated_as_an_escalation_attempt`).

### The forbidden list itself is intact

`LEARNABLE_PROPOSAL_KINDS` still contains exactly the five certified kinds.
Learning did not extend it (`test_only_the_five_certified_proposal_kinds_exist`).

### No mutation surface exists

* `AIGuardrailsEngine` exposes no `set_policy` / `mutate` / `reload` /
  `update_policy`.
* No learning module *calls* any such API — checked structurally via AST, not
  by substring, so a field named `approver_subject_type` cannot mask a real
  call (`test_no_module_grants_authority_to_a_model`).

## 3. Gate 12 — Learning authority

| Level | Name | Who may hold it | 19B-2 effect |
|---|---|---|---|
| L0 | Observe | automated | unchanged |
| L1 | Propose | automated | unchanged |
| L2 | Candidate | automated | unchanged |
| L3 | Validated | automated evaluation, **inactive** | evaluation implemented |
| L4 | Operational | **human approval required** | promotion implemented, HITL-bound |
| L5 | Security/policy | **outside learning** | unreachable |

### Level 5 remains unreachable

Three independent mechanisms:

1. **Type-level** (19B-1): `LearningCandidate._never_security_authority`
   refuses an L5 value.
2. **Gateway** (19B-1): an L5 request is denied with
   `GatewayDenialReason.L5_AUTHORITY_REQUEST`.
3. **Static** (19B-2): `test_the_learning_package_contains_no_level_5_assignment`
   walks the AST of every learning module and asserts no `authority=` keyword
   ever names L5.

### The model may only propose

`LearningLifecycleService` exposes no `auto_promote`, `auto_approve` or
`auto_rollback` (`test_the_model_may_only_propose_never_promote`).
`PromotionService` and `ApprovalCoordinator` take an explicit `Subject`, and
every path through them requires a HUMAN one.

### No security component was reimplemented

`test_no_parallel_security_or_audit_component_is_created` asserts that no
learning module defines a class named `AuditEngine`, `HITLManager`,
`AIGuardrailsEngine`, `AuthorizationEngine`, `GovernancePolicyEngine`,
`SecurityPlatform`, `Permission`, `Subject`, `AuthenticationService` or
`CredentialManager`.

19B-2 **binds** the existing components:

| Concern | Existing component used |
|---|---|
| Proposal boundary | `AIGuardrailsEngine.evaluate_learning_proposal` |
| Approval gate | `SecurityPlatform.request_approval` → `HITLManager.create_gate` |
| Approval decision | `SecurityPlatform.submit_approval_decision` → `HITLManager.submit_decision` |
| Approver validation | `GovernancePolicyEngine.validate_human_approver` |
| Resume token | `HITLManager.verify_resume_token` |
| Audit | `AuditEngine.record_security_event` + `SecretsManager.redact_structure` |

## 4. Security violations are disqualifiers, not signals

A security violation is **not** a negative score that can be traded off. It is
a hard failure:

```python
# PI-1 is a tripwire, not a weighted term.
if cand_v > 0:
    return InvariantStatus.FAIL   # regardless of every other metric
```

`test_security_violation_disqualifies_despite_gains_everywhere_else` proves a
candidate with a catastrophic security violation and an enormous latency gain
is still rejected, while the gain is still recorded honestly as `PASS` on PI-7.

## 5. Model confidence is never authoritative

* `RegressionEvaluator.evaluate()` has **no** confidence parameter.
* A Q4 (`EvidenceSource.NON_AUTHORITATIVE`) reference is rejected by the
  evidence assessor before any invariant is evaluated.
* `InvariantResult.model_annotation_authoritative` is typed `False`, so
  model text cannot become a verdict.
* `InvariantMetrics` fields are `Optional`; an unmeasured metric is `None`,
  not a favourable default.

## 6. Audit integrity

| Property | Mechanism | Test |
|---|---|---|
| 15 canonical events | `LearningAuditAction` | `test_all_fifteen_canonical_events_are_defined` |
| Uses the certified engine | delegates to `AuditEngine.record_security_event` | `test_audit_records_land_in_the_certified_audit_engine` |
| Lineage preserved | project, actor, timestamp, correlation, record ids | `test_audit_records_carry_lineage` |
| No secrets | `SecretsManager.redact_structure` + a defensive local key filter | `test_audit_details_are_redacted_by_the_certified_engine` |
| Audit failure is never a silent success | `strict=True` on success events | `test_injection_7_audit_emission_failure_is_never_a_silent_success` |
| Unavailable audit refuses to promote | `LearningAuditError` when no engine | `test_audit_without_an_engine_is_a_hard_failure` |

### The Gate 17 audit rule

The rule states an audit failure must never be *silently converted into a
successful promotion*. The implementation records **both** facts when the
commit succeeded but the audit did not:

* `PromotionRecord.state = PROMOTED` — the state change is real,
* `PromotionRecord.audit_failure_reason = "..."` — the audit is degraded,
* the caller receives `PromotionAuditError` — this is not a clean success.

No path exists in which a failed audit yields a clean `PROMOTED` return.

## 7. Gate 11 — Project isolation

Isolation is **structural**, not a filter:

* Records live under `<root>/<project_id>/`.
* `EvidenceRef.source_ref` is suffixed with the project id, so foreign
  evidence is detectable and rejected.
* Every read re-checks the envelope project *and* the payload project.
* There is no global listing API.

All five cross-project operations (read, evaluate, approve, promote, rollback)
fail closed, tested for both "same candidate id / different project" and
"different candidate id / different project" (`test_adversarial_isolation.py`).

## 8. Protected systems — verified untouched

`git diff --quiet HEAD` returns clean for every one of:

`ai_guardrails.py`, `hitl.py`, `governance.py`, `audit.py`,
`authorization.py`, `permissions.py`, `credentials.py`, `trust_boundary.py`,
`completion.py`, `artifact_catalog.py`, `physical_artifact_store.py`,
`artifacts/models.py`, `artifacts/store.py`, `review/engine.py`,
`composition_root.py`, `kernel/learning_engine.py`, `execution/engine.py`.

The complete tracked diff for this gate is three files, all in scope:

* `packages/learning/src/autoforge_learning/__init__.py` (exports)
* `packages/learning/README.md` (documentation)
* `.github/workflows/ci.yml` (CI wiring for the learning suite)

## 9. Residual risks and accepted limitations

| Risk | Assessment |
|---|---|
| No cryptographic signature on records | Records are SHA-256 content-addressed and tamper-*evident*, not tamper-*proof* against an attacker with write access to the store root. Matches the repository's existing artifact-catalog posture. |
| Single-process concurrency | Two processes sharing a store root are safe from torn writes (atomic replace) but are not serialised. A loser is rejected deterministically. No distributed-locking framework was introduced. |
| Audit degradation is recorded, not repaired | If the audit sink fails post-commit, the state change stands and is flagged. Automatic re-auditing is out of scope. |
| Tolerances are zero | CRITICAL/HIGH invariants currently admit no tolerance at all. Strictly more conservative than 19A-8 permits. |

## 10. Out of scope by instruction

No autonomous security-policy modification, credential change, permission
change, HITL bypass, Level 5 creation, or audit-policy change exists in this
gate. None is proposed, scaffolded, or reachable.