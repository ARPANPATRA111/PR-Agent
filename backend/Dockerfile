# =========================================================================
# Weekly Progress Agent - Optimized Multi-Stage Dockerfile
# =========================================================================
# Stage 1: Builder - Install dependencies
# Stage 2: Runtime - Minimal production image
# =========================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.12.14-slim-trixie@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Runtime
# -----------------------------------------------------------------------------
FROM python:3.12.14-slim-trixie@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS runtime

# Labels
LABEL version="2.0.0"
LABEL description="Invite-only Telegram tracking assistant"

# Apply current distribution security updates. Voice files are sent directly to
# the configured transcription provider, so no media processor is needed here.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Package installers are not needed at runtime. Removing them also removes
# vendored build-only parsers from the production attack surface.
RUN rm -rf \
    /usr/local/lib/python3.12/site-packages/pip* \
    /usr/local/bin/pip* \
    /opt/venv/lib/python3.12/site-packages/pip* \
    /opt/venv/bin/pip*

# Copy application code
COPY --chown=appuser:appgroup . .

# Create data directories
RUN mkdir -p /app/data/audio_temp /app/data/chroma /app/data/logs /app/data/backups \
    && chown -R appuser:appgroup /app/data

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://localhost:{port}/ready', timeout=5).read()" || exit 1

# Every container command (web or worker) passes through the migration guard.
# render_start.py executes an explicitly supplied command after migrating, or
# starts Uvicorn itself when the image is launched without one.
ENTRYPOINT ["python", "render_start.py"]
