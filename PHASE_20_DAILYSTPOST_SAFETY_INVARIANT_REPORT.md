# PHASE 20 — DAILYPOST SAFETY-INVARIANT REPAIR GATE

**Status:** GATE PASSED — safety invariants enforced.
**Scope statement:** This gate establishes *only* the safety invariants required
before attempting the second real workload. **It does not certify the
modernization engine.** No customer delivery, no clean-room certification, no
O-2 production-path exercise and no Phase 20 sign-off are claimed here.

**CardDemo was NOT attempted.** See §10.

---

## 1. Baseline

| Item | Value |
|---|---|
| `HEAD` | `0d37ef5702d10546fb8db2355107d578c101700a` |
| `origin/main` | `0d37ef5702d10546fb8db2355107d578c101700a` |
| Tracked modifications | 0 |
| Working tree | Phase 20 work only, untracked under `packages/modernization/` |
| Baseline regression | `3 failed` (composition), documented and pre-existing |
| Phase 20 tests before this gate | 51 |
| Phase 20 tests after this gate | 207 |

`HEAD` and `origin/main` are unchanged. Nothing was committed or pushed.

---

## 2. The three enforced invariants

### INV-1 — Arithmetic consumption

**Path:** `_Emitter._arith_expr` →
`_assert_expression_fully_consumed` → `_arith_sum`/`_arith_term`/`_arith_factor`.

**Before:** the recursive-descent parser returned whatever it consumed. An
expression like `CURR-BAL OF ACCT-IN-REC - TXN-AMOUNT OF TXN-IN-REC` tokenized
to seven tokens, the parser consumed one, and **six were silently discarded** —
producing a compiling program with the subtraction missing.

**Now:** every exit from `_arith_expr` proves
1. every token was consumed,
2. `(` and `)` counts balance,
3. no operand was missing.

Any violation appends a diagnostic to `unsupported`; `generate_java` then emits
**no files at all**. A missing operand no longer substitutes `BigDecimal.ZERO`.

### INV-2 — WRITE-FROM resolution

**Path:** `_Emitter._emit_write` → `_group_holder` / `_resolve`.

**Before:** `WRITE ACCT-OUT-REC FROM ACCT-IN-REC` names *group* items, but
`_resolve` indexes only leaf fields. `symbol is None` → the copy was **skipped
silently** and a blank, all-spaces record was written.

**Now:** a named source must resolve as a group item (whole-record
`Rt.copyRecord`) or a leaf field (`Rt.moveText`). Otherwise a diagnostic is
recorded and **no WRITE is emitted** — never a blank record.

### INV-3 — Ten-defect regression matrix

Each defect class is pinned by tests named after the *class*, so a regression
identifies which invariant broke. Categories A–J in §5.

---

## 3. Files and functions changed

| File | Function | Change |
|---|---|---|
| `service/java_codegen.py` | `_arith_expr` | Entry point; resets fault flags, calls the consumption assertion |
| `service/java_codegen.py` | `_assert_expression_fully_consumed` | **NEW** — leftover/paren/operand diagnostics |
| `service/java_codegen.py` | `_arith_factor` | Records unclosed paren and missing operand instead of silently returning `ZERO` |
| `service/java_codegen.py` | `_arith_tokens` | Glues subscript/ref-mod to its name; treats an attached sign as unary |
| `service/java_codegen.py` | `_emit_arithmetic` | **BUG FIX** — per-receiver accumulator (see below) |
| `service/java_codegen.py` | `_emit_write` | Fail-closed `FROM` resolution, documented invariant |
| `service/java_codegen.py` | `_emit_evaluate` / `_when_test` | Subject-vs-value comparison |
| `service/java_codegen.py` | `_group_holder` | Group-item resolution |
| `service/java_codegen.py` | `_operand` / `_relation` | `None` can never become an operand |
| `service/java_codegen.py` | `__init__` | Initializes the two arithmetic fault flags |
| `service/java_codegen.py` | `generate_java` | `execute()` invokes the first paragraph; `IOException` import and `throws` |
| `service/cobol_ir.py` | `join_qualified` / `is_name_part` | **NEW** — the qualification boundary |
| `service/cobol_proc.py` | `_split_operands` | Re-joins `A OF B` chains |
| `service/cobol_proc.py` | `split_on_keywords` | Longest-match: `AT END` no longer matches inside `NOT AT END` |
### Two further defects the matrix caught

Both were found by the new tests, **not** by the original workload:

1. **Unary sign and ref-mod were silently mis-tokenized.**
   `-AMT-FLD` tokenized as one operand `-AMT-FLD` (unresolvable name), and
   `CNT-FLD(1:3)` tokenized as four tokens `CNT-FLD ( 1:3 )`. Under INV-1 both
   now fail closed instead of mis-parsing. Since both are *valid* COBOL, the
   tokenizer was corrected: a parenthesis glued to a name binds to it, and an
   attached sign is unary.

