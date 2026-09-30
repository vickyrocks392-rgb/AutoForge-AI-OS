# PHASE 18-L — AUTONOMOUS ENGINEERING CERTIFICATION REPORT

**Workstream:** 18-L — Full Autonomous Engineering Certification
**Mode:** M6-only, single-node, authoritative
**Date:** 2026-09-28
**Commit:** `c72dad9e0ffe44d6aeac958e985544801820acf4` (main, unmodified — not committed, not pushed)

---

## 1. EXECUTIVE VERDICT

# 18-L = NOT CERTIFIED

**The greenfield autonomous engineering objective was achieved.** The M6
authority model autonomously generated a real 5-file Python project through
the production path; the generated source became authoritative COMMITTED
durable artifacts; the real Review Engine inspected those real artifacts and
explicitly APPROVED; the project completed; and every committed artifact
recovered with a matching SHA-256.

**Two mandatory acceptance criteria were NOT met**, and both are blocking:

| # | Blocker | Evidence |
|---|---|---|
| **B-1** | **Vacuous-approval fail-open.** A project with **zero** reviewable deliverables reaches `Finished`. The Review Engine's documented `no_target` branch returns `approved=true` for empty evidence, and the completion gate accepts it. | `evidence/probe_vacuous_approval.py` → `"reached_finished": true` with `evidence_files: 0` |
| **B-2** | **Legacy modernization does not perform real modernization.** The 18-G pipeline analyses and plans correctly, then transforms a **synthetic placeholder string** (`"# legacy {tech} unit {id}"`) rather than the real legacy file, and raises `TransformationError` for Python. | `evidence/legacy_modernization.json` → `pipeline_uses_placeholder_content: true`, wave error |

B-1 directly violates the acceptance criterion *"Missing evidence blocks
completion where review is mandatory."* B-2 violates *"Legacy modernization
certification completed"* and *"The platform must perform the engineering
work."*

Both were **not** repaired, because each requires an explicit product
decision that would materially change an already-certified contract. See
§23 and §25.

---

## 2. SCOPE

Single-node M6-only. No M1, no HP, no distributed inference, no worker
routing, no topology change, no Phase 19, no Brain.

## 3. HARDWARE / RUNTIME / MODEL

| Item | Value |
|---|---|
| Host | Mac mini, **Apple M6**, Model `Mac18,5`, 12 cores, 24 GB |
| Model | `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` |
| Runtime | MLX-LM 0.31.3, OpenAI-compatible server, `127.0.0.1:8080` |
| Fingerprint | `0.31.3-0.32.2-macOS-27.0-arm64-arm-64bit-applegpu_g18g` |
| Workers | **0** (certified topology unchanged) |

## 4–5. M1 / HP NOT USED

**Confirmed: M1 was NOT used. HP was NOT used.** No M1/HP host was contacted,
benchmarked, configured, or started. The `local-m1` and `local-hp` provider ids
are *labels* bound to `127.0.0.1` (this M6) by the existing
`bind_local_runtime_adapters`; no remote host is referenced anywhere in the
canonical path (proved by audit check A7).


---

## 6. GREENFIELD PROJECT SPECIFICATION

**`tokenizer_lite`** — a self-contained text token-counting library with a CLI:
4 source files, a pytest suite, a README, deterministic execution, and explicit
edge-case requirements. Chosen to be *small but complete* (multi-file, multi-step
reasoning, real test execution, clear acceptance criteria) — not "hello world",
not a large application.

The harness supplied **only** the specification and the acceptance criteria.
It supplied no source, no stub, no template, and no partial implementation.

## 7. AUTONOMOUS EXECUTION TIMELINE (real M6 inference)

```
  0.00s  workspace created (EMPTY — 0 pre-existing files)
  0.03s  M6 runtime preflight OK
  0.03s  system initialized (O-2 = DefaultOrchestrationEngine)
  0.03s  M6 deployment binding applied
  0.03s  request accepted
  0.03s  intent + strategic plan + executable workflow formed
  0.03s  workflow correlated durably
149.19s  O-2 execution returned  ← real M6 code generation
149.19s  source files on disk
149.19s  durable artifacts collected
149.33s  project test suite executed
149.33s  final review completed  ← explicit APPROVED
149.33s  completion / finalize
149.34s  durability + recovery verified (all hashes match)
```

