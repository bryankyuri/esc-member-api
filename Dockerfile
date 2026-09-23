# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
# Alembic must be in the image: there is no separate migration step, so the
# app upgrades the schema itself on boot (app/migrations.py) and reads both of
# these from the working directory. Without them the container crashes at
# startup instead of migrating.
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

# SQLite lives on a host volume (docker-compose mounts ./data:/app/data).
ENV DATABASE_URL=sqlite:////app/data/esc.db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# --proxy-headers so the app sees real client IPs (rate limiting) behind Caddy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
