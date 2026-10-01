# Security Gap Analysis (GATE 0)

Every finding below was verified against the code at `617fef5`. Findings marked
**PROVEN** were reproduced with a runnable exploit before repair, not inferred.

Severity: **P0** = immediate production blocker · **P1** = production security
requirement · **P2** = architectural/future · **P3** = hardening backlog.

---

## SHG-01 — Tool allowlist not enforced at execution (P0) — **REPAIRED**

**Location.** `packages/power_engines/src/autoforge_power_engines/agent/tools.py`
→ `ToolRegistry.execute_tool`; consumed by
`agent/runtime.py::StandaloneAgentRuntime.run`.

**Defect.** `CustomerAgentSpecification.allowed_tools` was used only to decide
which tool *schemas* were advertised to the model. `execute_tool` validated only
that the tool name was registered:

```python
def execute_tool(self, name, arguments):
    if name not in self._tools or name not in self._handlers:   # registration only
        raise KeyError(...)
    handler = self._handlers[name]
    return handler(**arguments)
```

The `allowed_tools` value was never consulted. Any model-emitted tool call for a
*registered* tool executed, regardless of whether the agent was granted it.

**Impact.** A capability declaration was decorative. An agent restricted to a
calculator could reach `structured_http` (real outbound network I/O),
`file_read` (filesystem), or any other registered tool — a direct privilege
escalation from model output to network side effect.

**PROVEN exploit** (pre-fix, real network request issued):

```
SPEC allowed_tools: ['calculator']
model emitted tool: structured_http | in allowed_tools? False
EXECUTE_RESULT: {'url': 'http://example.com', 'status_code': 200, ... 'status': 'success'}
BYPASS_CONFIRMED: True
```

**Repair.** Added `authorize_tool_call()` and made `allowed_tools` a required
capability declaration enforced *immediately before* the side effect. Omitting it
fails closed. The runtime now passes `self.spec.allowed_tools` and treats a
blocked call as a security outcome (`blocked_by="tool_authorization"`), never as a
successful tool result.

**Post-fix verification:**

```
EXECUTE_RESULT: {'error': "No tool allowlist was supplied; refusing to execute
'structured_http' without an explicit capability declaration.",
'status': 'error', 'blocked_by': 'tool_authorization'}
BYPASS_CONFIRMED: False
```

**Regression tests.**
`packages/power_engines/tests/test_agent_power_engine.py`:
`test_04_unknown_tool_rejection`, `test_04b_tool_outside_allowlist_is_blocked`,
`test_04c_missing_allowlist_fails_closed`.

---

## SHG-02 — Credential expiry recorded but never enforced (P1) — **REPAIRED**

**Location.** `packages/security/src/autoforge_security/credentials.py`
→ `CredentialManager.get_credential`.

**Defect.** `CredentialMetadata.expires_at` was persisted and copied through
rotation, but `get_credential` checked only `is_revoked`. Time-bound credentials
therefore returned their secret indefinitely after expiry.

**PROVEN (pre-fix).** `CRED_EXPIRY_ENFORCED: False` — a credential expired one day
in the past still returned its secret value.

**Repair.** Expiry is now evaluated on every read (after the revocation check,
preserving revocation precedence). Naive datetimes are normalized to UTC so the
comparison is total. Revocation-by-expiry is immediate and cannot be bypassed by
holding a previously resolved reference.

**Regression tests.** `packages/security/tests/test_adversarial_security.py`:
---

## SHG-03 — No AI Guardrails layer (P1) — **REPAIRED**

**Defect.** No trust-level taxonomy, action classification, capability model, or
canonical enforcement boundary existed for AI-originated actions. Consequential
control existed only where a caller happened to remember to call
`SecurityPlatform.authorize`.

**Repair.** New `packages/security/src/autoforge_security/ai_guardrails.py`:
9-level ordered `TrustLevel`, 10-value `ActionClass`, 22-value `Capability`
taxonomy, 5-value `GuardrailDecisionType`, and `AIGuardrailsEngine.enforce()` as
the single canonical entry point. Composes with (does not replace) the certified
engines. Exposed on the certified facade as `SecurityPlatform.guardrails` and
`SecurityPlatform.enforce_ai_action()` (audited).

---

## SHG-04 — No trust-boundary metadata on untrusted context (P1) — **REPAIRED**

**Defect.** `StandaloneAgentRuntime.assemble_context` and
`GroundedContextBuilder.build_context` concatenated customer text, retrieved RAG
chunks, and tool output into model context with no source metadata, no
instruction-vs-data separation, and no neutralization. Retrieved content could
read as instruction; context compaction could erase provenance entirely.

