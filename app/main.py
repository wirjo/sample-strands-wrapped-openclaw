"""
OpenClaw on Amazon Bedrock AgentCore Runtime — Strands SDK Wrapper

Thin wrapper that bridges AgentCore invocations to the OpenClaw gateway
running on the same machine via WebSocket.

Architecture:
- Python starts immediately on :8080 (AgentCore contract)
- OpenClaw gateway boots in a background thread on :18789
- First invocation waits for gateway to be ready (lazy init)
"""

import asyncio
import json
import os
import subprocess
import threading
import time
import uuid

import websockets
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

OPENCLAW_PORT = int(os.environ.get("OPENCLAW_PORT", "18789"))
OPENCLAW_WS = f"ws://127.0.0.1:{OPENCLAW_PORT}"
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

# Gateway state
_gateway_process = None
_gateway_ready = threading.Event()
_gateway_error = None


def _start_gateway():
    """Start OpenClaw gateway in background and wait for it to be healthy."""
    global _gateway_process, _gateway_error

    print("[openclaw-agentcore] Starting OpenClaw gateway...", flush=True)

    try:
        # Find openclaw binary
        import shutil
        openclaw_bin = shutil.which("openclaw")
        if not openclaw_bin:
            _gateway_error = "OpenClaw binary not found"
            print(f"[openclaw-agentcore] ERROR: {_gateway_error}", flush=True)
            return

        # Start gateway process
        _gateway_process = subprocess.Popen(
            [openclaw_bin, "gateway", "--port", str(OPENCLAW_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print(f"[openclaw-agentcore] Gateway process started (pid={_gateway_process.pid})", flush=True)

        # Wait for health check
        import urllib.request
        for i in range(120):  # Wait up to 120 seconds
            try:
                req = urllib.request.urlopen(f"http://127.0.0.1:{OPENCLAW_PORT}/health", timeout=2)
                if req.status == 200:
                    print(f"[openclaw-agentcore] Gateway ready (took {i+1}s)", flush=True)
                    _gateway_ready.set()
                    return
            except Exception:
                pass

            # Check if process died
            if _gateway_process.poll() is not None:
                output = _gateway_process.stdout.read() if _gateway_process.stdout else ""
                _gateway_error = f"Gateway process exited with code {_gateway_process.returncode}: {output[:500]}"
                print(f"[openclaw-agentcore] ERROR: {_gateway_error}", flush=True)
                return

            time.sleep(1)

        _gateway_error = "Gateway failed to become healthy within 120s"
        print(f"[openclaw-agentcore] ERROR: {_gateway_error}", flush=True)

    except Exception as e:
        _gateway_error = str(e)
        print(f"[openclaw-agentcore] ERROR starting gateway: {e}", flush=True)


# Start gateway in background thread immediately
_gateway_thread = threading.Thread(target=_start_gateway, daemon=True)
_gateway_thread.start()


async def invoke_openclaw(message: str, session_key: str = "agentcore") -> str:
    """Bridge a prompt to the OpenClaw gateway via its WebSocket protocol."""
    # Wait for gateway to be ready (blocks on first call)
    if not _gateway_ready.wait(timeout=120):
        return f"Error: OpenClaw gateway failed to start: {_gateway_error or 'timeout'}"

    try:
        async with websockets.connect(OPENCLAW_WS, open_timeout=10) as ws:
            # 1. Wait for connect.challenge event
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            challenge = json.loads(raw)
            if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
                return f"Error: Expected connect.challenge, got: {challenge}"

            # 2. Authenticate with connect request
            connect_id = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "req",
                "id": connect_id,
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 4,
                    "client": {"id": "gateway-client", "mode": "backend", "version": "1.0.0", "platform": "agentcore"},
                    "auth": {"token": GATEWAY_TOKEN} if GATEWAY_TOKEN else {},
                    "role": "operator",
                    "scopes": ["operator.admin", "operator.read", "operator.write"],
                },
            }))

            # Wait for connect response
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            connect_res = json.loads(raw)
            if connect_res.get("type") == "res" and connect_res.get("error"):
                return f"Error: Connect failed: {connect_res.get('error')}"

            # 3. Send agent request (runs a full agent turn)
            agent_id = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "req",
                "id": agent_id,
                "method": "agent",
                "params": {
                    "message": message,
                    "sessionKey": f"agent:main:{session_key}",
                    "idempotencyKey": agent_id,
                    "timeout": 120,
                },
            }))

            # 4. Wait for the accepted response, then listen for completion
            run_id = None
            collected_text = ""

            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=130)
                msg = json.loads(raw)
                msg_type = msg.get("type")

                # Response to our agent request (accepted/error)
                if msg_type == "res" and msg.get("id") == agent_id:
                    payload = msg.get("payload", {})
                    error = msg.get("error")
                    if error:
                        return f"Error: Agent request failed: {error}"
                    run_id = payload.get("runId")
                    status = payload.get("status")
                    if status != "accepted":
                        # Direct response (non-async)
                        result = payload.get("result", {})
                        text = result.get("text", payload.get("reply", payload.get("text", "")))
                        if text:
                            return text
                        return str(payload)
                    # Accepted — keep listening for the completion event
                    continue

                # Stream events from the agent run
                if msg_type == "event":
                    event_name = msg.get("event", "")
                    data = msg.get("data", {})

                    # agent.delta — streaming text chunks
                    if event_name == "agent.delta":
                        chunk = data.get("text", data.get("delta", ""))
                        collected_text += chunk
                        continue

                    # agent.done / run.completed — final response
                    if event_name in ("agent.done", "run.completed", "agent.completed"):
                        # Try to get the final text from the event data
                        final_text = data.get("text", data.get("reply", ""))
                        if final_text:
                            return final_text
                        # Fall back to messages array
                        messages = data.get("messages", [])
                        if messages:
                            last = messages[-1]
                            content = last.get("content", "")
                            if isinstance(content, list):
                                # Extract text parts
                                return "".join(
                                    p.get("text", "") for p in content
                                    if isinstance(p, dict) and p.get("type") == "text"
                                )
                            return str(content)
                        # Fall back to collected streaming text
                        if collected_text:
                            return collected_text
                        return str(data) if data else "Agent completed with no response."

                    # run.error — agent failed
                    if event_name in ("run.error", "agent.error"):
                        return f"Error: Agent run failed: {data.get('error', data.get('message', str(data)))}"

                    # Other events — skip
                    continue

            # If we exit the loop without a response, return what we collected
            if collected_text:
                return collected_text
            return "No response received from agent."

    except Exception as e:
        return f"Error invoking OpenClaw: {e}"


@app.entrypoint
def invoke(payload):
    """AgentCore invocation handler — bridges to OpenClaw gateway."""
    prompt = payload.get("prompt", payload.get("message", "Hello"))
    session_key = payload.get("session_id", "agentcore-default")

    result = asyncio.run(invoke_openclaw(prompt, session_key))
    return {"result": result}


if __name__ == "__main__":
    print("[openclaw-agentcore] Starting AgentCore wrapper on :8080", flush=True)
    app.run()
