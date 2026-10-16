"""Universal Customer Deployment & Orchestration Generator."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from autoforge_power_engines.delivery.spec import (
    CustomerDeploymentSpec,
    ServiceDefinition,
    assert_target_supported,
)


class DeploymentBuilder:
    """
    Generates all standardized customer deployment files:
    - docker-compose.yml
    - Dockerfile (non-root)
    - Deploy.command (macOS one-click)
    - deploy.sh (POSIX one-command fallback)
    - Deploy.bat (Windows one-click)
    - manage.sh (lifecycle CLI: start, stop, restart, status, logs)
    - config/deployment_manifest.json
    - .env and .env.example
    """

    def build_docker_compose(self, spec: CustomerDeploymentSpec) -> str:
        """Generates standard Docker Compose configuration from CustomerDeploymentSpec."""
        assert_target_supported(spec.target)
        lines: List[str] = ["version: '3.8'", "", "services:"]

        for s_name, svc in spec.services.items():
            lines.append(f"  {s_name}:")
            if svc.image:
                lines.append(f"    image: {svc.image}")
            else:
                lines.append("    build:")
                lines.append(f"      context: {svc.build_context or '.'}")
                lines.append(f"      dockerfile: {svc.dockerfile or 'Dockerfile'}")

            c_name = svc.container_name or f"customer_{s_name}_{spec.sanitized_project_id}"
            lines.append(f"    container_name: {c_name}")
            lines.append(f"    restart: {svc.restart_policy.value}")

            if svc.command:
                if isinstance(svc.command, list):
                    cmd_str = json.dumps(svc.command)
                    lines.append(f"    command: {cmd_str}")
                else:
                    lines.append(f"    command: {svc.command}")

            if svc.ports:
                lines.append("    ports:")
                for p in svc.ports:
                    lines.append(f'      - "{p.compose_format()}"')

            if svc.internal_ports:
                lines.append("    expose:")
                for ip in svc.internal_ports:
                    lines.append(f'      - "{ip}"')

            if svc.environment:
                lines.append("    environment:")
                for k, v in svc.environment.items():
                    lines.append(f"      - {k}={v}")

            if svc.volumes:
                lines.append("    volumes:")
                for v in svc.volumes:
                    lines.append(f"      - {v.compose_format()}")

            if svc.networks:
                lines.append("    networks:")
                for net in svc.networks:
                    lines.append(f"      - {net}")

            if svc.depends_on:
                lines.append("    depends_on:")
                for dep in svc.depends_on:
                    lines.append(f"      - {dep}")

            if svc.extra_hosts:
                lines.append("    extra_hosts:")
                for eh in svc.extra_hosts:
                    lines.append(f'      - "{eh}"')

            if svc.security_opt:
                lines.append("    security_opt:")
                for so in svc.security_opt:
                    lines.append(f"      - {so}")

            if svc.cap_drop:
                lines.append("    cap_drop:")
                for cap in svc.cap_drop:
                    lines.append(f"      - {cap}")

            if svc.cpu_limit or svc.memory_limit:
                lines.append("    deploy:")
                lines.append("      resources:")
                lines.append("        limits:")
                if svc.cpu_limit:
                    lines.append(f"          cpus: '{svc.cpu_limit}'")
                if svc.memory_limit:
                    lines.append(f"          memory: {svc.memory_limit}")

            if svc.read_only_root:
                lines.append("    read_only: true")

            lines.append("")

        if spec.networks:
            lines.append("networks:")
            for n_name, net in spec.networks.items():
                lines.append(f"  {n_name}:")
                lines.append(f"    driver: {net.driver}")
                if net.internal:
                    lines.append("    internal: true")
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    def build_dockerfile(
        self,
        base_image: str = "python:3.11-slim",
        entrypoint_cmd: str = "python3 src/app.py",
        expose_port: int = 8000,
    ) -> str:
        """Generates standard non-root customer Dockerfile with health checks."""
        cmd_parts = json.dumps(entrypoint_cmd.split())
        return f"""FROM {base_image}

WORKDIR /app

# Create non-root application user
RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY config/requirements.txt /app/config/
RUN pip install --no-cache-dir -r /app/config/requirements.txt

COPY src/ /app/src/
COPY config/ /app/config/
COPY artifacts/ /app/artifacts/

# Note: Persistent customer runtime data is mounted at runtime via volume, not baked into the image
RUN mkdir -p /app/data/logs /app/data/config /app/data/state /app/data/workspace && chown -R appuser:appuser /app

USER appuser

EXPOSE {expose_port}

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \\
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{expose_port}/health').read()" || exit 1

CMD {cmd_parts}
"""

    def build_deploy_command(self) -> str:
        """Generates double-clickable macOS Deploy.command launcher with error propagation."""
        return """#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
