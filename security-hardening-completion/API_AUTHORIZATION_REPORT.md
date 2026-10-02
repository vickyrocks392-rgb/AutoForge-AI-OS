# API Authorization Report (SHC-02)

## Threat model addressed

| Threat | Control |
|---|---|
| Another local process driving the API | Bearer authentication required on every non-public path |
| Malicious local application | Same; loopback is not treated as trusted |
| Compromised dependency issuing requests | Same; requires the configured key or a live session token |
| Malicious project input steering the agent | Guardrails + trust boundary upstream |
| SSRF / local-origin abuse from a browser | No CORS wildcard on API responses carrying data; auth required |
| Unauthorized project id substitution | `authorize_project()` before return/mutate |
| Cross-project artifact read | Scoped artifact access (SHC-07) |
| Cross-project artifact export | API path authorization + export content inspection |

## Enforcement point

`AutoForgeRequestHandler._authenticate_request(path)` is invoked at the top of
`do_GET`, `do_POST`, and `do_DELETE`, immediately after the `/api` prefix check
and **before** any routing, service call, or mutation.

```
request
  → path parsed
  → is it /api?  no → static assets (no auth; not data)
  → is it PUBLIC_API_PATHS? (/api/system/status only)
        yes → serve read-only status
        no  → _authenticate_request(path)
                 → ApiAuthenticator.authenticate(headers)     [identity]
                 → _extract_project_id(path)                   [resolve target]
                 → ApiAuthenticator.authorize_project(caller)   [object authz]
                 → serve
```

Authorization is evaluated **after** the requested resource identity is resolved
from the path and **before** the resource is fetched or mutated — the ordering
GATE 2 requires for IDOR resistance.

## Authentication sources (no second framework)

1. **Static API key** — `AUTOFORGE_API_KEY`, compared with
   `secrets.compare_digest` (constant-time).
2. **Certified session token** — resolved through the existing
   `SecurityPlatform.authentication.authenticate_token()`, which enforces
   revocation and expiry and re-resolves the subject from the identity provider.

Unauthenticated requests are refused with 401. There is no anonymous-privileged
fallback.

## Fail-closed behaviour

`ApiAuthenticator.__post_init__` raises `ApiAuthError` when authentication is
enabled and no key is configured. `create_server()` propagates this, so the
server **refuses to start** rather than exposing an unauthenticated API.

## Dev/test opt-in

Bypass requires an explicit, greppable opt-in:
`AUTOFORGE_API_AUTH_DISABLED=1` or `--allow-insecure-dev-auth`. The legacy Phase
16 behavioral suite sets the env var in `apps/api/tests/conftest.py`; the new
security suite explicitly removes it so real enforcement is exercised.

## Test evidence (16 tests, real socket)

| Test | Asserts |
|---|---|
| `test_missing_auth_is_rejected` | 401 on `/api/projects` |
| `test_invalid_token_is_rejected` | 401 on wrong key |
| `test_valid_api_key_is_accepted` | 200 with correct key |
| `test_read_only_status_path_is_public` | public allowlist limited to status |
| `test_mutating_endpoint_requires_auth` | 401 on POST /api/projects |
| `test_delete_endpoint_requires_auth` | 401 on DELETE |
| `test_cross_project_read_is_denied` | 403 on `/api/projects/proj-beta/output` |
| `test_cross_project_write_is_denied` | 403 on `/stop` |
| `test_authorized_project_is_allowed` | 200 for in-scope project |
| `test_cross_project_download_is_denied` | 403 on `download-source` |
| `test_cross_project_run_is_denied` | 403 on `/run` |
| `test_project_id_extraction_handles_encoding` | URL-decoded id resolution |
| `test_server_refuses_to_start_without_credentials` | fail-closed startup |
| `test_auth_is_disabled_only_via_explicit_env` | no implicit bypass |
| `test_auth_denial_is_audited` | denial recorded |
| `test_project_denial_is_audited` | project denial recorded |

## Residual risk

Session tokens are in-memory and process-scoped; a multi-process deployment
would need shared session storage. This is a Phase 20/23 concern and does not
affect the current single-process local-first deployment.
