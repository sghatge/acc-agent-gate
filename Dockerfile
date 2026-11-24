FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPSFORGE_API_HOST=0.0.0.0 \
    OPSFORGE_AUDIT_PATH=/var/lib/opsforge/audit.jsonl

WORKDIR /app

COPY requirements-api.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements-api.txt \
    && groupadd --system --gid 10001 opsforge \
    && useradd --system --uid 10001 --gid opsforge --create-home --shell /usr/sbin/nologin opsforge \
    && mkdir -p /var/lib/opsforge \
    && chown -R opsforge:opsforge /var/lib/opsforge /app

COPY --chown=opsforge:opsforge acc_agent_gate ./acc_agent_gate
COPY --chown=opsforge:opsforge opsforge ./opsforge

USER 10001:10001

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.getenv('OPSFORGE_API_PORT',os.getenv('PORT','8765')); urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=2).read()"

CMD ["python", "-m", "opsforge.api"]
