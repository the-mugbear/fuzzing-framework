# Build frontend
FROM node:18-bullseye AS ui-builder
WORKDIR /ui
COPY core/ui/spa/package*.json ./
RUN npm install
COPY core/ui/spa/ .
RUN npm run build

# Dockerfile for Fuzzer Core
FROM python:3.11-slim

LABEL maintainer="Ken Charles"
LABEL description="Portable Proprietary Protocol Fuzzer - Core Container"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY core/ ./core/
COPY agent/ ./agent/
COPY tests/ ./tests/
COPY --from=ui-builder /ui/dist ./core/ui/spa/dist/

# Create directories for data persistence
RUN mkdir -p /app/data/corpus /app/data/crashes /app/data/logs

# Expose API port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV FUZZER_CORPUS_DIR=/app/data/corpus
ENV FUZZER_CRASH_DIR=/app/data/crashes

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/system/health')"

# Run the Core API server
CMD ["python", "-m", "core.api.server"]
