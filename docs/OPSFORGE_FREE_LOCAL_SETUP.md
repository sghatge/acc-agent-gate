# OPSFORGE — no-cost local API setup

This is the zero-subscription path for learning and portfolio testing. It runs the API on your own computer using Docker Desktop and keeps the audit file in a named local Docker volume. It does not create a cloud service.

## Requirements
- Docker Desktop installed and running.
- Git repository cloned locally.
- PowerShell (Windows) or a Bash-compatible terminal.
- No Render account or paid hosting plan is required.

## Windows PowerShell
Run these commands from the repository folder:
```powershell
docker build -t opsforge-agent-api:local .
$env:OPSFORGE_API_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(48))"
docker volume create opsforge-audit
docker run -d --name opsforge-api -p 127.0.0.1:8765:8765 -e OPSFORGE_API_TOKEN=$env:OPSFORGE_API_TOKEN -e OPSFORGE_CORS_ORIGINS=https://sghatge.github.io -v opsforge-audit:/var/lib/opsforge opsforge-agent-api:local
$env:OPSFORGE_API_URL = "http://127.0.0.1:8765"
python scripts/opsforge_hosted_smoke.py
```

Stop the service when finished:
```powershell
docker stop opsforge-api
docker rm opsforge-api
Remove-Item Env:OPSFORGE_API_TOKEN
Remove-Item Env:OPSFORGE_API_URL
```

The named volume `opsforge-audit` remains on your computer after the container is removed. To remove the local audit data deliberately, run `docker volume rm opsforge-audit`.

## Bash
```bash
docker build -t opsforge-agent-api:local .
export OPSFORGE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker volume create opsforge-audit
docker run -d --name opsforge-api -p 127.0.0.1:8765:8765 -e OPSFORGE_API_TOKEN="$OPSFORGE_API_TOKEN" -e OPSFORGE_CORS_ORIGINS=https://sghatge.github.io -v opsforge-audit:/var/lib/opsforge opsforge-agent-api:local
OPSFORGE_API_URL=http://127.0.0.1:8765 python scripts/opsforge_hosted_smoke.py
```

## Important boundaries
- The API is published only on the local loopback interface.
- The generated token is local to this run; do not commit or share it.
- The audit volume is local persistence, not centralized immutable retention.
- HTTP is accepted only for localhost by the smoke script. Use HTTPS for remote deployment.
- The hosted API remains advisory-only. It does not connect to Adobe Campaign or Salesforce and does not send campaigns or create CRM records.
- The GitHub Pages demo can continue in synthetic mode without this API. CLI smoke testing is the reliable no-cost validation path.

## Next step
If a free hosting option becomes available and meets persistent audit, security and data-residency requirements, use the hosted deployment runbook. Do not move real customer data to an unreviewed free hosting tier.