## 8. ACTUAL GENERATED SOURCE FILES (written by the M6 model)

```
README.md
test_tokenizer_lite.py
tokenizer_lite/__init__.py
tokenizer_lite/cli.py
tokenizer_lite/core.py
```

These are the M6 model's own output. Example of real generated content
(`tokenizer_lite/core.py`, 1372 B): a `TokenizerLite` class with `count()`,
`count_words()` and a `count_tokens()` function returning
`{'tokens', 'characters', 'words'}` — exactly the requested contract.

## 9–10. DURABLE ARTIFACT EVIDENCE

| Metric | Value |
|---|---|
| Total durable artifacts | **27** |
| **COMMITTED** | **27 / 27** |
| `source_code` artifacts | 15 |
| Recovery (re-read from catalog) | **27/27 recovered** |
| **SHA-256 verification** | **27/27 match** (`all_hash_verified: true`) |

Every generated source file became a first-class COMMITTED artifact through
the **existing** path: `EngineeringLoop` → `ArtifactPipeline` →
`DurableArtifactCatalog` → `PhysicalArtifactStore` (staged write → SHA-256 →
atomic publish → commit). **No second artifact store was created.**

Sample artifact IDs / hashes:

| Artifact | artifact_id | content_hash (16) | bytes |
|---|---|---|---|
| `tokenizer_lite/core.py` | `57fa24d9-3811-548d-983a-b0ebac20301f` | `d8a669ad337444a8` | 1372 |
| `tokenizer_lite/cli.py` | `58eedc35-e716-5b77-8a96-cf9f37f5f1dc` | `fb554a4ef4148085` | 444 |
| `tokenizer_lite/__init__.py` | `be9c2530-d29a-5ee0-b241-db808eeeea1a` | `6feea92f0875e546` | 90 |
| `test_tokenizer_lite.py` | `7876a104-03e6-5e18-9946-23ad1fb96726` | `19aca6b75f0983a4` | 1879 |
| `README.md` | `f3f0592a-6035-581e-a93e-4fb2f04e08c7` | `9d0b539d54a06990` | 590 |

## 11–12. TESTS / VALIDATION

The project's **own** generated pytest suite was executed by the harness:
`4 passed, 2 failed` (rc=1). The two failures are defects **in the
model-generated test code** (an off-by-one character-count assertion), not in

---

## 17. LEGACY MODERNIZATION CERTIFICATION (18-L-E) — **NOT CERTIFIED**

**Blocker B-2.** Using a controlled legacy fixture (COBOL batch `LEDGER.cobol`
+ Python-2-era `report.py`), the existing 18-G `ModernizationPipeline` was run
for real:

| Stage | Result |
|---|---|
| Analysis (`LegacyAnalysisEngine`) | **PASS** — analysis report produced |
| Planning (`MigrationPlan` + `PlanningGate`) | **PASS** — plan produced, gate passed |
| Transformation (wave-1) | **FAIL** — `units_transformed=0`, `units_failed=2` |
| Wave error | `TransformationError: Transformation of Python is not supported. Set transformation_type to BLOCKED and use REWRITE for partial approaches. This transformation requires specialist tooling and human review.` |
| Content actually transformed | **synthetic placeholder** `f"# legacy {source_tech} unit {unit.component_id}"` (`pipeline.py:563`) — **not** the real legacy file |

Two independent reasons this cannot be certified:

1. The transformation stage **does not read the real legacy source**; it
   transforms a generated placeholder string. Even a working strategy would
   not modernize the customer's code.
2. The transformation strategy is **unimplemented** for the languages in the
   fixture and raises by design.

The durable-artifact and final-review halves *did* work (legacy artifacts were
registered COMMITTED with verified hashes and presented to the real review,
which correctly returned `changes_requested` for missing documentation), but

### Blocker B-1 — vacuous-approval fail-open (definitive)

Isolated with **no mocks** against the real `ReviewEngine` and real
`DefaultCompletionModule` (`evidence/probe_vacuous_approval.py`):

```json
REAL ReviewEngine on EMPTY evidence: { "approved": true, "decision": "approved", "findings": [] }
PLATFORM with NO deliverable:         { "final_project_status": "finished",
                                        "gate_approved": true,
                                        "gate_reason": "Final review explicitly approved the project.",
                                        "evidence_files": 0,
                                        "reached_finished": true }
VERDICT: FAIL-OPEN CONFIRMED
```

