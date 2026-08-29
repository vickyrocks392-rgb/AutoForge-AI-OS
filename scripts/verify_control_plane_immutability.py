"""
Comprehensive Control-Plane Immutability, Toolchain Discovery, and Runtime Delivery Verification.
"""

from __future__ import annotations
import glob
import hashlib
import json
import os
import sys
import tarfile
import time
import urllib.request

# Setup PYTHONPATH
sys.path = [os.path.abspath(p) for p in glob.glob("packages/*/src") + glob.glob("apps/*/src")] + sys.path

from autoforge_api.toolchain import PackagingToolchainManager, ProjectSandboxManager


def get_source_tree_checksums(root_dir: str) -> dict[str, str]:
    """Computes SHA256 checksums of all source and config files in apps/ and packages/."""
    checksums = {}
    for search_dir in ["apps", "packages"]:
        full_dir = os.path.join(root_dir, search_dir)
        for root, _, files in os.walk(full_dir):
            for file in sorted(files):
                if file.endswith((".py", ".js", ".html", ".css", ".json", ".md", ".toml")):
                    fpath = os.path.join(root, file)
                    relpath = os.path.relpath(fpath, root_dir)
                    with open(fpath, "rb") as f:
                        checksums[relpath] = hashlib.sha256(f.read()).hexdigest()
    return checksums


