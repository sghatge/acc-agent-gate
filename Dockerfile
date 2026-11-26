FROM python:3.12-slim

# uv is used only as a fast installer; runtime remains standard Python.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPSFORGE_API_HOST=0.0.0.0 \
    OPSFORGE_AUDIT_PATH=/var/lib/opsforge/audit.jsonl

WORKDIR /app

# Install the MCP package and the small set of dependencies used by the
# optional OPSFORGE HTTP API. The default command is the stdio MCP server;
# Render overrides it with the API command in render.yaml.
COPY pyproject.toml README.md LICENSE requirements-api.txt ./
COPY acc_agent_gate/ ./acc_agent_gate/
COPY opsforge/ ./opsforge/

RUN uv pip install --system --no-cache -r requirements-api.txt . \
    && groupadd --system --gid 10001 opsforge \
    && useradd --system --uid 10001 --gid opsforge --create-home --shell /usr/sbin/nologin opsforge \
    && mkdir -p /var/lib/opsforge \
    && chown -R opsforge:opsforge /var/lib/opsforge /app

USER 10001:10001

EXPOSE 8765

CMD ["acc-agent-gate"]
