# DCM - Decentralized Compute Market
# Dockerfile for Cloud Deployment

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data && chmod 755 /app/data

# Create non-root user (commented out for simplicity)
# RUN useradd -m appuser && chown -R appuser:appuser /app
# USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1

# Health check (use PORT from environment)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-10000}/health || exit 1

# Run the application (use PORT from environment)
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port $${PORT:-10000}"]
