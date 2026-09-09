#!/bin/bash
# 18-G Run 7 launcher: single real subsystem, production engine, real Maven + live app.
set -u
REPO="/Users/kalachanddash/Documents/AutoForge AI"
export JAVA_HOME="/opt/homebrew/Cellar/openjdk/26.0.2.1/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:/opt/homebrew/bin:/usr/bin:/bin"
export AUTOFORGE_M1_OLLAMA_URL="${AUTOFORGE_M1_OLLAMA_URL:-http://127.0.0.1:11434}"
export AUTOFORGE_HP_OLLAMA_URL="${AUTOFORGE_HP_OLLAMA_URL:-http://192.168.1.102:11434}"
export AUTOFORGE_QDRANT_URL="${AUTOFORGE_QDRANT_URL:-http://192.168.1.102:6333}"
export PYTHONPATH="$REPO/packages/modernization/src:$REPO/packages/kernel/src:$REPO/packages/knowledge_platform/src:$REPO/packages/ai_infrastructure/src:$REPO/packages/workforce/src"
cd "$REPO/packages/modernization/evidence" || exit 1
exec python3 run_18g_entry_d.py "$@"
