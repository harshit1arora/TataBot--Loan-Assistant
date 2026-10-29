# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core_service ./core_service

# Run as a non-root user: nothing in this service needs root.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /srv/data/storage \
    && chown -R app:app /srv
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"

# One worker per container; scale with replicas, not threads.
CMD ["uvicorn", "core_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
