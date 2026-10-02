# Egress Security Report (SHC-05 / SHC-06)

Two independent layers, both enforced **before transmission**.

---

## Layer 1 — Destination control

`validate_egress_url()` in `packages/security/src/autoforge_security/egress.py`.
Preserves the existing `validate_outbound_url` semantics and adds port and
metadata policy.

| Check | Rule |
|---|---|
| Scheme | `http`/`https` only; everything else denied (`file:`, `gopher:`, `ftp:` …) |
| Hostname | Must be present |
| Port | 12 sensitive ports blocked (22, 23, 25, 445, 3306, 5432, 6379, 9200, 11211, 27017, 2375, 2376, 10250) |
| Loopback | `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, `local`, … |
| Private | RFC1918 / unique-local |
| Link-local | includes `169.254.0.0/16` metadata range |
| Cloud metadata | explicit host list: `169.254.169.254`, `metadata.google.internal`, `metadata.goog`, `100.100.100.200`, `169.254.170.2`, `fd00:ec2::254` |
| Reserved / multicast / unspecified | denied |
| DNS rebinding | hostname resolved; **every** resolved IP re-checked |
| Domain allowlist | exact or subdomain match, enforced before resolution |

**Honest scope.** This blocks the standard SSRF classes. It does **not** claim
absolute protection: a hostile DNS server that returns a public IP at check time
and a private IP at connect time is a theoretical residual, mitigated by
resolution re-checks and, in the agent tool, per-redirect-hop re-validation. The
existing `tool_structured_http` already re-validates every redirect destination.

### Verified denials
`127.0.0.1`, `localhost`, `[::1]`, `10.0.0.5`, `192.168.1.1`, `172.16.0.1`,
`169.254.169.254`, `metadata.google.internal`, `file://`, `gopher://`, `ftp://`,
ports 22 and 6379, non-allowlisted domain, empty URL.

---

## Layer 2 — Content control (DLP)

`EgressPolicy.enforce(url, headers=, params=, body=)` walks the payload
recursively (mappings, lists, tuples, sets, bytes, depth ≤ 12) and classifies:

**Always DENY (never transmitted):**
- Registered secret values matched by value
- 10 secret shapes: AWS access key id, AWS secret key, GitHub token, Slack
  token, Google API key, OpenAI key, Anthropic key, bearer token, JWT,
  PEM private-key block
- Credential headers: `Authorization`, `Proxy-Authorization`, `X-API-Key`,
  `Api-Key`, `X-Auth-Token`, `Cookie`, `X-Amz-Security-Token`

**REDACT (request proceeds, value replaced):**
- Sensitive field names: `password`, `token`, `access_token`, `api_key`,
  `secret`, `client_secret`, `private_key`, `session_id`, …

This distinction matters: a model calling an ordinary login endpoint must still
work, so `password` fields are redacted rather than refused — while a genuine
credential in a header is refused outright.

**Wired into the real path:** `tool_structured_http` calls the policy before the
first byte is sent; a denial returns `{"status": "error",
"blocked_by": "egress_policy"}` and no request is made.

**Audit:** every decision appends to `EgressPolicy.audit` with
`egress.allowed`, `egress.allowed.redacted`, `egress.denied.destination`,
`egress.denied.secret`.

---

## Test evidence (22 tests)

| Group | Coverage |
|---|---|
| Destination | 11 parametrized blocked URLs, 2 blocked ports, public allow, domain allowlist, empty URL |
| Content | 8 parametrized secret payloads (incl. nested depth-4 and list), registered value, credential header, API-key header, query params, deep nesting (depth 7), bytes/sets |
| Ordering | destination denial occurs before content check |
| Positive | benign body allowed; sensitive field redacted while sibling fields survive |
| Audit | all three event types recorded |

## Residual risk

Payloads leaving by a path that does not construct an `EgressPolicy` (operator-
configured model providers, connectors) are not inspected. Those are not
AI-initiated requests, and routing them through content inspection would require
a network proxy rather than an in-process check.
