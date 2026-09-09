"""18-G Run 7 entry C1: tasks."""
from run_18g_entry_a import CODING, HP_CODING, HP_URL, M1_URL, REASON


def _ai_tasks():
    return [
        ("AccountServiceInquiry", "PRIMARY_CODING_ENGINE",
         "Design balance-inquiry validation rules for a Spring banking service.",
         "M1", M1_URL, CODING, "worker-m1-01"),
        ("TransferDoubleEntry", "SECONDARY_DISTRIBUTED_CODING_WORKER",
         "Design inter-account transfer invariants: debit source and credit "
         "destination by the same amount; reject non-positive amounts.",
         "HP", HP_URL, HP_CODING, "worker-hp-01"),
        ("CustomerOnboarding", "ARCHITECTURAL_REASONING_ENGINE",
         "Reason about customer onboarding validation and cross-module consistency.",
         "M1", M1_URL, REASON, "worker-m1-02"),
        ("AuditApiDesign", "SECONDARY_DISTRIBUTED_CODING_WORKER",
         "Design audit REST conventions: versioned paths and return codes.",
         "HP", HP_URL, HP_CODING, "worker-hp-02"),
        ("BatchOrchestration", "ARCHITECTURAL_REASONING_ENGINE",
         "Analyze BNKSTMT JCL orchestration: DATECARD 202606, SORTCODE 123456.",
         "M1", M1_URL, REASON, "worker-m1-02"),
        ("SecurityPolicy", "PRIMARY_CODING_ENGINE",
         "Design endpoint protection for transactional banking endpoints.",
         "M1", M1_URL, CODING, "worker-m1-01"),
    ]
