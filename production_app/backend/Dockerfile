FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required for some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for Docker caching
COPY requirements.txt requirements.txt
COPY requirements-dev.txt requirements-dev.txt

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user and give ownership of app directory
RUN useradd -m appuser \
  && mkdir -p /app/data \
  && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Start API or worker based on MODE env var (api|worker)
CMD ["python", "-m", "app.runtime"]
