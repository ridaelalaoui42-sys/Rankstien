#!/usr/bin/env bash
# RankStein Unified Production Runner
# Ensures clean environment, proxy readiness, and full pipeline execution

export PROJECT_ROOT="/c/Users/REDX420/Desktop/Rankstein"
export VENV_PYTHON="$PROJECT_ROOT/.venv/Scripts/python.exe"
export PROXY_URL="http://127.0.0.1:8000/gemini/v1/chat/completions"
export RANKSTEIN_GEMINI_PROXY_URL="$PROXY_URL"

# 1. Clean environment to prevent SRE module mismatch
unset PYTHONHOME
unset UV_INTERNAL__PYTHONHOME

cd "$PROJECT_ROOT"

echo "[1/4] Ensuring Odysseus Proxy is alive..."
if ! curl -s -m 5 "$PROXY_URL/health" > /dev/null; then
    echo "Starting proxy..."
    "$VENV_PYTHON" ody_proxy.py > data/logs/proxy.log 2>&1 &
    sleep 5
fi

if ! curl -s -m 5 "$PROXY_URL/health" > /dev/null; then
    echo "ERROR: Proxy failed to start. Check data/logs/proxy.log"
    exit 1
fi
echo "Proxy OK."

echo "[2/4] Running Content Generation (Turbo mode)..."
"$VENV_PYTHON" backend/scripts/turbo_articles.py --domain recetagenial --workers 1 --limit 5 --once

echo "[3/4] Running Verification and Publication..."
"$VENV_PYTHON" rankstein.py run --verify-and-publish --domain recetagenial

echo "[4/4] Starting Pinterest Distribution..."
"$VENV_PYTHON" run_autonomous.py run --once

echo "Pipeline execution complete."
