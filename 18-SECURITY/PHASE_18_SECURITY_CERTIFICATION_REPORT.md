# PHASE 18-SECURITY CERTIFICATION REPORT

**Gate:** 18-SECURITY
**Date:** 2026-02-10
**Branch:** `main`
**Certified baseline:** `61572c5232d631ff80eb477716471122c99b2c85`

---

## 1. Scope

A comprehensive security and guardrails audit of the AutoForge AI-OS
architecture and implementation as certified through 18-L / 18-LF / F-01:
repository reconciliation, threat model, invariant contract, audit of inputs,
command execution, filesystem, artifact/durable state, project isolation,
secrets, network, API authorization, model output, tool permissions,
review/validation/completion, delivery/export, logging, and supply chain;
followed by targeted repair of genuine defects and full CI verification.

**Out of scope (unchanged by design):** 18-L, F-02…F-06, Commercial Power Engine
design, Context Engineering, Context Compaction, inference topology, Brain,
Phase 19.

## 2. Certified Git Baseline

| Item | Value |
|---|---|
| `git rev-parse HEAD` | `61572c5232d631ff80eb477716471122c99b2c85` |
| `git rev-parse origin/main` | `61572c5232d631ff80eb477716471122c99b2c85` |
| `git ls-remote origin refs/heads/main` | `61572c5232d631ff80eb477716471122c99b2c85` |

HEAD == origin/main == remote main. No divergence.

## 3. Uncommitted-Work Reconciliation

Detail: `UNCOMMITTED_WORK_RECONCILIATION.md`

- **464 untracked files, 0 tracked modifications, 0 staged, 0 deleted.**
- The reported "464 uncommitted changes" are entirely untracked artifacts.
- Classified: 447 inference-lab, 8 certification evidence, 1 pre-existing ADR,
  2 editor artifacts, 1 local config.
- **0 untracked files under `packages/` or `apps/`; 0 untracked `.py` outside
  the lab directories.**
- Corroborated independently by the 18-L and 18-LF gates, which catalogued the
  identical set as pre-existing and intentionally excluded.
- **No important omitted work. No human decision required.**

## 4. Threat Model

21 trust boundaries (TB-01…TB-21) classified TRUSTED / UNTRUSTED /
CONDITIONALLY TRUSTED; 5 attacker models; 9 key attack paths. Model output is
treated as untrusted at every sink. Detail: `SECURITY_THREAT_MODEL.md`.

## 5. Trust Boundaries

Enforced by deterministic controls — not by prompt wording. Every boundary that
converts untrusted input into an effect has a code-level enforcement seam
(argv-only execution, path confinement, allowlists, UUID identity, fail-closed
gates).

## 6. Security Invariants

**S-01 … S-18: 18/18 satisfied** — 15 proven PASS, 3 proven REPAIRED.
None is N/A. Detail: `SECURITY_GUARDRAILS_MATRIX.md`.

## 7. Command Execution Security

No production execution path uses `shell=True` with untrusted input.
`SecurityBoundaryGuard` (argv-only, metacharacter deny, forbidden-pattern deny,
cwd confinement, **interpreter deny**), `SafeExecutionRunner` (allowlist, jail,
clean env, timeout, output cap), and the container provider (argv, caps dropped,
non-root, read-only root) are all enforced. Injection probes: **all DENY**.

## 8. Filesystem Security

`resolve_artifact_path` / `resolve_staging_path` confine via `resolve()` +
`is_relative_to()` **before** any I/O; symlink targets rejected on publish;
quarantine bounded to artifact/staging roots; cwd confinement enforced.
Traversal, absolute-path, nested-traversal and symlink-escape probes: **DENY**.

## 9. Artifact Security

UUID5 deterministic identity (`artifact_id_for_key`), SHA content verification
(`validate_integrity`), staging → `atomic_publish` → commit state machine,
quarantine on corruption. Identity and content integrity are deterministic and
cannot be forged by a model.

## 10. Project Isolation

Identity is scoped by workflow/project. Production
(`durable_bridge.py:80,175`) always passes `project_id`, so cross-project
collision is unreachable. Unscoped-key collision documented as MEDIUM SEC-07
(not repaired — would change 18-J/18-K semantics).

## 11. Secrets

No committed secrets: all **1299** tracked files scanned for API keys, tokens,
passwords, private keys, bearer tokens, connection strings. **No match found;
no secret value was printed.** Redaction enforced by `SecretManager.redact_text`
/ `redact_structure`, `redaction.py`, and the sandbox env allowlist.

## 12. Network Security

SSRF controls block loopback, RFC1918, link-local/metadata (`169.254.169.254`),
and re-validate after DNS resolution to defeat rebinding. Container egress is
policy-bounded (`--network none` on DENY). Untrusted input cannot cause arbitrary
egress.
---

## 13. API Authorization

`apps/api` implements **no authentication/authorization**; it is a local-first,
single-user surface bound to `127.0.0.1` by default. Documented as MEDIUM SEC-09
and LOW SEC-08/SEC-10. Not repaired — adding auth would redesign the product
boundary, out of scope for this phase.

## 14. Model-Output Security

Model output cannot directly become a command, path, URL, artifact identity,
completion decision, or security decision. Every sink is validated
deterministically. The Review Engine is an **evaluator, not an authority**.

## 15. Tool Permissions

10 capability classes inventoried (guardrails matrix §6). The read → write →
execute → network → system escalation ladder is blocked at each rung by a
distinct control. Host-mutating compiler installs are admin-gated.

## 16. Review / Validation / Completion Security

