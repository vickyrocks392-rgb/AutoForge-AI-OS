       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRNAUDT1.
      ******************************************************************
      * TRNAUDT1: TRANSACTION AUDITOR & COMPLIANCE VERIFICATION        *
      * PERFORMS MULTI-DIMENSIONAL INTEGRITY AND SANCTION VERIFICATION *
      ******************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY ACCMASTY.
       01  WS-MAX-SINGLE-TXN-LIMIT     PIC S9(11)V99 VALUE 5000000.00.
       01  WS-MIN-TXN-THRESHOLD        PIC S9(7)V99 VALUE 0.01.
       01  WS-SANCTION-PREFIX-1        PIC X(4) VALUE 'SANC'.
       01  WS-SANCTION-PREFIX-2        PIC X(4) VALUE 'REST'.
       01  WS-BLOCKED-COUNTRY-1        PIC X(3) VALUE 'PRK'.
       01  WS-BLOCKED-COUNTRY-2        PIC X(3) VALUE 'IRN'.

       01  WS-TEMP-NUMERIC             PIC 9(11)V99.
       01  WS-CURRENCY-VALID-FLAG      PIC X(1) VALUE 'N'.

       LINKAGE SECTION.
           COPY TRNREC0Y.
       01  LS-VALID-FLAG               PIC X(1).
       01  LS-ERR-CODE                 PIC X(4).
       01  LS-ERR-MSG                  PIC X(60).

       PROCEDURE DIVISION USING TRANSACTION-RECORD
                                LS-VALID-FLAG
                                LS-ERR-CODE
                                LS-ERR-MSG.
       0000-MAIN.
           MOVE 'Y' TO LS-VALID-FLAG
           MOVE SPACES TO LS-ERR-CODE
           MOVE SPACES TO LS-ERR-MSG

           PERFORM 1000-VERIFY-ACCOUNTS
           IF LS-VALID-FLAG = 'Y'
               PERFORM 2000-VERIFY-AMOUNT
           END-IF
           IF LS-VALID-FLAG = 'Y'
               PERFORM 3000-VERIFY-CURRENCIES
           END-IF
           IF LS-VALID-FLAG = 'Y'
               PERFORM 4000-VERIFY-TRANSACTION-TYPE
           END-IF
           IF LS-VALID-FLAG = 'Y'
               PERFORM 5000-VERIFY-SANCTION-LISTS
           END-IF
           GOBACK.

       1000-VERIFY-ACCOUNTS.
           IF TRN-SOURCE-ACCOUNT = SPACES OR TRN-TARGET-ACCOUNT = SPACES
               MOVE 'N' TO LS-VALID-FLAG
               MOVE 'EACT' TO LS-ERR-CODE
               MOVE 'SOURCE OR TARGET ACCOUNT IDENTIFIER MISSING'
                   TO LS-ERR-MSG
           ELSE
               IF TRN-SOURCE-ACCOUNT = TRN-TARGET-ACCOUNT
                   MOVE 'N' TO LS-VALID-FLAG
                   MOVE 'ESAM' TO LS-ERR-CODE
                   MOVE 'SOURCE AND TARGET ACCOUNTS CANNOT BE IDENTICAL'
                       TO LS-ERR-MSG
               ELSE
                   IF FUNCTION LENGTH(FUNCTION TRIM(TRN-SOURCE-ACCOUNT))
                       < 8
                       MOVE 'N' TO LS-VALID-FLAG
                       MOVE 'EACL' TO LS-ERR-CODE
                       MOVE 'SOURCE ACCOUNT LENGTH LESS THAN MINIMUM 8'
                           TO LS-ERR-MSG
                   END-IF
               END-IF
           END-IF.

       2000-VERIFY-AMOUNT.
           IF TRN-ORIG-AMOUNT < WS-MIN-TXN-THRESHOLD
               MOVE 'N' TO LS-VALID-FLAG
               MOVE 'EAMT' TO LS-ERR-CODE
               MOVE 'TRANSACTION AMOUNT BELOW MINIMUM THRESHOLD'
                   TO LS-ERR-MSG
           ELSE
               IF TRN-ORIG-AMOUNT > WS-MAX-SINGLE-TXN-LIMIT
                   MOVE 'N' TO LS-VALID-FLAG
                   MOVE 'ELIM' TO LS-ERR-CODE
                   MOVE 'TRANSACTION EXCEEDS MAXIMUM SINGLE SETTLEMENT LIMIT'
                       TO LS-ERR-MSG
               END-IF
           END-IF.

       3000-VERIFY-CURRENCIES.
           MOVE 'N' TO WS-CURRENCY-VALID-FLAG
           EVALUATE TRN-ORIG-CURRENCY
               WHEN 'USD'
               WHEN 'EUR'
               WHEN 'GBP'
               WHEN 'JPY'
               WHEN 'CAD'
               WHEN 'AUD'
               WHEN 'CHF'
                   MOVE 'Y' TO WS-CURRENCY-VALID-FLAG
               WHEN OTHER
                   MOVE 'N' TO WS-CURRENCY-VALID-FLAG
           END-EVALUATE

           IF WS-CURRENCY-VALID-FLAG = 'N'
               MOVE 'N' TO LS-VALID-FLAG
               MOVE 'ECUR' TO LS-ERR-CODE
               MOVE 'UNSUPPORTED ORIGINAL CURRENCY CODE'
                   TO LS-ERR-MSG
           ELSE
               IF TRN-SETTLE-CURRENCY NOT = 'USD' AND
                  TRN-SETTLE-CURRENCY NOT = 'EUR' AND
                  TRN-SETTLE-CURRENCY NOT = 'GBP'
                   MOVE 'N' TO LS-VALID-FLAG
                   MOVE 'ESET' TO LS-ERR-CODE
                   MOVE 'UNSUPPORTED SETTLEMENT CURRENCY CODE'
                       TO LS-ERR-MSG
               END-IF
           END-IF.

       4000-VERIFY-TRANSACTION-TYPE.
           EVALUATE TRN-TXN-TYPE
               WHEN 'XFER'
               WHEN 'PMNT'
               WHEN 'SETL'
               WHEN 'FREV'
                   CONTINUE
               WHEN OTHER
                   MOVE 'N' TO LS-VALID-FLAG
                   MOVE 'ETYP' TO LS-ERR-CODE
                   MOVE 'UNSUPPORTED OR INVALID TRANSACTION TYPE'
                       TO LS-ERR-MSG
           END-EVALUATE.

       5000-VERIFY-SANCTION-LISTS.
           IF TRN-SOURCE-ACCOUNT(1:4) = WS-SANCTION-PREFIX-1 OR
              TRN-TARGET-ACCOUNT(1:4) = WS-SANCTION-PREFIX-1 OR
              TRN-SOURCE-ACCOUNT(1:4) = WS-SANCTION-PREFIX-2 OR
              TRN-TARGET-ACCOUNT(1:4) = WS-SANCTION-PREFIX-2
               MOVE 'N' TO LS-VALID-FLAG
               MOVE 'ESNC' TO LS-ERR-CODE
               MOVE 'ACCOUNT SUBJECT TO STATUTORY SANCTIONS RESTRICTIONS'
                   TO LS-ERR-MSG
           END-IF.
