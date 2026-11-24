# MCP Policy Server — Phase 2 approval ledger

Phase 2 adds a durable SQLite-backed human approval ledger to the typed MCP
facade. The deterministic `AgentGate` remains the policy decision authority.

## Approval lifecycle

1. The MCP client calls `campaign_preflight_check`.
2. If deterministic QA passes, the client may call `campaign_request_execution`.
3. The gate evaluates the send request. A blocked request creates no approval record.
4. An eligible request is recorded in SQLite with a durable ticket, source ticket,
   campaign ID, request payload, payload SHA-256, policy SHA-256, required
   reviewer count, and the allowed reviewer roles.
5. Human decisions are recorded transactionally. The requester cannot approve
   their own request, a reviewer cannot decide the same ticket twice, roles are
   checked against the policy snapshot, and dual approval requires two distinct
   reviewers.
6. Rejection is terminal. Approval status is a review outcome only.

## Configuration

- `ACC_GATE_POLICY`: optional policy YAML path.
- `ACC_GATE_AUDIT`: hash-chained audit JSONL path.
- `ACC_GATE_APPROVAL_DB`: SQLite database path; defaults to
  `approval_queue.sqlite3`.

The database uses SQLite WAL mode, foreign keys, a busy timeout and
transactional state changes. Back it up and restrict filesystem permissions.
Use a durable volume in a hosted environment.

## Store API

The Python store is available as `PersistentApprovalStore`:

- `create_request(...)` persists an approval request and binds it to payload
  and policy digests.
- `get_request(ticket)` retrieves one request and its reviewer decisions.
- `list_requests(status, limit)` lists pending or historical requests.
- `decide(ticket, reviewer, role, decision, reason)` records an authorized
  human decision.

Phase 3 adds the authenticated reviewer HTTP API in
`acc_agent_gate.reviewer_api`. It derives reviewer identity and role from
server-side hashed bearer credentials, enforces role-scoped ticket visibility,
and records APPROVE/REJECT decisions. It remains review-only.

## Critical execution boundary

**An APPROVED ledger record does not authorize or execute a Campaign send.**
Phase 4 adds a local, HMAC-signed, short-lived, single-use authorization
evidence service. It revalidates the approval, exact payload and policy
fingerprints, original audit chain, current delivery state and current QA at
issuance and consumption. It atomically rejects token replay.

The authorization artifact is evidence only: it does not call
`AgentGate.approve`, invoke `AgentGate._execute`, or send a Campaign delivery.
No production Adobe Campaign connector is included; the bundled backend and
examples remain synthetic. See
[Phase 4 authorization design](EXECUTION_AUTHORIZATION.md).

No production Adobe Campaign connector is included. The bundled backend and
examples remain synthetic.

## Tests

```bash
python -m pytest -q tests/test_approval_store.py tests/test_policy_server.py tests/test_gate.py
```
