"""Decode the real golden-master records using the Phase 20 COBOL IR.

This answers, with certainty, how GnuCOBOL encodes signed DISPLAY numerics and
COMP-3 packed decimal in these specific workloads -- the exact bytes the
modernized Java must reproduce.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

from autoforge_modernization.service.cobol_ir import (  # noqa: E402
    build_record_layout,
    parse_data_entries,
    source_lines,
)

PLAYBOOK = Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads/playbook")
CARDDEMO = Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads/carddemo")


def layout_of(path: Path, name: str):
    entries, gaps = parse_data_entries(source_lines(path.read_text(errors="replace")))
    return build_record_layout(entries, record_name=name, gaps=gaps)


def show(title, layout, record_bytes):
    print(f"== {title} (record size {layout.size}) ==")
    for f in layout.fields:
        if not f.name or f.picture is None:
            continue
        unit = f.size // max(1, f.occurs)
        raw = record_bytes[f.offset: f.offset + unit]
        pretty = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
        print(
            f"  {f.name:<20} off={f.offset:<4} len={unit:<3} "
            f"{f.usage:<7} pic={f.picture.raw:<12} bytes={raw.hex(' ')}  |{pretty}|"
        )
    print()


def main() -> int:
    acct = layout_of(PLAYBOOK / "cobol" / "copybooks" / "ACCOUNT-REC.cpy", "ACCT")
    data = (PLAYBOOK / "out" / "accounts_out.dat").read_bytes()
    show("ACCOUNT-REC from real DAILYPOST output record 1", acct, data[: acct.size])

    txn = layout_of(PLAYBOOK / "cobol" / "copybooks" / "TXN-REC.cpy", "TXN")
    exc = (PLAYBOOK / "out" / "exceptions.dat").read_bytes()
    show("TXN-REC from real DAILYPOST exceptions record 1", txn, exc[: txn.size])

    out_rec = layout_of(CARDDEMO / "app" / "cbl" / "CBACT01C.cbl", "OUT")
    print("CBACT01C OUT-ACCT-REC layout:")
    for f in out_rec.fields:
        if f.name and f.picture is not None:
            print(
                f"   {f.name:<28} off={f.offset:<4} size={f.size:<4} "
                f"{f.usage:<7} {f.picture.raw}"
            )
    out_bytes = Path("/tmp/p20_feas/out.ps").read_bytes()
    print("\nreal out.ps record 1 bytes:", out_bytes[:107].hex(" "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())