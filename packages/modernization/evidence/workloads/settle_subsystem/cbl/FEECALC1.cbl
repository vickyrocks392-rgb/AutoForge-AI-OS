       IDENTIFICATION DIVISION.
       PROGRAM-ID. FEECALC1.
      ******************************************************************
      * FEECALC1: TIERED SETTLEMENT FEE CALCULATION ENGINE             *
      * APPLIES MULTI-TIER SLIDING SCALE AND CUSTOMER DISCOUNTS        *
      ******************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CALC-PERCENT-FEE         PIC S9(7)V99 VALUE ZEROES.
       01  WS-BASE-FEE                 PIC S9(7)V99 VALUE ZEROES.
       01  WS-CUSTOMER-DISCOUNT-PCT    PIC 9(2)V9(2) VALUE ZEROES.
       01  WS-DISCOUNT-AMT             PIC S9(7)V99 VALUE ZEROES.
       01  WS-FINAL-FEE                PIC S9(7)V99 VALUE ZEROES.

       LINKAGE SECTION.
       01  LS-ACCOUNT-ID               PIC X(16).
       01  LS-TXN-TYPE                 PIC X(4).
       01  LS-SETTLE-AMOUNT            PIC S9(11)V99.
       01  LS-FEE-AMOUNT               PIC S9(7)V99.

       PROCEDURE DIVISION USING LS-ACCOUNT-ID
                                LS-TXN-TYPE
                                LS-SETTLE-AMOUNT
                                LS-FEE-AMOUNT.
       0000-MAIN.
           MOVE ZEROES TO LS-FEE-AMOUNT
           MOVE ZEROES TO WS-CALC-PERCENT-FEE
           MOVE ZEROES TO WS-BASE-FEE
           MOVE ZEROES TO WS-CUSTOMER-DISCOUNT-PCT
           MOVE ZEROES TO WS-DISCOUNT-AMT
           MOVE ZEROES TO WS-FINAL-FEE

           PERFORM 1000-DETERMINE-CUSTOMER-TIER
           EVALUATE LS-TXN-TYPE
               WHEN 'FREV'
                   MOVE ZEROES TO LS-FEE-AMOUNT
               WHEN 'SETL'
                   PERFORM 2000-CALCULATE-SETTLEMENT-FEE
               WHEN 'XFER'
                   PERFORM 3000-CALCULATE-TRANSFER-FEE
               WHEN 'PMNT'
                   PERFORM 4000-CALCULATE-PAYMENT-FEE
               WHEN OTHER
                   MOVE 10.00 TO WS-BASE-FEE
           END-EVALUATE

           IF LS-TXN-TYPE NOT = 'FREV'
               PERFORM 5000-APPLY-TIER-DISCOUNT
           END-IF
           GOBACK.

       1000-DETERMINE-CUSTOMER-TIER.
           IF LS-ACCOUNT-ID(1:3) = 'VIP'
               MOVE 0.25 TO WS-CUSTOMER-DISCOUNT-PCT
           ELSE
               IF LS-ACCOUNT-ID(1:3) = 'COR'
                   MOVE 0.15 TO WS-CUSTOMER-DISCOUNT-PCT
               ELSE
                   IF LS-ACCOUNT-ID(1:3) = 'SME'
                       MOVE 0.05 TO WS-CUSTOMER-DISCOUNT-PCT
                   ELSE
                       MOVE 0.00 TO WS-CUSTOMER-DISCOUNT-PCT
                   END-IF
               END-IF
           END-IF.

       2000-CALCULATE-SETTLEMENT-FEE.
           IF LS-SETTLE-AMOUNT < 1000.00
               MOVE 1.50 TO WS-BASE-FEE
           ELSE
               IF LS-SETTLE-AMOUNT < 50000.00
                   COMPUTE WS-CALC-PERCENT-FEE ROUNDED =
                       LS-SETTLE-AMOUNT * 0.0010
                   COMPUTE WS-BASE-FEE = 2.50 + WS-CALC-PERCENT-FEE
                   IF WS-BASE-FEE > 25.00
                       MOVE 25.00 TO WS-BASE-FEE
                   END-IF
               ELSE
                   IF LS-SETTLE-AMOUNT < 250000.00
                       COMPUTE WS-CALC-PERCENT-FEE ROUNDED =
                           LS-SETTLE-AMOUNT * 0.0005
                       COMPUTE WS-BASE-FEE = 15.00 + WS-CALC-PERCENT-FEE
                       IF WS-BASE-FEE > 150.00
                           MOVE 150.00 TO WS-BASE-FEE
                       END-IF
                   ELSE
                       COMPUTE WS-CALC-PERCENT-FEE ROUNDED =
                           LS-SETTLE-AMOUNT * 0.0002
                       COMPUTE WS-BASE-FEE = 50.00 + WS-CALC-PERCENT-FEE
                       IF WS-BASE-FEE > 500.00
                           MOVE 500.00 TO WS-BASE-FEE
                       END-IF
                   END-IF
               END-IF
           END-IF.

       3000-CALCULATE-TRANSFER-FEE.
           IF LS-SETTLE-AMOUNT < 500.00
               MOVE 0.50 TO WS-BASE-FEE
           ELSE
               IF LS-SETTLE-AMOUNT < 25000.00
                   COMPUTE WS-CALC-PERCENT-FEE ROUNDED =
                       LS-SETTLE-AMOUNT * 0.0008
                   COMPUTE WS-BASE-FEE = 1.00 + WS-CALC-PERCENT-FEE
                   IF WS-BASE-FEE > 15.00
                       MOVE 15.00 TO WS-BASE-FEE
                   END-IF
               ELSE
                   COMPUTE WS-CALC-PERCENT-FEE ROUNDED =
                       LS-SETTLE-AMOUNT * 0.0004
                   COMPUTE WS-BASE-FEE = 5.00 + WS-CALC-PERCENT-FEE
                   IF WS-BASE-FEE > 75.00
                       MOVE 75.00 TO WS-BASE-FEE
                   END-IF
               END-IF
           END-IF.

       4000-CALCULATE-PAYMENT-FEE.
           IF LS-SETTLE-AMOUNT < 100.00
               MOVE 0.25 TO WS-BASE-FEE
           ELSE
               COMPUTE WS-CALC-PERCENT-FEE ROUNDED =
                   LS-SETTLE-AMOUNT * 0.0015
               COMPUTE WS-BASE-FEE = 0.75 + WS-CALC-PERCENT-FEE
               IF WS-BASE-FEE > 50.00
                   MOVE 50.00 TO WS-BASE-FEE
               END-IF
           END-IF.

       5000-APPLY-TIER-DISCOUNT.
           IF WS-CUSTOMER-DISCOUNT-PCT > ZEROES
               COMPUTE WS-DISCOUNT-AMT ROUNDED =
                   WS-BASE-FEE * WS-CUSTOMER-DISCOUNT-PCT
               COMPUTE WS-FINAL-FEE = WS-BASE-FEE - WS-DISCOUNT-AMT
               MOVE WS-FINAL-FEE TO LS-FEE-AMOUNT
           ELSE
               MOVE WS-BASE-FEE TO LS-FEE-AMOUNT
           END-IF.
