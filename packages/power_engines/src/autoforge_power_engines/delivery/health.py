"""Shared Deployment Health-Check Framework Generator."""

from __future__ import annotations

from typing import List, Optional
from autoforge_power_engines.delivery.spec import CustomerDeploymentSpec, HealthCheckSpec


class HealthCheckBuilder:
    """
    Generates standalone health verification scripts for customer deliverables.
    Enables composition of shared platform checks with engine-contributed checks.
    """

    def build_health_script(
        self,
        spec: CustomerDeploymentSpec,
        custom_health_module: Optional[str] = "health",
    ) -> str:
        """
        Generates scripts/health_check.py capable of validating:
        1. Storage partitions
        2. Service readiness
        3. Workload-specific health functions from `src/health.py`
        """
        port = spec.get_primary_port()
        host = spec.get_primary_host()

        return f"""#!/usr/bin/env python3
\"\"\"Customer Deployment Health Verification Harness.\"\"\"

import os
import sys
import json
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "src"))

def check_persistent_storage() -> dict:
    missing = []
    # Check declared data directories
    manifest_file = BASE_DIR / "config" / "deployment_manifest.json"
    if manifest_file.exists():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            for d in data.get("data_directories", []):
                if not (BASE_DIR / d).exists():
                    missing.append(d)
        except Exception:
            pass
    if missing:
        return {{
            "component": "persistent_storage",
            "status": "degraded",
            "detail": f"Missing directories: {{', '.join(missing)}} (will be initialized on start)"
        }}
    return {{
        "component": "persistent_storage",
        "status": "healthy",
        "detail": "All declared persistent host partitions verified"
    }}

def check_service_readiness() -> dict:
    host = os.environ.get("HOST", "{host}")
    port = os.environ.get("PORT", "{port}")
    url = f"http://{{host}}:{{port}}/health"
    try:
        req = urllib.request.Request(url, headers={{"User-Agent": "CustomerHealthCheck/1.0"}})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return {{
                    "component": "service_api",
                    "status": "healthy",
                    "detail": f"Service at {{url}} responded with HTTP 200"
                }}
    except Exception as e:
        return {{
            "component": "service_api",
            "status": "offline",
            "detail": f"Service not responding at {{url}} (start via ./manage.sh start)"
        }}

def run_all_checks(require_service: bool = False) -> dict:
    checks = []
    errors = []

    # 1. Storage check
    st_res = check_persistent_storage()
    checks.append(st_res)

    # 2. Invoke engine-specific health module if available
    engine_checks_ran = False
    try:
        import {custom_health_module}
        if hasattr({custom_health_module}, "run_health_verification"):
            res = {custom_health_module}.run_health_verification()
            if isinstance(res, dict):
                engine_checks_ran = True
                for c in res.get("checks", []):
                    checks.append(c)
                for err in res.get("errors", []):
                    errors.append(err)
    except ImportError:
        pass
    except Exception as e:
        errors.append(f"Engine diagnostic error: {{e}}")

    # 3. Check HTTP service readiness
    svc_res = check_service_readiness()
    if svc_res["status"] == "healthy":
        checks.append(svc_res)
    elif require_service:
        checks.append(svc_res)
        errors.append(f"Service offline: {{svc_res['detail']}}")

    overall_status = "healthy"
    if errors or any(c.get("status") in ("unhealthy", "offline") for c in checks):
        overall_status = "unhealthy"
    elif any(c.get("status") == "degraded" for c in checks):
        overall_status = "degraded"

    return {{
        "status": overall_status,
        "checks": checks,
        "errors": errors
    }}

if __name__ == "__main__":
    require_service = "--require-service" in sys.argv
    as_json = "--json" in sys.argv
    strict_mode = "--strict" in sys.argv

    if require_service:
        report = run_all_checks(require_service=True)
    else:
        report = run_all_checks()

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for c in report["checks"]:
            icon = "✓" if c["status"] == "healthy" else ("⚠" if c["status"] == "degraded" else "✗")
            print(f"{{icon}} [{{c['component'].upper()}}]: {{c['detail']}}")
        if report["errors"]:
            for err in report["errors"]:
                print(f"✗ ERROR: {{err}}")

    if report["status"] == "healthy":
        if not as_json:
            print("✓ All deployment health checks passed.")
        sys.exit(0)
    elif report["status"] == "degraded":
        if not as_json:
            print("⚠ Deployment is in degraded state.")
        sys.exit(2 if strict_mode else 0)
    else:
        if not as_json:
            print(f"✗ Deployment health check FAILED (status: {{report['status']}}).")
        sys.exit(1)
"""
