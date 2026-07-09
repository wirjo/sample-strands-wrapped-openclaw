#!/bin/bash
# bundle-openclaw.sh — Bundle OpenClaw + Node.js for static zip deployment
set -euo pipefail

ARCH="${1:-arm64}"
NODE_VERSION="22.22.0"

echo "Bundling OpenClaw for linux/${ARCH}..."

mkdir -p openclaw

# 1. Download Node.js binary
echo "Downloading Node.js ${NODE_VERSION} (${ARCH})..."
curl -sL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${ARCH}.tar.xz" | \
    tar -xJ --strip-components=1 -C openclaw/ "node-v${NODE_VERSION}-linux-${ARCH}/bin/node"

chmod +x openclaw/node

# 2. Install OpenClaw into bundled location
echo "Installing OpenClaw..."
cd openclaw
mkdir -p node_modules
../openclaw/node -e "const{execSync}=require('child_process');execSync('npm install openclaw --prefix .', {stdio:'inherit'})" 2>/dev/null || \
    npm install openclaw --prefix .
cd ..

# 3. Verify
echo "Verifying..."
./openclaw/node ./openclaw/node_modules/openclaw/openclaw.mjs --version

echo "Done. OpenClaw bundled in ./openclaw/"
echo "Total size: $(du -sh openclaw/ | cut -f1)"