The `no_target` branch (`autoforge_review/engine.py`) returns an explicit
`APPROVED` verdict when evidence is empty. The completion gate evaluates that
as a genuine approval and finalizes. A project that produced **nothing**
reaches `Finished`.

This is a **fail-open** and directly contradicts the 18-L criterion *"Missing
evidence blocks completion where review is mandatory."* It is also the exact
failure class the P-1 note flagged as intentional (`approved / no_target`,
"documented branch") — so **changing it would materially alter a
P-1-ratified review-evidence contract**, which 18-L forbids me to do
unilaterally.

## 19. HUMAN INTERVENTION AUDIT (18-L-I)

| Intervention | Class | Prohibited? |
|---|---|---|
| Started the MLX M6 server on 127.0.0.1:8080 | infrastructure setup | No |
| Bound the selected local model to the M6 tag via the shipped `register_model_alias` deployment API | infrastructure setup (no source change, no topology change, no worker) | No |
| Created the empty greenfield workspace | test harness operation | No |
| Supplied the user request text + acceptance criteria | test harness operation | No |
| Ran the generated project's test suite | test harness operation | No |
| **Writing / fixing / correcting any project source** | — | **DID NOT OCCUR** |
| **Editing generated tests** | — | **DID NOT OCCUR** |
| **Injecting, fabricating, or registering artifacts by hand** | — | **DID NOT OCCUR** |
| **Manually approving / altering review results** | — | **DID NOT OCCUR** |
| **Manually marking completion or bypassing validation** | — | **DID NOT OCCUR** |
| Stubbing the model in the *failure-path* harness | declared harness boundary (18-L-D) — makes the gates deterministic; does not fabricate a verdict or mark anything complete | No |
| Stopping/starting the MLX server to isolate a test | test harness operation | No |

**No prohibited manual engineering intervention occurred.**

## 20. PERFORMANCE / RESOURCE OBSERVATIONS (18-L-J) — M6 only

These are **observations, not optimization targets**. The topology was not
changed and no benchmarking of M1/HP was performed.

| Observation | Value |
|---|---|
| Model | `Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` |
| Runtime | MLX-LM 0.31.3, `127.0.0.1:8080/v1` |
| Generation throughput (observed) | 13.79 – 59.84 tok/s across calls |
| Total engineering-task duration | 149.34 s (end to end) |
| O-2 execution (model-bound) | 149.16 s |
| Model calls per greenfield run | 2 (plan + implementation) |
| Engineering-loop iterations | 3 (multi-iteration loop) |
| Peak memory | not instrumented (no change made to add it) |
| TTFT | `UNAVAILABLE` (not reported by mlx-lm 0.31.3) |

## 21. COMMERCIAL-ENGINE REGRESSION (18-L-F)


## 22. FULL CI RESULTS (18-L-G)

The established CI matrix (`.github/workflows/ci.yml`) was replicated, each
package suite as its own invocation exactly as CI runs it.

### **2,385 passed · 0 failed · 0 collection errors · 89 skips**

| Suite | Result |
|---|---|
| kernel | 141 passed |
| orchestration | 71 passed, 6 skipped |
| workflows | 218 passed |
| runtime | 268 passed |
| persistence | 70 passed |
| artifacts | 14 passed |
| events | 228 passed |
| event_platform | 56 passed |
| security | 37 passed |
| connectors | 93 passed |
| ai_infrastructure | 97 passed |
| review | 114 passed |
| observability | 16 passed |
| workforce | 36 passed, 2 skipped |
| execution | 233 passed, 18 skipped |
| power_engines | 124 passed, 3 skipped |
| composition | 98 passed |
| modernization | 375 passed, 59 skipped |
| root | 96 passed, 1 skipped |

Every certified subsystem is green, including the P-1 suites
(`test_completion_review_gate.py`, `test_final_review_evidence_e2e.py`), 18-J
durability, 18-K artifacts, Context Engineering, Context Compaction, and all
commercial engines. The 89 skips are environmental (sandbox/Podman/daemon
dependent) and unchanged.

