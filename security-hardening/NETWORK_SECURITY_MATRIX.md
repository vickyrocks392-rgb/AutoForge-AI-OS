# Network Security Matrix

Scope: all outbound network capability reachable by AI-originated actions.
The existing SSRF control is strong and was **preserved**; this pass closed the
reachability gap around it (SHG-01) and documented what remains.

## 1. Existing Controls (preserved)

`validate_outbound_url()` — `packages/power_engines/.../agent/tools.py`

| Check | Implementation |
|---|---|
| Protocol restriction | Only `http`/`https`; every other scheme rejected |
| Hostname presence | Empty/missing hostname rejected |
| Loopback | `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, `local` |
| IP literals | `ipaddress` checks for loopback/private/link-local/reserved |
| **DNS rebinding** | Hostname is **resolved** and every resolved IP is re-checked |
| Redirect re-validation | Each redirect hop re-validated against the same policy |
| Hop limit | Manual `allow_redirects=False`, max 3 hops |
| Method restriction | `GET`/`POST` only for the agent HTTP tool |
| Timeout | `min(timeout, 30.0)` |
| Domain allowlist | Optional `allowed_domains` |
| Private override | `allow_private` default `False`; opt-in only |

`HTTPRequestAction` (`automation/actions.py`) calls the same validator before
`requests.request`, and restricts methods to `GET/POST/PUT/PATCH/DELETE`.

## 2. Gap Closed This Pass — Reachability

**Before:** the SSRF validator was strong, but a model could reach the network
tool even when the agent specification never granted it. `allowed_tools` was not
enforced (SHG-01), so an agent restricted to `["calculator"]` could issue real
outbound requests — SSRF controls applied only *after* the capability decision had
already been bypassed.

**After:** `authorize_tool_call()` denies `structured_http` before the handler
runs. The SSRF validator remains as the second layer for genuinely authorized
network capability.

Result: **defence in depth** — capability first, then destination policy.

## 3. Remaining Network Findings

| ID | Finding | Severity | Status |
|---|---|---|---|
| NET-01 | Model-provider endpoints (`ollama`, `openai_compatible`, `gemini`, `anthropic`) call `urlopen` without `validate_outbound_url`. These are operator-configured, not model-controlled. | P3 | Accepted (operator trust boundary) |
| NET-02 | `knowledge_platform/rag18/embedding.py` and `connectors/github.py` call `urlopen` without the validator; both are operator/platform-configured. | P3 | Accepted |
| NET-03 | Generated customer-agent code (`agent/generator.py`) emits raw `requests.post(url, ...)` not re-validated at runtime. Host platform is not exposed; Review Engine flags dangerous execution. | P3 | Backlog (SHG-09) |
| NET-04 | No egress content inspection — a permitted host can still receive whatever the model places in a request body. | P2 | Requires Phase 20 egress proxy |
| NET-05 | No request/response size cap at the tool layer beyond timeout. | P3 | Backlog |

**No P0/P1 open network findings.**

## 4. Exfiltration Risk Assessment

The concern: generated code freely sending source/secrets/credentials/documents to
an attacker host.

| Control | Status |
|---|---|
| Destination must pass SSRF policy | **Enforced** |
| Agent must hold `network.outbound` | **Enforced (new)** |
| Request only reachable via an allowlisted tool | **Enforced (new)** |
| Secrets redacted from prompts/logs/audit | **Enforced** (`redact_structure`) |
| Raw credential values withheld from models | **Enforced** — `credential.use` requires `REQUIRE_ELEVATED_AUTHORITY`; `SecretValue.__str__` returns `***` |
| Request body content inspection | **Not implemented** (NET-04) |
| Egress destination allowlist per project/worker | **Partial** — `allowed_domains` exists on `SafetyConstraintsConfig` but is not populated by default |

Exfiltration therefore requires *all* of: an authorized `network.outbound`
capability, an allowlisted tool, and an SSRF-passing destination. Remaining
residual risk is data sent to an *approved* host — a P2 design item requiring an
egress proxy.

## 5. Adversarial Tests

Existing (Phase 18-Security, preserved and passing): loopback, RFC1918,
link-local/metadata `169.254.169.254`, DNS-rebinding, malformed model URL,
redirect re-validation.

New (this pass): `test_04b_tool_outside_allowlist_is_blocked` and
`test_04c_missing_allowlist_fails_closed` prove the reachability gate.