[ -f deploy.sh ] && chmod +x deploy.sh
[ -f manage.sh ] && chmod +x manage.sh
for s in scripts/*.sh; do [ -f "$s" ] && chmod +x "$s"; done
./deploy.sh
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "Deployment failed with exit code $EXIT_CODE."
fi
echo ""
read -p "Press [Enter] to exit..."
exit $EXIT_CODE
"""

    def build_deploy_sh(self, spec: CustomerDeploymentSpec) -> str:
        """Generates POSIX deploy.sh supporting containerized and local modes with health verification."""
        assert_target_supported(spec.target)
        port = spec.get_primary_port()
        host = spec.get_primary_host()
        data_dirs_str = " ".join(spec.data_directories) if spec.data_directories else "data/logs data/config"
        title = spec.project_name.upper()

        return f"""#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$DIR"

echo "============================================================"
echo "   CUSTOMER APPLICATION DEPLOYMENT — {title}"
echo "============================================================"

MODE="docker"
if [ "$1" == "--local" ]; then
    MODE="local"
fi

# 1. Initialize persistent storage partitions
mkdir -p {data_dirs_str}

# 2. Check configuration
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "Creating .env from .env.example..."
        cp .env.example .env
    fi
fi

if [ -f ".env" ]; then
    set -a
    . ./.env
    set +a
fi

PORT="${{PORT:-{port}}}"
HOST="${{HOST:-{host}}}"

# 3. Check deployment target
if [ "$MODE" == "docker" ]; then
    if ! command -v docker &> /dev/null; then
        echo "NOTICE: Docker was not found on this system."
        echo "Falling back to direct local Python deployment..."
        echo "No customer data was modified."
        MODE="local"
    fi
fi

if [ "$MODE" == "docker" ]; then
    echo "Checking Docker daemon status..."
    if ! docker info &> /dev/null; then
        echo "NOTICE: Docker daemon is not running."
        echo "Falling back to direct local Python deployment..."
        MODE="local"
    else
        echo "✓ Docker environment detected."
        echo "Starting containerized services via Docker Compose..."
        docker compose up -d --build
        echo "Waiting for services to become healthy..."
        sleep 3
    fi
fi

if [ "$MODE" == "local" ]; then
    echo "Running in local execution mode..."
    if [ ! -d ".venv" ]; then
        echo "Initializing local virtual environment..."
        if ! python3 -m venv .venv; then
            echo "ERROR: Failed to initialize virtual environment." >&2
            exit 1
        fi
    fi
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi
    
    if [ -f "config/requirements.txt" ]; then
        echo "Installing required dependencies..."
        if ! pip install -q -r config/requirements.txt; then
            echo "ERROR: Failed to install required dependencies." >&2
            exit 1
        fi
    fi
    
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo "Service is already running on port $PORT."
    else
        echo "Starting application in background (logs: data/logs/application.log)..."
        nohup python3 src/app.py > data/logs/application.log 2>&1 &
        echo $! > data/app.pid
        sleep 2
    fi
fi

# 4. Perform health verification
echo "Verifying deployment health..."
HEALTH_PASSED=0
if [ -f "scripts/health_check.py" ]; then
    if python3 scripts/health_check.py; then
        HEALTH_PASSED=1
    fi
elif [ -f "src/health.py" ]; then
    if python3 src/health.py; then
        HEALTH_PASSED=1
    fi
else
    # Verify port is listening
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        HEALTH_PASSED=1
    fi
fi

if [ "$HEALTH_PASSED" -eq 1 ]; then
    echo "============================================================"
    echo "   APPLICATION READY"
    echo "============================================================"
    echo "Application URL:  http://$HOST:$PORT"
    echo "Data Directory:   $DIR/data/"
    echo "Logs Directory:   $DIR/data/logs/"
    echo "Management CLI:   ./manage.sh [start|stop|restart|status|logs]"
    echo "============================================================"
    if [ "${{AUTO_OPEN_BROWSER:-true}}" == "true" ]; then
        if command -v open &> /dev/null; then
            open "http://$HOST:$PORT" 2>/dev/null
        elif command -v xdg-open &> /dev/null; then
            xdg-open "http://$HOST:$PORT" 2>/dev/null
        fi
    fi
else
    echo "============================================================"
    echo "   DEPLOYMENT FAILED — HEALTH GATES DID NOT PASS"
    echo "============================================================"
    echo "Check application logs for details: $DIR/data/logs/application.log"
    exit 1
fi
"""

    def build_deploy_bat(self, spec: CustomerDeploymentSpec) -> str:
        """Generates Windows Deploy.bat launcher."""
        port = spec.get_primary_port()
        dirs = [d.replace("/", "\\") for d in spec.data_directories] if spec.data_directories else ["data\\logs"]
        mkdir_lines = "\n".join(f"if not exist {d} mkdir {d}" for d in dirs)
        title = spec.project_name.upper()

        return f"""@echo off
echo ============================================================
echo    CUSTOMER APPLICATION DEPLOYMENT — {title}
echo ============================================================
cd /d "%~dp0"
{mkdir_lines}

if not exist .env (
    if exist .env.example copy .env.example .env
)

where docker >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo Docker detected. Starting Docker Compose...
    docker compose up -d --build
) else (
    echo Docker not found. Starting local Python service...
    if exist config\\requirements.txt python -m pip install -q -r config\\requirements.txt
    start /B python src\\app.py
)

timeout /t 3 /nobreak >nul
if exist scripts\\health_check.py python scripts\\health_check.py
start http://127.0.0.1:{port}
pause
"""

    def build_manage_sh(self, spec: CustomerDeploymentSpec) -> str:
        """Generates universal customer lifecycle management CLI."""
        primary_svc = spec.primary_service or "app"
        return f"""#!/usr/bin/env bash
DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$DIR"

ACTION="${{1:-status}}"
PORT="${{PORT:-{spec.get_primary_port()}}}"

case "$ACTION" in
    start)
        ./deploy.sh
        ;;
    stop)
        echo "Stopping customer application..."
        if command -v docker &> /dev/null && [ -f "docker-compose.yml" ]; then
            if ! docker compose down 2>/dev/null; then
                echo "Notice: docker compose down exited or services already stopped." >&2
            fi
        fi
        for pid_file in data/*.pid; do
            if [ -f "$pid_file" ]; then
                PID=$(cat "$pid_file")
                if kill -0 "$PID" 2>/dev/null; then
                    if ! kill -15 "$PID" 2>/dev/null; then
                        kill -9 "$PID" 2>/dev/null || echo "Notice: process $PID already exited." >&2
                    fi
                fi
                rm -f "$pid_file"
            fi
        done
        echo "✓ All services stopped."
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        echo "Checking application status..."
        python3 scripts/health_check.py 2>/dev/null || python3 src/health.py 2>/dev/null || echo "Service not responding."
        ;;
    logs)
        if [ -f "data/logs/application.log" ]; then
            tail -f -n 50 data/logs/application.log
        elif command -v docker &> /dev/null; then
            docker compose logs -f {primary_svc}
        else
            echo "No logs found in data/logs/application.log"
        fi
        ;;
    *)
        echo "Usage: ./manage.sh {{start|stop|restart|status|logs}}"
        exit 1
        ;;
esac
"""

    def build_manifest(self, spec: CustomerDeploymentSpec) -> Dict[str, Any]:
        """Generates machine-readable deployment manifest dictionary."""
        ports_dict = {}
        for s_name, svc in spec.services.items():
            if svc.ports:
                ports_dict[s_name] = svc.ports[0].host_port

        manifest: Dict[str, Any] = {
            "deployment_version": spec.deployment_version,
            "project_name": spec.project_name,
            "target": spec.target.value,
            "services": list(spec.services.keys()),
            "primary_service": spec.primary_service,
            "persistent_storage": spec.persistent_storage,
            "private_networking": spec.private_networking,
            "health_checks": bool(spec.health_checks),
            "ports": ports_dict,
            "data_directories": spec.data_directories,
        }

        # Include any workload-specific metadata
        for k, v in spec.metadata.items():
            manifest[k] = v

        return manifest

    def build_env_files(self, spec: CustomerDeploymentSpec) -> Tuple[str, str]:
        """
        Generates .env.example and .env strings.
        Ensures secrets are not hardcoded in templates.
        """
        header = [
            "# ============================================================",
            f"# Customer Application Environment Configuration",
            f"# Project: {spec.project_name}",
            "# ============================================================",
            f"HOST={spec.get_primary_host()}",
            f"PORT={spec.get_primary_port()}",
            f"AUTO_OPEN_BROWSER={str(spec.auto_open_browser).lower()}",
        ]

        for k, v in spec.global_environment.items():
            header.append(f"{k}={v}")

        env_content = (
            "# NOTICE: This file contains local runtime configuration.\n"
            "# DO NOT commit this file to version control.\n"
            + "\n".join(header)
            + "\n"
        )

        SENSITIVE_KEYWORDS = ("SECRET", "KEY", "TOKEN", "PASS", "AUTH", "CREDENTIAL")
        example_lines = [
            "# ============================================================",
            f"# Customer Application Environment Template (.env.example)",
            f"# Copy to .env and configure appropriate values",
            "# ============================================================",
        ]
        for line in header[4:]:
            if "=" in line:
                k, v = line.split("=", 1)
                k_upper = k.upper()
                if any(kw in k_upper for kw in SENSITIVE_KEYWORDS):
                    example_lines.append(f"{k}=your_{k.lower()}_here")
                else:
                    example_lines.append(line)
            else:
                example_lines.append(line)

        env_example = "\n".join(example_lines) + "\n"
        return env_example, env_content