**Repair.** New `packages/security/src/autoforge_security/trust_boundary.py`:
`TrustBoundary.segment()` tags every source with `TrustLevel` and a `kind`
(`INSTRUCTION` only for `SYSTEM_POLICY`), neutralizes 14 deterministic
instruction-injection idioms in DATA-only content, preserves markers through
`build_messages()`, and `redact_trust_from_compaction()` guarantees compaction can
never promote untrusted content to `INSTRUCTION`.

---

## SHG-05 — Self-improvement had no security boundary (P1) — **REPAIRED**

**Defect.** Nothing constrained a future Phase 19 learning subsystem from
granting itself permissions, credential access, network egress, or policy changes.

**Repair.** `AIGuardrailsEngine.evaluate_learning_proposal()` enforces the
propose-only contract. `LEARNING_FORBIDDEN_CAPABILITIES` explicitly names every
escalation path; proposals requesting them are denied. Permitted proposals must
still pass deterministic validation, security review, and human authorization
before promotion.

---

## SHG-06 — API has no authentication (P1) — **DEFERRED (documented)**

**Location.** `apps/api/src/autoforge_api/server.py`. No endpoint checks an
`Authorization` header; `/api/auth/me` returns a hardcoded PLATFORM_ADMIN identity.

**Mitigating factors.** The server binds `127.0.0.1` by default and is a
local-first single-user product. Responses are secret-redacted. Project ids are
path-sanitized (`_validate_project_dir`).

**Why deferred.** A correct fix requires an identity/session model bound to the
HTTP surface plus object-level authorization across ~40 endpoints — a Phase
20/23 architecture change. A partial token check would create false confidence
without a real identity substrate. Per the scope rule the remainder is
documented rather than half-built.

**Residual risk.** Any process able to reach the loopback port can drive the API.

---

## SHG-07 — No lockfile, SBOM, or dependency scanner (P3) — **DEFERRED**

**Defect.** Python workspace has no lockfile pinning, no SBOM generation, no
`pip-audit`/OSV integration.

**Why deferred.** Adding dependency scanning is a CI/SDLC change, not a runtime
security control, and no CVE data source is available in this environment. Per
instruction, **no CVE results are fabricated**. The exact gap and required
mechanism are recorded in `SECURITY_GAP_MATRIX.md`.

---

## SHG-08 — Artifact identity is not project-scoped (P2) — **DOCUMENTED**

**Location.** `packages/runtime/.../artifact_catalog.py` → `derive_artifact_key()`.

**Analysis.** The key omits `project_id`. Two projects sharing a
workflow/task/execution id and artifact name would derive the same UUID5 id.

**Why not changed.** `workflow_id` is `uuid.uuid4()` per execution
(`composition/kernel_adapters.py:126`), so a collision requires the *same* random
UUID across projects — not practical today. Changing key derivation would
invalidate durable artifact identity certified in 18-J/18-K and protected by the
scope rule. `list_artifacts(project_id)` already filters by project at query time.

**Disposition.** Documented as a Phase 20 multi-tenant architecture item.

---

## SHG-09 — Agent code generator emits unvalidated HTTP calls (P3)

**Location.** `packages/power_engines/.../agent/generator.py` emits
`requests.Session()` / `requests.post(url, ...)` into *generated* customer agent
code, which is not re-validated against `validate_outbound_url` at runtime.

**Mitigating factors.** Generated code is a deliverable, reviewed by the Review
Engine's `check_dangerous_execution` before delivery; the host platform is not
exposed.

**Disposition.** Backlog. Requires generated-code post-generation validation,
which would touch the protected Commercial Power Engine generator contract.

---

## Findings Summary

| ID | Severity | Area | Status |
|---|---|---|---|
| SHG-01 | **P0** | Tool/action authorization | **REPAIRED + tested** |
| SHG-02 | **P1** | Credential mediation | **REPAIRED + tested** |
| SHG-03 | **P1** | AI Guardrails layer | **REPAIRED + tested** |
| SHG-04 | **P1** | Trust boundary / injection | **REPAIRED + tested** |
| SHG-05 | **P1** | Self-improvement boundary | **REPAIRED + tested** |
| SHG-06 | P1 | API authentication | Deferred → Phase 20/23 |
| SHG-07 | P3 | Supply chain | Deferred → CI work |
| SHG-08 | P2 | Artifact identity scoping | Documented, no code change |
| SHG-09 | P3 | Generated-code egress validation | Backlog |

**P0 open: 0 · P1 open: 0 (1 deferred by scope rule) · P2: 1 · P3: 2**

`test_expired_credential_is_refused`, `test_unexpired_credential_is_returned`,
`test_credential_without_expiry_is_unaffected`, `test_revoked_credential_is_still_refused`.