def main():
    workspace_root = os.path.abspath(os.getcwd())
    print("============================================================")
    print("1. RECORDING AUTOFORGE CONTROL-PLANE CHECKSUMS BEFORE BUILD")
    print("============================================================")
    checksums_before = get_source_tree_checksums(workspace_root)
    print(f"Recorded {len(checksums_before)} source files in apps/ and packages/.")

    print("\n============================================================")
    print("2. VERIFYING TOOLCHAIN REGISTRY DISCOVERY & SANDBOX ISOLATION")
    print("============================================================")
    toolchain_mgr = PackagingToolchainManager()
    toolchains = toolchain_mgr.discover_toolchains()
    print(f"Discovered {len(toolchains)} toolchains on host node {toolchain_mgr.host_platform}:")
    for tc in toolchains:
        print(f"  - {tc.tool_name} ({tc.category}): {tc.status.value} | {tc.detected_path or tc.reason_if_unavailable}")

    can_native, native_reason, native_tool = toolchain_mgr.can_package_native_desktop()
    print(f"Native desktop packaging capability: {can_native} | Reason: {native_reason}")

    sandbox_mgr = ProjectSandboxManager(workspace_root=workspace_root)
    test_sbx = sandbox_mgr.create_sandbox("test-sbx-001")
    assert sandbox_mgr.validate_sandbox_path("test-sbx-001", os.path.join(test_sbx.root_directory, "src", "app.py")) is True
    # Test escaping to apps/ is rejected
    assert sandbox_mgr.validate_sandbox_path("test-sbx-001", os.path.join(workspace_root, "apps", "api", "src", "autoforge_api", "server.py")) is False
    print("Sandbox path isolation assertions verified successfully!")

    print("\n============================================================")
    print("3. RUNNING END-TO-END HTTP WORKFLOW AGAINST RUNNING SERVER")
    print("============================================================")
    server_base = "http://127.0.0.1:8787"

    # 3.1 Intent Scoping
    analyze_payload = json.dumps({"prompt": "Build me a simple calculator desktop application."}).encode("utf-8")
    req = urllib.request.Request(f"{server_base}/api/intent/analyze", data=analyze_payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        analyze_res = json.loads(resp.read().decode())
        print(f"Scoped Intent: '{analyze_res['title']}'")
        print(f"Requested Type: {analyze_res['tech_stack_proposal']['requested_type']}")
        print(f"Actual Type: {analyze_res['tech_stack_proposal']['actual_type']}")
        print(f"HITL Gate ID: {analyze_res['approval_id']}")
        assert analyze_res['tech_stack_proposal']['requested_type'] == "Desktop Application"
        assert analyze_res['tech_stack_proposal']['actual_type'] == "Web Application (Local Server & Client)"

    # 3.2 HITL Tech Stack Approval
    app_id = analyze_res["approval_id"]
    app_payload = json.dumps({"approval_id": app_id, "decision": "APPROVE"}).encode("utf-8")
    req = urllib.request.Request(f"{server_base}/api/intent/approve-stack", data=app_payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        app_res = json.loads(resp.read().decode())
        print(f"HITL Decision: {app_res['decision']} (Status: {app_res['status']})")
        assert app_res["decision"] == "APPROVE"

    # 3.3 Execute Build & Packaging
    exec_payload = json.dumps({
        "prompt": "Build me a simple calculator desktop application.",
        "stages": analyze_res["shortest_path_stages"],
        "approval_id": app_id,
    }).encode("utf-8")
    req = urllib.request.Request(f"{server_base}/api/intent/execute", data=exec_payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        exec_res = json.loads(resp.read().decode())
        proj_id = exec_res["project_id"]
        print(f"Build Executed: Project ID = {proj_id} (Status: {exec_res['status']})")
        assert exec_res["status"] == "COMPLETED"

    # 3.4 Physical Filesystem Verification
    dist_dir = os.path.join(workspace_root, "dist", proj_id)
    app_tar = os.path.join(dist_dir, f"autoforge-app-{proj_id}.tar.gz")
    src_tar = os.path.join(dist_dir, f"autoforge-src-{proj_id}.tar.gz")
    assert os.path.isfile(app_tar), f"Missing {app_tar}"
    assert os.path.isfile(src_tar), f"Missing {src_tar}"
    print(f"Verified physical distribution archive ({os.path.getsize(app_tar)} bytes): {app_tar}")
    print(f"Verified physical source archive ({os.path.getsize(src_tar)} bytes): {src_tar}")

    with tarfile.open(app_tar, "r:gz") as t:
        members = t.getnames()
        print(f"Archive contents: {members}")
        assert "app.py" in members and "test_app.py" in members

    # 3.5 Launch Runtime Process
    run_req = urllib.request.Request(f"{server_base}/api/projects/{proj_id}/run", data=json.dumps({}).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(run_req) as resp:
        run_res = json.loads(resp.read().decode())
        pid = run_res["pid"]
        port = run_res["port"]
        print(f"Launched Runtime Process: PID = {pid} on Port = {port}")
        assert run_res["status"] == "RUNNING"
        assert pid > 0 and port > 1024

    # 3.6 Query Health on Generated Process
    health_req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health")
    with urllib.request.urlopen(health_req) as resp:
        hres = json.loads(resp.read().decode())
        print(f"Health Response from PID {pid}: {hres}")
        assert hres["status"] == "ok"

    # 3.7 Calculation Verification
    calc_tests = [
        ("2 + 3", 5.0),
        ("10 - 4", 6.0),
        ("6 * 7", 42.0),
        ("20 / 5", 4.0),
        ("2 ** 8", 256.0),
        ("(12 + 8) * 3", 60.0),
    ]
    for expr, expected in calc_tests:
        calc_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/calc",
            data=json.dumps({"expression": expr}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(calc_req) as resp:
            cres = json.loads(resp.read().decode())
            print(f"  -> Calc: {expr} = {cres.get('result')} (Expected: {expected})")
            assert cres.get("result") == expected

    # 3.8 Stop Runtime Process
    stop_req = urllib.request.Request(f"{server_base}/api/projects/{proj_id}/stop", data=json.dumps({}).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(stop_req) as resp:
        stop_res = json.loads(resp.read().decode())
        print(f"Process Stopped: {stop_res['status']}")
        assert stop_res["status"] == "STOPPED"

    # 3.9 Restart Runtime Process
    run_req2 = urllib.request.Request(f"{server_base}/api/projects/{proj_id}/run", data=json.dumps({}).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(run_req2) as resp:
        run_res2 = json.loads(resp.read().decode())
        print(f"Restarted Runtime Process: PID = {run_res2['pid']} on Port = {run_res2['port']}")
        assert run_res2["status"] == "RUNNING"

    # Clean up stop
    with urllib.request.urlopen(stop_req) as resp:
        pass

    # 3.10 Download Endpoints
    down_req = urllib.request.Request(f"{server_base}/api/projects/{proj_id}/download")
    with urllib.request.urlopen(down_req) as resp:
        pkg_bytes = resp.read()
        assert len(pkg_bytes) > 100
        print(f"Verified /download endpoint ({len(pkg_bytes)} bytes downloaded)")

    src_down_req = urllib.request.Request(f"{server_base}/api/projects/{proj_id}/download-source")
    with urllib.request.urlopen(src_down_req) as resp:
        src_bytes = resp.read()
        assert len(src_bytes) > 100
        print(f"Verified /download-source endpoint ({len(src_bytes)} bytes downloaded)")

    print("\n============================================================")
    print("4. FORENSIC CONTROL-PLANE IMMUTABILITY VERIFICATION")
    print("============================================================")
    checksums_after = get_source_tree_checksums(workspace_root)

    modified_files = []
    added_files = []
    deleted_files = []

    for relpath, ck_before in checksums_before.items():
        if relpath not in checksums_after:
            deleted_files.append(relpath)
        elif checksums_after[relpath] != ck_before:
            modified_files.append(relpath)

    for relpath in checksums_after.keys():
        if relpath not in checksums_before:
            added_files.append(relpath)

    print(f"Total control-plane source files checked: {len(checksums_after)}")
    print(f"Modified files in apps/ or packages/: {len(modified_files)}")
    print(f"Added files in apps/ or packages/: {len(added_files)}")
    print(f"Deleted files in apps/ or packages/: {len(deleted_files)}")

    assert len(modified_files) == 0, f"Control plane files were modified! {modified_files}"
    assert len(added_files) == 0, f"Control plane files were added! {added_files}"
    assert len(deleted_files) == 0, f"Control plane files were deleted! {deleted_files}"

    print("CONTROL-PLANE IMMUTABILITY ASSERTION 100% PASSED (ZERO MUTATIONS TO AUTOFORGE SOURCE TREE).")
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