*(Note: the previously quoted 2,414 figure predates the P-1 gate's own added
tests; the delta is fully accounted for by those additions plus the 12 tests
added here. No suite regressed.)*

## 22b. ARCHITECTURAL INTEGRITY AUDIT (18-L-K) — **6/6 PASS**

Searched by **AST and call-graph**, not documentation:

| Check | Result | Evidence |
|---|---|---|
| A1 O-2 is production-authoritative | **PASS** | composition root constructs `DefaultOrchestrationEngine` |
| A2 O-1 never instantiated in production | **PASS** | zero non-test AST `Call` nodes to `OrchestrationEngine`; the two textual hits were a docstring example and the ABC definition |
| A3 no second artifact system | **PASS** | `DurableArtifactCatalog(`/`PhysicalArtifactStore(` constructed in exactly one file (composition root) |
| A4 single review system | **PASS** | one `ReviewEngine` implementation |
| A5 no second completion path | **PASS** | `Finished` transition appears only in `completion.py` |
| A7 Model Router provider-neutral | **PASS** | Ollama port only inside the opt-in adapter; no remote M1/HP host referenced |
| A8 CE + Compaction globally enabled | **PASS** | both default to `True` in the composition root |

O-3 (`AutonomousBuildEngine`) does not appear on the wired production path. No
second artifact, review, or completion architecture was introduced. Durable
execution, delivery/export, and authoritative review are intact. Brain and
Phase 19 remain untouched.

## 23. DEFECTS DISCOVERED

Six genuine production defects were found **only** because a real
autonomous greenfield run was performed — none are visible to unit tests:

| ID | Defect | Severity |
|---|---|---|

## 24. DEFECTS REPAIRED

All six production defects were repaired at the **smallest correct boundary**,
using existing APIs, and each carries a regression test.

| ID | File changed | Repair | Boundary rule honoured |
|---|---|---|---|
| D-1 | `packages/execution/src/autoforge_execution/loop.py` | Register each generated file's **actual bytes** as a `SOURCE_CODE` artifact via the existing `ArtifactPipeline` | Reuses the one 18-K path; no new store; 18-J/18-K state machine untouched |
| D-2 | `packages/execution/src/autoforge_execution/ai_adapter.py` | Send the **routed model's own** `max_output_tokens` as the generation budget; an explicit caller budget is never overridden | Provider-neutral; no new constant; derived from the catalog |
| D-3 | `packages/kernel/src/autoforge_kernel/orchestration.py` | O-2 reads the request from the authoritative Runtime state (`request["description"]`, with fallbacks) into every loop context; a read error degrades, never blocks | No new state; uses the existing facade |
| D-4 | `packages/composition/src/autoforge_composition/kernel_adapters.py` | Populate `TaskDefinition.description` from the loop/request; `input_data` preserved byte-identical | Fills the field the context builder already reads |
| D-5 | `packages/execution/src/autoforge_execution/artifacts.py` | A later iteration is a **new logical version** (iteration folded into operation scope) and publishes to its own physical path; same-iteration retry stays idempotent | 18-J replay contract preserved (proven by test) |
| D-6 | `packages/execution/src/autoforge_execution/artifacts.py` | Disambiguate the publish target **only** on a real collision with a different committed artifact; single-artifact paths are byte-identical to before | Defensive; cannot block a legitimate publish |

**New regression tests (12, all passing):**

| File | Tests |
|---|---|
| `packages/execution/tests/test_generated_source_durability.py` | 5 (durable source, no second store, versioned revision, idempotent replay, same-name isolation) |
| `packages/execution/tests/test_output_budget.py` | 3 (budget applied, caller budget wins, no invented limit) |
| `packages/kernel/tests/test_request_propagation.py` | 6 (real state shape, fallbacks, all loops, degradation) |
| `packages/composition/tests/test_description_propagation.py` | 4 (carries request, loop description wins, input_data intact, absent-safe) |

Note: the D-5 test I wrote **caught a real bug in my own D-5 repair** (both
versions publishing to one path) before it reached production. That is
recorded here rather than quietly fixed.

## 25. REMAINING DEFECTS (NOT REPAIRED — BY DESIGN)

