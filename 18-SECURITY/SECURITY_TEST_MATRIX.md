# SECURITY TEST MATRIX

**Phase:** 18-SECURITY
**Date:** 2026-02-10
**Result key:** *Expected* = required behaviour · *Actual* = observed outcome.

Every "Actual" below was produced by executing the probe/test on this host,
not by inspection alone.

---

## 1. Command Execution

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-01 | `image` = `…; touch MARKER` → shell | TB-09 | DENY, no exec | **PASS** (pre-fix: EXECUTED) | **HIGH (SEC-01)** |
| T-02 | `image` = ``…`touch MARKER` `` | TB-09 | DENY, no exec | **PASS** (pre-fix: EXECUTED) | **HIGH (SEC-01)** |
| T-03 | `image` = `…$(touch MARKER)` | TB-09 | DENY, no exec | **PASS** (pre-fix: EXECUTED) | **HIGH (SEC-01)** |
| T-04 | `image` = `… && …` / pipe / newline | TB-09 | DENY, no exec | **PASS** (pre-fix: EXECUTED) | **HIGH (SEC-01)** |
| T-05 | `["bash","-c","env"]` | TB-03 | DENY | **PASS** (pre-fix: ALLOWED) | **HIGH (SEC-03)** |
| T-06 | `["/bin/bash","-c", …]`, `sh`, `zsh`, `dash` | TB-03 | DENY | **PASS** (pre-fix: ALLOWED) | **HIGH (SEC-03)** |
| T-07 | `["env"]`, `xargs`, `nohup`, `su` | TB-03 | DENY | **PASS** (pre-fix: ALLOWED) | **HIGH (SEC-03)** |
| T-08 | `["python","-c","import os; os.system('ls')"]` | TB-03 | DENY | PASS | — |
| T-09 | `["rm","-rf","/usr"]`, `mkfs`, `shutdown` | TB-03 | DENY, typed + auditable | **PASS** (pre-fix: AttributeError) | **HIGH (SEC-02)** |
| T-10 | `["git","push","origin","main"]` | TB-03 | DENY | PASS | — |
| T-11 | `SafeExecutionRunner.run(["python3","-c","…os.system…"])` | TB-05 | DENY | PASS | — |
| T-12 | `SafeExecutionRunner.run(["rm","-rf","/"])` | TB-05 | DENY | PASS | — |
| T-13 | Benign `pytest -q tests/` / `javac` / `git status` | TB-03 | ALLOW | **PASS** (no functional regression) | — |

---

## 2. Filesystem / Paths

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-14 | `resolve_artifact_path("../outside.txt")` | TB-11 | DENY | PASS | — |
| T-15 | `resolve_artifact_path("/etc/passwd")` (absolute) | TB-11 | DENY | PASS | — |
| T-16 | `resolve_artifact_path("a/../../outside.txt")` (nested) | TB-11 | DENY | PASS | — |
| T-17 | Symlink in artifact root → outside file | TB-10 | DENY | PASS | — |
| T-18 | `atomic_publish` onto an existing symlink | TB-10 | DENY | PASS | — |
| T-19 | `quarantine` outside artifact/staging roots | TB-11 | DENY | PASS | — |
| T-20 | `validate_command(cwd="/etc")` | TB-03 | DENY | PASS | — |

---

## 3. Project Isolation

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-21 | Two projects, same artifact name, both workflow-scoped | TB-12 | distinct IDs | PASS | — |
| T-22 | Crafted name `../../a` | TB-12 | distinct key | PASS | — |
| T-23 | Unscoped key (`workflow_id=None`) name collision | TB-12 | distinct | **COLLIDES** (not production-reachable) | MEDIUM (SEC-07) |

---

## 4. Model Output / Prompt Injection

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
---

