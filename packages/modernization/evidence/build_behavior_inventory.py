#!/usr/bin/env python3
"""
AutoForge 18-G — Phase 1: Source Behavioral Inventory Extractor.
Extracts all imperative operations, conditions, arithmetic, and control flow from legacy COBOL sources
in the certified TRANSACTION_PROCESSING subsystem.
"""

import json
import re
from pathlib import Path

SUBSYSTEM_FILES = [
    "app/cbl/CBTRN01C.cbl",
    "app/cbl/CBTRN02C.cbl",
    "app/cbl/CBTRN03C.cbl",
    "app/cbl/CSUTLDTC.cbl",
    "app/cpy/CVACT01Y.cpy",
    "app/cpy/CVACT02Y.cpy",
    "app/cpy/CVACT03Y.cpy",
    "app/cpy/CVTRA01Y.cpy",
    "app/cpy/CVTRA02Y.cpy",
    "app/cpy/CVTRA03Y.cpy",
    "app/cpy/CVTRA04Y.cpy",
    "app/cpy/CVTRA05Y.cpy",
    "app/cpy/CVTRA06Y.cpy",
    "app/cpy/CVTRA07Y.cpy",
]

CARDDEMO_ROOT = Path("/Users/kalachanddash/Documents/AutoForge AI/.autoforge/carddemo")
OUTPUT_PATH = Path("/Users/kalachanddash/Documents/AutoForge AI/packages/modernization/evidence/behavior_inventory.json")

def extract_inventory():
    inventory = {
        "subsystem": "TRANSACTION_PROCESSING",
        "total_source_files": len(SUBSYSTEM_FILES),
        "files": {},
        "operation_counts": {
            "MOVE": 0,
            "COMPUTE": 0,
            "ADD": 0,
            "SUBTRACT": 0,
            "IF": 0,
            "EVALUATE": 0,
            "WHEN": 0,
            "PERFORM": 0,
            "CALL": 0,
            "READ": 0,
            "WRITE": 0,
            "REWRITE": 0,
            "RETURN_CODE": 0,
        },
        "total_operations": 0
    }

    for rel_path in SUBSYSTEM_FILES:
        full_path = CARDDEMO_ROOT / rel_path
        if not full_path.exists():
            continue

        file_ops = []
        current_section = "WORKING-STORAGE"
        current_para = "GLOBAL"

        with open(full_path, "r", encoding="latin-1", errors="ignore") as f:
            for idx, raw_line in enumerate(f, 1):
                # Standard fixed format COBOL line stripping
                line = raw_line[6:72].rstrip() if len(raw_line) >= 7 else raw_line.rstrip()
                if not line or line.startswith("*") or line.startswith("/"):
                    continue

                line_upper = line.strip().upper()

                # Detect divisions and sections
                if "PROCEDURE DIVISION" in line_upper:
                    current_section = "PROCEDURE DIVISION"
                elif "DATA DIVISION" in line_upper:
                    current_section = "DATA DIVISION"
                elif "WORKING-STORAGE SECTION" in line_upper:
                    current_section = "WORKING-STORAGE SECTION"

                # Detect paragraphs
                m_para = re.match(r"^([A-Z0-9-]+)\s*\.\s*$", line.strip(), re.IGNORECASE)
                if m_para and not line_upper.startswith(("EXIT", "GOBACK", "STOP", "IF", "ELSE", "PERFORM", "MOVE", "COMPUTE", "ADD", "SUBTRACT", "CALL")):
                    current_para = m_para.group(1).upper()
                    continue

                # Parse operations in PROCEDURE DIVISION
                if current_section == "PROCEDURE DIVISION":
                    op_type = None
                    if "MOVE " in line_upper and "TO " in line_upper:
                        if "RETURN-CODE" in line_upper:
                            op_type = "RETURN_CODE"
                        else:
                            op_type = "MOVE"
                    elif line_upper.startswith("COMPUTE ") or " COMPUTE " in line_upper:
                        op_type = "COMPUTE"
                    elif line_upper.startswith("ADD ") or " ADD " in line_upper:
                        op_type = "ADD"
                    elif line_upper.startswith("SUBTRACT ") or " SUBTRACT " in line_upper:
                        op_type = "SUBTRACT"
                    elif line_upper.startswith("IF ") or " IF " in line_upper:
                        op_type = "IF"
                    elif line_upper.startswith("EVALUATE ") or " EVALUATE " in line_upper:
                        op_type = "EVALUATE"
                    elif line_upper.startswith("WHEN ") or " WHEN " in line_upper:
                        op_type = "WHEN"
                    elif line_upper.startswith("PERFORM ") or " PERFORM " in line_upper:
                        op_type = "PERFORM"
                    elif line_upper.startswith("CALL ") or " CALL " in line_upper:
                        op_type = "CALL"
                    elif line_upper.startswith("READ ") or " READ " in line_upper:
                        op_type = "READ"
                    elif line_upper.startswith("WRITE ") or " WRITE " in line_upper:
                        op_type = "WRITE"
                    elif line_upper.startswith("REWRITE ") or " REWRITE " in line_upper:
                        op_type = "REWRITE"

                    if op_type:
                        inventory["operation_counts"][op_type] += 1
                        inventory["total_operations"] += 1
                        file_ops.append({
                            "line": idx,
                            "paragraph": current_para,
                            "type": op_type,
                            "statement": line.strip()
                        })

        inventory["files"][rel_path] = {
            "operations_count": len(file_ops),
            "operations": file_ops
        }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        json.dump(inventory, out, indent=2)

    print(f"Generated behavior inventory with {inventory['total_operations']} operations across {len(SUBSYSTEM_FILES)} files.")
    return inventory

if __name__ == "__main__":
    extract_inventory()