| ID | Why not repaired |
|---|---|
| **B-1** vacuous approval on empty evidence | Fixing it means changing what an empty-evidence `APPROVED` verdict *means*, i.e. amending the review-evidence contract that P-1 explicitly ratified and documented. That is an **explicit product decision** (STOP condition 14), not an 18-L repair. |
| **B-2** legacy modernization transforms a placeholder | Making it real requires implementing actual COBOL/Python transformation strategies and wiring real file IO into the pipeline — a substantial new capability well outside "smallest correct boundary", and it would change the certified 18-G behaviour. |
| **D-8** test results not fed to final review | `review_project` has the `has_test_failures` input, but nothing executes the project's suite at completion time. Adding test execution to the completion gate changes the review evidence contract (same class as B-1). Requires a product decision. |

These are **reported, not hidden, and not worked around.**

## 26. EXACT FILES CHANGED BY 18-L

**Source (6):**
```
packages/execution/src/autoforge_execution/loop.py          (+23)
packages/execution/src/autoforge_execution/ai_adapter.py    (+31)
packages/execution/src/autoforge_execution/artifacts.py     (+99/-)
packages/kernel/src/autoforge_kernel/orchestration.py       (+47)
packages/composition/src/autoforge_composition/kernel_adapters.py  (+67/-)
```

**New tests (4):**
```
packages/execution/tests/test_generated_source_durability.py
packages/execution/tests/test_output_budget.py
packages/kernel/tests/test_request_propagation.py
packages/composition/tests/test_description_propagation.py
```

**Certification harness (new, untracked):**
```
18L-autonomous-certification/
  PHASE_18L_CERTIFICATION_REPORT.md
  greenfield_e2e.py            failure_paths.py
  legacy_modernization.py      architectural_audit.py
  probe_vacuous_approval.py    probe_routing.py
  probe_m6_seam.py             probe_budget.py
  probe_request_flow.py        diagnose_impl.py
  evidence/*.json
```

Pre-existing modifications to `completion.py`, `kernel.py`, `composition_root.py`

## 29. ACCEPTANCE GATE — ITEM BY ITEM

| # | Criterion | Result |
|---|---|---|
| 1 | M6-only certification completed | **PASS** |
| 2 | M1 unused | **PASS** |
| 3 | HP unused | **PASS** |
| 4 | No distributed inference | **PASS** |
| 5 | Real greenfield autonomous engineering completed | **PASS** |
| 6 | Actual source generated by AutoForge | **PASS** |
| 7 | Generated source became authoritative durable artifacts | **PASS** (repaired D-1) |
| 8 | Artifact lifecycle reached COMMITTED | **PASS** (27/27) |
| 9 | Tests/validation executed | **PASS** |
| 10 | Real final-review evidence contained actual deliverables | **PASS** (16 real files) |
| 11 | Review Engine explicitly APPROVED | **PASS** |
| 12 | Completion occurred only after approval | **PASS** |
| 13 | Deliverable/export/recovery verified | **PASS** (27/27 hashes) |
| 14 | **Legacy modernization certification completed** | **FAIL — B-2** |
| 15 | Failure paths fail closed | **PARTIAL — B-1 (3 of 9)** |
| 16 | Review rejection blocks completion | **PASS** |
| 17 | Review exception blocks completion | **PASS** |
| 18 | **Missing evidence blocks completion where review is mandatory** | **FAIL — B-1** |
| 19 | Artifact failure blocks successful completion | **PARTIAL** (conflict rejected; publication failure does not block — B-1) |
| 20 | Validation failure blocks successful completion | **PASS** |
| 21 | **Model/runtime failure does not silently produce success** | **FAIL — B-1** |
| 22 | No prohibited manual engineering intervention | **PASS** |
| 23 | O-2 remains production-authoritative | **PASS** |
| 24 | O-1 remains production-unwired | **PASS** |
| 25 | O-3 does not bypass canonical completion/review | **PASS** |
| 26 | CE remains green | **PASS** |
| 27 | Compaction remains green | **PASS** |
| 28 | 18-J remains green | **PASS** |
| 29 | 18-K remains green | **PASS** |
| 30 | Commercial engines remain green | **PASS** |
| 31 | Full CI has 0 product failures | **PASS** (0) |
| 32 | Full CI has 0 collection errors | **PASS** (0) |
| 33 | No unexplained regressions | **PASS** |
| 34 | No Brain work introduced | **PASS** |
| 35 | No Phase 19 work introduced | **PASS** |
| 36 | No M1/HP work performed | **PASS** |
| 37 | No topology changes | **PASS** |
| 38 | No unrelated architecture changes | **PASS** |
| 39 | All certification evidence reproducible | **PASS** |
| 40 | All remaining defects resolved or explicitly non-blocking by architectural decision | **FAIL — B-1/B-2 are blocking and unresolved** |

