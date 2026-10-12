"""Developer self-check for the Phase 20 PROCEDURE DIVISION parser."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

from autoforge_modernization.service.cobol_proc import parse_procedure  # noqa: E402

WS = Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads")
DAILYPOST = WS / "playbook" / "cobol" / "DAILYPOST.cbl"
CBACT01C = WS / "carddemo" / "app" / "cbl" / "CBACT01C.cbl"


def dump(title: str, paragraphs: dict, gaps: list) -> int:
    print(f"== {title} ==")
    for name, stmts in paragraphs.items():
        if not stmts:
            continue
        print(f"  [{name or '<main>'}] {len(stmts)} statements")
        for stmt in stmts:
            extra = ""
            if stmt.kind == "if":
                extra = f"cond={stmt.attrs['condition_text']!r} then={len(stmt.attrs['then'])} else={len(stmt.attrs['else'])}"
            elif stmt.kind == "evaluate":
                extra = f"subject={stmt.attrs['subject_text']!r} whens={len(stmt.attrs['whens'])}"
            elif stmt.kind == "move":
                extra = f"{stmt.attrs['source']!r} -> {stmt.attrs['targets']}"
            elif stmt.kind == "perform_until":
                extra = f"until={stmt.attrs['condition_text']!r} body={len(stmt.attrs['body'])}"
            elif stmt.kind == "read":
                extra = f"file={stmt.attrs['file']} atEnd={len(stmt.attrs['at_end'])} notAtEnd={len(stmt.attrs['not_at_end'])}"
            elif stmt.kind == "write":
                extra = f"record={stmt.attrs['record']} from={stmt.attrs['from']}"
            elif stmt.kind == "arithmetic":
                extra = f"{stmt.attrs['op']} {stmt.attrs['operands']} {stmt.attrs['receivers']} giving={stmt.attrs['giving']}"
            elif stmt.kind == "compute":
                extra = f"{stmt.attrs['targets']} = {stmt.attrs['expression']}"
            elif stmt.kind == "call":
                extra = f"{stmt.attrs['target']} using {stmt.attrs['using']}"
            elif stmt.kind == "open":
                extra = f"{stmt.attrs['entries']}"
            elif stmt.kind == "display":
                extra = f"{stmt.attrs['operands']}"
            print(f"     L{stmt.line:<4} {stmt.kind:<14} {stmt.text[:64]}")
            if extra:
                print(f"          -> {extra[:150]}")
    if gaps:
        print(f"  GAPS ({len(gaps)}):")
        for gap in gaps[:20]:
            print(f"     L{gap.line} {gap.construct}: {gap.reason} | {gap.text[:70]}")
    else:
        print("  no gaps")
    print()
    return len(gaps)


def main() -> int:
    paragraphs, gaps = parse_procedure(DAILYPOST.read_text(errors="replace"))
    n1 = dump("DAILYPOST.cbl (free format)", paragraphs, gaps)

    paragraphs2, gaps2 = parse_procedure(CBACT01C.read_text(errors="replace"))
    n2 = dump("CBACT01C.cbl (fixed format)", paragraphs2, gaps2)

    print(f"TOTAL GAPS: DAILYPOST={n1} CBACT01C={n2}")
    return 0 if (n1 == 0 and n2 == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())