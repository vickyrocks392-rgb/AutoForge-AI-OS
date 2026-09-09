      ******************************************************************
      * SETLCOMY.CPY - COMMON SETTLEMENT WORK AREA & SYSTEM CONSTANTS  *
      ******************************************************************
       01  WS-SETTLEMENT-COMMON.
           05  WS-SYSTEM-DATE              PIC 9(8) VALUE ZEROES.
           05  WS-SYSTEM-TIME              PIC 9(6) VALUE ZEROES.
           05  WS-BASE-CURRENCY            PIC X(3) VALUE 'USD'.
           05  WS-BATCH-STATUS             PIC X(2) VALUE '00'.
               88  BATCH-SUCCESS           VALUE '00'.
               88  BATCH-WARNING           VALUE '04'.
               88  BATCH-ERROR             VALUE '08'.
               88  BATCH-FATAL             VALUE '12'.
           05  WS-TOTAL-RECORDS-READ       PIC 9(8) VALUE ZEROES.
           05  WS-TOTAL-PROCESSED          PIC 9(8) VALUE ZEROES.
           05  WS-TOTAL-REJECTED           PIC 9(8) VALUE ZEROES.
           05  WS-TOTAL-SETTLED-AMT        PIC S9(11)V99 VALUE ZEROES.
           05  WS-TOTAL-FEE-AMT            PIC S9(9)V99 VALUE ZEROES.
           05  WS-TOTAL-FX-SPREAD-AMT      PIC S9(9)V99 VALUE ZEROES.
           05  WS-AUDIT-TRAIL-SEQ          PIC 9(9) VALUE ZEROES.
