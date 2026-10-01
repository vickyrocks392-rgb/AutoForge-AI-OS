# SECURITY REPAIR REPORT

**Phase:** 18-SECURITY
**Date:** 2026-02-10
**Scope rule:** only findings classified BLOCKER/HIGH (and MEDIUM findings that
directly violate a mandatory invariant) were repaired. No architectural rewrite.

---

## 1. Files Changed (production)

| File | Change | Finding |
|---|---|---|
| `packages/execution/src/autoforge_execution/sandbox/provider.py` | +22 / −5 | SEC-01 |
| `packages/orchestration/src/autoforge_orchestration/security.py` | +38 / −2 | SEC-02, SEC-03 |

**Total: 2 files, +60 / −7.** Minimal, surgical, no unrelated edits.

---

## 2. Repairs

### SEC-01 — argv-only sandbox image probe

**Root cause.** Configuration value (`image`) interpolated into an `os.system`
shell string; a wrong attribute name (`self.image` vs `self._image`) masked the
sink via a swallowed `AttributeError`.

**Minimal fix.** Two argv-only `subprocess.run(..., shell=False)` calls with
timeouts; correct attribute; explicit fail-closed on exception. Added
`import subprocess`.

```python
img = subprocess.run(
    ["podman", "image", "exists", self._image],
    capture_output=True, timeout=10, shell=False,
)
self._is_avail = (img.returncode == 0)
```

**Regression test.** `packages/orchestration/tests/test_security_boundaries_sec01.py`
- 6 parametrized injection payloads assert no marker file is created;
- a source-level assertion forbids `os.system(` in the provider and requires the
  argv form.

**Security test.** Same file — the payloads *are* the security tests.

---

### SEC-02 — typed, auditable forbidden-pattern denial

**Root cause.** `match.pattern` on an `re.Match` object.

**Minimal fix.** `pattern.pattern` (the compiled regex). One expression changed
in two places (message + details).

**Regression test.** `test_sec02_forbidden_pattern_raises_typed_error`
(5 cases) asserts a `VerificationCommandError` whose message contains
`"forbidden pattern"` and whose `details` carries a `pattern` key — i.e. the
denial is attributable.

---

### SEC-03 — deny shell/interpreter binaries

**Root cause.** The guard validated the *arguments* of an argv list but never the
*executable*, so `bash -c "<cmd>"` delivered an arbitrary payload invisible to
every metacharacter and forbidden-pattern rule.

**Minimal fix.** Added `_SHELL_INTERPRETERS` (24 entries: POSIX shells,
`busybox`, `env`, `eval`, `exec`, `xargs`, `nohup`, `setsid`, `script`, `screen`,
`tmux`, `expect`, `sudo`, `su`, `doas`, …) and an executable check placed **first**
in `validate_command`, matched via `PurePosixPath(...).name.lower()` so
`/bin/bash` is caught identically.

**Regression test.** `test_sec03_shell_interpreters_are_denied` (10 cases,
including absolute paths) plus `test_sec03_empty_executable_is_denied`.

**Anti-regression guard.** `test_sec03_legitimate_engineering_commands_still_allowed`
(7 cases: `pytest`, `python -m pytest`, `unittest`, `javac`, `git status`,
`npm run build`, `node`) proves the hardening does not break engineering.

---

## 3. Test Results

```
packages/orchestration/tests/test_security_boundaries_sec01.py      7 tests
packages/orchestration/tests/test_security_boundaries_sec02_03.py 23 tests
                                                            total 30 tests

30 passed, 102 warnings in 1.76s
```

---

## 4. Regression Verification (full CI, per-package as CI runs it)

| Suite | Baseline | Post-fix | Delta |
|---|---|---|---|
| kernel | 161 passed | 161 passed | = |
| **orchestration** | 71 passed, 6 skipped | **101 passed**, 6 skipped | **+30 (new security tests)** |
| workflows | 218 passed | 218 passed | = |
| runtime | 268 passed | 268 passed | = |
| persistence | 70 passed | 70 passed | = |
| artifacts | 14 passed | 14 passed | = |
| events | 228 passed | 228 passed | = |
| event_platform | 56 passed | 56 passed | = |
| security | 37 passed | 37 passed | = |
| connectors | 93 passed | 93 passed | = |
| ai_infrastructure | 97 passed | 97 passed | = |
| review | 114 passed | 114 passed | = |
| observability | 16 passed | 16 passed | = |
| workforce | 36 passed, 2 skipped | 36 passed, 2 skipped | = |
| execution | 257 passed, 18 skipped | 257 passed, 18 skipped | = |
| power_engines | 1 failed, 123 passed, 3 skipped | 1 failed, 123 passed, 3 skipped | = (environmental, §5) |
| composition | 146 passed | 146 passed | = |
| modernization | 383 passed, 59 skipped | 383 passed, 59 skipped | = |
| tests (root) | 96 passed, 1 skipped | 96 passed, 1 skipped | = |

**0 collection errors. 0 new failures. 0 regressions.**
19 suites run individually, avoiding the CI-documented basename collisions.

Five Commercial Power Engines, canonical routing, deterministic validation,
Review, Completion, artifact durability, Context Engineering, Context
Compaction, 18-J and 18-K are all inside the suites above and remain green.
The M6 live inference path is **not** affected (no change to model, routing, or
inference topology), so the expensive M6 certification was correctly not re-run.

---

## 5. Failure Classification

| Failure | Classification | Evidence |
|---|---|---|
| `power_engines::test_health_check_script_execution_and_exit_codes` | **ENVIRONMENTAL** | Test asserts `--require-service` exits 1 because no service is running. A stale local Python process is listening on `127.0.0.1:8080` and answers `GET /health` with HTTP 200, so the probe reports healthy. Identical at baseline and post-fix; predates this phase; documented in the 18-L/18-LE chain as the known 8080 collision. Not a security regression, not caused by any change here. |

No failure was hidden, suppressed, or reclassified.