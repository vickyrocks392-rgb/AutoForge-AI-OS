# Custom AI Agent Deliverable — Production Deployment & Operational Runbook

**Audience:** Platform Engineers, Site Reliability Engineers, and Customer Operations Teams  
**Capability:** Custom AI Agent Deliverable (`autoforge_power_engines.agent`)  
**Specification Version:** AutoForge AI-OS Phase 20-C Gate 4 Production Runbook  
**Target Workload:** Standalone Customer AI Agent (FastAPI / SQLite / AST Math / Sandboxed Tools)  
**Approved Inference Authority:** Local MLX HTTP Endpoint (`http://127.0.0.1:19801/v1`) with Model `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2`  

---

## 1. Prerequisites and Supported Environment

### Supported Platforms
- **Host OS:** macOS (Darwin 23+ arm64 / Apple Silicon recommended) or Enterprise Linux (RHEL 9+, Ubuntu 22.04 LTS / 24.04 LTS x86_64 or aarch64).
- **Python Runtime:** Python 3.10, 3.11, or 3.12 (standard virtual environment).
- **Container Runtime (Optional):** Docker Engine 24+ and Docker Compose v2 (if running in containerized mode).
- **Inference Authority:** Local MLX OpenAI-compatible HTTP daemon listening on `127.0.0.1:19801` with approved model `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2`.

### Forbidden Configurations (Fail-Closed)
- Prohibited inference providers: Ollama (`11434`), M1 node, HP node, and unapproved remote cloud inference endpoints.
- Root container execution: The container MUST execute as unprivileged user (`appuser`, UID 1000).
- Publicly bound ports: Internal inference ports and container API ports must bind to loopback (`127.0.0.1`) only.

---

## 2. Configuration & Secrets Provisioning

The customer application is configured via environment variables and `config/settings.json`.

### Environment Template (`.env.example`)
```bash
# ============================================================
# Customer Application Environment Template (.env.example)
# Copy to .env and configure appropriate values
# ============================================================
HOST=127.0.0.1
PORT=8000
AUTO_OPEN_BROWSER=true
MODEL_PROVIDER=generic_http
MODEL_NAME=mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2
LLM_BASE_URL=http://127.0.0.1:19801/v1
MAX_ITERATIONS=10
MAX_TOOL_CALLS=5
REQUEST_TIMEOUT=120
MEMORY_ENABLED=true
```

### Pre-flight Validation Semantics
Configuration validation occurs strictly at process initialization (`src/config.py:load_settings()`) before serving any incoming requests:
1. `MODEL_PROVIDER`: Must equal `"generic_http"`. Specifying `"ollama"` or any other unapproved provider immediately raises `ValueError`.
2. `PORT`: Must parse to an integer in the range `1..65535`.
3. `MAX_ITERATIONS`: Must be an integer `>= 1`.
4. `MAX_TOOL_CALLS`: Must be an integer `>= 1`.
5. `REQUEST_TIMEOUT`: Must be a positive float `> 0.0`.
6. `LLM_BASE_URL`: Must begin with `http://` or `https://` and must not target port `11434` (Ollama port).

*Secrets Handling:* No plain credentials, API keys, or private keys are baked into the code, image layers, or manifests. The `.env` file should be restricted (`chmod 600 .env`) and excluded from version control (`.gitignore`).

---

## 3. Build & Package Verification

When receiving the distribution archive `delivery-<hash>.tar.gz`:

### A. Checksum Verification (Tested Command)
```bash
# Verify the archive integrity against its SHA-256 checksum
shasum -a 256 delivery-*.tar.gz
```

### B. Extraction & Integrity Check (Tested Command)
```bash
# Extract into dedicated target directory
mkdir -p /opt/customer_agent
tar -xzf delivery-*.tar.gz -C /opt/customer_agent
cd /opt/customer_agent

# Verify presence of all essential deployment artifacts
ls -la Dockerfile docker-compose.yml deploy.sh manage.sh .env.example config/
```

### C. Execute Internal Customer Test Suite (Tested Command)
```bash
# Run the self-contained regression tests before starting the service
python3 -m unittest discover -s tests -p "test_*.py" -v
```

---

## 4. Startup & Readiness Checks

The customer deliverable includes standard launchers supporting both native process and containerized execution.

### Native Host Process Mode (Tested Commands)
```bash
# Initialize persistent partitions and start application in background
./manage.sh start
# or manually:
./deploy.sh --local
```

### Containerized Deployment Mode (Illustrative Command — Requires Docker)
```bash
# If Docker Engine is installed and active on the host:
docker compose up -d --build
```

