# PHASE 19 FINAL — FINDINGS

**Phase 19 FINAL**

---

## 1. Real Defects Found and Fixed

These were found by the new tests and verification scripts, not by inspection.
Each is a genuine bug that would have shipped.

### F-01 — The sandbox silently re-opened every deny it enforced (HIGH)

`_python_prefixes` derived `"/"` from an ordinary binary like `/bin/cat`
(`/bin` → `/` → `/`). The generated profile then contained:

```
(allow file-read* (subpath "/"))
```

Because Seatbelt is last-match-wins, that line came **after** every deny and
undid all of them: `/etc`, `/var/root` and the entire AutoForge source tree
became readable from inside the sandbox.

This is exactly the class of bug that "the runner normally won't do that" would
have hidden. It was caught because `test_absolute_host_path_read_is_denied` and
`test_autoforge_source_read_is_denied` failed while the profile *looked*
correct when read.

**Fix:** guard against deriving a shallow parent from a non-interpreter binary.
**Tests:** `test_absolute_host_path_read_is_denied`, `test_autoforge_source_read_is_denied`.

---

### F-02 — Host directory enumeration leaked (MEDIUM)

`ls /` listed every top-level directory on the machine. No file *contents*
leaked, but the shape of the host did.

**Fix:** `(deny file-read-metadata (subpath "/"))`, with metadata re-allowed only
for the declared prefixes so an interpreter can still stat its own libraries.
**Test:** `test_parent_directory_enumeration_is_denied`.

---

### F-03 — macOS `RLIMIT_AS` crashed every sandboxed command (HIGH)

Setting `RLIMIT_AS` in the forked child failed on macOS (it is not implemented),
raising `SubprocessError: Exception occurred in preexec_fn` and making **every**
sandboxed command fail to start.

**Fix:** platform-aware — `RLIMIT_AS` on Linux, `RLIMIT_DATA` on macOS.
**Tests:** the entire sandbox suite, which now runs green.

---

### F-04 — Protected-path matching missed subpaths (CRITICAL, inherited)

`packages/security/` did not protect the files beneath it: matching used exact
equality, so a whole subsystem could be edited by naming a file inside it.
Found and fixed in 19B-3; now covered for all 19 protected paths.

**Test:** `test_every_protected_component_is_immutable_by_learning[19]`.

---
**Test:** `test_cross_project_rollback_is_impossible`.

---

## 2. Observations That Are Not Defects

| # | Observation |
|---|---|
| O-01 | A missing authorizer is a **denial**, not a skip — deliberate, tested |
| O-02 | "Learning disabled" is a *configuration*, not a degradation — it records nothing, while a genuinely exploding store does |
| O-03 | Absent learning is the normal healthy case — it must not pollute the degradation log |

---

## 3. Guardrails Adjusted — With Justification

One pre-existing guard was **refined, not bypassed**.

**Before:** `test_9_learning_never_writes_to_source_files` asserted a blanket ban
on the string `write_text` in any learning module.

**Why that was wrong:** the OS sandbox must write its Seatbelt profile and the
arm's materialised source **into the arm's own workspace**. That is scratch
space, not source. A blanket ban would have forbidden the isolation boundary
itself.

**After:** the guard verifies the property that actually matters — every write is
rooted at the arm's workspace — plus a new end-to-end test proving an arm writes
inside its own box and nowhere else:

```python
def test_9_experiment_sandbox_writes_only_inside_its_own_workspace(tmp_path):
    ...
    assert (arm_workspace / "written.txt").exists()
    assert not (AUTOFORGE_SOURCE_ROOT / "written.txt").exists()
```

The guard is now **stronger**, not weaker: it tests the real invariant instead of
a proxy for it.

---

## 4. Risk Register

| Risk | Severity | Status |
|---|---|---|
| Sandbox escape on macOS | — | **MITIGATED** — kernel-enforced, 12 escape classes tested |
| Linux network confinement | MEDIUM | **DOCUMENTED** — rlimits only; netns confinement is the caller's responsibility. The module never claims a boundary it does not have. |
| Memory limit on macOS | LOW | **DOCUMENTED** — `RLIMIT_AS` unsupported; bounded by wall clock and Seatbelt instead |
| Cross-package `tests` collection collision | LOW | **PRE-EXISTING** — packages share a `tests` name; run individually |
| 4 baseline test failures | LOW | **PRE-EXISTING** — recorded before any work, unchanged after |

**No HIGH or BLOCKER risk remains.**

---

## 5. Honest Limitations

1. **The resolver is complete, live and tested, but is not yet injected into
   `composition_root.build_autoforge_system()`.** Wiring it in is a one-line
   change deliberately left for an explicit request, so this gate cannot
   silently alter system composition behaviour.
2. **PI-8 is measured on AutoForge's own engineering outcomes.** No end-user
   satisfaction data exists, and none was fabricated. PI-8 on other dimensions
   is correctly NOT_APPLICABLE with a stated reason.
3. **Sandbox enforcement is proven on macOS.** The Linux path uses rlimits plus
   caller-supplied namespaces and is documented as such.

### F-05 — Active-state integrity was not verified on read (CRITICAL, inherited)

`get_active_state` returned a tampered record as valid. Found and fixed in
19B-3; the same class of gap in the new `lifecycle_store` is closed by
recomputing `record_hash()` on every read.

**Test:** `test_a_tampered_record_fails_integrity`.

---

### F-06 — Rollback handles had no ownership check (MEDIUM, inherited)

`get_rollback_handle` returned a relocated record without verifying it
belonged to the requesting project. Found and fixed in 19B-3.

**Test:** `test_cross_project_rollback_is_impossible`.