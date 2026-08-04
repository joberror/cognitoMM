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
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (cached separately from source)
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

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