### Verification of Service Liveness & Readiness (Tested Commands)
```bash
# 1. Liveness Probe (HTTP 200 confirms web process is alive)
curl -s http://127.0.0.1:8000/health | jq .

# Expected Liveness Output:
# {
#   "status": "healthy",
#   "liveness": "alive",
#   "project_name": "Apex-FinOps-Agent",
#   "model_provider": "generic_http",
#   "model_name": "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2",
#   "allowed_tools": ["calculator", "file_read", "document_lookup"]
# }

# 2. Readiness Probe (HTTP 200 confirms storage writable and MLX inference reachable)
curl -s http://127.0.0.1:8000/health/ready | jq .

# Expected Output when Ready:
# {
#   "status": "ready",
#   "liveness": "alive",
#   "inference": "available",
#   "storage": "writable"
# }

# If MLX inference endpoint is offline, /health/ready returns HTTP 503 Service Unavailable:
# {
#   "status": "not_ready",
#   "liveness": "alive",
#   "inference": "unavailable",
#   "storage": "writable",
#   "detail": "Inference endpoint unreachable"
# }
```

### Unified Deployment Health Harness (Tested Command)
```bash
# Runs full health verification across storage, configuration, and inference
python3 scripts/health_check.py
```

---

## 5. Approved Inference Endpoint Connectivity

### Host-to-MLX Connectivity (Tested Command)
The MLX inference service runs on the local host listening on port 19801:
```bash
curl -s http://127.0.0.1:19801/v1/models | jq .
```
Verify that `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2` appears in the returned models list.

