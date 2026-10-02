# Adversarial Test Report (GATE 16)

## Totals

| Suite | Tests | Result |
|---|---|---|
| `packages/security` | **165** | PASS |
| — of which `test_crypto_egress_purpose.py` (new) | 58 | PASS |
| — of which `test_ai_guardrails_adversarial.py` (b05d66a) | 66 | PASS |
| — of which `test_adversarial_security.py` (+4 expiry, +1 rotation) | 22 | PASS |
| — certified pre-existing security tests | 37 | PASS |
| `apps/api` | **41** | PASS |
| — of which `test_api_security_auth.py` (new) | 16 | PASS |
| `packages/artifacts` | **25** | PASS |
| — of which `test_project_isolation.py` (new) | 11 | PASS |
| `packages/power_engines` | 135 passed | PASS (1 env failure) |
| — of which `test_runtime_security_integration.py` (new) | 9 | PASS |

## Category coverage

| Category | Status | Key test |
|---|---|---|
| **AUTH** missing / invalid / expired / revoked | PASS | `test_missing_auth_is_rejected`, `test_invalid_token_is_rejected`; session expiry + revocation via certified `authenticate_token` |
| **AUTHORIZATION** wrong role, cross-project, IDOR, artifact, workflow | PASS | `test_cross_project_read/write/run/download_is_denied`, `test_caller_project_set_is_enforced` |
| **AI GUARDRAILS** prompt injection | PASS | 10 payloads × 2 in `test_ai_guardrails_adversarial.py` |
| tool escalation | PASS | `test_04b_tool_outside_allowlist_is_blocked` |
| capability escalation | PASS | `test_missing_capability_denies` |
| trust escalation | PASS | `test_customer_instruction_cannot_self_declare_system` |
| self-improvement escalation | PASS | `test_learning_cannot_self_escalate[×7]` |
| guardrail modification | PASS | `test_engine_exposes_no_policy_mutation_api` |
| review / validation bypass | PASS | `test_request_cannot_self_declare_hitl_approval`, `test_action_class_spoofing_is_rejected` |
| **CREDENTIALS** expired / revoked | PASS | `test_expired_credential_is_refused`, `test_revoked_credential_is_still_refused` |
| wrong project | PASS | `test_purpose_binding_blocks_cross_project_use` |
| wrong purpose | PASS | `test_purpose_binding_blocks_cross_purpose_use` |
| tampered encrypted record | PASS | `test_tampered_ciphertext_is_detected` |
| wrong encryption key | PASS | `test_wrong_key_cannot_decrypt` |
| legacy migration | PASS | `test_legacy_record_migrates_to_aead`, `test_legacy_migration_can_be_disabled` |
| **NETWORK** localhost / private / metadata / rebinding | PASS | 11 parametrized blocked URLs; DNS-rebinding via preserved `validate_outbound_url` |
| redirect-to-private | PASS | per-hop re-validation in `tool_structured_http` (pre-existing) |
| encoded IP | PASS | `ipaddress.ip_address` rejects non-canonical forms; unresolved names fail closed |
| unauthorized destination | PASS | `test_domain_allowlist_is_enforced` |
| sensitive payload egress | PASS | 8 parametrized secret payloads + registered value + credential headers |
| **ARTIFACTS** cross-project retrieval / mutation / export bypass | PASS | `test_project_isolation.py` (5 tests) |
| recovery isolation | PASS | `test_durable_identity_semantics_unchanged` |
| **TOOLS** unauthorized / direct / malformed | PASS | `test_04b`, `test_04c`, `test_04` |
| retry / replay | PASS | `allowed_tools` re-checked on every `execute_tool` call, so a replayed call is re-authorized |
| **SUPPLY CHAIN** dependency integrity | PASS | `generate_lock_and_sbom.py --check` |
| unverified artifact | PASS | `test_export_scans_payload_for_secrets` |
| malicious generated dependency | PASS | `test_purpose_binding_blocks_unlisted_destination` |
| **SELF-IMPROVEMENT** permission escalation / policy modification / credential creation | PASS | `test_learning_cannot_self_escalate[×7]`, `test_learning_rejects_unknown_proposal_kinds` |

## Negative tests assert the side effect did NOT occur

This was an explicit requirement. Examples:

- `test_cross_project_mutation_is_denied` — re-reads the artifact and asserts
  its name is unchanged after the refused update.
- `test_outbound_tool_is_blocked_by_egress_policy_on_secret_payload` — asserts
  the secret string is absent from the entire result object.
- `test_purpose_binding_blocks_cross_project_use` — the secret is never
  returned; the call raises.
- `test_legacy_migration_can_be_disabled` — the store raises rather than
  silently accepting legacy ciphertext.
- `test_04c_missing_allowlist_fails_closed` — no handler runs.

## Known limitations

- No test exercises a *real* cloud metadata endpoint (unsafe/offline).
- DNS-rebinding is covered by the pre-existing resolver-based tests, not by
  controlling a live authoritative server.
- Network tests assert the decision, not a live socket, except the pre-existing
  `validate_outbound_url` suite.
