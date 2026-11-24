from acc_agent_gate import AgentGate, AuditLog, MockCampaignInstance, load_policy
from acc_agent_gate.policy_server import build_server


def make_server():
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())
    return build_server(gate), gate


def test_preflight_approves_clean_delivery_but_never_authorizes_execution():
    server, gate = make_server()
    # Call the registered tool function through FastMCP's tool registry.
    result = server._tool_manager._tools["campaign_preflight_check"].fn("DM_BF26_HR")
    assert result.decision == "APPROVE"
    assert result.execution_authorized is False
    assert result.audit_fingerprint == gate.audit.entries[-1]["hash"]


def test_preflight_blocks_delivery_with_mandatory_qa_failure():
    server, _ = make_server()
    result = server._tool_manager._tools["campaign_preflight_check"].fn("DM_BF26_SI")
    assert result.decision == "BLOCK"
    assert "unsubscribe_link" in result.checks_failed
    assert result.execution_authorized is False


def test_execution_request_only_queues_human_approval():
    server, gate = make_server()
    result = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_HR")
    assert result.decision == "PENDING_HUMAN_APPROVAL"
    assert result.submitted is True
    assert result.approval_ticket
    assert result.execution_authorized is False
    assert gate.backend.deliveries["DM_BF26_HR"].state == "ready"


def test_blocked_execution_request_does_not_create_ticket_or_send():
    server, gate = make_server()
    result = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_SI")
    assert result.decision == "BLOCK"
    assert result.approval_ticket is None
    assert gate.backend.deliveries["DM_BF26_SI"].state == "ready"


def test_audit_verification_tool_reports_valid_chain():
    server, _ = make_server()
    server._tool_manager._tools["campaign_preflight_check"].fn("DM_BF26_HR")
    result = server._tool_manager._tools["audit_chain_verify"].fn()
    assert result.valid is True
    assert result.entries == 1
    assert len(result.head) == 64
