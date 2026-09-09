      ******************************************************************
      * FEESTRUY.CPY - TIERED FEE STRUCTURE & CALCULATION PARAMETERS   *
      ******************************************************************
       01  FEE-SCHEDULE-TABLE.
           05  FEE-TIER-COUNT              PIC 9(2) VALUE 4.
           05  FEE-TIER-ENTRIES OCCURS 4 TIMES INDEXED BY TIER-IDX.
               10  TIER-MIN-VOLUME         PIC S9(11)V99.
               10  TIER-MAX-VOLUME         PIC S9(11)V99.
               10  TIER-BASE-FIXED-FEE     PIC S9(5)V99.
               10  TIER-PERCENTAGE-RATE    PIC 9(2)V9(4).
               10  TIER-MIN-FEE            PIC S9(5)V99.
               10  TIER-MAX-FEE            PIC S9(5)V99.
