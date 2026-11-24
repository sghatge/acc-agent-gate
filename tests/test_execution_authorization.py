import pytest

from acc_agent_gate import AgentGate, AuditLog, MockCampaignInstance, load_policy
from acc_agent_gate.approval_store import PersistentApprovalStore
from acc_agent_gate.policy_server import build_server
from acc_agent_gate.execution_authorization import AuthorizationDenied, SingleUseAuthorizationService


@pytest.fixture
def setup(tmp_path):
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())
    store = PersistentApprovalStore(tmp_path / "approvals.sqlite3")
    server = build_server(gate, store)
    result = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_HR")
    assert result.approval_ticket
    store.decide(
        result.approval_ticket, reviewer="market-owner-01", role="market_owner",
        decision="APPROVE", reason="Reviewed QA evidence",
    )
    service = SingleUseAuthorizationService(
        store, gate, tmp_path / "authorization.sqlite3",
        signing_key="test-signing-key-that-is-at-least-32-bytes-long",
        ttl_seconds=120, clock=lambda: 1_800_000_000,
    )
    return service, result.approval_ticket, gate, store


def test_approved_ticket_issues_and_consumes_one_time_authorization(setup):
    service, ticket, gate, _ = setup
    result = service.consume(service.issue(ticket))
    assert result["authorized"] is True
    assert result["execution_performed"] is False
    assert result["single_use"] is True
    assert gate.backend.deliveries["DM_BF26_HR"].state == "ready"


def test_token_cannot_be_replayed(setup):
    service, ticket, _, _ = setup
    token = service.issue(ticket)
    service.consume(token)
    with pytest.raises(AuthorizationDenied, match="already consumed"):
        service.consume(token)


def test_pending_request_cannot_issue_authorization(tmp_path):
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())
    store = PersistentApprovalStore(tmp_path / "approvals.sqlite3")
    server = build_server(gate, store)
    result = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_HR")
    service = SingleUseAuthorizationService(
        store, gate, tmp_path / "authorization.sqlite3",
        signing_key="test-signing-key-that-is-at-least-32-bytes-long",
    )
    with pytest.raises(AuthorizationDenied, match="fully approved"):
        service.issue(result.approval_ticket)


def test_policy_change_invalidates_authorization(setup):
    service, ticket, gate, _ = setup
    gate.policy["kill_switch"] = True
    with pytest.raises(AuthorizationDenied, match="Policy changed"):
        service.issue(ticket)


def test_delivery_change_invalidates_authorization(setup):
    service, ticket, gate, _ = setup
    gate.backend.deliveries["DM_BF26_HR"].target_count += 1
    with pytest.raises(AuthorizationDenied, match="Delivery details"):
        service.issue(ticket)


def test_qa_failure_at_revalidation_blocks_authorization(setup):
    service, ticket, gate, _ = setup
    gate.backend.deliveries["DM_BF26_HR"].proof_sent = False
    with pytest.raises(AuthorizationDenied, match="Current policy or QA"):
        service.issue(ticket)


def test_audit_tampering_blocks_authorization(setup):
    service, ticket, gate, _ = setup
    gate.audit.entries[0]["decision"] = "allow"
    with pytest.raises(AuthorizationDenied, match="Audit chain"):
        service.issue(ticket)


def test_expired_token_is_rejected(setup):
    service, ticket, _, _ = setup
    token = service.issue(ticket)
    service.clock = lambda: 1_800_000_121
    with pytest.raises(AuthorizationDenied, match="expired"):
        service.consume(token)


def test_invalid_signature_is_rejected(setup):
    service, ticket, _, _ = setup
    token = service.issue(ticket)
    with pytest.raises(AuthorizationDenied, match="signature"):
        service.consume(token + "x")


def test_signing_key_must_be_strong(tmp_path):
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())
    store = PersistentApprovalStore(tmp_path / "approvals.sqlite3")
    with pytest.raises(ValueError, match="32 bytes"):
        SingleUseAuthorizationService(
            store, gate, tmp_path / "authorization.sqlite3", signing_key="short"
        )
