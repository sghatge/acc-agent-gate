"""Typed MCP facade for ACC Agent Gate.

The deterministic AgentGate remains the decision authority. This module only
exposes safe, structured MCP tools; it does not add an agent-controlled
approval or execution bypass.

Run with:
    python -m acc_agent_gate.policy_server
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

from .audit import AuditLog
from .gate import AgentGate, load_policy

DecisionLabel = Literal["APPROVE", "BLOCK", "PENDING_HUMAN_APPROVAL"]


class CheckEvidence(BaseModel):
    rule_id: str
    status: Literal["PASS", "FAIL", "UNKNOWN", "WARN"]
    message: str


class PreflightResponse(BaseModel):
    campaign_id: str
    decision: Literal["APPROVE", "BLOCK"]
    approval_meaning: str
    execution_authorized: bool = False
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: list[CheckEvidence] = Field(default_factory=list)
    audit_seq: int
    audit_fingerprint: str


class ExecutionRequestResponse(BaseModel):
    campaign_id: str
    decision: DecisionLabel
    submitted: bool
    execution_authorized: bool = False
    approval_ticket: str | None = None
    reason: str
    audit_seq: int
    audit_fingerprint: str


class AuditVerificationResponse(BaseModel):
    valid: bool
    entries: int
    broken_at: int | None = None
    head: str


def build_server(gate: AgentGate | None = None) -> FastMCP:
    """Build a server around an injectable gate (useful for tests)."""
    active_gate = gate or AgentGate(
        policy=load_policy(os.environ.get("ACC_GATE_POLICY")),
        audit=AuditLog(os.environ.get("ACC_GATE_AUDIT", "audit.jsonl")),
    )
    server = FastMCP("acc-agent-gate-policy")

    @server.tool()
    def campaign_preflight_check(delivery_id: str) -> PreflightResponse:
        """Run deterministic pre-send QA. APPROVE means eligible for human review, never execution authorization."""
        outcome = active_gate.call(
            "delivery.qa", {"delivery_id": delivery_id}, agent="mcp-policy-client"
        )
        qa = outcome["result"]
        blocked = qa["status"] == "fail"
        audit_entry = active_gate.audit.entries[-1]
        checks = [
            CheckEvidence(
                rule_id=item["id"],
                status="PASS" if item["passed"] else (
                    "WARN" if item["severity"] == "warning" else "FAIL"
                ),
                message=item["detail"],
            )
            for item in qa["checks"]
        ]
        return PreflightResponse(
            campaign_id=delivery_id,
            decision="BLOCK" if blocked else "APPROVE",
            approval_meaning=(
                "QA passed; eligible to request human approval. This is not send authorization."
                if not blocked else "Mandatory QA blocker(s) found; execution must remain blocked."
            ),
            execution_authorized=False,
            checks_passed=[item["id"] for item in qa["checks"] if item["passed"]],
            checks_failed=list(qa["blockers"]),
            warnings=list(qa["warnings"]),
            checks=checks,
            audit_seq=outcome["audit_seq"],
            audit_fingerprint=audit_entry["hash"],
        )

    @server.tool()
    def campaign_request_execution(delivery_id: str) -> ExecutionRequestResponse:
        """Request a governed send. A passing request is queued for human approval; this tool never approves or sends."""
        outcome = active_gate.call(
            "delivery.send", {"delivery_id": delivery_id}, agent="mcp-policy-client"
        )
        policy_decision = outcome["decision"]["decision"]
        result = outcome["result"]
        audit_entry = active_gate.audit.entries[-1]

        if policy_decision == "block":
            label: DecisionLabel = "BLOCK"
            reason = outcome["decision"]["reason"]
            ticket = None
        elif policy_decision == "needs_approval":
            label = "PENDING_HUMAN_APPROVAL"
            reason = outcome["decision"]["reason"]
            ticket = result.get("ticket")
        else:
            # Defensive: this endpoint must never silently execute a send.
            label = "BLOCK"
            reason = "Unexpected policy outcome; execution was not authorized by the MCP facade."
            ticket = None

        return ExecutionRequestResponse(
            campaign_id=delivery_id,
            decision=label,
            submitted=bool(ticket),
            execution_authorized=False,
            approval_ticket=ticket,
            reason=reason,
            audit_seq=outcome["audit_seq"],
            audit_fingerprint=audit_entry["hash"],
        )

    @server.tool()
    def audit_chain_verify() -> AuditVerificationResponse:
        """Verify the in-memory hash chain and return its current integrity status."""
        result = AuditLog.verify(active_gate.audit.entries)
        return AuditVerificationResponse(
            valid=result["valid"],
            entries=result["entries"],
            broken_at=result.get("broken_at"),
            head=result.get("head", ""),
        )

    # Expose the gate for local integration tests; it is not an MCP tool.
    server._acc_agent_gate = active_gate  # type: ignore[attr-defined]
    return server


mcp = build_server()

if __name__ == "__main__":
    mcp.run()
