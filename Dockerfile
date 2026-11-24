FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPSFORGE_API_HOST=0.0.0.0 \
    OPSFORGE_API_PORT=8765 \
    OPSFORGE_AUDIT_PATH=/var/lib/opsforge/audit.jsonl

WORKDIR /app

COPY requirements-api.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-api.txt \
    && useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin opsforge \
    && mkdir -p /var/lib/opsforge \
    && chown -R opsforge:opsforge /var/lib/opsforge /app

COPY --chown=opsforge:opsforge acc_agent_gate ./acc_agent_gate
COPY --chown=opsforge:opsforge opsforge ./opsforge

USER 10001:10001

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2).read()"

CMD ["python", "-m", "opsforge.api"]
