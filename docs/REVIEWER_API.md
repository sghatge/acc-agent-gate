# Authenticated Reviewer API — Phase 3

Phase 3 adds a separate HTTP service for authenticated human review of
persistent approval records. It is intentionally review-only.

## Endpoints

- `GET /health` — public liveness and execution-scope indicator.
- `GET /api/approvals?status=PENDING&limit=100` — list requests visible to
  the authenticated reviewer's configured role.
- `GET /api/approvals/{ticket}` — retrieve a role-eligible approval record.
- `POST /api/approvals/{ticket}/decision` — record APPROVE or REJECT.

Every endpoint except `/health` requires a bearer token. The reviewer identity
and role are derived from the server-side credential map. Client-supplied
reviewer or role fields are rejected. The API only exposes records whose
policy snapshot includes the reviewer's configured role.

## Configure reviewer credentials

Generate a high-entropy token and its SHA-256 digest:

```bash
python -c 'import secrets,hashlib; t=secrets.token_urlsafe(48); print("TOKEN="+t); print("SHA256="+hashlib.sha256(t.encode()).hexdigest())'
```

Set `ACC_GATE_REVIEWER_CREDENTIALS_JSON` to a JSON object keyed by token
hashes. Example (replace the hash and identities):

```bash
export ACC_GATE_REVIEWER_CREDENTIALS_JSON='{"<sha256-token-hash>":{"reviewer":"market-owner-01","role":"market_owner"},"<second-sha256-token-hash>":{"reviewer":"crm-ops-02","role":"crm_ops_lead"}}'
export ACC_GATE_APPROVAL_DB="approval_queue.sqlite3"
python -m acc_agent_gate.reviewer_api
```

For local single-reviewer development only, `ACC_GATE_REVIEWER_TOKEN` can
supply one token; it maps to `local-reviewer` / `market_owner`. Do not use
this fallback for shared or production deployments.

The reviewer credential map is trusted server configuration. Store raw
tokens in a secret manager and distribute each token only to its intended
reviewer. The service stores only SHA-256 token digests in its in-memory
credential map; it does not persist raw tokens.

## Example decision

```bash
curl -X POST http://127.0.0.1:8766/api/approvals/APR-0123456789AB/decision \
  -H "Authorization: Bearer $REVIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision":"APPROVE","reason":"Reviewed campaign QA evidence"}'
```

The response includes the updated approval record and
`execution_authorized: false`.

## Security controls

- Bearer authentication with SHA-256 credential lookup and constant-time
  digest comparison.
- Server-derived reviewer identity and role; client cannot impersonate another
  reviewer or elevate their role.
- Role-scoped list and detail access; ineligible tickets return not found.
- Request body limit, strict JSON object validation, allow-listed decision
  values, bounded reason length, and no-store response headers.
- Existing SQLite transaction enforces self-approval prevention, reviewer
  uniqueness, role eligibility, terminal rejection and dual-approval count.
- No approval/rejection MCP tool and no campaign execution route.

Run on loopback for local use. Before remote access, put the service behind a
trusted HTTPS reverse proxy, configure rate limiting, restrict network access,
use managed secrets, and persist/backup the SQLite database. This service is
not an enterprise SSO integration; production identity should be federated
through OIDC or an identity-aware gateway and mapped to server-side reviewer
principals.

## Explicit limitation

An APPROVED record is a human review outcome only. This service does not call
`AgentGate.approve`, mint execution tokens, re-evaluate live campaign state,
or execute a send. Those controls belong to the next execution-authorization
phase. The bundled Campaign backend remains synthetic.
