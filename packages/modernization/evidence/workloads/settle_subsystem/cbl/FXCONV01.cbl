       IDENTIFICATION DIVISION.
       PROGRAM-ID. FXCONV01.
      ******************************************************************
      * FXCONV01: FOREIGN EXCHANGE & SPREAD CONVERSION ENGINE          *
      * SUPPORTS DYNAMIC MATRIX SPREADS & TRIANGULATION ARITHMETIC     *
      ******************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SPREAD-BPS-STD           PIC 9(4)V9(4) VALUE 0.0025.
       01  WS-SPREAD-BPS-PREM          PIC 9(4)V9(4) VALUE 0.0015.
       01  WS-RATE-TABLE.
           05  FILLER                  PIC X(3) VALUE 'EUR'.
           05  FILLER                  PIC 9(5)V9(6) VALUE 1.085000.
           05  FILLER                  PIC X(3) VALUE 'GBP'.
           05  FILLER                  PIC 9(5)V9(6) VALUE 1.295000.
           05  FILLER                  PIC X(3) VALUE 'JPY'.
           05  FILLER                  PIC 9(5)V9(6) VALUE 0.006800.
           05  FILLER                  PIC X(3) VALUE 'CAD'.
           05  FILLER                  PIC 9(5)V9(6) VALUE 0.742000.
           05  FILLER                  PIC X(3) VALUE 'AUD'.
           05  FILLER                  PIC 9(5)V9(6) VALUE 0.655000.
           05  FILLER                  PIC X(3) VALUE 'CHF'.
           05  FILLER                  PIC 9(5)V9(6) VALUE 1.120000.
       01  WS-RATES REDEFINES WS-RATE-TABLE.
           05  WS-FX-PAIR OCCURS 6 TIMES INDEXED BY FX-IDX.
               10  WS-CURR-CODE        PIC X(3).
               10  WS-MID-RATE         PIC 9(5)V9(6).

       01  WS-MATCH-FROM               PIC X(1) VALUE 'N'.
       01  WS-MATCH-TO                 PIC X(1) VALUE 'N'.
       01  WS-RATE-FROM                PIC 9(5)V9(6) VALUE 1.000000.
       01  WS-RATE-TO                  PIC 9(5)V9(6) VALUE 1.000000.
       01  WS-CROSS-RATE               PIC 9(5)V9(6) VALUE 1.000000.
       01  WS-RAW-CONV-AMT             PIC S9(11)V99 VALUE ZEROES.
       01  WS-ACTIVE-SPREAD            PIC 9(4)V9(4) VALUE ZEROES.

       LINKAGE SECTION.
       01  LS-FROM-CURR                PIC X(3).
       01  LS-TO-CURR                  PIC X(3).
       01  LS-FROM-AMOUNT              PIC S9(11)V99.
       01  LS-SETTLE-AMOUNT            PIC S9(11)V99.
       01  LS-SPREAD-AMOUNT            PIC S9(7)V99.
       01  LS-EFFECTIVE-RATE           PIC 9(5)V9(6).

       PROCEDURE DIVISION USING LS-FROM-CURR
                                LS-TO-CURR
                                LS-FROM-AMOUNT
                                LS-SETTLE-AMOUNT
                                LS-SPREAD-AMOUNT
                                LS-EFFECTIVE-RATE.
       0000-MAIN.
           MOVE 'N' TO WS-MATCH-FROM
           MOVE 'N' TO WS-MATCH-TO
           MOVE 1.000000 TO WS-RATE-FROM
           MOVE 1.000000 TO WS-RATE-TO
           MOVE 1.000000 TO LS-EFFECTIVE-RATE
           MOVE ZEROES TO LS-SPREAD-AMOUNT
           MOVE LS-FROM-AMOUNT TO LS-SETTLE-AMOUNT

           IF LS-FROM-CURR = LS-TO-CURR
               MOVE 1.000000 TO LS-EFFECTIVE-RATE
               MOVE LS-FROM-AMOUNT TO LS-SETTLE-AMOUNT
               MOVE ZEROES TO LS-SPREAD-AMOUNT
           ELSE
               PERFORM 1000-RESOLVE-RATES
               PERFORM 2000-CALCULATE-CROSS-CONVERSION
           END-IF
           GOBACK.

       1000-RESOLVE-RATES.
           IF LS-FROM-CURR = 'USD'
               MOVE 1.000000 TO WS-RATE-FROM
               MOVE 'Y' TO WS-MATCH-FROM
           ELSE
               PERFORM VARYING FX-IDX FROM 1 BY 1
                   UNTIL FX-IDX > 6 OR WS-MATCH-FROM = 'Y'
                   IF WS-CURR-CODE(FX-IDX) = LS-FROM-CURR
                       MOVE 'Y' TO WS-MATCH-FROM
                       MOVE WS-MID-RATE(FX-IDX) TO WS-RATE-FROM
                   END-IF
               END-PERFORM
           END-IF

           IF LS-TO-CURR = 'USD'
               MOVE 1.000000 TO WS-RATE-TO
               MOVE 'Y' TO WS-MATCH-TO
           ELSE
               PERFORM VARYING FX-IDX FROM 1 BY 1
                   UNTIL FX-IDX > 6 OR WS-MATCH-TO = 'Y'
                   IF WS-CURR-CODE(FX-IDX) = LS-TO-CURR
                       MOVE 'Y' TO WS-MATCH-TO
                       MOVE WS-MID-RATE(FX-IDX) TO WS-RATE-TO
                   END-IF
               END-PERFORM
           END-IF.

       2000-CALCULATE-CROSS-CONVERSION.
           IF WS-RATE-TO > ZEROES
               COMPUTE WS-CROSS-RATE ROUNDED =
                   WS-RATE-FROM / WS-RATE-TO
               MOVE WS-CROSS-RATE TO LS-EFFECTIVE-RATE
           ELSE
               MOVE 1.000000 TO LS-EFFECTIVE-RATE
           END-IF

           IF LS-FROM-AMOUNT > 100000.00
               MOVE WS-SPREAD-BPS-PREM TO WS-ACTIVE-SPREAD
           ELSE
               MOVE WS-SPREAD-BPS-STD TO WS-ACTIVE-SPREAD
           END-IF

           COMPUTE WS-RAW-CONV-AMT ROUNDED =
               LS-FROM-AMOUNT * LS-EFFECTIVE-RATE
           COMPUTE LS-SPREAD-AMOUNT ROUNDED =
               WS-RAW-CONV-AMT * WS-ACTIVE-SPREAD
           COMPUTE LS-SETTLE-AMOUNT ROUNDED =
               WS-RAW-CONV-AMT - LS-SPREAD-AMOUNT.
