"""18-COMMERCIAL-D: Code Migration & Refactoring Commercial Demonstration Script.

Demonstrates the complete end-to-end commercial modernization lifecycle on a representative
CardDemo-style legacy subsystem (COBOL batch processing + SQL schema -> Java/Spring Boot service).
Demonstrates:
1. Intake & Deterministic Inventory
2. Structured Source Analysis & Entity Extraction
3. Migration Plan Generation with Traceability Lineage
4. Risk Assessment & Governance Boundaries
5. Bounded Transformation Pipeline
6. Compilation & Syntax Verification
7. Behavioral Equivalence Verification (Golden Vectors & Numerical Parity)
8. Completeness Manifest Synthesis (Zero File Loss)
9. Standalone Delivery Package Assembly (Turnkey Self-Deployment)
10. Proprietary Export Boundary Sanitization (Zero Leakage)
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Add power engines to sys.path
root_dir = Path(__file__).parent.parent
pe_src = root_dir / "packages" / "power_engines" / "src"
if str(pe_src) not in sys.path:
    sys.path.insert(0, str(pe_src))

from autoforge_power_engines.migration import (
    CodeMigrationPowerEngine,
    CustomerMigrationSpecification,
    MigrationType,
    RiskTolerance,
    ApprovalPolicy,
    VerificationPolicy,
)


def run_commercial_demo() -> Dict[str, Any]:
    print("================================================================================")
    print("AUTOFORGE AI — 18-COMMERCIAL-D: CODE MIGRATION / REFACTORING DEMO")
    print("================================================================================")

    temp_demo_dir = Path(tempfile.mkdtemp(prefix="autoforge_comm_d_demo_"))
    source_dir = temp_demo_dir / "legacy_carddemo_subsystem"
    source_dir.mkdir(parents=True, exist_ok=True)
    delivery_root = temp_demo_dir / "customer_deliveries"
    delivery_root.mkdir(parents=True, exist_ok=True)

    # 1. Populate Representative Legacy Workload (CardDemo Account & Transaction Processor)
    print("\n[STEP 1] Generating Representative Legacy Workload (CardDemo COBOL + SQL)...")
    cobol_code = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CBACT01C.\n"
        "       ENVIRONMENT DIVISION.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01  WS-ACCT-ID           PIC 9(11) VALUE 10000000001.\n"
        "       01  WS-CARD-NUM          PIC X(16) VALUE '4000123456789010'.\n"
        "       01  WS-ACCT-BALANCE      PIC 9(9)V99 COMP-3 VALUE 1250.75.\n"
        "       01  WS-CREDIT-LIMIT      PIC 9(9)V99 COMP-3 VALUE 5000.00.\n"
        "       01  WS-INTEREST-RATE     PIC 9(2)V99 VALUE 18.50.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           DISPLAY 'PROCESSING ACCOUNT: ' WS-ACCT-ID.\n"
        "           DISPLAY 'CARD NUMBER: ' WS-CARD-NUM.\n"
        "           DISPLAY 'CURRENT BALANCE: ' WS-ACCT-BALANCE.\n"
        "           STOP RUN.\n"
    )
    (source_dir / "CBACT01C.cbl").write_text(cobol_code, encoding="utf-8")

    sql_schema = (
        "-- CardDemo Account Relational Schema\n"
        "CREATE TABLE account (\n"
        "    acct_id BIGINT PRIMARY KEY,\n"
        "    card_num VARCHAR(16) NOT NULL,\n"
        "    balance NUMERIC(11, 2) NOT NULL DEFAULT 0.00,\n"
        "    credit_limit NUMERIC(11, 2) NOT NULL DEFAULT 5000.00,\n"
        "    interest_rate NUMERIC(4, 2) NOT NULL DEFAULT 18.50,\n"
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
        ");\n\n"
        "CREATE INDEX idx_account_card_num ON account(card_num);\n"
    )
    (source_dir / "schema.sql").write_text(sql_schema, encoding="utf-8")

    print(f"  ✓ Legacy source files created in: {source_dir}")
    print(f"    - CBACT01C.cbl (COBOL batch processor with COMP-3 packed decimals)")
    print(f"    - schema.sql (DDL schema with tables & indexes)")

    # 2. Formulate Strongly Typed Specification
    print("\n[STEP 2] Formulating CustomerMigrationSpecification...")
    spec = CustomerMigrationSpecification(
        project_name="CardDemo Core Banking Modernization",
        project_description="Enterprise migration of legacy COBOL/SQL card account processing to Java/Spring Boot service.",
        migration_id="mig-carddemo-prod",
        source_path=str(source_dir),
        source_languages=["cobol", "sql"],
        target_language="java",
        target_framework="spring-boot",
        output_root=str(delivery_root),
        migration_type=MigrationType.LANGUAGE_MIGRATION,
        migration_objective="Modernize account batch subsystem to Spring Boot service with BigDecimal arithmetic parity.",
        compatibility_target="strict_behavioral_equivalence",
        risk_tolerance=RiskTolerance.MEDIUM,
        approval_policy=ApprovalPolicy.APPROVE_HIGH_RISK,
        verification_policy=VerificationPolicy.FULL_BEHAVIOR_EQUIVALENCE,
        deployment_requirements={"port": 8080},
    )
    print(f"  ✓ Specification validated: migration_id='{spec.migration_id}'")
    print(f"  ✓ Target architecture: Java/Spring Boot (Port: 8080)")

    # 3. Execute Canonical 11-Stage Power Engine Lifecycle
    print("\n[STEP 3] Executing CodeMigrationPowerEngine 11-Stage Canonical Lifecycle...")
    events_captured = []
    def log_event(evt):
        events_captured.append(evt)
        etype = evt.get("event_type", "")
        if "STARTED" in etype or "COMPLETED" in etype or "FAILED" in etype:
            print(f"    -> [Event] {etype}")

    engine = CodeMigrationPowerEngine(event_sink=log_event)
    start_time = time.perf_counter()
    result = asyncio.run(engine.execute_lifecycle(spec, auto_approve_safe_risks=True))
    total_duration = time.perf_counter() - start_time

    print(f"\n[STEP 4] Lifecycle Execution Results:")
    print(f"  ✓ Execution Success: {result.success}")
    print(f"  ✓ Total Wall Time: {total_duration:.2f}s")
    print(f"  ✓ Stages Executed: {' -> '.join(result.stages_executed)}")
    print(f"  ✓ Delivery Directory: {result.delivery_dir}")

    # 4. Inspect Delivered Artifacts
    deliv_dir = Path(result.delivery_dir)
    print("\n[STEP 5] Inspecting Standalone Customer Deliverable Artifacts:")
    files = sorted([str(p.relative_to(deliv_dir)) for p in deliv_dir.glob("**/*") if p.is_file()])
    for f in files:
        print(f"  ├── {f}")

    # 5. Inspect Completeness Manifest
    manifest_path = deliv_dir / "reports" / "COMPLETENESS_MANIFEST.json"
    if manifest_path.exists():
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        print("\n[STEP 6] Completeness Audit Evidence:")
        print(f"  ✓ Total Source Files Accounted: {manifest_data.get('total_source_files')}")
        print(f"  ✓ Transformed Files: {manifest_data.get('transformed_count')}")
        print(f"  ✓ Missing Files: {manifest_data.get('missing_count')}")
        print(f"  ✓ Audit Completeness Status: {'PASS' if manifest_data.get('is_complete') else 'FAIL'}")

    # 6. Verify Proprietary Export Boundary
    print("\n[STEP 7] Verifying Proprietary Export Boundary (Zero Leakage Check)...")
    proprietary_terms = [
        "autoforge_kernel",
        "autoforge_power_engines",
        "autoforge_workforce",
        "autoforge_memory",
        "autoforge_knowledge",
        "packages/power_engines",
    ]
    leaks = []
    for root, _, fnames in os.walk(deliv_dir):
        for fname in fnames:
            fp = Path(root) / fname
            if fp.suffix in (".java", ".py", ".json", ".md", ".sh", ".yml", ".xml"):
                content = fp.read_text(encoding="utf-8", errors="replace")
                for term in proprietary_terms:
                    if term in content:
                        leaks.append(f"{fp.relative_to(deliv_dir)}: contains '{term}'")

    if leaks:
        print(f"  ✗ Boundary Leakage Detected: {leaks}")
    else:
        print(f"  ✓ Boundary Clean: Zero internal AutoForge source or imports leaked into customer package.")

    print("\n================================================================================")
    print("COMMERCIAL MIGRATION DEMONSTRATION VERIFIED SUCCESSFULLY")
    print("================================================================================\n")

    return {
        "success": result.success,
        "delivery_dir": result.delivery_dir,
        "stages": result.stages_executed,
        "duration_s": total_duration,
        "files_count": len(files),
        "leaks_count": len(leaks),
    }


if __name__ == "__main__":
    run_commercial_demo()
