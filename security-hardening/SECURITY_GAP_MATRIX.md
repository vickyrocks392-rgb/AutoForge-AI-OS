# Security Gap Matrix (GATE 15)

Consolidated register of every finding across all gates. **CLOSED** = repaired +
regression-tested · **DEFERRED** = documented for a later phase, no code change.

---

## 1. AI Guardrails (GATE 1)

| ID | Control | Existing | Status |
|---|---|---|---|
| G1-1 | Trust-level taxonomy (9 ordered levels) | none | **CLOSED** |
| G1-2 | Explicit guardrail decisions (5 values) | `DecisionType` (different semantics) | **CLOSED** |
| G1-3 | Canonical enforcement entry point | none — callers opted in ad hoc | **CLOSED** |
| G1-4 | Action classification | none | **CLOSED** |
| G1-5 | Capability model (22 capabilities) | `Permissions` (roles, orthogonal) | **CLOSED** |
| G1-6 | Model cannot instantiate/mutate guardrail policy | n/a | **CLOSED** |
| G1-7 | Correlated, auditable decisions | `AuditRecord` | **CLOSED** |
| G1-8 | Fail-closed for sensitive operations | partial | **CLOSED** |
| G1-9 | Guardrails enforced, not just documented | n/a | **CLOSED** |

## 2. Prompt / Context Injection (GATE 2)

| ID | Control | Status |
|---|---|---|
| G2-1 | Source/trust metadata preserved | **CLOSED** |
| G2-2 | Instruction vs data distinction | **CLOSED** |
| G2-3 | Retrieved docs cannot override policy | **CLOSED** |
| G2-4 | Legacy source not executable authority | **CLOSED** |
| G2-5 | Tool output cannot change authorization | **CLOSED** |
| G2-6 | Compaction cannot erase trust metadata | **CLOSED** |
| G2-7 | Adversarial injection tests | **CLOSED** (10 payloads × 2 + 8) |

## 3. Tool / Action Guardrails (GATE 3)

| ID | Control | Status |
|---|---|---|
| G3-1 | Action classification | **CLOSED** |
| G3-2 | Capability check | **CLOSED** |
| G3-3 | Project/resource scope | **Existing** (`AuthorizationEngine` step 6) |
| G3-4 | Worker permission check | **Existing** (`WORKER_SECURITY_PROFILES`) |
| G3-5 | Sandbox check | **Existing** (`SandboxPolicyEngine`, `SecurityBoundaryGuard`) |
| G3-6 | Network policy check | **Existing** (`validate_outbound_url`) |
| G3-7 | Credential policy check | **CLOSED** (expiry) |
| G3-8 | HITL requirement | **CLOSED** |
| G3-9 | **Enforcement immediately before side effect** | **CLOSED** (SHG-01) |
| G3-10 | Direct-bypass negative tests | **CLOSED** |

## 4. Capability Least Privilege (GATE 4)

| ID | Control | Status |
|---|---|---|
| G4-1 | Explicit capability scopes | **CLOSED** |
| G4-2 | Workers receive only required capabilities | **CLOSED** |
| G4-3 | Existing worker profiles preserved | **Existing**, extended not replaced |

## 5. Network / SSRF (GATE 5)

| ID | Control | Status |
|---|---|---|
| G5-1 | Destination validation | **Existing** |
| G5-2 | SSRF / private-network / DNS-rebinding | **Existing** |
| G5-3 | Protocol + timeout limits | **Existing** |
| G5-4 | Capability gate before network reach | **CLOSED** (SHG-01) |
| G5-5 | Egress content inspection (anti-exfiltration) | **DEFERRED** → P2 |
| G5-6 | Request size limits | **DEFERRED** → P3 |

## 6. Credential Mediation (GATE 6)

| ID | Control | Status |
|---|---|---|
| G6-1 | Capability-mediated access | **CLOSED** |
| G6-2 | Expiration enforced | **CLOSED** (SHG-02) |
| G6-3 | Revocation enforced | **Existing** |
| G6-4 | Secret non-disclosure | **Existing** |
| G6-5 | Purpose binding | **DEFERRED** → P2 |
| G6-6 | Strong local encryption at rest | **DEFERRED** → P1 (XOR store) |