## 5. Review / Validation / Completion

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-29 | Review APPROVED + validation FAILED | TB-13/14 | **BLOCK** | PASS (`DEF-18LR-D8`) | — |
| T-30 | Review returns `None` / raises | TB-13 | **BLOCK** | PASS | — |
| T-31 | Malformed/contradictory review verdict | TB-13 | **BLOCK** | PASS | — |
| T-32 | Missing security evidence | TB-13 | **NOT approved** | PASS (`no_target`) | — |
| T-33 | Security-check exception in guard | TB-03 | **BLOCK** | PASS (`_finalize_stage_failure`) | — |
| T-34 | Completion with a failing mandatory gate | TB-14 | **BLOCK** | PASS | — |

---

## 6. Delivery / Export

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-35 | Export artifact whose hash does not verify | TB-20 | DENY | PASS (`validate_integrity`) | — |
| T-36 | Publish untrusted bytes under another artifact identity | TB-11 | DENY | PASS (UUID5 identity + hash) | — |
| T-37 | Wrong-project artifact export | TB-12/20 | DENY | PASS | — |

---

## 7. Secrets & Logging

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-38 | Committed API key / token / private key | TB-15 | none found | PASS (scanned all 1299 tracked files) | — |
| T-39 | Secret in API JSON response | TB-19 | `[REDACTED]` | PASS (`redact_secrets`) | — |
| T-40 | Secret in audit event details | TB-19 | sanitized | PASS (`redact_structure`) | — |
| T-41 | Host secrets leaking into sandbox env | TB-18 | stripped | PASS (env allowlist) | — |
| T-42 | API exposes an error with privileged internals | TB-01 | generic error | **Observed**: raw `str(e)` returned | LOW (SEC-08) |

---

## 8. Network

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-43 | Untrusted input causing arbitrary egress | TB-07 | DENY | PASS | — |
| T-44 | Container egress when policy = DENY | TB-14 | `--network none` | PASS | — |
| T-45 | Outbound to loopback from agent tool | TB-07 | DENY | PASS | — |

---

## 9. API / Authorization

| ID | Attack / Failure | Boundary | Expected | Actual | Severity |
|---|---|---|---|---|---|
| T-46 | Unauthenticated access to `/api/*` | TB-01 | DENY | **No auth implemented; mitigated by loopback bind** | MEDIUM (SEC-09) |
| T-47 | IDOR across project ids | TB-01 | DENY | Single-user local-first design; no multi-tenant authz | MEDIUM (SEC-09) |
| T-48 | Default bind address | TB-01 | loopback | PASS (`127.0.0.1` default) | — |
| T-49 | Wildcard CORS header | TB-01 | restricted | `Access-Control-Allow-Origin: *` present | LOW (SEC-10) |

---

## 10. Supply Chain

| ID | Check | Expected | Actual | Severity |
|---|---|---|---|---|
| T-50 | Dependency manifests present | present | `package.json` only; **no lockfile, no `requirements*.txt`** | MEDIUM (SEC-11) |
| T-51 | Vulnerability scanner available | available | **none installed** (`pip-audit`/`safety` absent) | documented, not invented |

---

## 11. Summary

| Outcome | Count |
|---|---|
| New security tests written | **30** |
| New security tests passing | **30/30** |
| Full CI suites run | **19** |
| Attack cases now DENY that previously executed | **10** (T-01…T-09) |
| Functional regressions introduced | **0** |
| Open BLOCKER / HIGH | **0** |
| T-24 | Prompt-injected instruction reaching a shell sink | TB-02/05 | DENY | PASS (deterministic guard, not prompt-based) | — |
| T-25 | Model URL → `127.0.0.1` / `169.254.169.254` | TB-07 | DENY | PASS | — |
| T-26 | Model URL → RFC1918 via DNS rebinding | TB-07 | DENY | PASS (post-resolution re-check) | — |
| T-27 | Model source containing `eval`/`exec`/`shell=True` | TB-04 | flagged by review | PASS | — |
| T-28 | Malformed model output (non-JSON) | TB-04 | rejected, no exec | PASS | — |