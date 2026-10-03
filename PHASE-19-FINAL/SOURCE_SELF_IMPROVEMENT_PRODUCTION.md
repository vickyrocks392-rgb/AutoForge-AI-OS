# SOURCE SELF-IMPROVEMENT — PRODUCTION

**Phase 19 FINAL — Gates 18, 19**

---

## 1. Production Source Is Never Modified Directly

Every change is diff-based and hash-identified. A proposal carries
`base_content_hash` and `proposed_content_hash`; the change is prepared in an
**isolated workspace**, and the source tree is untouched until a human approves
it through all ten gates.

The E2E test proves the source tree is unmodified while a change is being
prepared:

```python
shutil.copytree(project, workspace / "copy")
(workspace / "copy" / "fixture_module.py").write_text(proposed_content)
assert (project / "fixture_module.py").read_text() == base_content
```

---

## 2. Ten Mandatory Gates

| # | Gate | Blocks |
|---|---|---|
| 1 | `syntax_check` | unparseable code |
| 2 | `type_check` | type errors |
| 3 | `lint` | style violations |
| 4 | `unit_tests` | failing tests |
| 5 | `security_tests` | the Phase 18 security suite |
| 6 | `regression_tests` | regressions |
| 7 | `performance_tests` | slowdowns |
| 8 | `build` | build breakage |
| 9 | `deterministic_validation` | criterion tampering |
| 10 | `promotion_authorization` | self-authorization |

Every gate is `GateStatus.PASSED` or the candidate cannot promote. A `NOT_RUN`
gate blocks exactly like a `FAILED` one — there is no "skipped means fine".

---

## 3. Self-Serving Edits Are Blocked (Gate 19)

| Attack | Blocked by | Test |
|---|---|---|
| delete the tests | `unit_tests` **and** `regression_tests` | `test_test_deletion_blocks_promotion` |
| modify the benchmarks | `deterministic_validation` | `test_benchmark_modification_blocks_promotion` |
| exfiltrate credentials | refused before scoring | `test_credential_exfiltration_is_denied_before_scoring` |
| authorise its own promotion | `promotion_authorization` | `test_a_candidate_cannot_authorize_its_own_promotion` |

A candidate cannot redefine the criteria that judge it.

---

## 4. Protected Components Are Immutable (Gate 19)

All 19 protected paths are denied, tested both alone and combined with benign
files. Prefix matching matters:

> `packages/security/` protects every file beneath it. A whole subsystem cannot
> be edited simply by naming a file inside it.

**This was a real defect.** Protected-path matching originally used exact
equality, so `packages/security/` did not protect the files under it. Fixed in
19B-3 and now covered for every entry.

Independently, the **OS sandbox denies the AutoForge source tree** for read and
write from inside any experiment arm — so even a compromised arm cannot read or
modify the learning or security implementation.

---

## 5. Versioned, Diffable, Attributable, Reversible, Auditable

| Property | Mechanism |
|---|---|
| versioned | `version_id` + `version_number` on every active state |
| diffable | unified diff carried on the proposal |
| attributable | `candidate_id` on the promoted state and the rollback handle |
| reversible | `base_content_hash` identifies the exact prior content; `verify_diff_is_reversible` proves it |
| auditable | real `AIGuardrailsEngine` gate + `LearningAuditAction.CANDIDATE_CREATED` |

---

## 6. Real Build and Test Execution

`test_gate35_source_change_is_isolated_diffed_and_evaluated` runs a **real
`pytest` subprocess** against the isolated copy and asserts `returncode == 0`.
The change is not simulated; the tests genuinely execute.

Phase 19 FINAL adds the kernel-level half: arms now execute inside the real
Seatbelt sandbox with credential-free environments and bounded resources.