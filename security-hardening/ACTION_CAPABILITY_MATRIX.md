# Action Capability Matrix

Least-privilege capabilities required by each action class. Enforced by
`AIGuardrailsEngine.evaluate_capabilities()`; no capability, no execution.

## 1. Full Capability Taxonomy (22)

| Namespace | Capability | Value |
|---|---|---|
| filesystem | read | `filesystem.read` |
| filesystem | write | `filesystem.write` |
| filesystem | delete | `filesystem.delete` |
| process | execute | `process.execute` |
| network | outbound | `network.outbound` |
| git | read | `git.read` |
| git | write | `git.write` |
| git | destructive | `git.destructive` |
| credentials | request | `credentials.request` |
| credentials | use | `credentials.use` |
| credentials | administer | `credentials.administer` |
| artifacts | create | `artifacts.create` |
| artifacts | modify | `artifacts.modify` |
| artifacts | publish | `artifacts.publish` |
| artifacts | delete | `artifacts.delete` |
| deployment | prepare | `deployment.prepare` |
| deployment | execute | `deployment.execute` |
| security | read | `security.read` |
| security | modify | `security.modify` |

## 2. Action Class → Required Capability

| Action class | Required capability | Security-sensitive | Default outcome for model-origin |
|---|---|---|---|
| `READ` | `filesystem.read` | No | ALLOW (with capability) |
| `WRITE` | `filesystem.write` | No | ALLOW (with capability) |
| `DELETE` | `filesystem.delete` | **Yes** | REQUIRE_HITL |
| `EXECUTE` | `process.execute` | **Yes** | REQUIRE_HITL |
| `NETWORK` | `network.outbound` | No | ALLOW + egress policy |
| `CREDENTIAL` | `credentials.use` | **Yes** | REQUIRE_ELEVATED_AUTHORITY |
| `PUBLISH` | `artifacts.publish` | **Yes** | REQUIRE_HITL |
| `DEPLOY` | `deployment.execute` | **Yes** | REQUIRE_ELEVATED_AUTHORITY / HITL |
| `MIGRATE` | `deployment.execute` | **Yes** | REQUIRE_ELEVATED_AUTHORITY / HITL |
| `GOVERNANCE` | `security.modify` | **Yes** | DENY (non-authoritative trust) |

Every class has a non-empty requirement — asserted by
`test_every_action_class_has_capability_requirement`.

## 3. Action Classification

Deterministic prefix mapping; unknown actions fall through to `EXECUTE`
(most restrictive), so new or malformed actions fail closed.

| Prefix | Class |
|---|---|
| `read`, `get`, `list`, `view`, `search`, `inspect` | READ |
| `delete`, `remove`, `destroy`, `purge`, `drop` | DELETE |
| `network`, `http`, `fetch`, `outbound`, `request_url` | NETWORK |
| `credential`, `secret`, `token` | CREDENTIAL |
| `publish`, `release` | PUBLISH |
| `deploy`, `cutover` | DEPLOY |
| `migrat*` | MIGRATE |
| `governance`, `policy`, `security_config`, `configure` | GOVERNANCE |
| `write`, `create`, `update`, `modify`, `patch`, `put` | WRITE |
| *anything else / empty* | **EXECUTE** |

Classification is **re-derived by the platform** on every request. A payload
declaring `READ` for `delete_artifact` is rejected as `INVALID_REQUEST`.

## 4. Relationship to Existing Models

Capabilities are **orthogonal** to the certified `Permissions` taxonomy:

- `Permission` answers *"which role may perform this class of action?"*
- `Capability` answers *"what does this specific side effect require?"*

Worker profiles (`WORKER_SECURITY_PROFILES`) were **not** replaced. The capability
layer is enforced at the side effect and derives from the agent specification's
`allowed_tools`, which the repair made load-bearing.

## 5. Learning-System Capability Ban

`LEARNING_FORBIDDEN_CAPABILITIES` denies self-improvement these outright:

`credentials.use`, `credentials.administer`, `credentials.request`,
`network.outbound`, `security.modify`, `deployment.execute`, `process.execute`,
`filesystem.delete`, `git.destructive`

A learning proposal requesting any of these is denied regardless of proposal
kind — proven by `test_learning_cannot_self_escalate` (7 parametrized cases).