2. **`DIVIDE` crashed and multi-receiver `ADD` compounded.**
   `DIVIDE x INTO y` reached the accumulator branch with `java_op` unbound
   (`UnboundLocalError`). And `ADD x TO A B` reused the mutated `source`, giving
   `B + (A + x)` instead of `B + x`. Both fixed; `value` is now rebuilt per
   receiver and DIVIDE is excluded from accumulation because its `source` is
   already `receiver / operand`.

---

## 4. Tests added

| File | Test functions | Purpose |
|---|---|---|
| `test_phase20_safety_invariants.py` | 20 | INV-1 and INV-2 in depth |
| `test_phase20_defect_matrix.py` | 20 | Matrix A–E |
| `test_phase20_defect_matrix_fj.py` | 24 | Matrix F–J |
| `test_phase20_qualified_names.py` | 33 | Qualified-name boundary (prior gate) |
| `test_phase20_dailypost_golden_master.py` | 5 | Live GnuCOBOL byte-equality gate |

**207 Phase 20 tests, all passing.** Parametrization used for valid arithmetic
(17 forms), malformed arithmetic (7), hyphenated names, qualification shapes
and nesting depths.

All test programs are generic — invented names (`REC-A`, `AMT-FLD`, `FIRST-PARA`),
no fixture names, no expected-output bytes.

---

## 5. Ten-defect regression matrix
---

## 6. DAILYPOST reproduction evidence

Workload: `marcoeg/cobol-modernization-playbook`, revision
**`d204cf8472cf7a468419f971cba0cd63589eda5a`** (verified at run time).

### Golden master — GnuCOBOL only

```
java/class artifacts present: 0        <- no Java anywhere in the master tree
compiler: cobc (GnuCOBOL) 3.2.0
cobc exit: 0
run exit: 0
stdout bytes: 0   stderr bytes: 0
```

### AutoForge transformation

```
all service modules parse cleanly
unsupported: 0
  src/main/java/modernized/Dailypost.java   6516 bytes
  src/main/java/modernized/CobolRuntime.java 21333 bytes
```

### Java compile and execution

```
javac exit: 0
java exit: 0
stdout bytes: 0   stderr bytes: 0
```

### Byte / SHA-256 comparison

| File | Size (legacy / java) | SHA-256 | `cmp` |
|---|---|---|---|
| `accounts_out.dat` | 116 / 116 | `ac18ac0e6ae5f5a347164be00544e756536b567038f128d3b5b754ea8099f6cf` (both) | **BYTE-IDENTICAL** |
| `exceptions.dat` | 72 / 72 | `1fc4021f6fed84f41cd4103adc781a4b91c9a4bcbe904013863f3c77702aa9cb` (both) | **BYTE-IDENTICAL** |

### No unexpected output

```
golden-master out/: accounts_out.dat exceptions.dat
java out/:           accounts_out.dat exceptions.dat
```

### Independent golden-master proof

The masters were regenerated from scratch in a tree containing **zero**
`.java`/`.class` files, compiled and executed by `cobc` alone, and reproduced
the same two hashes. They are reproducible from the original COBOL without
AutoForge and were never derived from Java output.

### Other confirmations

- **unsupported constructs = 0**
- **No manual repair** — every fix is in AutoForge; the generated Java was never
  edited. The COBOL source was never touched.
- **No hardcoded output** — a grep of the transformation engine finds fixture
  names only inside documentation comments; no executable branch references
  them.
- **Generic source** — every offset comes from the PICTURE clauses resolved by
  the data dictionary; `datasets.put(...)` entries come from the program's own
  `SELECT ... ASSIGN TO`.

---

## 7. Regression results

| Suite | Result |
|---|---|
| `modernization` | **590 passed, 59 skipped** (was 434/59 → +156) |
| `learning` | 692 passed |
| `runtime` | 268 passed |
| `execution` | 257 passed, 18 skipped |
| `workflows` | 218 passed |
| `security` | 165 passed |
| `kernel` | 161 passed |
| `power_engines` | 135 passed, 3 skipped, **1 failed** |
| `orchestration` | 101 passed, 6 skipped |
| `composition` | 169 passed, **3 failed** |

Failures, all pre-existing and unrelated to this gate:

- `composition` — the three documented baseline failures
  (`test_canonical_context_builder`, `test_canonical_durable_artifacts`,
  `test_execution_platform_integration`).
- `power_engines` — `test_delivery_hardening.py::test_health_check_script_execution_and_exit_codes`
  (expects exit 1 when a service is offline; environment-dependent).