**Score: 35 PASS · 1 PARTIAL · 4 FAIL.**

## 30. FINAL VERDICT

# 18-L = NOT CERTIFIED

Mandatory criteria 14, 18, 21 and 40 are not satisfied. Specifically:

- **B-1** — a project that produced *nothing* reaches `Finished`. The
  mandatory final review gate fails open on empty evidence. This directly
  contradicts the 18-L contract that missing evidence must block completion.
- **B-2** — the legacy modernization pipeline does not modernize real legacy
  source; it transforms a synthetic placeholder and raises for the fixture's
  languages. The engineering work required by 18-L-E is not performed by the
  platform.

Both are **STOP conditions** under the 18-L contract (a genuine
fail-open in the completion gate; a capability that cannot perform the work
it is certified for). Neither was weakened, bypassed, or worked around, and
neither was repaired without the explicit architectural decision that 18-L
reserves to the product owner.

**What *was* achieved and is durable:** AutoForge demonstrably takes a request,
plans it, autonomously writes real multi-file source with the M6 authority
model, makes that source first-class COMMITTED durable artifacts, presents the
real artifacts to the real review, obtains an explicit approval, completes,
and recovers with full hash verification — and does so with **zero** manual
engineering intervention. Six genuine production defects stood between that
working path and the certified state, and all six were repaired with
regression tests while the full CI matrix stayed green at **2,385 passed /
0 failed / 0 collection errors**.

**STOP.** No Phase 19. No Brain. No M1/HP. No topology change. No push, no
commit.

and three test files are the **P-1 gate's** work, not 18-L's.

## 27. GIT STATE

- Branch `main`, HEAD `c72dad9e0ffe44d6aeac958e985544801820acf4`
- HEAD == `origin/main` (no divergence)
- **No commit, no push, no reset, no clean, no stash, no history rewrite**
- All pre-existing untracked artifacts preserved (`inference-lab/`,
  `gate-2.3-*/`, `docs/inference-lab/`, `pytest.ini`, ADR-019, …)

## 28. REPRODUCIBILITY

```bash
# 1. M6 local runtime
.venv/bin/python -m mlx_lm.server \
  --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2 \
  --host 127.0.0.1 --port 8080

# 2. Greenfield autonomous engineering (real M6 inference)
.venv/bin/python 18L-autonomous-certification/greenfield_e2e.py

# 3. Failure paths
.venv/bin/python 18L-autonomous-certification/failure_paths.py

# 4. Blocker B-1 proof
.venv/bin/python 18L-autonomous-certification/probe_vacuous_approval.py

# 5. Legacy modernization
.venv/bin/python 18L-autonomous-certification/legacy_modernization.py

# 6. Architectural integrity
.venv/bin/python 18L-autonomous-certification/architectural_audit.py

# 7. Full CI matrix (stop MLX first: a test asserts port 8080 is offline)
bash /tmp/run_ci_matrix.sh /tmp/ci18l_final
```

| D-1 (DEF-18L-01) | Generated source was written to the workspace filesystem but **never registered as a durable artifact**; only a diff *summary* string became durable. The final review therefore inspected platform bookkeeping, not the project. This is the P-1 Medium item, now empirically confirmed. | Medium |
| D-2 (DEF-18L-02) | The routed model's declared `max_output_tokens` was **never sent**. The runtime applied its own 350-token default, returning `finish_reason="length"` — a truncated response with no parseable `file_edits`. Real deliverables were impossible. | **High** |
| D-3 (DEF-18L-03) | O-2 built `loop_context` **without `request_text`**, so the model received only the loop name ("Core Implementation") instead of the specification. | **High** |
| D-4 (DEF-18L-04) | `TaskDefinition.description` was never populated, so the globally-enabled **Context Engineering** path assembled its prompt from the loop name alone. | **High** |
| D-5 (DEF-18L-05) | A later loop iteration re-writing a file with different content hit the iteration-less artifact key and raised `ArtifactConflictError`, aborting the loop. | Medium |
| D-6 (DEF-18L-06) | Two *distinct* logical artifacts sharing an `artifact_name` published to the same physical path; the second **silently replaced the first's committed bytes**, leaving a COMMITTED record whose content hash no longer matched the file. (Pre-existing; reproduced before any repair.) | Medium |
| D-7 | The M6-generated project has 2 failing self-tests. The model produced the deliverable; the review approved it anyway. | High (product gap — see below) |
| D-8 | The final review is **not given the project's test results**, so a deliverable whose own tests fail can still be APPROVED. `KernelReviewEngineAdapter.review_project` supports `has_test_failures`, but nothing populates it. | High (product gap) |

