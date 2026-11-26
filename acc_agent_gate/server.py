"""Fail-closed MCP interface for the ACC Agent Gate.

Run with: python -m acc_agent_gate.server
Transport: stdio. Standard output is reserved for MCP JSON-RPC messages.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Literal

from .audit import AuditLog
from .gate import AgentGate, load_policy

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

logging.basicConfig(
    level=os.environ.get("ACC_GATE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("acc_agent_gate.mcp")

gate = AgentGate(
    policy=load_policy(os.environ.get("ACC_GATE_POLICY")),
    audit=AuditLog(os.environ.get("ACC_GATE_AUDIT", "audit.jsonl")),
)
mcp = _Server(
    "acc-agent-gate",
    instructions=(
        "ACC Agent Gate is a fail-closed governance MCP server for Adobe Campaign Classic. "
        "It exposes seven policy-gated tools: campaign_discover, schema_browse, query_run, "
        "delivery_qa, delivery_send, workflow_control, and js_execute. Start with "
        "campaign_discover, then inspect schemas before bounded queries. Run delivery_qa "
        "before delivery_send. A needs_approval result is never permission to execute; "
        "human approval is deliberately not exposed as an agent tool. js_execute only "
        "analyses scripts and never executes them. All actions use the configured YAML "
        "policy and append to a hash-chained audit log. The bundled backend is synthetic "
        "and does not connect to a production Adobe Campaign instance. Never claim that "
        "a Campaign operation was executed unless a separately configured, human-governed "
        "adapter confirms it."
    ),
)


def _out(result: dict[str, Any]) -> str:
    """Serialize a gate result without writing to the MCP protocol stream."""
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def _input_error(code: str, message: str, remediation: str) -> str:
    """Return a consistent, actionable validation error."""
    return _out({
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "rule": "mcp_input_validation",
            "decision": "block",
            "remediation": remediation,
            "human_approval_required": False,
        },
    })


@mcp.tool()
def campaign_discover() -> str:
    """Describe the configured Campaign instance and its available resources.

    Purpose & outcome: Return the instance overview, market metadata, schema inventory and counts through the policy gate.
    When to use / boundaries: Call before schema browsing or query planning; this is read-only and does not replace authorization for later actions.
    Parameters: No parameters.
    Failure & next step: A blocked result includes the policy rule and reason; review the named YAML rule with the Campaign governance owner before retrying.
    """
    return _out(gate.call("campaign.discover", {}, agent="mcp-client"))


@mcp.tool()
def schema_browse(schema: str) -> str:
    """Inspect the fields exposed by one Campaign schema through the governance gate.

    Purpose & outcome: Return approved schema metadata for a single Campaign schema.
    When to use / boundaries: Call after campaign_discover and before constructing a query; never infer field names or use this tool to read recipient data.
    Parameters: schema is a non-empty Campaign schema identifier such as nms:recipient, 1-128 characters.
    Failure & next step: A blocked result identifies the policy rule and reason; confirm the identifier and ask the policy owner to review any YAML allow-list change.
    """
    if not schema.strip() or len(schema) > 128:
        return _input_error("invalid_schema", "schema must be 1-128 characters.", "Supply one valid Campaign schema identifier.")
    return _out(gate.call("schema.browse", {"schema": schema.strip()}, agent="mcp-client"))


@mcp.tool()
def query_run(schema: str, select_csv: str, where_json: str = "{}", group_by: str = "", limit: int = 100) -> str:
    """Run a bounded, read-only Campaign query through the policy gate.

    Purpose & outcome: Retrieve approved fields with PII masking, row caps and policy-enforced read-only semantics.
    When to use / boundaries: Call only after campaign_discover and schema_browse; this gate must run before any downstream Campaign query action. Never use it for writes, exports or unbounded extraction.
    Parameters: schema is one identifier (1-128 characters); select_csv is 1-20 comma-separated field names; where_json is a flat JSON object string (default {}); group_by is one optional field name; limit is an integer from 1 through 1000.
    Failure & next step: Invalid inputs return mcp_input_validation. A policy block returns the YAML rule ID and reason; narrow the query or request a documented policy-owner review. Masking and row-limit decisions remain authoritative.
    """
    if not schema.strip() or len(schema) > 128:
        return _input_error("invalid_schema", "schema must be 1-128 characters.", "Supply one valid Campaign schema identifier.")
    fields = [item.strip() for item in select_csv.split(",") if item.strip()]
    if not fields or len(fields) > 20 or any(len(item) > 128 for item in fields):
        return _input_error("invalid_select", "select_csv must contain 1-20 comma-separated field names.", "Provide a bounded list of schema field names.")
    if not 1 <= limit <= 1000:
        return _input_error("invalid_limit", "limit must be between 1 and 1000.", "Choose a limit within the allowed range.")
    try:
        where = json.loads(where_json or "{}")
    except json.JSONDecodeError as exc:
        return _input_error("invalid_where_json", f"where_json is not valid JSON: {exc.msg}.", 'Pass a JSON object string, for example {"@country":"HR"}.')
    if not isinstance(where, dict) or any(isinstance(v, (dict, list)) for v in where.values()):
        return _input_error("invalid_where_shape", "where_json must be a flat JSON object.", "Use primitive string, number, boolean or null filter values.")
    args = {"schema": schema.strip(), "select": fields, "where": where, "group_by": group_by.strip() or None, "limit": limit}
    return _out(gate.call("query.run", args, agent="mcp-client"))


@mcp.tool()
def delivery_qa(delivery_id: str) -> str:
    """Run deterministic pre-send quality and compliance checks for one delivery.

    Purpose & outcome: Return delivery QA status, blockers, warnings and remediation evidence.
    When to use / boundaries: Call before requesting any delivery send; a clean QA result is eligibility for human review, not send authorization.
    Parameters: delivery_id is one non-empty delivery identifier, maximum 128 characters.
    Failure & next step: A blocked result identifies the YAML rule and reason; fix the named QA evidence and rerun QA. Do not bypass a blocker with a prompt override.
    """
    if not delivery_id.strip() or len(delivery_id) > 128:
        return _input_error("invalid_delivery_id", "delivery_id must be 1-128 characters.", "Supply one valid delivery identifier.")
    return _out(gate.call("delivery.qa", {"delivery_id": delivery_id.strip()}, agent="mcp-client"))


@mcp.tool()
def delivery_send(delivery_id: str) -> str:
    """Submit one delivery-send request to the gate; this tool never grants human approval.

    Purpose & outcome: Evaluate send eligibility and, only when policy permits, create a human-approval request.
    When to use / boundaries: Call delivery_qa first, then call this gate before any downstream send action. Never interpret needs_approval as permission to send.
    Parameters: delivery_id is one non-empty delivery identifier, maximum 128 characters.
    Failure & next step: QA or policy blocks include the blocking rule and reason; remediate evidence or ask the designated human approver/policy owner. Approval remains outside the MCP tool surface.
    """
    if not delivery_id.strip() or len(delivery_id) > 128:
        return _input_error("invalid_delivery_id", "delivery_id must be 1-128 characters.", "Supply one valid delivery identifier.")
    return _out(gate.call("delivery.send", {"delivery_id": delivery_id.strip()}, agent="mcp-client"))


@mcp.tool()
def workflow_control(workflow: str, action: Literal["start", "pause", "stop"]) -> str:
    """Request a policy-checked lifecycle action for one Campaign workflow.

    Purpose & outcome: Evaluate a start, pause or stop request against protected-workflow and session-control policies.
    When to use / boundaries: Call this gate before every downstream workflow control action; protected privacy, consent and compliance workflows must not be changed by an agent.
    Parameters: workflow is one non-empty identifier, maximum 128 characters; action must be exactly start, pause or stop.
    Failure & next step: A blocked result names the YAML rule and reason; do not retry with a different spelling or bypass. Obtain governance-owner review and a reviewed policy change where appropriate.
    """
    if not workflow.strip() or len(workflow) > 128:
        return _input_error("invalid_workflow", "workflow must be 1-128 characters.", "Supply one valid workflow identifier.")
    return _out(gate.call("workflow.control", {"workflow": workflow.strip(), "action": action}, agent="mcp-client"))


@mcp.tool()
def js_execute(script: str) -> str:
    """Analyse a proposed Campaign server-side JavaScript snippet without executing it.

    Purpose & outcome: Classify script risks and return a dry-run or block decision; this MCP tool does not execute JavaScript.
    When to use / boundaries: Call before considering any downstream JS-related Campaign action. Treat writes, sends, system commands and network egress as prohibited unless separately reviewed and implemented by a human-controlled adapter.
    Parameters: script is one non-empty script string up to 20000 characters; do not include credentials or personal data.
    Failure & next step: A blocked result identifies the analyzer finding or YAML rule and reason; remove the risky operation and request security-owner review. Never treat dry_run as execution approval.
    """
    if not script.strip() or len(script) > 20000:
        return _input_error("invalid_script", "script must be 1-20000 characters.", "Provide a bounded script without secrets or personal data.")
    return _out(gate.call("js.execute", {"script": script}, agent="mcp-client"))


def main() -> None:
    """Start the MCP stdio server; diagnostic logs are directed to stderr."""
    logger.info("Starting ACC Agent Gate MCP server (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
