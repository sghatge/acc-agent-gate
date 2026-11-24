# Phase 4 — Signed Execution Authorization

Phase 4 introduces a small authorization library for the synthetic Campaign
backend. It is deliberately separate from the MCP agent surface and the
human-review HTTP API.

## Security model

An APPROVED ledger ticket is still only human-review evidence. A trusted
execution service must explicitly call `ExecutionAuthorizer.issue(ticket)`
to obtain a short-lived permit, then pass that permit to
`ExecutionAuthorizer.execute(token)`.

The permit is HMAC-SHA256 signed and binds:
- approval ticket and campaign/delivery ID;
- approved payload SHA-256 and current policy SHA-256;
- original send-request audit fingerprint;
- distinct human approver identities and roles;
- issuer, audience, schema version, issue time, expiry and a random JTI.

The default maximum lifetime is 300 seconds (the call default is 120 seconds).
The signing key must contain at least 32 bytes and must be supplied from a
secret manager or environment configuration by the hosting service. Never
commit the key or put it in an agent prompt.

## Checks at issuance and consumption

Both operations fail closed unless:
- the durable ticket is APPROVED and has the required distinct approvals;
- each decision is APPROVE and its role is allowed by the saved policy snapshot;
- the requester is not an approver;
- the current policy digest matches the policy digest captured at request time;
- the complete audit chain verifies and contains the exact original
  `delivery.send` request fingerprint/ticket;
- campaign ID, market, audience size and ready state still match the approved
  snapshot;
- current deterministic QA/policy evaluation still returns
  `needs_approval` with the same approval threshold.

Consumption atomically inserts the token JTI into a durable SQLite replay
table before the side effect. A duplicate token is rejected. If the process
fails after the JTI is claimed, the permit remains consumed; this intentionally
prefers at-most-once execution over an unsafe automatic retry.

## Integration sketch

```python
from acc_agent_gate import AgentGate, AuditLog, load_policy
from acc_agent_gate.approval_store import PersistentApprovalStore
from acc_agent_gate.execution_authorizer import ExecutionAuthorizer

gate = AgentGate(policy=load_policy(), audit=AuditLog("audit.jsonl"))
approvals = PersistentApprovalStore("approval_queue.sqlite3")

# Inject a secret from a managed secret store; never hardcode it.
authorizer = ExecutionAuthorizer(
    gate=gate,
    approval_store=approvals,
    secret=execution_signing_secret,
    replay_db="execution_replay.sqlite3",
)

permit = authorizer.issue("APR-APPROVEDTICKET", ttl_seconds=120)
result = authorizer.execute(permit)
```

The example ticket is illustrative. The hosting service must authenticate and
authorize its operator before calling `issue`; this module does not expose an
agent-callable issuance tool or an unauthenticated network endpoint.

## Explicit boundaries

- This phase has no production Adobe Campaign adapter and sends only through
  the bundled synthetic backend.
- The MCP policy server cannot issue or consume execution permits.
- The reviewer API cannot issue or consume execution permits.
- HMAC provides integrity/authenticity, not confidentiality; the permit payload
  is encoded, not encrypted. Treat permits as bearer credentials.
- Use TLS for transport, strict network isolation, secret rotation, backups,
  monitoring and an identity-aware operator service before any remote use.
- A consumed permit is not automatically recoverable after a crash. Reconcile
  the synthetic/real executor's idempotency state manually before issuing a
  new approval request.

This is a portfolio-grade reference implementation, not a production-ready
Campaign execution connector or a substitute for enterprise security review.
