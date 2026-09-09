      ******************************************************************
      * TRNREC0Y.CPY - TRANSACTION RECORD DEFINITION                   *
      ******************************************************************
       01  TRANSACTION-RECORD.
           05  TRN-TXN-ID                  PIC X(20).
           05  TRN-SOURCE-ACCOUNT          PIC X(16).
           05  TRN-TARGET-ACCOUNT          PIC X(16).
           05  TRN-TXN-TYPE                PIC X(4).
               88  TXN-TRANSFER            VALUE 'XFER'.
               88  TXN-PAYMENT             VALUE 'PMNT'.
               88  TXN-SETTLEMENT          VALUE 'SETL'.
               88  TXN-FEE-REVERSAL        VALUE 'FREV'.
           05  TRN-TXN-STATUS              PIC X(2).
               88  TXN-STATUS-PENDING      VALUE '00'.
               88  TXN-STATUS-APPROVED     VALUE '01'.
               88  TXN-STATUS-REJECTED     VALUE '99'.
           05  TRN-ORIG-CURRENCY           PIC X(3).
           05  TRN-ORIG-AMOUNT             PIC S9(11)V99.
           05  TRN-SETTLE-CURRENCY         PIC X(3).
           05  TRN-SETTLE-AMOUNT           PIC S9(11)V99.
           05  TRN-EXCHANGE-RATE           PIC 9(5)V9(6).
           05  TRN-FEE-AMOUNT              PIC S9(7)V99.
           05  TRN-SPREAD-AMOUNT           PIC S9(7)V99.
           05  TRN-VALUE-DATE              PIC 9(8).
           05  TRN-ERROR-CODE              PIC X(4).
           05  TRN-DESCRIPTION             PIC X(40).
