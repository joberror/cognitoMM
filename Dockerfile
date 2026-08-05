# syntax=docker/dockerfile:1
# Dockerfile
# ========================================================================
#  Multi-stage build: install deps, then copy only runtime essentials.
# ========================================================================

# ---- Builder stage ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install system build deps (only needed for compilation)
# The slim base image ships an apt "docker-clean" hook that deletes downloaded
# .deb archives after install; disable it so the BuildKit cache mounts below
# actually retain packages/lists across rebuilds (apt is the slowest step).
RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

# apt cache mounts: downloaded .debs (/var/cache/apt) and package lists
# (/var/lib/apt) persist across rebuilds. sharing=locked prevents concurrent
# builds from corrupting the cache; id= scopes the cache to this project so a
# shared builder (CI, other local images) can't pollute it. Lists stay in the
# mount (not the layer) and are re-verified by the apt-get update below on every
# build, so there's no need to rm them afterwards (don't reintroduce that).
RUN --mount=type=cache,id=cognito-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=cognito-apt-var,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev

# Install Python dependencies (cached separately from source)
# BuildKit cache mount persists pip's wheel/http cache across rebuilds, so
# dependency downloads happen once and rebuilds reuse them (faster + resilient
# to network hiccups). sharing=locked prevents concurrent builds from corrupting
# the cache. The syntax line above guarantees --mount support; if a builder ever
# can't fetch the dockerfile:1 frontend, the line can be dropped (the default
# BuildKit frontend on Docker 24+ supports cache mounts on its own).
COPY requirements.txt .
RUN --mount=type=cache,id=cognito-pip-cache,target=/root/.cache/pip,sharing=locked pip install --user -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

# Copy only the installed packages from builder
COPY --from=builder /root/.local /root/.local

# Ensure our local bin dir is on PATH
ENV PATH=/root/.local/bin:$PATH

# Runtime system deps (none beyond what the slim image provides)
# Healthcheck: use the Flask /health endpoint (installed from builder)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health').read()" || exit 1

# Copy application source
COPY . .

# Expose port (HF Spaces default is 7860)
EXPOSE ${PORT}

# Run the application
CMD ["python", "main.py"]