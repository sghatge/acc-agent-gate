# Hosted deployment: Render

This runbook deploys the OPSFORGE authenticated API as a Docker web service.
It does **not** deploy the static dashboard (already hosted on GitHub Pages),
connect to Adobe Campaign or Salesforce, or enable production write actions.

## 1. Deploy from the repository

1. Sign in to Render and choose **New → Blueprint**.
2. Connect the GitHub repository `sghatge/acc-agent-gate`.
3. Select the repository's `render.yaml` blueprint and deploy.
4. Render builds the existing Dockerfile, provisions a persistent 1 GB disk,
   generates a long random `OPSFORGE_API_TOKEN`, and checks `/health`.
5. Wait for the service to report **Live**. Copy its HTTPS origin, for example
   `https://your-service-name.onrender.com` (use the actual URL Render assigns).

The blueprint uses the Singapore region as a practical Asia-Pacific starting
point. Confirm data-residency and organizational requirements before using
real business data. The persistent disk requires a paid Render service plan;
do not remove it for a service expected to retain its audit chain.

## 2. Retrieve and protect the API token

In the Render service dashboard, open **Environment** and retrieve the
generated `OPSFORGE_API_TOKEN` through the platform's protected controls.
Treat it as a password. Do not paste it into GitHub, source code, a ticket,
or a public chat. The dashboard keeps the token in page memory only.

The initial blueprint uses the compatibility single-token mode, which grants
the token the `operator` role. For multi-user access, replace that variable
with `OPSFORGE_API_CREDENTIALS_JSON` containing SHA-256 token hashes and
actor/role mappings; then remove `OPSFORGE_API_TOKEN`. Generate and deliver
each raw token through a secure secret-delivery channel. See
[the API/RBAC guide](opsforge-api.md#role-based-access-control).

## 3. Connect the dashboard

1. Open the [OPSFORGE dashboard](https://sghatge.github.io/acc-agent-gate/opsforge/).
2. Choose **Authenticated Python API**.
3. Enter the Render HTTPS origin (no trailing slash) and the bearer token.
4. Run a harmless synthetic-data task first.

The blueprint allow-lists only `https://sghatge.github.io` for browser CORS.
Do not add wildcard origins. If you host a fork or custom dashboard, update
`OPSFORGE_CORS_ORIGINS` to that exact origin and redeploy.

## 4. Verify the service

Public liveness check:

```bash
curl https://YOUR-SERVICE.onrender.com/health
```

Expected response includes `"status":"healthy"`,
`"execution_scope":"advisory_only"`, the four agent names and configured
role names. This endpoint is intentionally public and contains no credentials.

Authenticated smoke test (replace placeholders; use synthetic data only):

```bash
curl -X POST https://YOUR-SERVICE.onrender.com/api/agents/research/run \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Summarize the purpose of an email campaign QA checklist."}'
```

A successful response should include a request ID, the authorization role and
`"execution_scope":"advisory_only"`. An unauthorized request should return
HTTP 401. A role attempting an agent outside its permission set should return
HTTP 403 and create an audit event.

## 5. Production gates before real organizational use

- Put the service behind the platform's HTTPS endpoint; never expose plain HTTP.
- Keep the persistent disk attached and back up the audit file. A hash chain is
  tamper-evident, not immutable or a substitute for centralized retention.
- Rotate credentials and use per-user RBAC. The single generated token is an
  operator credential, not an enterprise identity solution.
- Add an OIDC/Entra ID identity-aware gateway and map verified identities to
  least-privilege roles before broad organizational rollout.
- Configure rate limiting and request-size limits at the edge; monitor service
  health, error rates, latency and disk capacity.
- Validate audit-chain continuity and test recovery from backup.
- Review data residency, privacy, retention and vendor security requirements.
- Keep Gemini disabled until separately approved; enabling it requires both
  server-side configuration and an authorized operator/admin role.
- Use synthetic or approved test data only until security and privacy reviews
  are complete.

## Scope and limitations

The API is advisory-only. It does not authenticate to, read from, or mutate
Adobe Campaign, Salesforce, or production CRM systems. The Render blueprint
creates deployment infrastructure only; it does not create an enterprise SSO
integration, immutable audit storage, a centralized monitoring stack, or a
production security approval.
