# Security Architecture Review (GATE 1)

Traced the real runtime path, then verified each rung has a genuine enforcement
point. Corrections to the previous report are called out explicitly.

## Traced path

```
Human / API request
  → ApiAuthenticator.authenticate()          [apps/api/auth.py]        NEW
  → ApiAuthenticator.authorize_project()     [apps/api/auth.py]        NEW
  → SecurityPlatform.authorize()             [autoforge_security]      certified
  → TrustBoundary (context assembly)         [agent/runtime.py]        NEW wiring
  → AIGuardrailsEngine.enforce()             [autoforge_security]      b05d66a
  → authorize_tool_call()                    [agent/tools.py]          b05d66a
  → SandboxPolicyEngine / SecurityBoundaryGuard                       certified
  → validate_outbound_url + EgressPolicy     [security/egress.py]      NEW
  → CredentialManager (expiry + purpose)      [security/credentials.py] NEW
  → ProjectScopedArtifactAccess               [artifacts/scoped_access] NEW
  → execution → validation → review → completion → delivery            certified
  → AuditEngine / SecurityEventPublisher                                 certified
```

## Enforcement-point audit

| Rung | Real enforcement point? | Verdict |
|---|---|---|
| Model output cannot obtain authority | `TrustLevel` declared by platform; `enforce()` never reads model claims | **YES** |
| Model output cannot bypass authorization | `authorize_tool_call()` inside `execute_tool()`; runtime passes `spec.allowed_tools` | **YES** |
| Tool calls authorized at execution time | `execute_tool()` → `authorize_tool_call()`, fail-closed without allowlist | **YES** |
| Capabilities least-privileged | `ACTION_CAPABILITIES` per action class; missing capability → DENY | **YES** |
| Trust levels preserved through context | `assemble_context()` now routes every block through `TrustBoundary` | **YES (fixed this pass)** |
| Trust preserved through compaction | `redact_trust_from_compaction()` downgrades `INSTRUCTION`→`DATA` for non-system trust | **YES** |
| Self-improvement cannot grant authority | `evaluate_learning_proposal()` + `LEARNING_FORBIDDEN_CAPABILITIES` | **YES** |
| Credentials not accessed outside authorization | expiry + purpose binding + project binding in `get_credential()` | **YES** |
| Network actions cannot bypass egress controls | `EgressPolicy.enforce()` before transmission in `tool_structured_http` | **YES (fixed this pass)** |
| Security policy not modifiable by model output | no policy-mutation API; frozen models; governance changes from non-authoritative trust → DENY | **YES** |
| Review/validation/completion not bypassable | untouched; 114 review tests + 257 execution tests pass | **YES** |

## Correction to the prior report

The previous certification asserted criterion 13 ("guardrails actually enforced,
not merely documented") citing `enforce_ai_action()`. Tracing showed:

- `authorize_tool_call()` **was** genuinely enforced (inside `execute_tool`).
- `AIGuardrailsEngine` and `TrustBoundary` were **not** called from any
  production path — only from `packages/security` and tests.

That is an overstatement in the prior report, now corrected: this pass wires
`TrustBoundary` into the real `StandaloneAgentRuntime.assemble_context()` and
`EgressPolicy` into `ToolRegistry`, and both are proven by
`packages/power_engines/tests/test_runtime_security_integration.py`.

## What was deliberately NOT changed

| System | Reason |
|---|---|
| 18-L orchestrator completion/review gating | No concrete regression found; GATE 14 re-verified passing |
| 18-J/18-K durable artifact identity | Isolation added *above* the storage layer instead |
| Review Engine | Untouched; all tests pass |
| `Permissions` / `Roles` / `WorkerSecurityProfile` | Extended (capabilities), never replaced |
| Five Commercial Power Engines | Only `agent/` sub-package touched, for concrete security dependencies |

## Remaining architectural seams (documented, not hidden)

1. `enforce_ai_action()` is the canonical audited entry point but is not called
   from inside the orchestration engine's stage loop. Adding it there would
   reopen the protected 18-L contract without concrete evidence. The side-effect
   binding (`authorize_tool_call`) is already in place, so this is defence in
   depth, not a gap in the critical path.
2. `LocalArtifactStore.get()` remains unscoped for in-plane engine use; external
   consumers go through `ProjectScopedArtifactAccess` and the API authorization
   layer.
