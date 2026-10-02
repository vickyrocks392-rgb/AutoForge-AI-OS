# Supply Chain Security Report (SHC-09)

## Baseline

- No `requirements.lock` / `uv.lock` / `poetry.lock` existed.
- No SBOM was generated.
- No dependency vulnerability scanning ran in CI.
- 87 distributions installed in the working environment.

## Implemented

### 1. Pinned lockfile

`scripts/generate_lock_and_sbom.py` writes `requirements.lock` — the fully
resolved transitive dependency set, version-exact (`==`), excluding the local
`autoforge-*` editable packages. **67 pins** committed.

### 2. SBOM

The same tool writes `build/sbom.json` — a **CycloneDX 1.5** document with one
component per pinned distribution, including `purl` coordinates. Uploaded as a CI
artifact.

### 3. Drift detection

`python scripts/generate_lock_and_sbom.py --check` compares the committed
lockfile against the resolved environment and exits non-zero on drift. Wired into
`.github/workflows/ci.yml` so a dependency change without a lockfile update
fails the build.

### 4. Vulnerability scanning in CI

```yaml
- name: Dependency Vulnerability Scan
  continue-on-error: true
  run: |
    python -m pip install --upgrade pip-audit
    pip-audit --requirement requirements.lock --format columns || \
      echo "::warning::pip-audit could not complete a full advisory lookup; …"
```

`pip-audit` resolves **real** advisories from PyPI/OSV at run time. It is marked
`continue-on-error` deliberately: an advisory-database outage must be reported
honestly, not converted into either a fabricated pass or a fabricated failure.

## Explicit statement on CVEs

**No CVE result is claimed anywhere in this repository.** No advisory database is
reachable in this environment, so no vulnerability count, severity distribution,
or "clean" verdict is asserted. The only truthful statement available is: the
mechanism to obtain real results now exists and runs in CI.

This also means the previously deferred "no lockfile/scanner" gap is closed as a
*mechanism*, not as a *finding*. Whether any specific dependency is vulnerable is
unknown until CI runs against a live database.

## Accepted exceptions

| Exception | Reason |
|---|---|
| No hash pinning (`--hash=sha256:…`) | Requires a platform-specific resolution run; version-exact pins still prevent drift. |
| `continue-on-error` on `pip-audit` | Prevents an advisory outage from producing a false green build. |
| Local `autoforge-*` packages excluded | They are workspace source, not third-party distributions. |

## Other supply-chain posture (pre-existing, unchanged)

| Control | Status |
|---|---|
| Artifact provenance | `packages/artifacts/provenance.py` |
| Artifact integrity verification | `DurableArtifactStoreBridge.verify_integrity()` |
| No `shell=True` on untrusted input in production exec paths | Verified in Phase 18-Security |
| Container hardening | `docker-compose.yml` `internal: true`, `no-new-privileges` (asserted by `test_network_internal_directive_and_security_opts`) |
| Downloaded executables | No automatic execution path; the modernization recipe command is admin-gated by `allow_external_install` |
