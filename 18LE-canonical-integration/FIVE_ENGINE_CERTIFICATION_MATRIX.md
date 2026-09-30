# 18-LE — FIVE COMMERCIAL ENGINE CERTIFICATION MATRIX

**Two results per engine**, as required: **A. Existing Engine Certification** and
**B. Canonical Integration**. No engine is marked broken because of a routing
failure — routing was the missing edge, not an engine defect.

Evidence: `evidence/canonical_routing.json`, `evidence/canonical_architecture_trace.json`.

---

## 1. Required matrix

| Engine | Existing Certification | Canonical Routing | Real Output | Deterministic Validation | Durable Artifacts | Review | Completion |
|---|---|---|---|---|---|---|---|
| **RAG Knowledge** | **PASS** (123 PE tests) | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| **Custom AI Agent** | **PASS** (123 PE tests) | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| **AI Automation** | **PASS** (123 PE tests) | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| **Code Migration** | **PASS** (123 PE tests) | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| **Legacy Modernization** | **PASS** (383 mod + 91 G.3/B-2) | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |

---

## 2. A. Existing engine certification (unchanged)

| Engine | Suite | Result |
|---|---|---|
| All four Power Engines | `packages/power_engines/tests/` | **123 passed, 3 skipped, 1 environmental** |
| Legacy Modernization | `packages/modernization/tests/` | **383 passed, 59 skipped** |
| G.3 real-source + B-2 | `test_18lr_b2_real_source_transformation.py`, `test_g3_llm_and_transform.py` | **91 passed** |

**The single failure is environmental, not a product defect:**
`test_health_check_script_execution_and_exit_codes` declares a service on host
port **8080**; the operator's MLX inference server occupies it, so
`--require-service` correctly finds it online and asserts "offline". Confirmed by
`lsof`; documented in 18-LR §2; not caused by this gate.

**No engine source file was modified.** `git diff --name-only` contains no
`power_engines/` file. The only `modernization/` entry is `pipeline.py`, which is
18-LR's pre-existing B-2 repair, not this gate's.

---

## 3. B. Canonical integration — per engine

| Aspect | RAG | Agent | Automation | Migration | Modernization |
|---|---|---|---|---|---|
| Capability | `rag_knowledge` | `custom_ai_agent` | `ai_automation` | `code_migration` | `legacy_modernization` |
| Resolution source | `project_configuration` | `project_configuration` | `project_configuration` | `project_configuration` | `project_configuration` |
| **Engine actually invoked** | **`RAGKnowledgePowerEngine`** | **`CustomAIAgentPowerEngine`** | **`AIAutomationPowerEngine`** | **`CodeMigrationPowerEngine`** | **`ModernizationPipeline`** |
| Loops routed | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| Loop status | `complete` | `complete` | `complete` | `complete` | `complete` |
| Real output (delivery) | ✅ | ✅ | ✅ | ✅ | n/a (transform) |
| Boundary adaptation | base spec | base spec (engine adapts internally) | **typed spec** (engine rejects base by design) | **typed spec + real source** (engine rejects base by design) | **sync → `asyncio.to_thread`**, real G.2 reconnaissance |
| Engine verification transported | `grounding_score`, `real_inference`, `syntax_valid`, `tests_passed`, `tests_run` | `defects_count`, `passed`, `proprietary_violations` | `defects_count`, `passed`, `proprietary_violations` | `passed`, `failed`, `inconclusive`, `total` | `pipeline_status`, `real_source`, `transformation_records`, `units_transformed`, `units_failed`, `wave_count`, `gate_decisions`, `analysis_present` |
| Durable artifacts | committed | 4 committed | committed | committed | committed |
| Review evidence | present | 4 files | present | present | present |

**Custom AI Agent — full 11-stage lifecycle observed** (the most complete proof):
```
engine_stages: [INTAKE, UNDERSTAND_ANALYZE, PLAN, EXECUTE, OBSERVE, VERIFY,
                DIAGNOSE, REPAIR, RE_VERIFY, PACKAGE, DELIVER]
engine_verification_scorecard: {defects_count: 0, passed: true,
                                proprietary_violations: 0}
delivery_exists: true
durable_artifacts: 4, durable_all_committed: true
```

**Legacy Modernization — B-2 non-regression:** real COBOL `LEDGER.cbl` + JCL
`LEDGER.jcl` in, real modernized output out. The router **refuses** to synthesise a
placeholder and raises explicitly when no real `legacy_source_root` is declared —
B-2 cannot regress through the new adapter. The certified G.3 suite remains
**91 passed**.

---

## 4. Two-dimension summary (the gate's required separation)

| Engine | ENGINE IMPLEMENTATION | CANONICAL INTEGRATION | Change vs 18-LR |
|---|---|---|---|
| RAG Knowledge | **PASS** | **PASS** | FAIL → **PASS** |
| Custom AI Agent | **PASS** | **PASS** | FAIL → **PASS** |
| AI Automation | **PASS** | **PASS** | FAIL → **PASS** |
| Code Migration | **PASS** | **PASS** | FAIL → **PASS** |
| Legacy Modernization | **PASS** | **PASS** | FAIL → **PASS** |

At 18-LR every engine was `IMPLEMENTATION=PASS / INTEGRATION=FAIL`. **No engine's
implementation status changed**; only the missing integration edge was built.

`"capabilities_tested": 5, "canonical_routing_pass": true`

---

## 5. Evidence that engines were not modified

| Check | Result |
|---|---|
| `git diff --name-only` ∩ `power_engines/src` | **empty** |
| `git diff --name-only` ∩ `modernization/src` | only `pipeline.py` (18-LR's pre-existing B-2 repair) |
| Power-engine test count unchanged | 123 passed, same as 18-LD's re-run |
| Modernization test count unchanged | 383 passed, same as 18-LR/18-LD |

The engines are **called**, never modified. All adaptation happens at the routing
boundary in `capability_router.py`.
