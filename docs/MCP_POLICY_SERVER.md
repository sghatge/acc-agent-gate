# MCP Policy Server — Phase 1

A typed MCP interface over the existing ACC Agent Gate. The existing
`AgentGate`, policy-as-code, pre-send QA, approval queue and hash-chained
audit ledger remain the source of truth.

## Decision boundary

- `campaign_preflight_check` returns `APPROVE` only when deterministic QA
  has no blocking failures. APPROVE means **eligible for human review**, not
  permission to send.
- `campaign_request_execution` submits a send request to the existing gate.
  A clean request returns `PENDING_HUMAN_APPROVAL` with a ticket. A failed
  request returns `BLOCK`.
- `audit_chain_verify` verifies the current in-memory audit chain.

Human approvals are deliberately not exposed as MCP tools. The MCP client
cannot approve its own request, and this facade never executes a delivery.
The ticket is held in the existing in-process queue for this Phase 1
integration; a separate human approval surface is not yet connected to this
MCP process. Persistent queue and authenticated reviewer integration are
follow-on work. The existing gate re-checks policy when its approval method
is invoked.

## Run locally

```bash
pip install -r requirements.txt
python -m acc_agent_gate.policy_server
```

The server uses the MCP SDK's stdio transport by default. Point an MCP client
at the repository's Python environment:

```json
{
  "mcpServers": {
    "acc-agent-gate-policy": {
      "command": "python",
      "args": ["-m", "acc_agent_gate.policy_server"],
      "env": {
        "ACC_GATE_POLICY": "policy/default.yaml",
        "ACC_GATE_AUDIT": "audit.jsonl"
      }
    }
  }
}
```

## Structured tool outputs

| Tool | Purpose | Important output |
|---|---|---|
| `campaign_preflight_check` | Run deterministic pre-send QA | APPROVE/BLOCK, individual checks, audit fingerprint |
| `campaign_request_execution` | Request a governed send | BLOCK or PENDING_HUMAN_APPROVAL, ticket, audit fingerprint |
| `audit_chain_verify` | Verify audit integrity | validity, entry count, chain head |

All outputs explicitly include `execution_authorized: false` where relevant.

## Configuration

- `ACC_GATE_POLICY`: optional policy YAML path.
- `ACC_GATE_AUDIT`: audit JSONL path (defaults to `audit.jsonl`).

Use synthetic data only. The bundled backend is a mock Campaign instance;
this phase does not connect to or execute against a production Adobe Campaign
environment.

## Security notes and known limitations

- The policy engine is deterministic and fails closed for unknown tools.
- The audit chain is tamper-evident; it is not immutable storage or a digital
  signature. Protect the audit file and retain external copies for durable
  evidence.
- Approval tickets currently use the existing in-process approval queue and
  are not yet wired to a separate reviewer UI. A restart loses pending
  tickets. Production deployment requires a connected human approval
  surface, persistent storage, authenticated approver identity, authorization
  controls and concurrency-safe state transitions.
- This phase intentionally does not introduce execution tokens. A token is
  not a substitute for human authorization. Any future token must be
  cryptographically signed, single-use, short-lived, bound to the exact
  campaign payload and policy version, and revalidated at execution time.
- No campaign execution is exposed by this MCP facade.

## Tests

```bash
python -m pytest -q tests/test_policy_server.py tests/test_gate.py
```
