"""Developer self-check for the Phase 20 assembled program model."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

from autoforge_modernization.service.cobol_program import build_program_model  # noqa: E402

WS = Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads")


def show(title, model):
    print(f"== {title} ==")
    print(f"  program_id : {model.program_id}  ({model.source_format} format)")
    print(f"  files      : {sorted(model.files)}")
    for name, fd in sorted(model.files.items()):
        print(f"      {name:<16} org={fd.organization:<11} assign={fd.assign}")
    print(f"  records    :")
    for name, layout in sorted(model.records.items()):
        print(f"      {name:<22} size={layout.size:<5} fields={len(layout.fields)}")
    print(f"  working    :")
    for name, layout in sorted(model.working_storage.items()):
        leaves = [f"{f.name}:{f.picture.raw if f.picture else 'grp'}"
                  for f in layout.fields if f.name]
        print(f"      {name:<22} size={layout.size:<4} {leaves[:6]}")
    print(f"  paragraphs : {sorted(model.paragraphs)}")
    print(f"  calls      : {sorted(model.calls)}")
    print(f"  copybooks  : {sorted(set(model.copybooks))}")
    print(f"  GAPS       : {len(model.gaps)}")
    for gap in model.gaps[:12]:
        print(f"      L{gap.line} {gap.construct}: {gap.reason} | {gap.text[:80]}")
    print()
    return len(model.gaps)


def main() -> int:
    playbook = WS / "playbook"
    dailypost = build_program_model(
        (playbook / "cobol" / "DAILYPOST.cbl").read_text(errors="replace"),
        source_path="cobol/DAILYPOST.cbl",
        copybook_dirs=[playbook / "cobol" / "copybooks"],
    )
    n1 = show("DAILYPOST.cbl", dailypost)

    carddemo = WS / "carddemo"
    cbact01c = build_program_model(
        (carddemo / "app" / "cbl" / "CBACT01C.cbl").read_text(errors="replace"),
        source_path="app/cbl/CBACT01C.cbl",
        copybook_dirs=[carddemo / "app" / "cpy", carddemo / "app" / "cpy-bms"],
    )
    n2 = show("CBACT01C.cbl", cbact01c)

    print("GAPS:", n1, n2)
    return 0 if (n1 == 0 and n2 == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())