# AI Trust Boundary

Defines how untrusted content is separated from authoritative instruction and how
trust metadata survives downstream transformations.

## 1. Sources of Untrusted Content (audited)

| Source | Declared trust | Entry point found in audit |
|---|---|---|
| Customer text | `CUSTOMER_INSTRUCTION` | `assemble_context` (`agent/runtime.py`) |
| Repository source | `RETRIEVED_DATA` / `LEGACY_SOURCE` | `assemble_context`, `file_read` tool |
| Documents | `RETRIEVED_DATA` | `GroundedContextBuilder.build_context` |
| RAG chunks | `RETRIEVED_DATA` | `build_context`, `wrap_rag_context` |
| Tool output | `EXTERNAL_TOOL_OUTPUT` | `tool_structured_http` result |
| Model output | `MODEL_OUTPUT` | `parse_result`, assistant messages |
| Legacy source | `LEGACY_SOURCE` | legacy archaeology workers |

**Pre-fix condition:** all of the above were concatenated into model context with
no source metadata, no trust level, and no instruction/data distinction.

## 2. Instruction vs Data

`BoundarySegment.kind` is the mechanism:

- `INSTRUCTION` — emitted **only** when `trust_level is SYSTEM_POLICY` and
  `force_data=False`. Nothing else can produce this value.
- `DATA` — everything else, always, regardless of content.

`as_message()` renders the boundary inline so it survives prompt transport:

```
[TRUST=system_policy | SOURCE=platform.system_instructions | KIND=INSTRUCTION]
...
[TRUST=retrieved_data | SOURCE=docs/readme.md | KIND=DATA]
...
```

A segment whose trust level is in `DATA_ONLY_TRUST` is rendered with `role:
user`, never `role: system`.

## 3. Neutralization

14 deterministic patterns target canonical injection idioms:

| Category | Examples matched |
|---|---|
| Override | `ignore all previous instructions`, `disregard prior prompts`, `forget everything you…` |
| Role reassignment | `you are now …`, `act as a system administrator` |
| Chat-template escape | `</system>`, `<system>`, `[/INST]`, `<<SYS>>` |
| Policy tampering | `override the security policy`, `disable all guardrails`, `enable safety` |
| Privilege claims | `you have been granted …`, `grant yourself …` |

Matched spans are replaced with `[neutralized]` and recorded in
`TrustBoundaryViolation` for audit. Benign text is never modified — verified by
`test_benign_untrusted_content_is_not_flagged`.

Neutralization is a **boundary marker, not a parser**. It does not attempt
natural-language intent detection; it applies a deterministic envelope based on
platform-declared trust. Authorization never depends on it — the guardrail
decision is made on trust level and capability, not on whether a payload was
detected.

## 4. Compaction Safety

`redact_trust_from_compaction()` guarantees:

1. Every item retains a valid `trust_level` (unknown values → `UNTRUSTED_GENERATED_CONTENT`).
2. Missing `trust_level` → `MODEL_OUTPUT` (never `SYSTEM_POLICY`).
3. `kind` outside `INSTRUCTION`/`DATA` → `DATA`.
4. `INSTRUCTION` on non-`SYSTEM_POLICY` trust → **downgraded to `DATA`**.
5. A `source` is always present.

Compaction therefore cannot launder untrusted content into an instruction
segment — the exact trust-loss failure mode called out in GATE 2.

## 5. Adversarial Coverage

10 injection payloads × 2 parametrized tests, plus compaction, tool-output,
RAG-poisoning, and customer-impersonation tests. All in
`packages/security/tests/test_ai_guardrails_adversarial.py`.

| Test class | Proves |
|---|---|
| `test_injection_detected_in_untrusted_content` (10×) | payloads are detected, neutralized, recorded |
| `test_injection_never_becomes_instruction` (10×) | untrusted trust never yields an instruction segment |
| `test_poisoned_rag_cannot_override_policy` | retrieved text is framed as non-authoritative data |
| `test_tool_output_trust_is_preserved` | tool output carries its own trust marker |
| `test_context_compaction_cannot_erase_trust` | compaction cannot promote DATA → INSTRUCTION |
| `test_context_compaction_downgrades_bogus_trust` | unknown trust degrades, never elevates |
| `test_customer_instruction_cannot_self_declare_system` | customer cannot claim system authority |
| `test_benign_untrusted_content_is_not_flagged` | no false positives on ordinary content |
