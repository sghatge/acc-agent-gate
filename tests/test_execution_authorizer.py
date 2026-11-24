from datetime import datetime, timedelta, timezone

import pytest

from acc_agent_gate import AgentGate, AuditLog, MockCampaignInstance, load_policy
from acc_agent_gate.approval_store import PersistentApprovalStore
from acc_agent_gate.execution_authorizer import AuthorizationError, ExecutionAuthorizer
from acc_agent_gate.policy_server import build_server


SECRET = "phase-four-test-signing-secret-with-more-than-32-bytes"


def setup_flow(tmp_path, *, clock=None):
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())
    store = PersistentApprovalStore(tmp_path / "approvals.sqlite3")
    server = build_server(gate, store)
    request = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_HR")
    assert request.approval_ticket
    store.decide(
        request.approval_ticket,
        reviewer="market-owner-01",
        role="market_owner",
        decision="APPROVE",
        reason="QA evidence reviewed",
    )
    authorizer = ExecutionAuthorizer(
        gate=gate,
        approval_store=store,
        secret=SECRET,
        replay_db=tmp_path / "replay.sqlite3",
        clock=clock,
    )
    return gate, store, request.approval_ticket, authorizer


def test_approved_request_issues_bound_short_lived_permit_and_executes_once(tmp_path):
    gate, _, ticket, authorizer = setup_flow(tmp_path)
    token = authorizer.issue(ticket, ttl_seconds=60)
    assert gate.backend.deliveries["DM_BF26_HR"].state == "ready"

    result = authorizer.execute(token)
    assert result["execution_authorized"] is True
    assert result["permit_consumed"] is True
    assert result["result"]["status"] == "sent"
    assert gate.backend.deliveries["DM_BF26_HR"].state == "sent"
    assert len(gate.backend.sent_log) == 1

    with pytest.raises(AuthorizationError, match="already been consumed"):
        authorizer.execute(token)
    assert len(gate.backend.sent_log) == 1


def test_tampered_signature_is_rejected_without_send(tmp_path):
    gate, _, ticket, authorizer = setup_flow(tmp_path)
    token = authorizer.issue(ticket)
    body, signature = token.split(".")
    changed = body[:-1] + ("A" if body[-1] != "A" else "B")
    with pytest.raises(AuthorizationError, match="signature"):
        authorizer.execute(changed + "." + signature)
    assert gate.backend.sent_log == []


def test_expired_permit_is_rejected(tmp_path):
    now = [datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)]
    gate, _, ticket, authorizer = setup_flow(tmp_path, clock=lambda: now[0])
    token = authorizer.issue(ticket, ttl_seconds=30)
    now[0] += timedelta(seconds=31)
    with pytest.raises(AuthorizationError, match="expired"):
        authorizer.execute(token)
    assert gate.backend.sent_log == []


def test_changed_audience_invalidates_permit(tmp_path):
    gate, _, ticket, authorizer = setup_flow(tmp_path)
    token = authorizer.issue(ticket)
    gate.backend.deliveries["DM_BF26_HR"].target_count += 1
    with pytest.raises(AuthorizationError, match="audience size changed"):
        authorizer.execute(token)
    assert gate.backend.sent_log == []


def test_policy_change_invalidates_permit(tmp_path):
    gate, _, ticket, authorizer = setup_flow(tmp_path)
    token = authorizer.issue(ticket)
    gate.policy["kill_switch"] = True
    with pytest.raises(AuthorizationError, match="Policy changed"):
        authorizer.execute(token)
    assert gate.backend.sent_log == []


def test_audit_tampering_invalidates_permit(tmp_path):
    gate, _, ticket, authorizer = setup_flow(tmp_path)
    token = authorizer.issue(ticket)
    gate.audit.entries[0]["reason"] = "tampered"
    with pytest.raises(AuthorizationError, match="Audit chain integrity"):
        authorizer.execute(token)
    assert gate.backend.sent_log == []


def test_unapproved_ticket_cannot_issue_permit(tmp_path):
    gate = AgentGate(MockCampaignInstance(), load_policy(), AuditLog())
    store = PersistentApprovalStore(tmp_path / "approvals.sqlite3")
    server = build_server(gate, store)
    request = server._tool_manager._tools["campaign_request_execution"].fn("DM_BF26_HR")
    authorizer = ExecutionAuthorizer(
        gate=gate, approval_store=store, secret=SECRET,
        replay_db=tmp_path / "replay.sqlite3",
    )
    with pytest.raises(AuthorizationError, match="not fully approved"):
        authorizer.issue(request.approval_ticket)
    assert gate.backend.sent_log == []


def test_permit_lifetime_is_bounded(tmp_path):
    _, _, ticket, authorizer = setup_flow(tmp_path)
    with pytest.raises(AuthorizationError, match="lifetime"):
        authorizer.issue(ticket, ttl_seconds=301)


def test_modified_approval_payload_snapshot_is_rejected(tmp_path):
    gate, store, ticket, authorizer = setup_flow(tmp_path)
    with store._connect() as db:
        db.execute(
            "UPDATE approval_requests SET payload_json=? WHERE ticket=?",
            ('{"delivery_id":"DM_BF26_HR","market":"HR","target_count":1,"audit_fingerprint":"forged"}', ticket),
        )
    with pytest.raises(AuthorizationError, match="payload integrity"):
        authorizer.issue(ticket)
    assert gate.backend.sent_log == []