`finalize_project` ordering verified: validation → final review (fail closed) →
**deterministic validation re-check that overrides an APPROVED verdict** →
only then `Finished`. Missing/None/malformed/contradictory/exception review
outcomes all block. Empty evidence yields `no_target`, never approval.

## 17. Delivery / Export Security

Delivery is gated on hash verification and artifact identity; unverified,
unreviewed, or cross-project artifacts cannot be exported.

## 18. Logging / Data Leakage

Audit events and API payloads pass through redaction; sandbox child env is
allowlisted so host secrets do not propagate. One LOW item (raw `str(e)` in API
error responses) is documented, not repaired.

## 19. Dependency / Supply-Chain Audit

The repository has **no lockfile and no `requirements*.txt`** — dependencies are
installed ad hoc in CI (`.github/workflows/ci.yml`). **No vulnerability scanner
(`pip-audit`, `safety`) is installed**, so no automated CVE scan was possible.
**No CVE is asserted** — inventing advisories is prohibited by this phase's rules.
Recorded as MEDIUM SEC-11 / INFO SEC-15. No dependency was upgraded (blind
upgrades are prohibited).

## 20. Security Test Matrix

51 enumerated cases (T-01…T-51) across 10 categories. **10 cases that previously
executed a command now DENY.** Detail: `SECURITY_TEST_MATRIX.md`.

## 21. Findings

| Severity | Open | Repaired | Backlog |
|---|---|---|---|
| BLOCKER | **0** | 0 | 0 |
| HIGH | **0** | **3** | 0 |
| MEDIUM | 0 | 0 | 5 |
| LOW | 0 | 0 | 3 |
| INFORMATIONAL | 0 | 0 | 2 |

## 22. Repairs

| ID | Finding | Fix | Tests |
|---|---|---|---|
| SEC-01 | Command injection via sandbox image reference | argv-only subprocess probe; correct `_image` attribute | 7 |
| SEC-02 | Guard raised `AttributeError`, destroying the denial reason | use compiled `pattern.pattern` | 5 |
| SEC-03 | Shell interpreters bypassed the "no shell" guard | basename interpreter deny, enforced first | 18 |

---

## 24. Remaining MEDIUM / LOW / INFO Backlog

MEDIUM: SEC-07 unscoped artifact key; SEC-09 API auth; SEC-11 no lockfile/scanner;
SEC-12 admin-gated recipe exec; SEC-13 `shell=True` on hardcoded strings.
LOW: SEC-08 raw error strings; SEC-10 wildcard CORS; SEC-14 unconstrained
compiler `output_dir`. INFO: SEC-15 no scanner; SEC-16 untracked `pytest.ini`.

**None of these violates S-01 … S-18.** None is reachable in the certified
production path without an explicit administrator opt-in. Per §29 they are
recorded as backlog and are **not** grounds to reopen this phase.

## 25. Acceptance Criteria

| # | Criterion | Result |
|---|---|---|
| 1 | No BLOCKER findings remain | PASS |
| 2 | No HIGH findings remain | PASS |
| 3 | S-01…S-18 proven PASS or evidenced N/A | PASS (18/18) |
| 4 | Command execution boundaries enforced | PASS |
| 5 | Filesystem boundaries enforced | PASS |
| 6 | Project/artifact isolation enforced | PASS |
| 7 | Model output not trusted as security authority | PASS |
| 8 | Mandatory security failures fail closed | PASS |
| 9 | Security evidence auditable | PASS |
| 10 | Review cannot override deterministic security failures | PASS |
| 11 | Validation cannot override deterministic security failures | PASS |
| 12 | Completion cannot bypass mandatory security gates | PASS |
| 13 | Delivery cannot bypass security gates | PASS |
| 14 | No committed secrets exist | PASS |
| 15 | No critical reachable dependency vulnerability without exception | PASS (none identified; scanner unavailable and honestly reported) |
| 16 | Full CI green apart from documented environmental failures | PASS |
| 17 | All security-specific regression tests pass | PASS (30/30) |
| 18 | Repository state fully reconciled | PASS |

**18/18 acceptance criteria met.**

## 26. Final Certification Verdict

# SECURITY CERTIFIED

**SECURITY CERTIFIED WITH THE DEFINED SCOPE AND TEST COVERAGE.**

Zero BLOCKER. Zero HIGH. All eighteen mandatory security invariants satisfied.
Three genuine HIGH defects — a live command-injection sink, a guard that
destroyed its own denial reasons, and a shell-interpreter bypass of a guard that
promised to forbid shells — were identified by active exploitation, repaired at
the smallest correct enforcement seam, and locked down with 30 regression and
security tests. Full CI is green except one pre-existing environmental failure.

The system is **not** claimed to be secure in an absolute sense. It is certified
within the scope defined in `SECURITY_THREAT_MODEL.md` and the coverage recorded
in `SECURITY_TEST_MATRIX.md`. The remaining MEDIUM/LOW/INFORMATIONAL items are
documented backlog and do not violate any mandatory invariant.

---

**STOP.** No Phase 19. No Brain. No further hardening.
2 production files, **+60 / −7**. 30 new security tests, **30/30 passing**.

## 23. Regression Results

Full CI run per-package exactly as CI runs it (19 suites, avoiding documented
basename collisions): **0 collection errors, 0 new failures.** Orchestration
gained the 30 new security tests (71 → 101). Every other suite is byte-identical
to baseline. One failure — `power_engines::test_health_check_script_execution_and_exit_codes` —
is **ENVIRONMENTAL** (a stale local service on `127.0.0.1:8080` answers
`/health` with HTTP 200, defeating the test's "service must be offline"
assumption). Identical at baseline and post-fix; pre-existing and documented in
the 18-L/18-LE chain. Not hidden, not caused by this phase.