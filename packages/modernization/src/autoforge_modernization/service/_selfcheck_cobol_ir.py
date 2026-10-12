"""Developer self-check for the Phase 20 COBOL IR (not part of the package API).

Validates :mod:`cobol_ir` against REAL copybooks whose record sizes are
independently known: the DAILYPOST ``FILE SECTION`` declares LRECL 58/72 and
CardDemo's ``READACCT.jcl`` declares LRECL 107/110 with RECLN 300.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

from autoforge_modernization.service.cobol_ir import (  # noqa: E402
    build_record_layout,
    parse_data_entries,
    parse_picture,
    source_lines,
)

WS = Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads")
PLAYBOOK = WS / "playbook"
CARDDEMO = WS / "carddemo"


def layout_for(path: Path, record_name: str):
    entries, gaps = parse_data_entries(source_lines(path.read_text(errors="replace")))
    layout = build_record_layout(entries, record_name=record_name, gaps=gaps)
    return layout, gaps


def check(label: str, actual: int, expected: int) -> bool:
    ok = actual == expected
    print(f"{'OK ' if ok else 'BAD'} {label}: actual={actual} expected={expected}")
    return ok


def main() -> int:
    results = []

    print("== PICTURE parsing ==")
    p = parse_picture("S9(11)V99")
    results.append(check("S9(11)V99 digits", p.digits, 13))
    results.append(check("S9(11)V99 scale", p.scale, 2))
    p = parse_picture("X(12)")
    results.append(check("X(12) chars", p.char_count, 12))
    p = parse_picture("9(8)")
    results.append(check("9(8) digits", p.digits, 8))

    print("\n== Playbook copybooks (LRECL declared in DAILYPOST FILE SECTION) ==")
    acct, g1 = layout_for(PLAYBOOK / "cobol" / "copybooks" / "ACCOUNT-REC.cpy", "ACCT-IN-REC")
    results.append(check("ACCOUNT-REC size", acct.size, 58))
    txn, g2 = layout_for(PLAYBOOK / "cobol" / "copybooks" / "TXN-REC.cpy", "TXN-IN-REC")
    results.append(check("TXN-REC size", txn.size, 72))
    for f in acct.fields:
        if f.name:
            print(
                f"     {f.name:<20} off={f.offset:<4} size={f.size:<4} "
                f"usage={f.usage:<8} pic={f.picture.raw if f.picture else '-'}"
            )

    print("\n== CardDemo CVACT01Y (header says RECLN 300) ==")
    acctrec, g3 = layout_for(CARDDEMO / "app" / "cpy" / "CVACT01Y.cpy", "ACCOUNT-RECORD")
    results.append(check("ACCOUNT-RECORD size", acctrec.size, 300))

    all_gaps = g1 + g2 + g3
    if all_gaps:
        print("\nUnexpected gaps:")
        for gap in all_gaps:
            print("   ", gap.as_dict())
    results.append(check("unexpected gaps", len(all_gaps), 0))

    print("\n" + ("ALL COBOL IR CHECKS PASSED" if all(results) else "COBOL IR CHECKS FAILED"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())