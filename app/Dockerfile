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
COPY main.py start.sh ./
RUN chmod +x start.sh

# Copy OpenClaw config to /app/.openclaw (portable, doesn't depend on HOME)
COPY .openclaw/ /app/.openclaw/

# Set environment so OpenClaw finds its config regardless of user
ENV PYTHONUNBUFFERED=1 \
    OPENCLAW_PORT=18789 \
    HOME=/app \
    OPENCLAW_HOME=/app/.openclaw

# AgentCore Runtime service contract port
EXPOSE 8080

CMD ["/app/start.sh"]
