from acc_agent_gate import AgentGate, AuditLog, MockCampaignInstance, load_policy
from acc_agent_gate.approval_store import PersistentApprovalStore
from acc_agent_gate.policy_server import build_server


def make_server(tmp_path):
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())
    store = PersistentApprovalStore(tmp_path / "approval.sqlite3")
    return build_server(gate, store), gate, store


def test_preflight_approves_clean_delivery_but_never_authorizes_execution(tmp_path):
    server, gate, _ = make_server(tmp_path)
    result = server._tool_manager._tools["campaign_preflight_check"].fn("DM_BF26_HR")
    assert result.decision == "APPROVE"
    assert result.execution_authorized is False
    assert result.audit_fingerprint == gate.audit.entries[-1]["hash"]


def test_preflight_blocks_delivery_with_mandatory_qa_failure(tmp_path):
    server, _, _ = make_server(tmp_path)
    result = server._tool_manager._tools["campaign_preflight_check"].fn("DM_BF26_SI")
    assert result.decision == "BLOCK"
    assert "unsubscribe_link" in result.checks_failed
    assert result.execution_authorized is False


def test_execution_request_creates_durable_human_approval_record(tmp_path):
    server, gate, store = make_server(tmp_path)
    result = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_HR")
    assert result.decision == "PENDING_HUMAN_APPROVAL"
    assert result.approval_requested is True
    assert result.approval_ticket
    assert result.execution_authorized is False
    assert gate.backend.deliveries["DM_BF26_HR"].state == "ready"
    request = store.get_request(result.approval_ticket)
    assert request["status"] == "PENDING"
    assert request["payload"]["delivery_id"] == "DM_BF26_HR"
    assert request["payload_sha256"]
    assert request["policy_sha256"]
    assert request["execution_authorized"] is False


def test_blocked_execution_request_does_not_create_ticket_or_send(tmp_path):
    server, gate, store = make_server(tmp_path)
    result = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_SI")
    assert result.decision == "BLOCK"
    assert result.approval_ticket is None
    assert store.list_requests() == []
    assert gate.backend.deliveries["DM_BF26_SI"].state == "ready"


def test_audit_verification_tool_reports_valid_chain(tmp_path):
    server, _, _ = make_server(tmp_path)
    server._tool_manager._tools["campaign_preflight_check"].fn("DM_BF26_HR")
    result = server._tool_manager._tools["audit_chain_verify"].fn()
    assert result.valid is True
    assert result.entries == 1
    assert len(result.head) == 64
