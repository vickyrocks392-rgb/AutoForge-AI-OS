import os
from pathlib import Path

def create_unseen_workload():
    base_dir = Path(".autoforge/unseen_workloads/payroll_enterprise")
    (base_dir / "app" / "cbl").mkdir(parents=True, exist_ok=True)
    (base_dir / "app" / "cpy").mkdir(parents=True, exist_ok=True)
    (base_dir / "app" / "jcl").mkdir(parents=True, exist_ok=True)

    # 1. PRMAS01Y.cpy
    (base_dir / "app" / "cpy" / "PRMAS01Y.cpy").write_text("""      *****************************************************************
      * PRMAS01Y.CPY - EMPLOYEE PAYROLL MASTER RECORD COPYBOOK
      *****************************************************************
       01  EMP-PAYROLL-RECORD.
           05  EMP-ID                  PIC X(08).
           05  EMP-NAME                PIC X(30).
           05  EMP-DEPT                PIC X(04).
           05  EMP-HOURLY-RATE         PIC 9(05)V99.
           05  EMP-YTD-GROSS           PIC 9(08)V99.
           05  EMP-YTD-TAX             PIC 9(08)V99.
           05  EMP-YTD-NET             PIC 9(08)V99.
           05  EMP-STATUS              PIC X(02).
""")

    # 2. PRTIM02Y.cpy
    (base_dir / "app" / "cpy" / "PRTIM02Y.cpy").write_text("""      *****************************************************************
      * PRTIM02Y.CPY - EMPLOYEE TIMECARD RECORD COPYBOOK
      *****************************************************************
       01  EMP-TIMECARD-RECORD.
           05  TC-EMP-ID               PIC X(08).
           05  TC-PERIOD-END-DATE      PIC X(10).
           05  TC-REG-HOURS            PIC 9(03)V99.
           05  TC-OT-HOURS             PIC 9(03)V99.
           05  TC-SHIFT-CODE           PIC X(01).
           05  TC-STATUS-FLAG          PIC X(02).
""")

    # 3. PRDED03Y.cpy
    (base_dir / "app" / "cpy" / "PRDED03Y.cpy").write_text("""      *****************************************************************
      * PRDED03Y.CPY - STATUTORY DEDUCTIONS & BENEFITS COPYBOOK
      *****************************************************************
       01  EMP-DEDUCTION-RECORD.
           05  DED-EMP-ID              PIC X(08).
           05  DED-FICA-RATE           PIC 9(02)V99.
           05  DED-FED-TAX-RATE        PIC 9(02)V99.
           05  DED-STATE-TAX-RATE      PIC 9(02)V99.
           05  DED-401K-PCT            PIC 9(02)V99.
           05  DED-HEALTH-PREMIUM      PIC 9(04)V99.
""")

    # 4. PRSUM04Y.cpy
    (base_dir / "app" / "cpy" / "PRSUM04Y.cpy").write_text("""      *****************************************************************
      * PRSUM04Y.CPY - GENERAL LEDGER PAYROLL SUMMARY RECORD COPYBOOK
      *****************************************************************
       01  PAYROLL-SUMMARY-RECORD.
           05  SUM-CYCLE-DATE          PIC X(10).
           05  SUM-TOTAL-GROSS         PIC 9(10)V99.
           05  SUM-TOTAL-TAX           PIC 9(10)V99.
           05  SUM-TOTAL-DEDUCTIONS    PIC 9(10)V99.
           05  SUM-TOTAL-NET           PIC 9(10)V99.
           05  SUM-HEADCOUNT           PIC 9(06).
""")

    # 5. PRCOM01Y.cpy
    (base_dir / "app" / "cpy" / "PRCOM01Y.cpy").write_text("""      *****************************************************************
      * PRCOM01Y.CPY - COMMON INTER-MODULE COMMUNICATION AREA
      *****************************************************************
       01  PAYROLL-COMMON-AREA.
           05  COMM-RETURN-CODE        PIC 9(04).
           05  COMM-ERROR-MESSAGE      PIC X(80).
           05  COMM-PROCESSED-COUNT    PIC 9(06).
           05  COMM-REJECT-COUNT       PIC 9(06).
""")

    # 6. PRWAG02C.cbl
    (base_dir / "app" / "cbl" / "PRWAG02C.cbl").write_text("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRWAG02C.
       AUTHOR. AUTOFORGE LEGACY ENTERPRISE.
      *****************************************************************
      * PRWAG02C - WAGE AND OVERTIME CALCULATION SERVICE
      *****************************************************************
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-VARS.
           05  WS-HOURLY-RATE          PIC 9(05)V99 VALUE 25.00.
           05  WS-REG-HOURS            PIC 9(03)V99 VALUE 40.00.
           05  WS-OT-HOURS             PIC 9(03)V99 VALUE 10.00.
           05  WS-REG-PAY              PIC 9(07)V99 VALUE 0.
           05  WS-OT-PAY               PIC 9(07)V99 VALUE 0.
           05  WS-SHIFT-BONUS          PIC 9(05)V99 VALUE 0.
           05  WS-GROSS-PAY            PIC 9(07)V99 VALUE 0.
           05  WS-REJECT-COUNT         PIC 9(04) VALUE 0.
           05  WS-RETURN-CODE          PIC 9(04) VALUE 0.

       COPY PRTIM02Y.

       PROCEDURE DIVISION.
       0000-CALCULATE-WAGES.
           PERFORM 1000-VALIDATE-TIMECARD
           IF WS-REJECT-COUNT = 0
               PERFORM 2000-COMPUTE-REGULAR-PAY
               PERFORM 3000-COMPUTE-OVERTIME-PAY
               PERFORM 4000-SUM-GROSS-PAY
           ELSE
               MOVE 4 TO WS-RETURN-CODE
           END-IF
           GOBACK.

       1000-VALIDATE-TIMECARD.
           IF WS-REG-HOURS < 0 OR WS-REG-HOURS > 80
               ADD 1 TO WS-REJECT-COUNT
               MOVE 101 TO WS-RETURN-CODE
           END-IF
           IF WS-OT-HOURS < 0 OR WS-OT-HOURS > 40
               ADD 1 TO WS-REJECT-COUNT
               MOVE 102 TO WS-RETURN-CODE
           END-IF.

       2000-COMPUTE-REGULAR-PAY.
           COMPUTE WS-REG-PAY = WS-HOURLY-RATE * WS-REG-HOURS.

       3000-COMPUTE-OVERTIME-PAY.
           IF WS-OT-HOURS > 0
               COMPUTE WS-OT-PAY = (WS-HOURLY-RATE * WS-OT-HOURS * 15) / 10
           ELSE
               MOVE 0 TO WS-OT-PAY
           END-IF.

       4000-SUM-GROSS-PAY.
           COMPUTE WS-GROSS-PAY = WS-REG-PAY + WS-OT-PAY + WS-SHIFT-BONUS.
""")

    # 7. PRDED03C.cbl
    (base_dir / "app" / "cbl" / "PRDED03C.cbl").write_text("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRDED03C.
       AUTHOR. AUTOFORGE LEGACY ENTERPRISE.
      *****************************************************************
      * PRDED03C - STATUTORY DEDUCTION & 401K WITHHOLDING
      *****************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DED-VARS.
           05  WS-GROSS-PAY            PIC 9(07)V99 VALUE 1500.00.
           05  WS-FICA-DED             PIC 9(06)V99 VALUE 0.
           05  WS-FED-TAX-DED          PIC 9(06)V99 VALUE 0.
           05  WS-401K-DED             PIC 9(06)V99 VALUE 0.
           05  WS-HEALTH-DED           PIC 9(05)V99 VALUE 50.00.
           05  WS-TOTAL-DEDUCTIONS     PIC 9(07)V99 VALUE 0.
           05  WS-REJECT-COUNT         PIC 9(04) VALUE 0.
           05  WS-RETURN-CODE          PIC 9(04) VALUE 0.

       COPY PRDED03Y.

       PROCEDURE DIVISION.
       0000-PROCESS-DEDUCTIONS.
           PERFORM 1000-COMPUTE-FICA
           PERFORM 2000-COMPUTE-FED-TAX
           PERFORM 3000-COMPUTE-401K
           PERFORM 4000-TOTAL-DEDUCTIONS
           GOBACK.

       1000-COMPUTE-FICA.
           COMPUTE WS-FICA-DED = (WS-GROSS-PAY * 765) / 10000.

       2000-COMPUTE-FED-TAX.
           IF WS-GROSS-PAY > 2000
               COMPUTE WS-FED-TAX-DED = (WS-GROSS-PAY * 22) / 100
           ELSE
               COMPUTE WS-FED-TAX-DED = (WS-GROSS-PAY * 15) / 100
           END-IF.

       3000-COMPUTE-401K.
           COMPUTE WS-401K-DED = (WS-GROSS-PAY * 5) / 100.

       4000-TOTAL-DEDUCTIONS.
           COMPUTE WS-TOTAL-DEDUCTIONS = WS-FICA-DED + WS-FED-TAX-DED + WS-401K-DED + WS-HEALTH-DED.
""")

    # 8. PRTAX04C.cbl
    (base_dir / "app" / "cbl" / "PRTAX04C.cbl").write_text("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRTAX04C.
       AUTHOR. AUTOFORGE LEGACY ENTERPRISE.
      *****************************************************************
      * PRTAX04C - STATE & MUNICIPAL TAX SERVICE
      *****************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TAX-VARS.
           05  WS-GROSS-PAY            PIC 9(07)V99 VALUE 1500.00.
           05  WS-STATE-TAX-DED        PIC 9(06)V99 VALUE 0.
           05  WS-MUNICIPAL-TAX-DED    PIC 9(05)V99 VALUE 0.
           05  WS-TAX-CREDIT           PIC 9(05)V99 VALUE 25.00.
           05  WS-TOTAL-STATE-TAX      PIC 9(06)V99 VALUE 0.
           05  WS-RETURN-CODE          PIC 9(04) VALUE 0.

       PROCEDURE DIVISION.
       0000-COMPUTE-STATE-TAXES.
           PERFORM 1000-CALC-STATE-RATE
           PERFORM 2000-CALC-MUNICIPAL-RATE
           PERFORM 3000-APPLY-TAX-CREDIT
           GOBACK.

       1000-CALC-STATE-RATE.
           COMPUTE WS-STATE-TAX-DED = (WS-GROSS-PAY * 5) / 100.

       2000-CALC-MUNICIPAL-RATE.
           COMPUTE WS-MUNICIPAL-TAX-DED = (WS-GROSS-PAY * 1) / 100.

       3000-APPLY-TAX-CREDIT.
           IF WS-STATE-TAX-DED > WS-TAX-CREDIT
               COMPUTE WS-TOTAL-STATE-TAX = WS-STATE-TAX-DED - WS-TAX-CREDIT + WS-MUNICIPAL-TAX-DED
           ELSE
               MOVE WS-MUNICIPAL-TAX-DED TO WS-TOTAL-STATE-TAX
           END-IF.
""")

    # 9. PRUTLDTC.cbl
    (base_dir / "app" / "cbl" / "PRUTLDTC.cbl").write_text("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRUTLDTC.
       AUTHOR. AUTOFORGE LEGACY ENTERPRISE.
      *****************************************************************
      * PRUTLDTC - PAYROLL CALENDAR & DATE VALIDATION UTILITY
      *****************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATE-VARS.
           05  WS-DATE-STRING          PIC X(10) VALUE "2026-09-30".
           05  WS-CYCLE-DAYS           PIC 9(02) VALUE 14.
           05  WS-DATE-STATUS          PIC 9(04) VALUE 0.
           05  WS-RETURN-CODE          PIC 9(04) VALUE 0.

       PROCEDURE DIVISION.
       0000-VALIDATE-PAYROLL-DATE.
           IF WS-DATE-STRING = SPACES
               MOVE 4 TO WS-RETURN-CODE
           ELSE
               MOVE 0 TO WS-RETURN-CODE
           END-IF
           GOBACK.
""")

    # 10. PRMAS01C.cbl
    (base_dir / "app" / "cbl" / "PRMAS01C.cbl").write_text("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRMAS01C.
       AUTHOR. AUTOFORGE LEGACY ENTERPRISE.
      *****************************************************************
      * PRMAS01C - PAYROLL MASTER BATCH PROCESSOR & POSTING
      *****************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MASTER-VARS.
           05  WS-EMP-ID               PIC X(08) VALUE "EMP00101".
           05  WS-HOURLY-RATE          PIC 9(05)V99 VALUE 30.00.
           05  WS-REG-HOURS            PIC 9(03)V99 VALUE 40.00.
           05  WS-OT-HOURS             PIC 9(03)V99 VALUE 5.00.
           05  WS-GROSS-PAY            PIC 9(07)V99 VALUE 0.
           05  WS-TOTAL-DEDUCTIONS     PIC 9(07)V99 VALUE 0.
           05  WS-STATE-TAX            PIC 9(06)V99 VALUE 0.
           05  WS-NET-PAY              PIC 9(07)V99 VALUE 0.
           05  WS-YTD-GROSS            PIC 9(08)V99 VALUE 45000.00.
           05  WS-YTD-NET              PIC 9(08)V99 VALUE 35000.00.
           05  WS-REJECT-COUNT         PIC 9(04) VALUE 0.
           05  WS-RETURN-CODE          PIC 9(04) VALUE 0.

       COPY PRMAS01Y.
       COPY PRCOM01Y.

       PROCEDURE DIVISION.
       0000-PROCESS-PAYROLL-MASTER.
           PERFORM 1000-INVOKE-WAGE-CALC
           PERFORM 2000-INVOKE-DEDUCTION-CALC
           PERFORM 3000-INVOKE-TAX-CALC
           PERFORM 4000-COMPUTE-NET-PAY
           PERFORM 5000-UPDATE-YTD-BALANCES
           GOBACK.

       1000-INVOKE-WAGE-CALC.
           CALL "PRWAG02C"
           COMPUTE WS-GROSS-PAY = (WS-HOURLY-RATE * WS-REG-HOURS) + (WS-HOURLY-RATE * WS-OT-HOURS * 15 / 10).

       2000-INVOKE-DEDUCTION-CALC.
           CALL "PRDED03C"
           COMPUTE WS-TOTAL-DEDUCTIONS = (WS-GROSS-PAY * 765 / 10000) + (WS-GROSS-PAY * 15 / 100) + (WS-GROSS-PAY * 5 / 100) + 50.

       3000-INVOKE-TAX-CALC.
           CALL "PRTAX04C"
           COMPUTE WS-STATE-TAX = (WS-GROSS-PAY * 5 / 100) - 25 + (WS-GROSS-PAY * 1 / 100).

       4000-COMPUTE-NET-PAY.
           COMPUTE WS-NET-PAY = WS-GROSS-PAY - WS-TOTAL-DEDUCTIONS - WS-STATE-TAX.

       5000-UPDATE-YTD-BALANCES.
           ADD WS-GROSS-PAY TO WS-YTD-GROSS
           ADD WS-NET-PAY TO WS-YTD-NET.
""")

    # 11. PRSUM05C.cbl
    (base_dir / "app" / "cbl" / "PRSUM05C.cbl").write_text("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRSUM05C.
       AUTHOR. AUTOFORGE LEGACY ENTERPRISE.
      *****************************************************************
      * PRSUM05C - GENERAL LEDGER SUMMARY REGISTER DISBURSEMENT
      *****************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SUMMARY-VARS.
           05  WS-CYCLE-GROSS          PIC 9(09)V99 VALUE 150000.00.
           05  WS-CYCLE-DEDUCTIONS     PIC 9(09)V99 VALUE 45000.00.
           05  WS-CYCLE-NET            PIC 9(09)V99 VALUE 0.
           05  WS-HEADCOUNT            PIC 9(05) VALUE 100.
           05  WS-AVG-NET-PAY          PIC 9(06)V99 VALUE 0.
           05  WS-RETURN-CODE          PIC 9(04) VALUE 0.

       COPY PRSUM04Y.

       PROCEDURE DIVISION.
       0000-POST-SUMMARY-REGISTER.
           COMPUTE WS-CYCLE-NET = WS-CYCLE-GROSS - WS-CYCLE-DEDUCTIONS
           IF WS-HEADCOUNT > 0
               COMPUTE WS-AVG-NET-PAY = WS-CYCLE-NET / WS-HEADCOUNT
           ELSE
               MOVE 0 TO WS-AVG-NET-PAY
           END-IF
           GOBACK.
""")

    # 12. PAYROLL.jcl
    (base_dir / "app" / "jcl" / "PAYROLL.jcl").write_text("""//PAYROLL  JOB (101),'MASTER PAYROLL',CLASS=A,MSGCLASS=X
//STEP10   EXEC PGM=PRWAG02C
//STEP20   EXEC PGM=PRDED03C
//STEP30   EXEC PGM=PRTAX04C
//STEP40   EXEC PGM=PRMAS01C
//STEP50   EXEC PGM=PRSUM05C
""")

    # 13. PAYWAGE.jcl
    (base_dir / "app" / "jcl" / "PAYWAGE.jcl").write_text("""//PAYWAGE  JOB (101),'WAGE CALC',CLASS=A,MSGCLASS=X
//STEP10   EXEC PGM=PRWAG02C
""")

    # 14. PAYTAX.jcl
    (base_dir / "app" / "jcl" / "PAYTAX.jcl").write_text("""//PAYTAX   JOB (101),'TAX CALC',CLASS=A,MSGCLASS=X
//STEP10   EXEC PGM=PRTAX04C
""")

    # 15. PAYPOST.jcl
    (base_dir / "app" / "jcl" / "PAYPOST.jcl").write_text("""//PAYPOST  JOB (101),'PAY POSTING',CLASS=A,MSGCLASS=X
//STEP10   EXEC PGM=PRMAS01C
//STEP20   EXEC PGM=PRSUM05C
""")

if __name__ == "__main__":
    create_unseen_workload()
    print("Created unseen payroll workload.")
