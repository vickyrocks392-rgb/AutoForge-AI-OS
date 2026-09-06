ASM01    CSECT
         STM   14,12,12(13)
         LR    12,15
         USING ASM01,12
         LA    11,SAVEAREA
         ST    13,4(11)
         ST    11,8(13)
         LR    13,11
         L     13,4(13)
         LM    14,12,12(13)
         XR    15,15
         BR    14
SAVEAREA DS    18F
         END   ASM01
