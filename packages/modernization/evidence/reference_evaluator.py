#!/usr/bin/env python3
"""
AutoForge 18-G — Phase 3: Independent Reference Evaluator.
Evaluates COBOL business logic independently without referencing or importing any generated Java code.
Provides the golden ground truth for Behavioral Equivalence Testing.
"""

import re
from typing import Dict, Any, Tuple

class ReferenceCobolEvaluator:
    """Independent reference implementation of CardDemo Transaction Processing business rules."""

    @staticmethod
    def validate_transaction(
        card_num: str,
        credit_limit: int,
        curr_credit: int,
        curr_debit: int,
        tran_amt: int,
        exp_date: str,
        orig_ts: str
    ) -> Dict[str, Any]:
        """
        Derives from CBTRN02C.cbl:
        1500-A-LOOKUP-XREF & 1500-B-LOOKUP-ACCT
        COMPUTE WS-TEMP-BAL = ACCT-CURR-CYC-CREDIT - ACCT-CURR-CYC-DEBIT + DALYTRAN-AMT
        """
        temp_bal = curr_credit - curr_debit + tran_amt
        fail_reason = 0
        fail_desc = ""

        if not card_num or not card_num.strip():
            fail_reason = 100
            fail_desc = "INVALID CARD NUMBER FOUND"
        elif credit_limit < temp_bal:
            fail_reason = 102
            fail_desc = "OVERLIMIT TRANSACTION"
        elif exp_date and orig_ts:
            clean_orig = orig_ts[:10] if len(orig_ts) >= 10 else orig_ts
            if exp_date < clean_orig:
                fail_reason = 103
                fail_desc = "TRANSACTION RECEIVED AFTER ACCT EXPIRATION"

        return {
            "failReason": fail_reason,
            "failReasonDesc": fail_desc,
            "tempBalance": temp_bal
        }

    @staticmethod
    def update_account_balance(
        curr_bal: int,
        curr_credit: int,
        curr_debit: int,
        tran_amt: int
    ) -> Dict[str, Any]:
        """
        Derives from CBTRN02C.cbl:
        2800-UPDATE-ACCOUNT-REC
        ADD DALYTRAN-AMT TO ACCT-CURR-BAL
        IF DALYTRAN-AMT >= 0
           ADD DALYTRAN-AMT TO ACCT-CURR-CYC-CREDIT
        ELSE
           ADD DALYTRAN-AMT TO ACCT-CURR-CYC-DEBIT
        """
        new_bal = curr_bal + tran_amt
        new_credit = curr_credit
        new_debit = curr_debit

        if tran_amt >= 0:
            new_credit += tran_amt
        else:
            new_debit += abs(tran_amt)

        return {
            "newBalance": new_bal,
            "newCycleCredit": new_credit,
            "newCycleDebit": new_debit
        }

    @staticmethod
    def evaluate_date(date_str: str, format_str: str = "YYYY-MM-DD") -> int:
        """
        Derives from CSUTLDTC.cbl and CEEDAYS specification:
        FC_NORMAL (0) = Valid date
        FC_ERROR (3) = Invalid format / bad picture string
        FC_SEVERE (4) = Empty string / insufficient data
        """
        if not date_str or not date_str.strip():
            return 4  # FC_SEVERE

        clean = date_str.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", clean) or re.match(r"^\d{8}$", clean) or re.match(r"^\d{4}/\d{2}/\d{2}$", clean):
            return 0  # FC_NORMAL
        else:
            return 3  # FC_ERROR

    @staticmethod
    def evaluate_file_status(status_str: str) -> int:
        """
        Derives from CBTRN01C.cbl / CBTRN02C.cbl:
        '00' -> 0 (APPL-AOK)
        '10' -> 16 (APPL-EOF)
        other -> 12 (I/O error)
        """
        if status_str == "00":
            return 0
        elif status_str == "10":
            return 16
        else:
            return 12

    @staticmethod
    def evaluate_return_code(reject_count: int) -> int:
        """
        Derives from CBTRN02C.cbl:
        IF WS-REJECT-COUNT > 0 MOVE 4 TO RETURN-CODE
        """
        if reject_count > 0:
            return 4
        return 0