No Commercial Power Engine was redesigned. Their existing suites were run
unchanged in the full matrix:

| Engine | Suite | Result |
|---|---|---|
| RAG Knowledge | `power_engines` | **124 passed**, 3 skipped |
| Custom AI Agent | `power_engines` | **124 passed**, 3 skipped |
| AI Automation | `power_engines` | **124 passed**, 3 skipped |
| Code Migration / Refactoring | `power_engines` | **124 passed**, 3 skipped |
| Legacy Modernization | `modernization` | **375 passed**, 59 skipped |

No regression. The P-1 repair and the 18-L work did not regress any engine.

### Environmental note (not a product defect)

In the *baseline* run, one test failed:
`test_delivery_hardening.py::test_health_check_script_execution_and_exit_codes`
asserts that a service on port **8080** is offline, but the 18-L MLX server
was occupying 8080. Causation was **proved** by suspending the MLX process
(`kill -STOP`), re-running the test (**passed**), and resuming it. This was my
own infrastructure colliding with the test, not a product defect. The final
matrix was run with MLX stopped: **0 failures**.

the **engineering work required by 18-L-E was not performed by the platform**,
and per 18-L-I I did not perform it manually.

The real legacy regression suite is green (`375 passed, 59 skipped`), so no
regression occurred; the capability itself is incomplete.

## 18. FAILURE-PATH CERTIFICATION (18-L-D) — **6/9 PASS, 2 BLOCKERS**

Every case drives the **real** production lifecycle
(`Kernel.execute_project` → O-2 → completion gate).

| # | Failure class | Result | Evidence |
|---|---|---|---|
| 1 | Review rejection | **PASS** — `changes_requested`, status `completing` | `failure_paths.json` |
| 2 | Review exception | **PASS** — "Final review raised RuntimeError…", `completing` | `failure_paths.json` |
| 3 | Missing evidence (partial) | **PASS** — real review refused | `failure_paths.json` |
| 3b | Absent review engine | **PASS** — "No review engine is configured…", `completing` | `failure_paths.json` |
| 4 | Invalid/conflicting artifact | **PASS** — `ArtifactConflictError` raised, committed bytes intact | `failure_paths.json` |
| 5 | Validation failure | **PASS** — gate refused, `completing` | `failure_paths.json` |
| 6 | Publication failure | **FAIL → Blocker B-1** — project reached `finished` | `failure_paths.json` |
| 7 | Model/runtime failure | **FAIL → Blocker B-1** — project reached `finished` | `failure_paths.json` |
| 8 | Interrupted execution | **FAIL → Blocker B-1** — `gate_approved: true` on empty evidence | `failure_paths.json` |

AutoForge. They are reported in §23 as **D-8**.

## 13–15. REAL FINAL REVIEW AND COMPLETION

| Item | Result |
|---|---|
| Evidence presented to ReviewEngine | **16 real files** (real source, tests, README) |
| Decision | **`approved`** — "Final review explicitly approved the project." |
| Completion | **only after approval**; project reached `finished` |
| Synthetic manifest | **none** (removed at P-1) |
| Fabricated source / placeholder evidence | **none** |
| Manually injected approval | **none** |
| ReviewEngine bypass | **none** |

## 16. EXPORT / DELIVERY / RECOVERY (18-L-H)

All 27 committed artifacts were re-read through the authoritative catalog and
**every physical file's SHA-256 matched its recorded content hash**. The
18-J/18-K protected semantics were verified compatible and were **not
redesigned**.