## 7. Model Output Trust Boundary (GATE 7)

| ID | Control | Status |
|---|---|---|
| G7-1 | Schema validation before execution | **Existing** (`AgentVerifier`) |
| G7-2 | Tool-call allowlist before execution | **CLOSED** (SHG-01) |
| G7-3 | Guardrail decision before execution | **CLOSED** |
| G7-4 | No `model output → direct execution` | **CLOSED** |
| G7-5 | Malformed/adversarial output tests | **CLOSED** |

## 8. Policy Tamper Resistance (GATE 8)

| ID | Control | Status |
|---|---|---|
| G8-1 | Model cannot modify security/sandbox/HITL policy | **CLOSED** |
| G8-2 | Worker privilege escalation blocked | **CLOSED** |
| G8-3 | Self-approval blocked | **Existing** (`validate_human_approver`) |
| G8-4 | Self-elevation blocked | **CLOSED** |
| G8-5 | No runtime policy-mutation API | **CLOSED** |

## 9. Self-Improvement Boundary (GATE 9)

| ID | Control | Status |
|---|---|---|
| G9-1 | Learning may propose workflows/routing/optimizations/patterns | **CLOSED** |
| G9-2 | Learning cannot grant capabilities/credentials/network/policy | **CLOSED** |
| G9-3 | Promotion requires validation + review + authorization | **CLOSED** |
| G9-4 | Explicit anti-self-escalation tests | **CLOSED** (7 parametrized) |

## 10. Artifact / Project / Tenant Isolation (GATE 10)

| ID | Control | Status |
|---|---|---|
| G10-1 | Durable artifact identity | **Existing** — frozen, protected |
| G10-2 | Project-scoped artifact listing | **Existing** |
| G10-3 | Project scoping in artifact key | **DEFERRED** → P2 (SHG-08) |
| G10-4 | Multi-tenant isolation | **DEFERRED** → Phase 20 |

## 11. API Security (GATE 11)

| ID | Control | Status |
|---|---|---|
| G11-1 | Authentication on protected endpoints | **DEFERRED** → P1 (SHG-06) |
| G11-2 | Object-level authorization / IDOR | **DEFERRED** → Phase 20/23 |
| G11-3 | Project isolation | **Partial** — loopback bind + id sanitization |
| G11-4 | Request validation | **Existing** (pydantic) |
| G11-5 | Secure error handling | **Existing** (secret redaction) |
| G11-6 | Rate limiting | **DEFERRED** → P3 |

## 12. Supply Chain / Build (GATE 12)

| ID | Control | Status |
|---|---|---|
| G12-1 | Lockfile / dependency pinning | **DEFERRED** → P3 (SHG-07) |
| G12-2 | Vulnerability scanning | **DEFERRED** → P3 — **no CVE data available; no results fabricated** |
| G12-3 | SBOM generation | **DEFERRED** → P3 |
| G12-4 | Artifact provenance | **Existing** |
| G12-5 | Release integrity | **Existing** |

## 13–15. Testing, Integration, Certification

| ID | Control | Status |
|---|---|---|
| G13 | Adversarial matrix, ≥26 categories | **CLOSED** |
| G14 | Full-path integration verification | **CLOSED** — `SECURITY_HARDENING_REPORT.md` §6 |
| G15 | Certification | **PASS WITH DEFERRED ITEMS** |

---

## Severity Roll-up

| Severity | Open | Closed this pass | Deferred (documented) |
|---|---|---|---|
| **P0** | **0** | 1 (SHG-01) | 0 |
| **P1** | **0** | 4 (SHG-02…05) | 2 (G6-6, G11-1) |
| **P2** | — | — | 4 (G5-5, G6-5, G10-3, G10-4) |
| **P3** | — | — | 6 |

**No BLOCKER. No unresolved HIGH.**
