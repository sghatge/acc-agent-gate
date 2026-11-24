# MCP Policy Server — governed approval and execution lifecycle

The typed MCP facade delegates every Campaign operation to the deterministic
`AgentGate`. The gate remains the policy decision authority; the MCP client
cannot approve its own request or override policy.

## Approval lifecycle

1. The MCP client calls `campaign_preflight_check`.
2. If deterministic QA passes, the client may call
   `campaign_request_execution`.
3. A blocked request creates no approval record.
4. An eligible request is persisted in the SQLite approval ledger with a
   durable ticket, source ticket, campaign/delivery ID, canonical payload
   digest, policy digest, required reviewer count and allowed reviewer roles.
5. Human decisions are recorded transactionally. The requester cannot approve
   their own request; reviewers must be distinct and authorized by the saved
   role snapshot. Rejection is terminal.

## Authenticated reviewer surface — Phase 3

The authenticated reviewer API is implemented in
`acc_agent_gate.reviewer_api`. Reviewer identity and role are derived from
server-side hashed bearer credentials, not client-supplied actor headers.
The API enforces role-scoped ticket visibility and records APPROVE/REJECT
decisions. It remains a review surface; an approval is not by itself an
execution permit.

## Single-use authorization — Phase 4

`acc_agent_gate.execution_authorizer.ExecutionAuthorizer` issues a
short-lived HMAC-SHA256 permit only after revalidating:

- required distinct human approvals and separation of duties;
- canonical payload and current policy digests;
- audit-chain integrity and the original send-request fingerprint;
- current delivery identity, market, target count and ready state;
- current deterministic policy and QA decision.

The permit is bound to the approved request and has a bounded lifetime. Its
JTI is recorded in a SQLite replay registry; the permit can be consumed only
once. Consumption repeats the checks before the synthetic backend action.
Tampering, policy drift, QA failure, delivery changes, expiry and replay fail
closed.

## Governance Control Room — Phase 5

`streamlit_app.py` provides a hands-on synthetic walkthrough of campaign
selection, QA, review request, reviewer decision, permit issuance and
single-use consumption. The page is a portfolio demonstration, not a
production operator console. Its bundled Campaign backend is synthetic.

## Configuration

- `ACC_GATE_POLICY`: optional policy YAML path.
- `ACC_GATE_AUDIT`: hash-chained audit JSONL path.
- `ACC_GATE_APPROVAL_DB`: SQLite database path.
- `ACC_GATE_AUTH_SIGNING_KEY`: strong secret for a separately configured
  authorization service; never commit it or place it in an agent prompt.

Use a cryptographically random signing key of at least 32 bytes. Protect
SQLite files with filesystem permissions and durable storage appropriate to
the environment.

## Critical execution boundary

The Streamlit demonstration can execute only against the bundled synthetic
Campaign backend. The authenticated OPSFORGE API is advisory-only. There is
no production Adobe Campaign connector, no real CRM write path and no
enterprise identity integration in this repository.

Before organizational production use, require an independently reviewed
Campaign adapter, provider-side idempotency, execution-time payload
revalidation, OIDC/Entra ID, centralized durable audit retention, backup and
restore testing, TLS, edge rate limits, monitoring, data-residency review and
security approval.

## Tests

```bash
python -m pytest -q
```
