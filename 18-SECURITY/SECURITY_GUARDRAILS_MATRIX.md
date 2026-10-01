# SECURITY GUARDRAILS MATRIX

**Phase:** 18-SECURITY
**Date:** 2026-02-10

Status legend: **PASS** = proven by code + test · **REPAIRED** = was a defect,
now fixed with regression coverage.

---

## 1. Security Invariant Contract (S-01 … S-18)

| ID | Invariant | Enforcement seam | Evidence | Status |
|---|---|---|---|---|
| **S-01** | User input must not obtain unintended privileged execution | API handler + `SecurityBoundaryGuard` + sandbox | `TB-01`, `TB-03` | PASS |
| **S-02** | Model output never becomes trusted executable authority | Deterministic validation precedes every exec | `TB-04/05` | PASS |
| **S-03** | Commands execute only through approved execution boundaries | `SecurityBoundaryGuard`, `SafeExecutionRunner`, argv-only subprocess | SEC-01/02/03 repaired | **REPAIRED** |
| **S-04** | Filesystem ops confined to authorized workspace | `resolve_artifact_path` / `resolve_staging_path` | probe: traversal denied | PASS |
| **S-05** | Path traversal must not escape authorized roots | `resolve()` + `is_relative_to()` before any I/O | probe: traversal + symlink denied | PASS |
| **S-06** | Project A cannot access Project B's durable state | workflow/project-scoped `derive_artifact_key` + store roots | §4 isolation probe | PASS |
| **S-07** | Artifact identity and content integrity deterministic | UUID5 `artifact_id_for_key` + `validate_integrity` | `TB-11` | PASS |
| **S-08** | Secrets never exposed via context, logs, artifacts, reports | `SecretManager.redact_*`, `redaction.py`, env allowlist | secret scan + redaction tests | PASS |
| **S-09** | Review approval must not override deterministic security failures | `completion.py` DEF-18LR-D8 guard | `TB-13/14` | PASS |
| **S-10** | Validation success must not override security-policy violations | deterministic gate runs after review, blocks | `completion.py:686-705` | PASS |
| **S-11** | A security-check failure must fail closed | `except Exception → _finalize_stage_failure`; `evaluate_final_review_result` | `TB-03` | PASS |
| **S-12** | Missing security evidence ≠ approval | empty evidence → `no_target` verdict, not approval | `completion.py:212` | PASS |
| **S-13** | Tool permissions explicit and bounded | `ALLOWLISTED_COMMANDS`, env allowlist, `NetworkMode`, container caps | `TB-17/18` | PASS |
| **S-14** | Network access no broader than capability boundary | `NetworkMode.DENY` → `--network none` | `provider.py:382-385` | PASS |
| **S-15** | Autonomous execution recoverable and attributable | durable stores, idempotency, audit trail | `TB-21` | PASS |
| **S-16** | Security decisions must be auditable | typed `VerificationCommandError` + `details` | **SEC-02 repaired** | **REPAIRED** |
| **S-17** | Untrusted paths/commands/URLs/args/config must not bypass validation | per-boundary validators, no LLM authority | `TB-02/05/06/07` | PASS |
| **S-18** | Completion must not occur when a mandatory security gate fails | `finalize_project` gate ordering | `completion.py:637-705` | PASS |

**S-01 … S-18: 18/18 satisfied** (15 proven PASS, 3 proven REPAIRED).

---

## 2. Command Execution Boundaries

| Seam | Control | Result |
|---|---|---|
| `orchestration/security.py` | argv-only; metacharacter deny; forbidden-pattern deny; cwd confinement; **interpreter deny (new)** | ENFORCED |
| `power_engines/migration/safety.py` | `ALLOWLISTED_COMMANDS`, `DANGEROUS_PATTERNS`, sanitized env, timeout, output cap, `shell=False` | ENFORCED |
| `execution/sandbox/provider.py` | argv-only container run; `--cap-drop ALL`; `--user 1000`; `no-new-privileges`; read-only root | ENFORCED |
---

## 3. Filesystem Boundaries

| Control | Location | Result |
|---|---|---|
| Artifact root confinement | `PhysicalArtifactStore.resolve_artifact_path` | ENFORCED |
| Staging root confinement | `PhysicalArtifactStore.resolve_staging_path` | ENFORCED |
| Symlink rejection on publish | `atomic_publish` rejects symlink target | ENFORCED |
| Quarantine boundary | `quarantine` requires artifact/staging root, rejects symlinks | ENFORCED |
| Catalog traversal re-check | `commit_artifact` `is_relative_to` assertions | ENFORCED |
| Workspace cwd confinement | `SecurityBoundaryGuard.validate_command(cwd=…)` | ENFORCED |
| Container workspace mount | single `-v <ws>:/workspace:rw`, `-w /workspace` | ENFORCED |

Checks execute **before** the sensitive filesystem operation.

---

## 4. Project Isolation

`derive_artifact_key` scopes identity by workflow/task/execution + name, and
`artifact_id_for_key` is UUID5 over a fixed namespace. Different workflows
therefore yield different keys/IDs (verified). Production
(`artifacts/durable_bridge.py:80,175`) always passes `workflow_id=project_id`,
so two projects cannot collide.

**Accepted limitation (MEDIUM, backlog SEC-07):** when *no* scope is supplied,
keys degrade to `artifact::::artifact:<name>` and two projects with an
unscoped artifact of the same name collide. Not reachable on the production
bridge, which always supplies the project scope. Fixing it would change 18-J/18-K
identity semantics and was therefore **not** done in this phase.

---

## 5. Model-Output Trust Posture

Model output is untrusted at every sink. The Review Engine remains an
**evaluator**, never an authority: `completion.py` treats its verdict as an input
and re-checks deterministic validation afterwards, so `APPROVED + validation
FAILED` still blocks. Proven by the existing
`packages/orchestration/tests/test_review_fail_closed.py` suite plus the kernel
completion gate ordering.

---

## 6. Tool Permission Inventory

| Tool / capability | Privilege | Boundary | Validation |
|---|---|---|---|
| Workspace file read/write | workspace-scoped | `resolve_*_path` confinement | ENFORCED |
| `SafeExecutionRunner` | process exec | allowlist + jail + clean env | ENFORCED |
| Container sandbox | process exec | argv, caps dropped, non-root, RO root, net policy | ENFORCED |
| HTTP request (agent) | network egress | SSRF host validator + DNS re-check | ENFORCED |
| Calculator (automation) | compute | pure AST, no `eval`/`exec` | ENFORCED |
| Webhook trigger | ingress | HMAC/Bearer + payload size cap | ENFORCED |
| Web search / document tools | egress | allowlisted actions only | ENFORCED |
| Compiler toolchains (`javac`/`cobc`/`node`) | host exec | **admin-gated by `allow_external_install`** | Accepted (MEDIUM) |

Escalation ladder read → write → execute → network → system is blocked at each
rung by a distinct deterministic control; no single model action spans two rungs.
| `execution/sandbox/provider.py` (`is_available`) | **argv-only probe (repaired)** | ENFORCED |
| `modernization/tooling_resolver.py` | `shell=True` on a **hardcoded** verify table | Accepted risk (LOW, backlog) |
| `modernization/capabilities/providers.py` | `recipe["command"].split()`, argv, **gated by `allow_external_install`** | Accepted (MEDIUM, backlog) |

No production execution path uses `shell=True` with untrusted input.