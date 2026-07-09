"""
OpenClaw on Amazon Bedrock AgentCore Runtime — Strands SDK Wrapper

Thin wrapper that bridges AgentCore invocations to the OpenClaw gateway
running on the same machine via WebSocket.
"""

import asyncio
import json
import os
import uuid

import websockets
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

OPENCLAW_PORT = int(os.environ.get("OPENCLAW_PORT", "18789"))
OPENCLAW_WS = f"ws://127.0.0.1:{OPENCLAW_PORT}"
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")


async def invoke_openclaw(message: str, session_key: str = "agentcore") -> str:
    """Bridge a prompt to the OpenClaw gateway via its WebSocket protocol."""
    async with websockets.connect(OPENCLAW_WS, open_timeout=10) as ws:
        # 1. Wait for connect.challenge event
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        challenge = json.loads(raw)
        if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
            raise RuntimeError(f"Expected connect.challenge, got: {challenge}")

        # 2. Authenticate with connect request
        connect_id = str(uuid.uuid4())
        await ws.send(json.dumps({
            "type": "req",
            "id": connect_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {"id": "agentcore-strands-wrapper", "mode": "backend", "version": "1.0.0"},
                "auth": {"token": GATEWAY_TOKEN} if GATEWAY_TOKEN else {},
                "role": "operator",
                "scopes": ["operator.admin", "operator.read", "operator.write"],
            },
        }))

        # Wait for connect response
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        connect_res = json.loads(raw)
        if connect_res.get("type") == "res" and not connect_res.get("ok", True):
            raise RuntimeError(f"Connect failed: {connect_res}")

        # 3. Send agent request (runs a full agent turn)
        agent_id = str(uuid.uuid4())
        await ws.send(json.dumps({
            "type": "req",
            "id": agent_id,
            "method": "agent",
            "params": {
                "message": message,
                "sessionKey": session_key,
                "idempotencyKey": agent_id,
                "timeout": 120,
            },
        }))

        # 4. Wait for the response (may receive events before final response)
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=130)
            msg = json.loads(raw)
            if msg.get("type") == "res" and msg.get("id") == agent_id:
                payload = msg.get("payload", {})
                return payload.get("reply", payload.get("response", ""))

    return ""


@app.entrypoint
def invoke(payload):
    """AgentCore invocation handler — bridges to OpenClaw gateway."""
    prompt = payload.get("prompt", payload.get("message", "Hello"))
    session_key = payload.get("session_id", "agentcore-default")

    result = asyncio.run(invoke_openclaw(prompt, session_key))
    return {"result": result}


if __name__ == "__main__":
    app.run()
