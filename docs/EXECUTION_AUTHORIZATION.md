# Phase 4 — Execution-time revalidation and single-use authorization

## Scope

Phase 4 introduces a local authorization-evidence primitive for the durable
human approval ledger. It does **not** execute Adobe Campaign actions, call
the Campaign backend, or expose an execution endpoint.

The service issues a short-lived HMAC-SHA256 token only when it can verify all
of the following:

1. The approval ticket exists and is in the APPROVED state.
2. The required number of distinct reviewers approved, each with a role
   permitted by the approval snapshot; the requester did not approve.
3. The canonical approved payload digest still matches the stored digest.
4. The current deterministic policy digest still matches the policy snapshot.
5. The original delivery.send request is present in a valid audit hash chain,
   and its fingerprint matches the fingerprint embedded in the approved payload.
6. The current delivery remains in the expected ready state, with unchanged
   market and target count.
7. The gate re-runs current send policy and QA, and still returns
   needs_approval with the same approval count.

## Token behavior

- HMAC-SHA256 signed; signing key must be at least 32 bytes.
- Default lifetime: 120 seconds; maximum configurable lifetime: 300 seconds.
- Bound to ticket, payload digest, policy digest, and original audit fingerprint.
- A SQLite-backed token registry atomically changes each token from
  issued to consumed; replay is rejected.
- Token consumption repeats approval, policy, audit, delivery, and QA checks
  before the atomic one-time state transition.
- The response explicitly reports execution_performed: false.

## Local usage

The class is SingleUseAuthorizationService in
acc_agent_gate.execution_authorization.

~~~python
service = SingleUseAuthorizationService(
    approval_store=approval_store,
    gate=agent_gate,
    database="authorization_tokens.sqlite3",
    signing_key=os.environ["ACC_GATE_AUTH_SIGNING_KEY"],
    ttl_seconds=120,
)
token = service.issue(approved_ticket)
evidence = service.consume(token)
assert evidence["authorized"] is True
assert evidence["execution_performed"] is False
~~~

Keep ACC_GATE_AUTH_SIGNING_KEY out of source control and use a cryptographically
random value with at least 32 bytes of entropy. The token is a proof artifact,
not permission to bypass the deterministic gate.

## Explicit production boundary

This phase intentionally does not connect token consumption to
AgentGate._execute, AgentGate.approve, the MCP tools, or a real Campaign
instance. No remote endpoint is added. The current Campaign backend remains
synthetic. Before any real execution integration, add an independently
reviewed execution adapter that accepts only a consumed authorization record,
revalidates the exact payload immediately before dispatch, enforces an
idempotency key at the provider boundary, and records the provider result in
durable centralized audit storage.

Run the focused suite:

~~~bash
python -m pytest -q tests/test_execution_authorization.py
~~~
