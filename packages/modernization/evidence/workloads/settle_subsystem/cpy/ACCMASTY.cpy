      ******************************************************************
      * ACCMASTY.CPY - ACCOUNT MASTER RECORD DEFINITION                *
      ******************************************************************
       01  ACCOUNT-MASTER-RECORD.
           05  ACC-ACCOUNT-ID              PIC X(16).
           05  ACC-CUSTOMER-ID             PIC X(12).
           05  ACC-ACCOUNT-TYPE            PIC X(2).
               88  ACC-TYPE-CHECKING       VALUE 'CH'.
               88  ACC-TYPE-SAVINGS        VALUE 'SV'.
               88  ACC-TYPE-MERCHANT       VALUE 'MC'.
               88  ACC-TYPE-SETTLEMENT     VALUE 'ST'.
           05  ACC-STATUS                  PIC X(1).
               88  ACC-ACTIVE              VALUE 'A'.
               88  ACC-DORMANT             VALUE 'D'.
               88  ACC-FROZEN              VALUE 'F'.
               88  ACC-CLOSED              VALUE 'C'.
           05  ACC-CURRENCY-CODE           PIC X(3).
           05  ACC-CURRENT-BALANCE         PIC S9(11)V99.
           05  ACC-AVAILABLE-BALANCE       PIC S9(11)V99.
           05  ACC-OVERDRAFT-LIMIT         PIC S9(9)V99.
           05  ACC-TIER-LEVEL              PIC 9(2).
           05  ACC-DAILY-VOLUME-ACCUM      PIC S9(11)V99.
           05  ACC-DAILY-TXN-COUNT         PIC 9(5).
           05  ACC-LAST-ACTIVITY-DATE      PIC 9(8).
           05  ACC-RESERVED                PIC X(32).
