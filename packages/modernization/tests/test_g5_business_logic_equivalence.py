"""Unit tests for AutoForge 18-G Business-Logic Equivalence."""

import json
from pathlib import Path
import pytest
import sys

evidence_dir = Path(__file__).resolve().parents[1] / "evidence"
sys.path.insert(0, str(evidence_dir))

from reference_evaluator import ReferenceCobolEvaluator

def test_reference_evaluator_validate_transaction_under_limit():
    res = ReferenceCobolEvaluator.validate_transaction(
        card_num="1234567890123456",
        credit_limit=5000,
        curr_credit=3000,
        curr_debit=1000,
        tran_amt=500,
        exp_date="2028-12-31",
        orig_ts="2026-09-06"
    )
    assert res["failReason"] == 0
    assert res["failReasonDesc"] == ""
    assert res["tempBalance"] == 2500

def test_reference_evaluator_validate_transaction_over_limit():
    res = ReferenceCobolEvaluator.validate_transaction(
        card_num="1234567890123456",
        credit_limit=2000,
        curr_credit=1500,
        curr_debit=0,
        tran_amt=1000,
        exp_date="2028-12-31",
        orig_ts="2026-09-06"
    )
    assert res["failReason"] == 102
    assert res["failReasonDesc"] == "OVERLIMIT TRANSACTION"
    assert res["tempBalance"] == 2500

def test_reference_evaluator_validate_transaction_expired():
    res = ReferenceCobolEvaluator.validate_transaction(
        card_num="1234567890123456",
        credit_limit=5000,
        curr_credit=100,
        curr_debit=0,
        tran_amt=100,
        exp_date="2025-01-01",
        orig_ts="2026-09-06"
    )
    assert res["failReason"] == 103
    assert res["failReasonDesc"] == "TRANSACTION RECEIVED AFTER ACCT EXPIRATION"

def test_reference_evaluator_validate_transaction_invalid_card():
    res = ReferenceCobolEvaluator.validate_transaction(
        card_num="",
        credit_limit=5000,
        curr_credit=100,
        curr_debit=0,
        tran_amt=100,
        exp_date="2028-01-01",
        orig_ts="2026-09-06"
    )
    assert res["failReason"] == 100
    assert res["failReasonDesc"] == "INVALID CARD NUMBER FOUND"

def test_reference_evaluator_update_account_balance():
    # Credit path (positive)
    res1 = ReferenceCobolEvaluator.update_account_balance(curr_bal=10000, curr_credit=2000, curr_debit=500, tran_amt=500)
    assert res1["newBalance"] == 10500
    assert res1["newCycleCredit"] == 2500
    assert res1["newCycleDebit"] == 500

    # Debit path (negative)
    res2 = ReferenceCobolEvaluator.update_account_balance(curr_bal=10000, curr_credit=2000, curr_debit=500, tran_amt=-250)
    assert res2["newBalance"] == 9750
    assert res2["newCycleCredit"] == 2000
    assert res2["newCycleDebit"] == 750

def test_reference_evaluator_date_semantics():
    assert ReferenceCobolEvaluator.evaluate_date("2026-09-06", "YYYY-MM-DD") == 0
    assert ReferenceCobolEvaluator.evaluate_date("20260906", "YYYYMMDD") == 0
    assert ReferenceCobolEvaluator.evaluate_date("INVALID-DATE", "YYYY-MM-DD") == 3
    assert ReferenceCobolEvaluator.evaluate_date("", "YYYY-MM-DD") == 4

def test_reference_evaluator_file_status():
    assert ReferenceCobolEvaluator.evaluate_file_status("00") == 0
    assert ReferenceCobolEvaluator.evaluate_file_status("10") == 16
    assert ReferenceCobolEvaluator.evaluate_file_status("23") == 12

def test_reference_evaluator_return_code():
    assert ReferenceCobolEvaluator.evaluate_return_code(0) == 0
    assert ReferenceCobolEvaluator.evaluate_return_code(3) == 4

def test_certification_report_exists_and_certified():
    report_file = evidence_dir / "g5_business_logic_equivalence_report.json"
    assert report_file.exists()
    with open(report_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["status"] == "CERTIFIED"
    assert data["behavioral_test_suite"]["known_discrepancies"] == 0
    assert data["behavioral_test_suite"]["passed"] == 25
    assert data["nloc_accounting"]["properly_migrated_nloc"] == 5026
