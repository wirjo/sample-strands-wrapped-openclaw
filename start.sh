#!/bin/bash
# start.sh — Start OpenClaw gateway daemon, then launch Strands wrapper
set -euo pipefail

echo "[openclaw-agentcore] Starting OpenClaw on AgentCore Runtime..."

# Start OpenClaw gateway in background (bundled binary)
if [ -x "./openclaw/node" ]; then
    # Static zip deployment — use bundled Node.js + OpenClaw
    echo "[openclaw-agentcore] Using bundled OpenClaw binary"
    ./openclaw/node ./openclaw/node_modules/openclaw/openclaw.mjs gateway run --port ${OPENCLAW_PORT:-18789} &
elif command -v openclaw &>/dev/null; then
    # Container deployment — OpenClaw installed globally
    echo "[openclaw-agentcore] Using system OpenClaw"
    openclaw gateway run --port ${OPENCLAW_PORT:-18789} &
else
    echo "[openclaw-agentcore] ERROR: OpenClaw not found"
    exit 1
fi

OPENCLAW_PID=$!

# Wait for gateway to be healthy
echo "[openclaw-agentcore] Waiting for OpenClaw gateway..."
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:${OPENCLAW_PORT:-18789}/health > /dev/null 2>&1; then
        echo "[openclaw-agentcore] Gateway ready (took ${i}s)"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "[openclaw-agentcore] ERROR: Gateway failed to start within 60s"
        exit 1
    fi
    sleep 1
done

# Start the Strands wrapper (serves AgentCore contract on :8080)
echo "[openclaw-agentcore] Starting AgentCore wrapper on :8080"
exec python main.py
