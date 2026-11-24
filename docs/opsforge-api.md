## OPSFORGE authenticated agent API

The unified dashboard can run locally with synthetic examples or connect to
this optional Python HTTP service for authenticated execution of the four
OPSFORGE agents.

### Start the local service

Generate a random bearer token:

```bash
export OPSFORGE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python -m opsforge.api
```

PowerShell:

```powershell
$env:OPSFORGE_API_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(48))"
python -m opsforge.api
```

The service listens on `127.0.0.1:8765` by default. The single-token
compatibility mode assigns the token the `operator` role. Use the multi-user
credential map below to apply distinct roles.

### Role-based access control

For multi-user access, configure `OPSFORGE_API_CREDENTIALS_JSON` as a JSON
object whose keys are SHA-256 hashes of bearer tokens. Store only token hashes
on the server; give each user the corresponding raw token through a secure
secret-delivery channel.

Generate a token and its hash:

```bash
python -c 'import secrets,hashlib; t=secrets.token_urlsafe(48); print("TOKEN="+t); print("SHA256="+hashlib.sha256(t.encode()).hexdigest())'
```

Configure the map as a server environment variable (replace the example hash):

```bash
export OPSFORGE_API_CREDENTIALS_JSON='{"<sha256-token-hash>":{"actor":"crm-analyst-01","role":"analyst"},"<qa-sha256-token-hash>":{"actor":"campaign-qa-01","role":"qa"},"<operator-sha256-token-hash>":{"actor":"ops-lead","role":"operator"}}'
python -m opsforge.api
```

| Role | Research | CRM Ops | Adobe Campaign QA | Marketing Analytics | Gemini |
|---|---:|---:|---:|---:|---:|
| `analyst` | Yes | Yes | No | Yes | No |
| `qa` | No | No | Yes | No | No |
| `operator` | Yes | Yes | Yes | Yes | Yes, if server-enabled |
| `admin` | Yes | Yes | Yes | Yes | Yes, if server-enabled |

The API derives the audit actor and role from the configured credential.
Client-supplied actor headers are not trusted. The `analyst` role cannot
invoke Adobe Campaign QA; the `qa` role cannot invoke analytics or CRM
operations. Gemini requires both an `operator` or `admin` role and the
server-side `OPSFORGE_ENABLE_GEMINI=true` switch, plus a configured Gemini
API key.

### Endpoints

- `GET /health` — public liveness, available agent names and role names.
- `POST /api/agents/research/run`
- `POST /api/agents/crm_operations/run`
- `POST /api/agents/adobe_campaign_qa/run`
- `POST /api/agents/marketing_analytics/run`

Every execution endpoint requires `Authorization: Bearer <token>` and a JSON
object body. Requests are limited to 64 KiB. Agent names are allow-listed;
task validation remains in each agent.

### Example request

```bash
curl -X POST http://127.0.0.1:8765/api/agents/marketing_analytics/run \
  -H "Authorization: Bearer $OPSFORGE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"period":"Sample","campaigns":[{"name":"Launch","sends":10000,"delivered":9800,"opens":4900,"clicks":980,"conversions":98,"bounces":200}]}'
```

### Dashboard connection

Select **Authenticated Python API** in the OPSFORGE dashboard, enter the API
origin and bearer token, then run the selected agent. The token remains in page
memory only and is not written to browser storage. The browser only permits
HTTPS for remote origins; HTTP is allowed for localhost development.

Set `OPSFORGE_CORS_ORIGINS` to the exact dashboard origin, for example:

```bash
export OPSFORGE_CORS_ORIGINS="https://sghatge.github.io"
```


### Container deployment

The repository includes a minimal non-root Docker image for the API. Build it:

```bash
docker build -t opsforge-agent-api .
docker volume create opsforge-api-audit
```

For the single-operator local mode:

```bash
docker run --detach --name opsforge-api \
  --publish 8765:8765 \
  --env OPSFORGE_API_TOKEN="$OPSFORGE_API_TOKEN" \
  --env OPSFORGE_CORS_ORIGINS="https://sghatge.github.io" \
  --mount source=opsforge-api-audit,target=/var/lib/opsforge \
  --restart unless-stopped \
  opsforge-agent-api
```

For multi-user RBAC, pass `OPSFORGE_API_CREDENTIALS_JSON` from your platform's
secret manager instead of `OPSFORGE_API_TOKEN`. Do not put real credentials
in a committed Compose file, Dockerfile, build argument or GitHub repository.

The image listens on `0.0.0.0:8765`, runs as an unprivileged user, exposes
`/health` for container health checks and writes the hash-chained audit log
under `/var/lib/opsforge`. Keep that path on persistent storage. Managed
container platforms can set `PORT`; the API uses it when
`OPSFORGE_API_PORT` is not set. Configure TLS termination, rate limiting,
secret injection and a persistent audit volume before public deployment.

### Security and deployment notes

- The API is advisory-only. It does not connect to or mutate Adobe Campaign,
  Salesforce, or other production systems; it cannot send or approve a delivery.
- Multi-user mode stores SHA-256 token hashes and configured actor/role labels.
  It is a basic service-level RBAC layer, not enterprise SSO. For production,
  integrate OIDC/identity-aware gateway, short-lived credentials, rotation and
  centralized per-user authorization.
- Keep the service on loopback for local use. For remote use, place it behind a
  trusted HTTPS reverse proxy; never expose the development HTTP listener
  directly to the public internet. Apply request-rate limits at the proxy.
- CORS uses an exact origin allow-list. Do not use wildcard origins with bearer
  credentials.
- Audit events are hash-chained in `var/opsforge-api-audit.jsonl`. They contain
  the credential-configured actor, role, agent, request ID, outcome and a task
  digest—not prompts, source content, credentials or generated reports.
  The actor label is verified against the credential configuration, not an
  external corporate identity provider.
- Audit-chain corruption or persistence failure withholds the API response.
  The local hash chain is tamper-evident, not immutable storage; protect and
  back up the audit file and move to centralized durable storage before rollout.

Verify the audit chain:

```bash
python -c "from opsforge.api_audit import verify_audit_log; print(verify_audit_log('var/opsforge-api-audit.jsonl'))"
```

Run API tests:

```bash
python -m pytest -q tests/test_opsforge_api.py
```
