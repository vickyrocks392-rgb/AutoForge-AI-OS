# 18-LE — GREENFIELD CERTIFICATION REPORT

**FRESH autonomous run. M6-only, single-node. Nothing reused from any previous
greenfield project.** Evidence: `evidence/greenfield.json`.

---

## 1. Verdict

# GREENFIELD CERTIFIED — `final_state = ProjectStatus.FINISHED`

A real M6-generated Python package was produced, its **own** test suite was
executed deterministically **by the platform**, the result governed completion, and
every artifact was durably committed with a verified SHA-256.

---

## 2. Environment

| Item | Value |
|---|---|
| Model | `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` |
| Runtime | MLX-LM on `127.0.0.1:8080` (operator's, already running) |
| Workers | **0** — inference topology unchanged |
| M1 / HP | **not contacted, not configured** |
| Model binding | existing `BaseProviderAdapter.register_model_alias` deployment seam (configuration only, **no source change**) — exactly as 18-L did |

---

## 3. The G-1/G-2/G-3 contract

| Gate | Criterion | Evidence |
|---|---|---|
| **G-1** | A deterministic verification contract exists | `Request.configuration["verification_command"] = "python -m pytest -q tests"` — **declared by the requester**, never invented |
| **G-2** | The verification contract executes | `artifacts/cmd_python_iter_1.log` → `2 passed`, `EXIT_CODE: 0` |
| **G-3** | The deterministic status governs completion | `required=True, performed=True, passed=True, exit_code=0` → `FINISHED` |

**No verification command was silently invented.** The contract is the project's
own pytest command, declared through `Request.configuration` exactly as DECISION B
layer 1 prescribes.

---

## 4. Results

| Requirement | Result | Evidence |
|---|---|---|
| Actual model generation | ✅ | real M6 inference; real source files |
| Real source produced | ✅ | `textmetrics/core.py`, `textmetrics/__init__.py`, `tests/test_textmetrics.py`, `README.md` |
| Source artifacts durable | ✅ | **10/10 `committed`** (4 `source_code`, 1 `diff`, 1 `execution_log`, 1 `evaluation_report`, 3 `summary`) |
| Verification contract exists (G-1) | ✅ | declared command, durable in project state |
| Verification actually executes (G-2) | ✅ | `cmd_python_iter_1.log` |
| **Passing deterministic validation** | ✅ | `exit_code: 0` |
| Validation evidence reaches Review | ✅ | 9 evidence files, incl. the command log and the evaluation report |
| Review explicitly APPROVED | ✅ | review gate approved; completion proceeded |
| **Completion succeeds** | ✅ | **`ProjectStatus.FINISHED`** |
| Artifacts recoverable, matching SHA-256 | ✅ | `all_exist=True, all_hashes_match=True` |
| Zero manual engineering intervention | ✅ | no generated file edited, created or stubbed by hand |


---

## 5. The 18-L gap, closed

**Before (18-L / 18-LD greenfield):**
```
evaluation_report_iter_{1,2,3}.json:
   "status": "inconclusive", "test_results": null, "deterministic_checks": []
no cmd_*.log artifacts at all — zero commands were executed
project's own suite: 2 failed, 4 passed
final review: APPROVED  →  project: finished      ← unsafe
```

**After (18-LE):**
```
cmd_python_iter_1.log:   STDOUT ".. 2 passed"  EXIT_CODE 0
evaluation_report_iter_1.json:
   status: passed
   deterministic_checks: [ ... real checks ... ]
   test_results: { ... real counts ... }
validation: required=True, performed=True, passed=True, exit_code=0
final_state: ProjectStatus.FINISHED                ← safe
```

The loop now actually **runs** the project's declared verification, and the result
is real evidence rather than an absence.

---

## 6. The inverted failure — proof the gate has teeth

An earlier iteration of this same probe produced tests with genuine model
arithmetic errors:

```
generated test: assert char_count('hello\nworld\t') == 11   # actually 12
```

The platform detected it and **blocked**:

```
cmd_python_iter_*.log        FAILED ... 1 failed
evaluation_report            status: failed,
                             deterministic_checks: [exit_code != 0]
validation                   required=True, passed=False, exit_code=1
final_state                  ProjectStatus.COMPLETING     ← never FINISHED
```

The repair cycle ran all 3 iterations (producing versioned `.v2`/`.v3` artifacts
through the existing 18-K versioning) and the loop still refused to certify a
project whose own tests failed.

**This is the exact 18-L failure inverted.** In 18-L, a project whose tests failed
(`2 failed, 4 passed`) reached `FINISHED` with an `APPROVED` review. In 18-LE the
same condition is **blocked**, because deterministic validation now produces truth
and the completion gate enforces it.

---

## 7. Human-intervention audit

| Intervention | Class | Performed? |
|---|---|---|
| Started / stopped / reconfigured the MLX M6 server | infrastructure | **No** — operator's, already running |
| Supplied the greenfield request text and acceptance criteria | harness | Yes (the request is the specification) |
| Declared `verification_command` in `Request.configuration` | harness | Yes — **this is the DECISION B layer-1 contract**, not an intervention on output |
| Bound the served model tag to the catalog ids via `register_model_alias` | deployment configuration | Yes — the existing provider-neutral seam, no source change |
| Created the empty workspace | harness | Yes |
| **Wrote, edited or corrected any generated source** | — | **No — none occurred** |
| **Created, registered or altered any project artifact** | — | **No — none occurred** |
| **Invoked, stubbed or influenced the Review Engine's verdict** | — | **No — none occurred** |
| **Transitioned any project state by hand** | — | **No — none occurred** |
| **Modified M1, HP, worker scheduling or inference topology** | — | **No — none occurred** |
| Ran the project's own test suite to observe it | harness observation | Yes — the declared verification contract, executed by the platform |

---

## 8. Reproducibility

```bash
.venv/bin/python 18LE-canonical-integration/probe_greenfield.py
# → evidence/greenfield.json
```

The probe drives the real composed system end to end. It uses no mocks and no
bypasses, and records the model, the declared verification contract, the durable
artifact counts, the validation truth, the review evidence set, the generated file
list and the artifact hash-integrity result.
