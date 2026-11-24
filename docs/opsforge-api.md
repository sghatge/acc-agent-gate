## OPSFORGE authenticated agent API

The unified dashboard is a static showcase. To execute the Python agents over
HTTP, run the optional local API service:

```bash
export OPSFORGE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m opsforge.api
```

PowerShell:

```powershell
$env:OPSFORGE_API_TOKEN = [Convert]::ToBase64String([byte[]](1..48 | ForEach-Object { Get-Random -Maximum 256 }))
python -m opsforge.api
```

The service listens on `127.0.0.1:8765` by default. It exposes:

- `GET /health` — public liveness and agent capability metadata.
- `POST /api/agents/research/run`
- `POST /api/agents/crm_operations/run`
- `POST /api/agents/adobe_campaign_qa/run`
- `POST /api/agents/marketing_analytics/run`

Every execution endpoint requires `Authorization: Bearer <OPSFORGE_API_TOKEN>`
and a JSON object body. Requests are limited to 64 KiB. Agent names are
allow-listed; task validation remains in each agent. `use_gemini` is disabled
unless the server operator explicitly sets `OPSFORGE_ENABLE_GEMINI=true`
and configures the Gemini API key.

### Example request

```bash
curl -X POST http://127.0.0.1:8765/api/agents/marketing_analytics/run \
  -H "Authorization: Bearer $OPSFORGE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"period":"Sample","campaigns":[{"name":"Launch","sends":10000,"delivered":9800,"opens":4900,"clicks":980,"conversions":98,"bounces":200}]}'
```

### Security and deployment notes

- The API is advisory-only and does not connect to or mutate Adobe Campaign,
  Salesforce, or other production systems.
- A random bearer token is a minimal single-service credential, not enterprise
  identity management. Use an identity-aware gateway/OIDC provider, short-lived
  credentials, secret rotation and per-user authorization before team rollout.
- Keep the service on loopback for local use. For remote use, place it behind a
  trusted HTTPS reverse proxy; never expose the development HTTP listener
  directly to the public internet. Apply request-rate limits at the proxy.
- Set `OPSFORGE_CORS_ORIGINS` to a comma-separated exact origin allow-list
  before browser access. Do not use wildcard origins with bearer credentials.
  The GitHub Pages UI does not call this API automatically.
- Audit events are hash-chained in `var/opsforge-api-audit.jsonl`. They contain
  an unverified actor label, agent, request ID, outcome and a task digest—not prompts, source
  content, credentials or generated reports. Protect and back up the audit file;
  a local hash chain is tamper-evident, not immutable storage.
- Failed audit persistence withholds the API response. This is a local
  fail-closed safeguard, not a replacement for centralized durable audit storage.

Verify the audit chain:

```bash
python -c "from opsforge.api_audit import verify_audit_log; print(verify_audit_log('var/opsforge-api-audit.jsonl'))"
```

Run API tests:

```bash
python -m pytest -q tests/test_opsforge_api.py
```
