"""
AutoForge Phase 17-B Smoke Test: End-to-End Real Runtime Execution & Delivery Verification.
Verifies:
1. Physical project creation on disk in builds/<id>/
2. Real code generation and pytest execution
3. Real OS process spawning and PID tracking
4. Live HTTP API calculation verification (2+3=5, 10-4=6, 6*7=42, 20/5=4)
5. Process termination (stop) and relaunch
6. Physical delivery archive creation in dist/<id>/
"""

import asyncio
import glob
import json
import os
import sys
import time
import urllib.request

# Setup PYTHONPATH for monorepo
src_paths = [os.path.abspath(p) for p in glob.glob("packages/*/src") + glob.glob("apps/*/src")]
sys.path = src_paths + sys.path

from autoforge_api.runtime_manager import ApplicationRuntimeManager
from autoforge_api.service import AutoForgeApiService
from autoforge_api.models import IntentExecutionRequest


def test_real_runtime_execution():
    print("=" * 80)
    print("AUTFORGE REAL RUNTIME & DELIVERY VERIFICATION")
    print("=" * 80)

    service = AutoForgeApiService()
    prompt = "Build me a simple calculator application."
    print(f"[1/6] Building project from idea: '{prompt}'...")

    req = IntentExecutionRequest(prompt=prompt)
    exec_res = service.execute_intent_pipeline(req)
    proj_id = exec_res.project_id
    print(f"      Project ID: {proj_id}")
    print(f"      Status: {exec_res.status}")
    assert exec_res.status == "COMPLETED"

    # 1. Verify files on disk
    print("\n[2/6] Verifying physical files on disk...")
    workspace_root = service.runtime_manager.workspace_root
    proj_dir = os.path.join(workspace_root, "builds", proj_id)
    if not os.path.isdir(proj_dir):
        proj_dir = os.path.join(workspace_root, "apps", "builds", proj_id)
    print(f"      Physical Project Directory: {proj_dir}")
    assert os.path.isdir(proj_dir), f"Directory {proj_dir} does not exist"

    app_file = os.path.join(proj_dir, "app.py")
    test_file = os.path.join(proj_dir, "test_app.py")
    readme_file = os.path.join(proj_dir, "README.md")

    assert os.path.isfile(app_file), "app.py missing"
    assert os.path.isfile(test_file), "test_app.py missing"
    assert os.path.isfile(readme_file), "README.md missing"

    print(f"      - app.py: {os.path.getsize(app_file)} bytes")
    print(f"      - test_app.py: {os.path.getsize(test_file)} bytes")
    print(f"      - README.md: {os.path.getsize(readme_file)} bytes")

    # 2. Verify Output & Tests
    print("\n[3/6] Verifying Project Output & Pytest...")
    output = service.get_project_output(proj_id)
    print(f"      Output Status: {output.status}")
    print(f"      Tests Passed: {output.test_results.get('passed')} / {output.test_results.get('total')}")
    assert output.test_results.get("status") == "GREEN"
    assert output.test_results.get("passed") >= 4

    # 3. Launch Process in Local Runtime
    print("\n[4/6] Launching Application in Local Runtime...")
    launch_res = service.launch_project_app(proj_id)
    print(f"      Launch Status: {launch_res.get('status')}")
    print(f"      Process ID (PID): {launch_res.get('pid')}")
    print(f"      Allocated Port: {launch_res.get('port')}")
    print(f"      Application URL: {launch_res.get('url')}")
    assert launch_res.get("status") == "RUNNING"
    assert launch_res.get("pid") is not None
    assert launch_res.get("port") is not None

    port = launch_res.get("port")

    # 4. Interact with Live Running Application Process over HTTP
    print("\n[5/6] Interacting with Live Application over HTTP...")
    # Test Health Endpoint
    req_h = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3)
    assert req_h.status == 200
    health_data = json.loads(req_h.read().decode("utf-8"))
    print(f"      GET /api/health -> {health_data}")
    assert health_data.get("status") == "ok"

    # Test Calculations directly executed by the live Python process
    test_expressions = [
        ("2 + 3", 5.0),
        ("10 - 4", 6.0),
        ("6 * 7", 42.0),
        ("20 / 5", 4.0),
        ("(2 + 3) * 4", 20.0),
    ]

    for expr, expected in test_expressions:
        data = json.dumps({"expression": expr}).encode("utf-8")
        req_c = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/calc",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_c, timeout=3) as resp:
            assert resp.status == 200
            res_data = json.loads(resp.read().decode("utf-8"))
            print(f"      POST /api/calc '{expr}' -> Result: {res_data.get('result')}")
            assert abs(float(res_data.get("result")) - expected) < 1e-6

    # 5. Stop and Relaunch Application Process
    print("\n[6/6] Stopping and Relaunching Application Process...")
    stop_res = service.stop_project_app(proj_id)
    print(f"      Stop Status: {stop_res.get('status')}")
    assert stop_res.get("status") == "STOPPED"

    # Verify Relaunch
    relaunch_res = service.launch_project_app(proj_id)
    print(f"      Relaunch Status: {relaunch_res.get('status')} (PID: {relaunch_res.get('pid')})")
    assert relaunch_res.get("status") == "RUNNING"
    service.stop_project_app(proj_id)

    # 6. Verify Physical Delivery Archive (.tar.gz)
    exp = service.export_project_archive(proj_id)
    print(f"\n[Delivery] Archive File: {exp.get('filename')}")
    print(f"           Absolute Path: {exp.get('absolute_path')}")
    print(f"           Archive Size: {exp.get('size_bytes')} bytes")
    assert os.path.isfile(exp.get("absolute_path"))
    assert exp.get("size_bytes") > 100

    print("\n" + "=" * 80)
    print("SUCCESS: REAL APPLICATION RUNTIME AND DELIVERY VERIFIED 100%")
    print("=" * 80)


if __name__ == "__main__":
    test_real_runtime_execution()