### Container-to-Host Inference Connectivity (Docker Context)
Inside Docker containers, `127.0.0.1` refers to the container itself. To connect to the host's MLX daemon safely:
- The Compose configuration defines:
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  environment:
    - LLM_BASE_URL=http://host.docker.internal:19801/v1
  ```
- This bridges container egress to the host machine without binding MLX to public interfaces or running the container with `--net=host`.

---

## 6. Safe Smoke-Test Procedure

After verifying readiness, perform a single-turn and multi-turn smoke test:

### A. Health & Status Probe (Tested Command)
```bash
curl -s http://127.0.0.1:8000/status | jq .
```

### B. Single-Turn Agent Chat Request (Tested Command)
```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Calculate total corporate expense: 14500 + 32500 - 4200", "session_id": "smoke-test-001"}' | jq .
```
Verify that:
- Response returns status `"completed"` or `"verifying"`.
- Tool execution trace shows `calculator` was invoked with duration and clean result `42800`.
- The final response answers the user request accurately.

### C. Multi-Turn Session Memory Retention Test (Tested Command)
```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Now divide that result by 4", "session_id": "smoke-test-001"}' | jq .
```
Verify that the agent retains context from `smoke-test-001` and computes `10700`.

---

## 7. Log Inspection & Troubleshooting

Application logs are written to both standard output and `data/logs/application.log`.

### Inspecting Live Logs (Tested Command)
```bash
tail -f -n 100 data/logs/application.log
```

### Log Format and Correlation Identifiers
Operational log lines follow the structured format:
```
2026-10-16 00:45:10,123 [INFO] [agent.service] [STARTUP] Service initialized: project=Apex-FinOps-Agent provider=generic_http port=8000
2026-10-16 00:45:12,456 [INFO] [agent.service] [REQUEST] correlation_id=req-7a8b9c1d session_id=smoke-test-001 endpoint=/chat
2026-10-16 00:45:12,789 [INFO] [agent.service] [TOOL_OUTCOME] correlation_id=req-7a8b9c1d tool=calculator duration_ms=1.2 status=SUCCESS
2026-10-16 00:45:13,012 [INFO] [agent.service] [EXECUTION] correlation_id=req-7a8b9c1d status=completed iterations=2 tools=1 latency_ms=556.0
2026-10-16 00:46:00,000 [INFO] [agent.service] [SHUTDOWN] Service shutting down; flushing memory connections.
```

### Common Issues & Diagnostic Resolutions
| Symptom | Probable Cause | Action |
|---|---|---|
| `HTTP 503: Inference endpoint unreachable` | MLX daemon not running on port 19801 | Start MLX server or verify `LLM_BASE_URL` in `.env` |
| `HTTP 503: Storage partition unwritable` | Permissions on `./data/` are restrictive | Run `chmod -R u+rwX ./data/` |
| Process exits on startup with `ValueError` | Prohibited provider (e.g. `ollama`) or invalid port in `.env` | Correct `.env` to use `MODEL_PROVIDER=generic_http` |
| Port conflict on start (`Address already in use`) | Existing process listening on configured port | Stop existing process via `./manage.sh stop` or change `PORT` in `.env` |

---

## 8. Graceful Shutdown

### Stopping Local Process (Tested Command)
```bash
./manage.sh stop
```
The script reads `data/app.pid`, sends `SIGTERM` (`kill -15`), waits for the application to flush SQLite write-ahead logs, and cleans up the PID file.

### Stopping Container Deployment (Illustrative Command — Requires Docker)
```bash
docker compose down
```

---

## 9. Restart & Recovery

### Standard Restart (Tested Command)
```bash
./manage.sh restart
```

### Recovery from Unclean Host Termination
If the host terminates unexpectedly:
1. Verify `data/state/conversations.db` SQLite integrity:
   ```bash
   sqlite3 data/state/conversations.db "PRAGMA integrity_check;"
   ```
2. Remove any stale PID file:
   ```bash
   rm -f data/*.pid
   ```
3. Start the application:
   ```bash
   ./manage.sh start
   ```

---

## 10. SQLite & Workspace Backup and Restore

### Backup Procedure (Tested Commands)
```bash
# 1. Ensure backup destination exists
BACKUP_DIR="/opt/backups/agent_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# 2. Use SQLite online backup API or safe backup command (prevents WAL tearing)
sqlite3 data/state/conversations.db ".backup '$BACKUP_DIR/conversations.db'"

# 3. Snapshot configuration and workspace data
cp -r config "$BACKUP_DIR/config"
cp -r data/workspace "$BACKUP_DIR/workspace"

echo "Backup completed successfully at $BACKUP_DIR"
```

### Restore Procedure (Tested Commands)
```bash
# 1. Stop application before restoring state
./manage.sh stop

# 2. Restore database and workspace
cp "$BACKUP_DIR/conversations.db" data/state/conversations.db
cp -r "$BACKUP_DIR/workspace/"* data/workspace/
cp -r "$BACKUP_DIR/config/"* config/

# 3. Restart application and verify health
./manage.sh start
python3 scripts/health_check.py
```

---

## 11. Upgrade & Rollback Procedure

### Zero-Data-Loss Upgrade Process
1. Stop running service: `./manage.sh stop`.
2. Take a full snapshot of `./data/` and `./config/`.
3. Extract new deliverable package code into application directory without overwriting `data/`.
4. Run regression tests in the new directory: `python3 -m unittest discover -s tests`.
5. Start service: `./manage.sh start`.
6. Verify readiness: `curl -s http://127.0.0.1:8000/health/ready`.

### Rollback Process
1. Stop updated service: `./manage.sh stop`.
2. Restore previous code version.
3. Restore database from pre-upgrade backup if schema migrations were applied.
4. Restart previous service: `./manage.sh start`.

*Data Preservation Guarantee:* Neither deploy nor rollback scripts delete existing customer databases or workspace documents.

---

## 12. Data Retention and Deletion Boundaries

### Storage Partitions
- `data/state/`: SQLite database `conversations.db` storing session IDs, conversation history, and agent state transitions.
- `data/workspace/`: Sandboxed customer document storage for document reading and report writing.
- `data/logs/`: Structured application logs with automatic correlation IDs.

### Retention & Purge Procedures
To purge session history while retaining application deployment:
```bash
# Stop application
./manage.sh stop

# Purge session records older than 30 days via SQL
sqlite3 data/state/conversations.db "DELETE FROM messages WHERE timestamp < datetime('now', '-30 days'); VACUUM;"

# Restart application
./manage.sh start
```

---

## 13. Security Limitations & Incident Response Basics

### Known Operational Boundaries
1. **Container Is Not a Complete Sandbox:** Docker containers provide process and resource isolation, but kernel exploits can escape unhardened containers. The deliverable drops all Linux capabilities (`cap_drop: [ALL]`), enables `no-new-privileges`, runs as non-root `appuser`, and binds ports to loopback.
2. **SSRF Guardrails:** Outbound HTTP tools block private RFC1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopbacks (`127.0.0.1`, `localhost`), and cloud metadata (`169.254.169.254`).
3. **AST Expression Evaluation:** Arithmetic expressions are parsed into Python AST and evaluated strictly against mathematical operators and constants (`sqrt`, `abs`, `sin`, `cos`, `pi`). Dynamic code execution (`eval`, `exec`, `__import__`) is strictly blocked.

### Incident Response Runbook
1. **Suspicious Activity Detected:** Immediately stop the service (`./manage.sh stop`).
2. **Triage Logs:** Inspect `data/logs/application.log` for error correlation IDs, suspicious inputs, or attempted path traversals.
3. **Verify Confinement:** Confirm that files outside `data/workspace` remain unmodified using filesystem checksums.
4. **Isolate Persistence:** Archive `data/` for forensics and contact the AutoForge security response team.
