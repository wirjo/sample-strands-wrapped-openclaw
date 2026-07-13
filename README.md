# Sample: Deploy OpenClaw on Amazon Bedrock AgentCore Runtime

Deploy [OpenClaw](https://openclaw.ai) as a serverless agent on [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/) using a lightweight [Strands SDK](https://strandsagents.com/) wrapper.

## How It Works

```
┌───────────────────────────────────────────────────────────────┐
│ AgentCore Runtime (microVM / static zip)                       │
│                                                               │
│  ┌────────────────────────┐     ┌──────────────────────────┐ │
│  │  main.py               │     │  OpenClaw Gateway        │ │
│  │  BedrockAgentCoreApp   │─WS─→│  (full agent engine)     │ │
│  │  :8080                 │←────│  :18789                  │ │
│  │  /invocations + /ping  │     │  tools/memory/MCP/skills │ │
│  └────────────────────────┘     └──────────────────────────┘ │
│           ↑                              ↑                    │
│           │ AgentCore                    │ Bedrock            │
│           │ Protocol                     │ (IAM role)         │
└───────────┼──────────────────────────────┼────────────────────┘
            │                              │
      Client Request                 Amazon Bedrock
```

**main.py** (~15 lines) is the only glue code. It:
1. Receives invocations from AgentCore on `:8080`
2. Forwards them to the OpenClaw gateway via WebSocket
3. Returns OpenClaw's response

**OpenClaw** does all the thinking — tools, memory, web search, code execution, MCP servers, skills.

## Prerequisites

- AWS account with Bedrock model access (Claude Sonnet 4.6)
- Python 3.11+
- [AgentCore CLI](https://github.com/aws/agentcore-cli): `npm install -g @aws/agentcore`
- AWS credentials configured (`aws sts get-caller-identity` should succeed)

## Quick Start

### 1. Clone

```bash
git clone https://github.com/wirjo/sample-strands-wrapped-openclaw.git
cd sample-strands-wrapped-openclaw
```

### 2. Configure

Edit `.openclaw/openclaw.json` to set your preferred model and region:

```json
{
  "models": {
    "providers": {
      "amazon-bedrock": {
        "baseUrl": "https://bedrock-runtime.us-east-1.amazonaws.com",
        "api": "bedrock-converse-stream",
        "auth": "aws-sdk",
        "models": [{ "id": "global.anthropic.claude-sonnet-4-6", "name": "Claude Sonnet 4.6" }]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": { "primary": "amazon-bedrock/global.anthropic.claude-sonnet-4-6" }
    }
  }
}
```

### 3. Test Locally

```bash
pip install -r requirements.txt

# Start OpenClaw gateway (requires Node.js 22+ and openclaw installed globally)
openclaw gateway run &

# Start the wrapper
python main.py

# Test
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is Amazon Bedrock AgentCore?"}'
```

### 4. Deploy to AgentCore

```bash
# Bundle OpenClaw + create deployment zip
bash scripts/deploy.sh

# Deploy via AgentCore CLI
agentcore deploy --artifact agent.zip
```

## Project Structure

```
.
├── main.py                     # Strands wrapper (BedrockAgentCoreApp → OpenClaw)
├── start.sh                    # Entrypoint: starts gateway + wrapper
├── requirements.txt            # Python dependencies
├── .openclaw/
│   ├── openclaw.json           # OpenClaw config (Bedrock provider, model, tools)
│   └── workspace/
│       └── AGENTS.md           # Agent instructions
├── openclaw/                   # Bundled binary (created by scripts/bundle-openclaw.sh)
│   ├── node                    # Node.js ARM64 binary
│   └── node_modules/openclaw/  # OpenClaw package
└── scripts/
    ├── bundle-openclaw.sh      # Download + bundle Node.js + OpenClaw
    └── deploy.sh               # Package zip + deploy
```

## Step-by-Step: How Strands Interfaces with OpenClaw

The integration has two layers: the **HTTP layer** (AgentCore → Strands) and the **WebSocket layer** (Strands → OpenClaw).

### End-to-End Request Flow

```
Client → AgentCore → :8080/invocations → main.py → ws://127.0.0.1:18789 → OpenClaw → Bedrock → Response
```

### Layer 1: AgentCore → Strands (HTTP)

**Step 1:** AgentCore sends an HTTP request to the container:

```http
POST /invocations HTTP/1.1
Host: localhost:8080
Content-Type: application/json
x-amzn-bedrock-agentcore-runtime-session-id: abc123

{"prompt": "What is Amazon Bedrock?"}
```

**Step 2:** `BedrockAgentCoreApp` (Strands SDK) receives this and calls our `@app.entrypoint` function with the payload:

```python
@app.entrypoint
def invoke(payload):
    # payload = {"prompt": "What is Amazon Bedrock?"}
    prompt = payload.get("prompt", "Hello")
    result = asyncio.run(invoke_openclaw(prompt))
    return {"result": result}
```

Strands handles all the HTTP plumbing — parsing, health checks (`/ping`), error responses.

### Layer 2: Strands → OpenClaw (WebSocket)

**Step 3:** Open a WebSocket connection to the OpenClaw gateway:

```python
async with websockets.connect("ws://127.0.0.1:18789") as ws:
```

OpenClaw's gateway listens on port 18789 (configurable). It uses a custom JSON-RPC-over-WebSocket protocol — not HTTP REST.

**Step 4:** Receive the `connect.challenge` event. The gateway immediately sends a challenge when a client connects:

```json
← { "type": "event", "event": "connect.challenge", "payload": { "nonce": "abc..." } }
```

**Step 5:** Authenticate by sending a `connect` request. This tells OpenClaw who we are:

```json
→ {
    "type": "req",
    "id": "uuid-1",
    "method": "connect",
    "params": {
      "minProtocol": 3,
      "maxProtocol": 4,
      "client": { "id": "gateway-client", "mode": "backend" },
      "auth": { "token": "gateway-token" },
      "role": "operator",
      "scopes": ["operator.admin", "operator.read", "operator.write"]
    }
  }
```

**Step 6:** Receive the connect response (authenticated):

```json
← { "type": "res", "id": "uuid-1", "ok": true, "payload": { ... } }
```

**Step 7:** Send the `agent` request. This is the key method — it runs a **full agent turn** inside OpenClaw:

```json
→ {
    "type": "req",
    "id": "uuid-2",
    "method": "agent",
    "params": {
      "message": "What is Amazon Bedrock?",
      "sessionKey": "agentcore-default",
      "idempotencyKey": "uuid-2",
      "timeout": 120
    }
  }
```

**What happens inside OpenClaw during this step:**
1. Loads session context (memory, conversation history)
2. Builds the system prompt (from AGENTS.md, workspace files)
3. Calls Amazon Bedrock (Claude Sonnet 4.6) via the configured provider
4. If the model requests tool calls → executes them (web search, code, files, etc.)
5. Loops until the model produces a final response (multi-turn tool use)
6. Saves session state for next invocation

**Step 8:** Receive the agent response:

```json
← {
    "type": "res",
    "id": "uuid-2",
    "ok": true,
    "payload": {
      "reply": "Amazon Bedrock is a fully managed service that provides..."
    }
  }
```

### Layer 3: Response Back to Client

**Step 9:** `main.py` returns the response to Strands:

```python
return {"result": "Amazon Bedrock is a fully managed service that provides..."}
```

**Step 10:** `BedrockAgentCoreApp` sends the HTTP response to AgentCore:

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"result": "Amazon Bedrock is a fully managed service that provides..."}
```

AgentCore returns this to the original client.

### Health Check Flow (Parallel)

AgentCore polls `/ping` every few seconds to manage container lifecycle:

```http
GET /ping HTTP/1.1
→ {"status": "Healthy", "time_of_last_update": 1720000000}
```

- `"Healthy"` → container is idle, AgentCore may terminate it
- `"HealthyBusy"` → processing a request, AgentCore will NOT terminate

`BedrockAgentCoreApp` handles this automatically.

### Summary Table

| Step | Direction | Protocol | What Happens |
|------|-----------|----------|-------------|
| 1-2 | Client → Strands | HTTP POST `:8080/invocations` | AgentCore delivers the prompt |
| 3 | Strands → OpenClaw | WebSocket connect | Open connection to gateway |
| 4-6 | Strands ↔ OpenClaw | WS JSON-RPC | Challenge + authenticate |
| 7 | Strands → OpenClaw | WS JSON-RPC `"agent"` | Send the prompt |
| (internal) | OpenClaw → Bedrock | Bedrock Converse API | LLM reasoning + tool use loop |
| 8 | OpenClaw → Strands | WS JSON-RPC response | Return final answer |
| 9-10 | Strands → Client | HTTP 200 JSON | Deliver response to AgentCore |

## Deployment Options

### Static Zip (recommended for AgentCore)

Bundle everything into a zip file. OpenClaw binary + Node.js are included so no Docker is needed:

```bash
bash scripts/deploy.sh
# Creates agent.zip with: main.py + start.sh + openclaw/ + .openclaw/
```

### Container (Docker)

For more control or if you need additional system dependencies:

```dockerfile
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install Node.js + OpenClaw
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g openclaw

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x start.sh && mkdir -p /root/.openclaw
COPY .openclaw/ /root/.openclaw/

EXPOSE 8080
ENTRYPOINT ["/app/start.sh"]
```

## Configuration

### Model

Set in `.openclaw/openclaw.json` under `agents.defaults.model.primary`:

```
amazon-bedrock/global.anthropic.claude-sonnet-4-6    # Cross-region (recommended)
amazon-bedrock/us.anthropic.claude-sonnet-4-6        # US regional
amazon-bedrock/eu.anthropic.claude-sonnet-4-6        # EU regional
```

### Gateway Auth

For production, enable gateway token auth:

```json
{
  "gateway": {
    "auth": { "mode": "token", "token": "your-secret-token" }
  }
}
```

Then set `OPENCLAW_GATEWAY_TOKEN=your-secret-token` in your environment.

### Tools

OpenClaw's full tool stack is available. Configure in `.openclaw/openclaw.json`:

```json
{
  "tools": {
    "profile": "full",
    "exec": { "host": "gateway", "security": "full", "ask": "off" },
    "deny": ["browser", "canvas"]
  }
}
```

### Skills

Add OpenClaw skills to `.openclaw/workspace/skills/` or install via ClawHub:

```bash
clawhub install jina-reader --no-input
clawhub install deep-research-pro --no-input
```

## Validation

This project has been deployed and validated end-to-end on AgentCore Runtime in `ap-southeast-2`.

**Deployment details:**
- Runtime: `openclawagent_openclaw_strands` (Container build, READY status)
- Stack: `AgentCore-openclawagent-default` (CloudFormation)
- Model: `global.anthropic.claude-haiku-4-5-20251001-v1:0` (cross-region inference)
- Region: `ap-southeast-2`

**Test invocation:**
```bash
$ agentcore invoke "Say hello in one sentence"
→ "Hey. I just came online. Who are you, and who am I?"
```

**Validated flow:**
1. ✅ Container image builds successfully via CodeBuild
2. ✅ Python starts on `:8080` immediately (meets AgentCore health check contract)
3. ✅ OpenClaw gateway boots in background thread on `:18789`
4. ✅ WebSocket handshake: challenge → connect (with `platform` field) → authenticated
5. ✅ Agent request accepted → Bedrock LLM call succeeds → full response returned
6. ✅ Cross-region inference via `global.` model ID prefix
7. ✅ Session persistence across invocations (same `sessionKey`)

**Key fixes applied during validation:**
| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Container killed by AgentCore | Python wasn't serving `:8080` fast enough | Boot OpenClaw in background thread, serve HTTP immediately |
| WebSocket auth failed | Missing `platform` field in connect params | Added `"platform": "agentcore"` to client object |
| "LLM request failed" | Model ID needs `global.` prefix for cross-region | Changed to `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| CDK build fails on fresh clone | `lib/cdk-stack.ts` not in git (CLI generates at create time) | Force-added to repo |
| Gateway auth error | `gateway.auth.mode: "off"` not a valid value | Changed to `"none"` |

## Comparison with Other Approaches

| | **This repo** (Strands wrapper) | [aws-samples](https://github.com/aws-samples/sample-host-openclaw-on-amazon-bedrock-agentcore) | [sample-strands-openclaw](https://github.com/wirjo/sample-strands-openclaw) |
|---|---|---|---|
| **Deployment** | Static zip or container | Container + CDK | Container |
| **Wrapper** | Python (Strands SDK) | Node.js (raw HTTP) | TypeScript (Strands SDK) |
| **Complexity** | ~15 lines | ~2000 lines | ~50 lines |
| **Multi-user** | Single session | Per-user isolation | Single session |
| **Channels** | None (AgentCore only) | Telegram + Slack | None |
| **Best for** | Quick deployment | Production multi-tenant | SDK reference |

## Related

- [OpenClaw Documentation](https://docs.openclaw.ai)
- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
- [Strands Agents SDK](https://strandsagents.com/)
- [AgentCore CLI](https://github.com/aws/agentcore-cli)
- [Feature Request: Native AgentCore mode](https://github.com/openclaw/openclaw/issues/101627)

## License

MIT
