# Stage 1: Build Frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /frontend
COPY chat-ui/ .
RUN npm install
RUN npm run build

# Stage 2: Build Backend
FROM python:3.12-slim AS backend-builder
WORKDIR /flare-defai

# Copy requirements and configuration files for better caching
COPY pyproject.toml README.md ./

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev git && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies directly without using -e flag
RUN pip install --upgrade pip && \
    pip install hatchling && \
    pip install build && \
    pip install aiohttp pydantic-settings requests structlog google-generativeai httpx cryptography pyjwt pyopenssl fastapi uvicorn web3

# Copy application code
COPY src/ ./src/

# Stage 3: Final Image
FROM python:3.12-slim

# Install nginx
RUN apt-get update && apt-get install -y nginx supervisor curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=backend-builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=backend-builder /flare-defai/src ./src
COPY --from=backend-builder /flare-defai/pyproject.toml .
COPY --from=backend-builder /flare-defai/README.md .

# Copy frontend files
COPY --from=frontend-builder /frontend/build /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/sites-enabled/default

# Setup supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Add PYTHONPATH to ensure modules are found
ENV PYTHONPATH=/app

# Allow workload operator to override environment variables
LABEL "tee.launch_policy.allow_env_override"="GEMINI_API_KEY,GEMINI_MODEL,WEB3_PROVIDER_URL,WEB3_EXPLORER_URL,SIMULATE_ATTESTATION"
LABEL "tee.launch_policy.log_redirect"="always"

EXPOSE 80

# Start supervisor (which will start both nginx and the backend)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]