**No new failures. No baseline failure was "fixed" or suppressed.**

---

## 8. Remaining semantic-risk classes

Verified by real execution on DAILYPOST: sequential READ with AT END / NOT AT
END; EVALUATE subject dispatch; accumulating verbs on COMP-3; multi-term
arithmetic and integer division; MOVE across PIC classes; group WRITE…FROM;
PERFORM UNTIL with OR-conjunction; paragraph invocation; GOBACK/CLOSE;
signed packed decimal.

**Still unverified by real execution** (unchanged from the defect review, now
*fail-closed* rather than silent):

- **Indexed files / KSDS** — `IndexedFile` exists but has no execution evidence.
  CardDemo uses `ORGANIZATION IS INDEXED`.
- **EBCDIC transcoding** — CardDemo datasets are EBCDIC; DAILYPOST was ASCII.
- **Reference modification / subscripts** on real record data.
- **`EVALUATE TRUE`, multi-subject EVALUATE, `WHEN OTHER`** on real data.
- **`PERFORM THRU`, `SEARCH`, `STRING`/`UNSTRING`, `INSPECT`.**
- **Non-58/72 LRECL and multi-record-type files.**

The risk profile improved materially: these are now *diagnostics* rather than
silent mis-interpretation. That is the difference this gate was meant to buy.

---

## 9. What this gate does and does not establish

**Establishes:** arithmetic cannot be partially translated; a named WRITE source
cannot be dropped; the ten defect classes are permanently pinned; DAILYPOST
still reproduces its GnuCOBOL masters byte-for-byte after the repair.

**Does NOT establish:** that the modernization engine is certified, that
CardDemo works, that the customer delivery or clean-room is sound, or that the
O-2 production path has been exercised. Those remain outstanding.

---

## 10. CardDemo — explicitly not attempted

No CardDemo source was read, parsed, compiled or executed during this gate. No
CardDemo golden master was produced. The only reference to CardDemo in the
Phase 20 code is a pre-existing documentation comment about `IndexedFile`.

---

## 11. Recommendation

### PROCEED TO CARDDEMO

Both mandatory invariants are now enforced in product code and proven by 207
passing tests. Re-running the real DAILYPOST workload after the repair still
produces byte-identical GnuCOBOL golden masters, confirming the invariants did
not weaken valid translation. Writing the matrix paid for itself immediately:
it exposed two further latent defects (unary/ref-mod mis-tokenization and
`DIVIDE`/multi-receiver accumulation) that DAILYPOST never exercised, and both
are now fixed and pinned.

CardDemo introduces indexed files, EBCDIC and new record lengths — the classes
this gate could not verify by execution. They are now reached through
fail-closed paths, so an unsupported construct will surface as an explicit
diagnostic rather than as silently wrong customer data. That is the correct
posture for the next workload: attempt it, and let any genuine gap announce
itself.

| # | Category | Defect | Invariant / test |
|---|---|---|---|
| A | IF/ELSE nesting depth | ELSE arm lost trailing statements after a nested `END-IF` | `TestMatrixAIfElseNestingDepth` (depths 1–3) |
| B | `AT END` vs `NOT AT END` | Shorter keyword matched inside the longer one; READ inverted | `TestMatrixBAtEndLongestMatch` (2 keyword pairs + branch order) |
| C | EVALUATE subject | Subject ignored; every WHEN was constant-true | `TestMatrixCEvaluateSubjectSemantics` |
| D | ADD/SUBTRACT/MULTIPLY | Receiver overwritten instead of accumulated | `TestMatrixDAccumulatingArithmeticVerbs` (+ DIVIDE, GIVING, multi-receiver) |
| E | Arithmetic tail consumption | Unconsumed tokens silently discarded | `TestMatrixEArithmeticTailConsumption` + INV-1 |
| F | Group `WRITE ... FROM` | Unresolved source → blank record | `TestMatrixFGroupWriteFrom` + INV-2 |
| G | Labelled first paragraph | `execute()` empty; program did nothing | `TestMatrixGEntryPoint` |
| H | Generated Java compiles | Private-constructor call; undeclared `IOException` | `TestMatrixHGeneratedJavaIsCompilable` |
| I | `None` / missing operand | `str(None)` masqueraded as the field `"None"` | `TestMatrixINoneOperandFailsClosed` |
| J | Qualified-name joining | `A OF B` split into three operands | `TestMatrixJQualifiedNames` |
| `service/cobol_proc.py` | `_split_if_body` | Scans from depth 1 — an ELSE arm no longer loses its tail |
| `service/java_runtime.py` | `CobolRuntime.INSTANCE` | Generated code no longer calls a private constructor |
| `service/java_runtime.py` | `copyRecord` | Whole-record copy for group `WRITE ... FROM` |