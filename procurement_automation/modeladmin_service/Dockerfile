FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY src ./src

RUN useradd -m appuser \
  && mkdir -p /app/data \
  && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app/src

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8100/health/ || exit 1

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8100", "--workers", "2", "--timeout", "600", "--graceful-timeout", "120", "modeladmin_service.main:app"]
