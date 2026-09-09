       IDENTIFICATION DIVISION.
       PROGRAM-ID. BALUPDT1.
      ******************************************************************
      * BALUPDT1: ACCOUNT BALANCE & LEDGER MUTATION SUBPROGRAM         *
      * APPLIES MULTI-ACCOUNT DEBIT/CREDIT RULES AND LIMIT CHECKS      *
      ******************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TOTAL-DEBIT-REQUIRED     PIC S9(11)V99 VALUE ZEROES.
       01  WS-ACCOUNT-LIMIT-TABLE.
           05  FILLER                  PIC X(16) VALUE 'CH-CORP-0010992'.
           05  FILLER                  PIC S9(11)V99 VALUE 25000000.00.
           05  FILLER                  PIC X(16) VALUE 'MC-SETL-8829101'.
           05  FILLER                  PIC S9(11)V99 VALUE 50000000.00.
           05  FILLER                  PIC X(16) VALUE 'VIP-ACCT-992019'.
           05  FILLER                  PIC S9(11)V99 VALUE 10000000.00.
       01  WS-LIMIT-ENTRIES REDEFINES WS-ACCOUNT-LIMIT-TABLE.
           05  WS-LIMIT-ENTRY OCCURS 3 TIMES INDEXED BY LIM-IDX.
               10  WS-LIMIT-ACC-ID     PIC X(16).
               10  WS-MAX-BALANCE-CAP  PIC S9(11)V99.

       01  WS-FOUND-LIMIT              PIC X(1) VALUE 'N'.
       01  WS-ACTIVE-LIMIT             PIC S9(11)V99 VALUE 5000000.00.

       LINKAGE SECTION.
       01  LS-SOURCE-ACCOUNT           PIC X(16).
       01  LS-TARGET-ACCOUNT           PIC X(16).
       01  LS-SETTLE-AMOUNT            PIC S9(11)V99.
       01  LS-FEE-AMOUNT               PIC S9(7)V99.
       01  LS-STATUS-CODE              PIC X(2).

       PROCEDURE DIVISION USING LS-SOURCE-ACCOUNT
                                LS-TARGET-ACCOUNT
                                LS-SETTLE-AMOUNT
                                LS-FEE-AMOUNT
                                LS-STATUS-CODE.
       0000-MAIN.
           MOVE '00' TO LS-STATUS-CODE
           MOVE 'N'  TO WS-FOUND-LIMIT
           MOVE 5000000.00 TO WS-ACTIVE-LIMIT

           COMPUTE WS-TOTAL-DEBIT-REQUIRED =
               LS-SETTLE-AMOUNT + LS-FEE-AMOUNT

           PERFORM 1000-RESOLVE-LIMITS
           PERFORM 2000-VERIFY-MUTATION-RULES
           GOBACK.

       1000-RESOLVE-LIMITS.
           PERFORM VARYING LIM-IDX FROM 1 BY 1
               UNTIL LIM-IDX > 3 OR WS-FOUND-LIMIT = 'Y'
               IF WS-LIMIT-ACC-ID(LIM-IDX) = LS-SOURCE-ACCOUNT
                   MOVE 'Y' TO WS-FOUND-LIMIT
                   MOVE WS-MAX-BALANCE-CAP(LIM-IDX) TO WS-ACTIVE-LIMIT
               END-IF
           END-PERFORM.

       2000-VERIFY-MUTATION-RULES.
           IF LS-SOURCE-ACCOUNT(1:4) = 'BLCK' OR
              LS-TARGET-ACCOUNT(1:4) = 'BLCK'
               MOVE '08' TO LS-STATUS-CODE
           ELSE
               IF WS-TOTAL-DEBIT-REQUIRED > WS-ACTIVE-LIMIT
                   MOVE '04' TO LS-STATUS-CODE
               ELSE
                   MOVE '00' TO LS-STATUS-CODE
               END-IF
           END-IF.
