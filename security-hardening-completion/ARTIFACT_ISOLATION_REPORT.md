# Artifact Isolation Report (SHC-07 / SHC-08)

## Defect

`LocalArtifactStore.get(artifact_id)` and `DurableArtifactStoreBridge.get(artifact_id)`
accept a bare artifact id with **no project scope**. A caller possessing another
project's artifact id could read or mutate it. There was no object-level
authorization anywhere in the artifact layer.

## Repair strategy — isolation above, identity below

GATE 7 requires: *if changing physical keys would risk 18-J/18-K compatibility,
preserve physical compatibility and enforce logical/project authorization above
the storage layer.*

**Durable identity was NOT changed.** `derive_artifact_key()` and the UUID5
`artifact_id` derivation in `packages/runtime/.../artifact_catalog.py` are exactly
as certified. No persisted artifact becomes unreachable.

New `packages/artifacts/src/autoforge_artifacts/scoped_access.py` provides
`ProjectScopedArtifactAccess`, which wraps any `ArtifactStoreProtocol`:

| Method | Enforcement |
|---|---|
| `get(artifact_id, project_id=…, caller_projects=…)` | Resolve artifact, compare `project_id`, then compare caller set — **before** returning |
| `update(artifact, project_id=…)` | Same checks **before** mutating |
| `list_artifacts(caller_projects=…)` | Filters to the caller's projects |
| `export_payload(…)` | Authorizes, then inspects outgoing payload for secrets |

## Export / generated-content control (SHC-08)

`export_payload` runs the canonical egress content inspection before any
delivery. Model-generated source containing a secret is refused:
`ProjectAccessDeniedError("Export of artifact … blocked: sensitive material
detected …")`. Clean generated source passes through unchanged.

Destination authorization for the API download paths is enforced separately at
the HTTP layer (see `API_AUTHORIZATION_REPORT.md`).

## Test evidence (11 tests, `packages/artifacts/tests/test_project_isolation.py`)

| Test | Asserts |
|---|---|
| `test_cross_project_read_is_denied` | cross-project `get` raises |
| `test_cross_project_mutation_is_denied` | cross-project `update` raises **and stored artifact is unchanged** |
| `test_authorized_project_can_read` | in-scope access works |
| `test_caller_project_set_is_enforced` | caller project set honoured |
| `test_listing_is_filtered_to_caller_projects` | listing scoped |
| `test_missing_artifact_raises_not_found` | correct error class |
| `test_export_scans_payload_for_secrets` | secret-bearing export blocked |
| `test_export_allows_clean_generated_source` | clean export passes |
| `test_export_is_refused_cross_project` | export cannot cross projects |
| `test_durable_identity_semantics_unchanged` | ids/projects unchanged by the layer |
| `test_two_projects_same_name_do_not_collide` | identical names in two projects stay isolated |

## Residual risk

The scoped layer must be *used* by callers. `LocalArtifactStore.get()` itself
remains unscoped for internal engine use — this is deliberate, since the durable
engine operates inside the control plane. Any new external consumer must go
through `ProjectScopedArtifactAccess`; the API download/run/stop paths already do
via the HTTP authorization layer.

Multi-tenant isolation remains a Phase 20 item for a single-tenant local-first
product.
