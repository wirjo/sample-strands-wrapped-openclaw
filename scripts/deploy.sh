#!/bin/bash
# deploy.sh — Package and deploy to AgentCore Runtime
set -euo pipefail

echo "=== Packaging OpenClaw for AgentCore Runtime ==="

# 1. Bundle OpenClaw if not already bundled
if [ ! -x "./openclaw/node" ]; then
    echo "Step 1: Bundling OpenClaw..."
    bash scripts/bundle-openclaw.sh arm64
else
    echo "Step 1: OpenClaw already bundled, skipping"
fi

# 2. Install Python dependencies
echo "Step 2: Installing Python dependencies..."
pip install -r requirements.txt -t ./lib --quiet

# 3. Create deployment zip
echo "Step 3: Creating deployment zip..."
rm -f agent.zip
zip -r agent.zip \
    main.py \
    start.sh \
    requirements.txt \
    .openclaw/ \
    openclaw/ \
    lib/ \
    -x "*.pyc" -x "__pycache__/*"

echo "=== Deployment package ready: agent.zip ($(du -sh agent.zip | cut -f1)) ==="
echo ""
echo "Deploy with:"
echo "  agentcore deploy --artifact agent.zip"
echo ""
echo "Or via SDK:"
echo "  python scripts/deploy-sdk.py"
