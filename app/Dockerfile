FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install OpenClaw globally
RUN npm install -g openclaw && npm cache clean --force

# Install Python dependencies
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py ./

# Copy OpenClaw config
COPY .openclaw/ /app/.openclaw/

# Ensure writable workspace for OpenClaw
RUN mkdir -p /app/.openclaw/workspace /app/.openclaw/agents

ENV PYTHONUNBUFFERED=1 \
    OPENCLAW_PORT=18789 \
    HOME=/app

# AgentCore Runtime service contract port
EXPOSE 8080

# Start Python directly — it boots OpenClaw gateway in a background thread
CMD ["python", "main.py"]
