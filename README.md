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

## How the WebSocket Bridge Works

The OpenClaw gateway speaks a JSON-RPC-over-WebSocket protocol:

```
1. Connect to ws://127.0.0.1:18789
2. Receive: { type: "event", event: "connect.challenge", ... }
3. Send:    { type: "req", method: "connect", params: { auth: {...}, role: "operator" } }
4. Receive: { type: "res", id: "...", ok: true }  (authenticated)
5. Send:    { type: "req", method: "agent", params: { message: "...", sessionKey: "..." } }
6. Receive: { type: "res", id: "...", payload: { reply: "..." } }  (agent response)
```

The `"agent"` method runs a full agent turn — OpenClaw handles tool calls, memory, reasoning, and returns the final response.

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
