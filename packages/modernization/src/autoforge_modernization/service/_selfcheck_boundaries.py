import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "packages" / "modernization" / "src"))

from autoforge_modernization.service.boundaries import (  # noqa: E402
    BoundaryViolation,
    CustomerBoundary,
    ProjectAccessGuard,
    is_within,
)


def main() -> int:
    failures = []

    bd = CustomerBoundary(repo_root=ROOT, project_id="carddemo-modernization")
    assert bd.output_root.name == "Modernization Output", bd.output_root
    assert bd.output_root == ROOT / "Modernization Output"
    assert bd.project_root == bd.output_root / "carddemo-modernization"
    print("OK  boundary paths:", bd.output_root, "->", bd.project_root)

    for bad in ["..", ".", "a/b", "con", "", "-leading", "x" * 200]:
        try:
            bd.section(bad)
            failures.append(f"segment {bad!r} was accepted")
        except BoundaryViolation:
            pass
    print("OK  hostile/traversal segments rejected")

    for owned in ["packages", "apps", "services", "tests", "docs", "scripts"]:
        try:
            bd.assert_writable_customer_path(ROOT / owned / "X.java")
            failures.append(f"autoforge dir {owned} accepted")
        except BoundaryViolation:
            pass
    print("OK  AutoForge-owned source dirs rejected")

    # traversal out of the customer boundary
    try:
        bd.assert_inside_boundary(bd.project_root / ".." / ".." / "packages" / "x.java")
        failures.append("traversal out of boundary accepted")
    except BoundaryViolation:
        print("OK  traversal out of boundary rejected")

    # absolute path outside the project
    try:
        bd.assert_inside_boundary(ROOT)
        failures.append("repo root accepted as customer path")
    except BoundaryViolation:
        print("OK  foreign absolute path rejected")

    assert is_within(bd.project_root / "legacy-source", bd.project_root)
    assert not is_within(ROOT / "packages", bd.project_root)
    print("OK  is_within semantics")

    g = ProjectAccessGuard(owner_project_id="proj-a", known_project_ids=("proj-a", "proj-b"))
    assert g.assert_owner("proj-a") == "proj-a"
    for other in ["proj-b", "proj-c", ""]:
        try:
            g.assert_owner(other)
            failures.append(f"cross-project access {other!r} accepted")
        except BoundaryViolation:
            pass
    try:
        g.assert_owner_in_paths([ROOT / "Modernization Output" / "proj-b" / "x"])
        failures.append("foreign project path accepted")
    except BoundaryViolation:
        pass
    print("OK  project isolation fails closed")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nALL BOUNDARY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())