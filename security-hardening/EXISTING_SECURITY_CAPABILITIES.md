# Existing Security Capabilities Inventory (GATE 0)

Phase 18-Security is CERTIFIED and must not be rebuilt. This document records what
already exists, where it lives, and its enforcement quality, so that the gap
analysis does not duplicate working controls.

## 1. Certified Security Platform — `packages/security` (`autoforge-security`)

| # | Capability | Module | Status | Notes |
|---|---|---|---|---|
| 1 | Identity & subject model | `identity.py`, `models.Subject` | **Existing** | `HUMAN` / `SERVICE` / `WORKER` / `ANONYMOUS`; frozen, `extra="forbid"` |
| 2 | Authentication (password) | `authentication.py` | **Existing** | Token issuance/validation, brute-force defense |
| 3 | Session lifecycle | `models.Session` | **Existing** | TTL, expiry, `is_revoked` |
| 4 | API keys | `models.CredentialType.API_KEY` | **Existing** | Managed via `CredentialManager` |
| 5 | RBAC & fine-grained authz | `authorization.py`, `roles.py`, `permissions.py` | **Existing** | 40+ permissions, canonical roles, contextual project scoping |
| 6 | Governance policy engine | `governance.py` | **Existing** | Deterministic `ALLOW`/`DENY`/`REQUIRE_HITL`/`REQUIRE_ELEVATED_ROLE` |
| 7 | HITL approval | `hitl.py` | **Existing** | Gates, expiry, replay protection, signed resume tokens |
| 8 | Secrets management | `secrets.py` | **Existing** | `SecretValue` with permanently redacted `__str__`/`__repr__` |
| 9 | Credential storage | `credentials.py` | **Existing** | In-memory + XOR "encrypted" local store, rotate/revoke |
| 10 | Recursive secret redaction | `secrets.redact_structure` | **Existing** | Applied to audit records and API responses |
| 11 | Sandbox policy | `sandbox.py` | **Existing** | Workspace confinement, traversal + dangerous-command filters, env sanitization |
| 12 | Worker security profiles | `worker_guard.py` | **Existing** | 23 profiles, read-only / propose-only / legacy flags |
| 13 | Audit trail | `audit.py` | **Existing** | Correlated by project/workflow/task/worker/execution/trace |
| 14 | Security events | `events.py` | **Existing** | Canonical event bus integration (`TASK_UPDATED`, `APPROVAL_*`) |
| 15 | Unified facade | `engine.SecurityPlatform` | **Existing** | Orchestrates all subsystems; used by downstream packages |

**Certified control count: 15. None were replaced, removed, or weakened by this pass.**

## 2. Adjacent Security Controls Outside `packages/security`

These are real, working controls found during the forensic audit. They are
recorded so the gap analysis credits them rather than re-implementing them.

| Control | Location | Enforcement quality |
|---|---|---|
| `SecurityBoundaryGuard` (argv-only, interpreter deny, metachar deny, cwd confinement) | `packages/orchestration/src/autoforge_orchestration/security.py` | **Strong.** Repaired in Phase 18-Security (SEC-03). Denies `bash -c`, `env`, `xargs`, `su`. |
| Sandbox image probe (argv-only, no shell) | `packages/execution/src/autoforge_execution/sandbox/provider.py` | **Strong.** Repaired in Phase 18-Security (SEC-01). |
| `SafeExecutionRunner` (allowlist, jail, no `shell=True`) | `packages/power_engines/src/autoforge_power_engines/migration/safety.py` | **Strong** |
| `validate_outbound_url` (SSRF: loopback, RFC1918, link-local, DNS resolution, redirect re-validation) | `packages/power_engines/src/autoforge_power_engines/agent/tools.py` | **Strong.** Post-resolution re-check; redirects re-validated per hop. |
| `validate_workspace_path` (traversal, symlink, `.ssh`/`.env`/`.git`) | `packages/power_engines/src/autoforge_power_engines/agent/tools.py` | **Strong** |
| `SafetyConstraintsConfig` (`deny_shell`, `deny_arbitrary_python`, `path_confinement`, `deny_private_networks`, `allowed_domains`) | `packages/power_engines/.../agent/spec.py` | **Strong** as a *declared* constraint — see SHG-01 for the enforcement gap. |
| Review-engine dangerous-execution checks (`os.system`, `shell=True`, `exec`, pickle, unsafe YAML) | `packages/review/src/autoforge_review/checks.py` | **Strong** — deterministic static analysis. |
| Review / validation / completion gates | `packages/review`, `packages/orchestration` | **Strong** |
| Durable artifact identity (UUID5 from workflow/task/execution/name) | `packages/runtime/.../artifact_catalog.py` | **Strong** (see SHG-08 for scoping note) |
| RAG grounding + numeric-consistency audit | `packages/power_engines/.../rag/grounding.py` | **Partial** — grounding exists, trust boundary did not (SHG-04). |
| API response secret redaction | `apps/api/src/autoforge_api/redaction.py` | **Strong** |
| Project-id path sanitization (`basename`, `..` rejection) | `apps/api/.../runtime_manager._validate_project_dir` | **Strong** |

## 3. What Was Genuinely Absent Before This Pass

Confirmed by direct inspection and empirical probing:

1. **No AI Guardrails layer.** No trust-level taxonomy, no action classification,
   no capability model, no canonical enforcement entry point for AI-originated
   actions. `grep -ri guardrail` matched only `packages/security/README.md`.
2. **No execution-point tool authorization.** `ToolRegistry.execute_tool`
   verified only *registration*, not the agent's `allowed_tools`.
3. **No trust-boundary metadata.** `StandaloneAgentRuntime.assemble_context` and
   `GroundedContextBuilder.build_context` spliced untrusted text into prompts with
   no source/trust markers and no instruction-vs-data separation.
4. **No self-improvement security boundary.** Nothing constrained a Phase 19
   learning subsystem from self-granting capabilities.

## 4. Disposition

The certified platform was **extended**, never forked. New modules
(`ai_guardrails.py`, `trust_boundary.py`) sit *above* the certified engines and
delegate authority decisions to them; they add no parallel authorization,
governance, sandbox, secrets, or audit implementation.
