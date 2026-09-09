       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPRTGEN.
      ******************************************************************
      * REPRTGEN: SETTLEMENT BATCH SUMMARY REPORT GENERATOR            *
      * PRODUCES STRUCTURED EXECUTIVE RECONCILIATION AUDIT LEDGER      *
      ******************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FORMATTED-DATE           PIC X(10).
       01  WS-FORMATTED-TOTAL-AMT      PIC $$$,$$$,$$9.99.
       01  WS-FORMATTED-FEE-AMT        PIC $$$,$$$,$$9.99.
       01  WS-FORMATTED-FX-AMT         PIC $$$,$$$,$$9.99.
       01  WS-NET-SETTLED-AMT          PIC S9(11)V99 VALUE ZEROES.
       01  WS-FORMATTED-NET-AMT        PIC $$$,$$$,$$9.99.
       01  WS-SUCCESS-RATE             PIC 9(3)V9(2) VALUE ZEROES.

       LINKAGE SECTION.
           COPY SETLCOMY.

       PROCEDURE DIVISION USING WS-SETTLEMENT-COMMON.
       0000-MAIN.
           MOVE WS-TOTAL-SETTLED-AMT TO WS-FORMATTED-TOTAL-AMT
           MOVE WS-TOTAL-FEE-AMT     TO WS-FORMATTED-FEE-AMT
           MOVE WS-TOTAL-FX-SPREAD-AMT TO WS-FORMATTED-FX-AMT

           COMPUTE WS-NET-SETTLED-AMT =
               WS-TOTAL-SETTLED-AMT - WS-TOTAL-FEE-AMT
           MOVE WS-NET-SETTLED-AMT   TO WS-FORMATTED-NET-AMT

           IF WS-TOTAL-RECORDS-READ > ZEROES
               COMPUTE WS-SUCCESS-RATE ROUNDED =
                   (WS-TOTAL-PROCESSED / WS-TOTAL-RECORDS-READ) * 100.00
           ELSE
               MOVE ZEROES TO WS-SUCCESS-RATE
           END-IF

           DISPLAY '***************************************************'
           DISPLAY '* AUTOFORGE FINANCIAL SETTLEMENT BATCH LEDGER     *'
           DISPLAY '***************************************************'
           DISPLAY 'BASE CURRENCY       : ' WS-BASE-CURRENCY
           DISPLAY 'TOTAL RECORDS READ  : ' WS-TOTAL-RECORDS-READ
           DISPLAY 'TOTAL PROCESSED     : ' WS-TOTAL-PROCESSED
           DISPLAY 'TOTAL REJECTED      : ' WS-TOTAL-REJECTED
           DISPLAY 'SUCCESS PERCENTAGE  : ' WS-SUCCESS-RATE '%'
           DISPLAY 'TOTAL SETTLED GROSS : ' WS-FORMATTED-TOTAL-AMT
           DISPLAY 'TOTAL FEES ASSESSED : ' WS-FORMATTED-FEE-AMT
           DISPLAY 'TOTAL FX SPREAD AMT : ' WS-FORMATTED-FX-AMT
           DISPLAY 'TOTAL NET SETTLED   : ' WS-FORMATTED-NET-AMT
           DISPLAY 'FINAL BATCH STATUS  : ' WS-BATCH-STATUS
           DISPLAY 'AUDIT TRAIL RECORDS : ' WS-AUDIT-TRAIL-SEQ
           DISPLAY '***************************************************'
           GOBACK.
