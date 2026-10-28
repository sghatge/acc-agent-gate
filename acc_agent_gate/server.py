"""MCP server exposing the *gated* Campaign tools.

Point Claude, Cursor or any MCP client at this server instead of directly at
Campaign. Every tool call goes through AgentGate first.

    python -m acc_agent_gate.server            # stdio transport

Approvals are deliberately NOT exposed as MCP tools: the agent can request
an action, but only a human (CLI / UI / ticketing hook) can approve it.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .audit import AuditLog
from .gate import AgentGate, load_policy

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

gate = AgentGate(policy=load_policy(os.environ.get("ACC_GATE_POLICY")),
                 audit=AuditLog(os.environ.get("ACC_GATE_AUDIT", "audit.jsonl")))
mcp = _Server("acc-agent-gate")


def _out(res: dict[str, Any]) -> str:
    return json.dumps(res, ensure_ascii=False, indent=2, default=str)


@mcp.tool(description="Describe the Campaign instance: markets, schemas, counts. Read-only.")
def campaign_discover() -> str:
    return _out(gate.call("campaign.discover", {}, agent="mcp-client"))


@mcp.tool(description="Show fields of a Campaign schema (e.g. nms:recipient). Read-only.")
def schema_browse(schema: str) -> str:
    return _out(gate.call("schema.browse", {"schema": schema}, agent="mcp-client"))


@mcp.tool(description="Run a read-only query. PII is masked, row counts are capped, writes are blocked.")
def query_run(schema: str, select: list[str], where: dict[str, Any] | None = None,
              group_by: str | None = None, limit: int = 100) -> str:
    args = {"schema": schema, "select": select, "where": where or {}, "group_by": group_by, "limit": limit}
    return _out(gate.call("query.run", args, agent="mcp-client"))


@mcp.tool(description="Run the pre-send QA gate on a delivery and return every check.")
def delivery_qa(delivery_id: str) -> str:
    return _out(gate.call("delivery.qa", {"delivery_id": delivery_id}, agent="mcp-client"))


@mcp.tool(description="Request a send. Blocked unless QA passes; otherwise queued for human approval.")
def delivery_send(delivery_id: str) -> str:
    return _out(gate.call("delivery.send", {"delivery_id": delivery_id}, agent="mcp-client"))


@mcp.tool(description="Request start/pause/stop on a workflow. Protected workflows are blocked.")
def workflow_control(workflow: str, action: str) -> str:
    return _out(gate.call("workflow.control", {"workflow": workflow, "action": action}, agent="mcp-client"))


@mcp.tool(description="Submit server-side JS. It is analysed and dry-run; writes/sends/egress are blocked.")
def js_execute(script: str) -> str:
    return _out(gate.call("js.execute", {"script": script}, agent="mcp-client"))


if __name__ == "__main__":
    mcp.run()
