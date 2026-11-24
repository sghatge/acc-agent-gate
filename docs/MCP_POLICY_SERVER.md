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

The MCP server exposes no approval or rejection tool. The durable store is
currently a service-layer primitive for a future authenticated reviewer
surface; it does not yet expose a web reviewer UI or HTTP decision endpoint.

## Critical execution boundary

**An APPROVED ledger record does not authorize or execute a Campaign send.**
This phase deliberately does not mint an execution token, call
`AgentGate.approve`, or invoke the Campaign backend. The existing in-process
`AgentGate` approval queue remains separate. Phase 3 must connect a
reviewer-authenticated surface to the policy re-check and execution path using
a signed, short-lived, single-use authorization bound to the exact payload,
policy digest and audit fingerprint. Until then, treat this phase as durable
review evidence only.

No production Adobe Campaign connector is included. The bundled backend and
examples remain synthetic.

## Tests

```bash
python -m pytest -q tests/test_approval_store.py tests/test_policy_server.py tests/test_gate.py
```
