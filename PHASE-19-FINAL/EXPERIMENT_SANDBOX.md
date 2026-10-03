# EXPERIMENT SANDBOX

**Phase 19 FINAL — Gates 5, 6, 7, 10**

---

## 1. The Problem Being Closed

19B-3 reported honestly that experiment arms used **injected runners**. That is
a contract, not a boundary: an in-process runner can reach anything the host
process can reach.

Phase 19 FINAL replaces it with a genuine OS-enforced boundary.

---

## 2. Two Kernel Mechanisms, No New Platform

The task forbids inventing a container or orchestration platform. These are the
platform's own primitives:

| Mechanism | Enforces |
|---|---|
| **macOS Seatbelt** (`/usr/bin/sandbox-exec`) | filesystem, network, process creation |
| **POSIX rlimits** (`resource.setrlimit`) | CPU, file size, open files, address space, process count |

Both are enforced by the kernel, not by cooperative checks inside the runner.

**If no OS boundary is available, `run_sandboxed` raises `SandboxUnavailable`
and the command does not run.** An experiment that cannot be isolated must not
run.

---

## 3. The Seatbelt Profile

Written deny-first, then narrowed. Seatbelt is *last-match-wins*, so this
ordering is what makes an omission safe — forgetting an allow makes the policy
stricter, never weaker.

**Denied regardless of policy:**
- every write outside the arm's own workspace
- all network (unless explicitly permitted)
- `/etc`, `/private/etc`, `/var/root`
- **the entire AutoForge source tree, for both read and write**
- directory enumeration of `/`

**Re-allowed only for:** the arm's workspace, declared read paths, and the
declared interpreter's own installation prefix.

---

## 4. A Real Bug This Surfaced

While building the profile, `_python_prefixes` derived `"/"` from `/bin/cat`
(`/bin` → `/` → `/`). The resulting `(allow file-read* (subpath "/"))` silently
undid **every** deny above — `/etc` and the AutoForge source became readable
again.

The test suite caught it (`test_absolute_host_path_read_is_denied` failed while
the profile looked correct when inspected). The fix guards against deriving a
shallow parent from a non-interpreter binary.

Recorded here because it is exactly the class of bug that "the runner normally
won't do that" would have hidden.

---

## 5. Default Policy — Deny by Default

| Control | Default |
|---|---|
| network | **denied** (including loopback and cloud metadata) |
| production credentials | **never inherited** |
| filesystem write | confined to the arm's own workspace |
| AutoForge source | **denied for read and write** |
| environment | rebuilt from an allowlist; credential-shaped names dropped |
| `HOME` / `TMPDIR` | redirected into the workspace |
| undeclared capabilities | nothing outside the declared argv runs |

Credential-shaped variables are dropped **even when allowlisted**:

```
AWS_  AZURE_  GCP_  GOOGLE_  ANTHROPIC_  OPENAI_  NPM_TOKEN  HF_TOKEN
GITHUB_TOKEN  GH_TOKEN  SSH_  GPG_  SLACK_  STRIPE_  DATADOG_  SENTRY_
AUTOFORGE_MASTER_KEY  MASTER_KEY  API_KEY  APIKEY  SECRET  TOKEN
PASSWORD  PASSWD  CREDENTIAL  PRIVATE_KEY  SESSION_KEY
```

---

## 6. Escape Tests (Gate 6) — All Verified Blocked

| Escape | Result |
|---|---|
| path traversal (`../../../../etc/passwd`) | blocked |
| absolute host path read | blocked |
| AutoForge source read | blocked |
| AutoForge source write | blocked |
| write outside the workspace | blocked |
| parent directory enumeration | blocked |
| network access | blocked |
| loopback access | blocked |
| cloud metadata (169.254.169.254) | blocked |
| environment credential leakage | blocked |
| nonexistent executable | refused before execution |
| empty argv | refused |
| credential allowlist bypass | blocked even when allowlisted |

Each test asserts the **specific failure**, and the working tests prove the
sandbox is not simply a brick: `test_python_executes_inside_the_sandbox` shows
a real interpreter still starts and runs.

---

## 7. Resource Governance (Gate 7)

| Limit | Mechanism |
|---|---|
| wall clock | timeout, then the **process group** is `SIGKILL`ed |
| CPU seconds | `RLIMIT_CPU` |
| address space | `RLIMIT_AS` (Linux) |
| file size | `RLIMIT_FSIZE` |
| open files | `RLIMIT_NOFILE` |
| processes | `RLIMIT_NPROC` |
| core dumps | `RLIMIT_CORE = 0` |
| output | captured with a declared bound and explicitly truncated |

Tested: an infinite loop is killed by the wall clock; a CPU burner is killed by
`RLIMIT_CPU`; oversized output is truncated rather than exhausting memory.

---

## 8. Reproducibility (Gate 10)

`run_sandboxed_arm` returns an `ArmExecutionRecord` containing everything needed
to reconstruct the run independently:

`arm`, `argv`, `exit_code`, `stdout`, `stderr`, `duration_seconds`, `workspace`,
`source_hash`, `config_hash`, `environment_hash`, `interpreter`,
`policy_summary`, `limits`, `executed_at`.

Verified by replaying a recorded run and reproducing both the output and every
hash, and by confirming two arms cannot see or overwrite each other's files.

---

## 9. Platform Note

macOS does not implement `RLIMIT_AS`; setting it fails in the child. The code is
platform-aware and records this honestly rather than silently skipping it. On
Linux the rlimits are the boundary and network confinement remains the caller's
responsibility — this module never claims a boundary it does not have.