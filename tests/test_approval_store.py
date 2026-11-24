import pytest

from acc_agent_gate.approval_store import (
    ApprovalConflict,
    ApprovalNotFound,
    PersistentApprovalStore,
)


@pytest.fixture
def store(tmp_path):
    return PersistentApprovalStore(tmp_path / "approvals.sqlite3")


def request(store, required=1):
    return store.create_request(
        source_ticket="APR-001",
        campaign_id="DM_BF26_HR",
        requester="mcp-policy-client",
        payload={"delivery_id": "DM_BF26_HR", "target_count": 12000},
        policy={"version": "test-v1", "require_qa": "pass"},
        approvals_required=required,
        allowed_roles=["market_owner", "crm_ops_lead"],
    )


def test_request_survives_store_restart(tmp_path):
    path = tmp_path / "approvals.sqlite3"
    first = PersistentApprovalStore(path)
    created = request(first)
    restarted = PersistentApprovalStore(path)
    loaded = restarted.get_request(created["ticket"])
    assert loaded["status"] == "PENDING"
    assert loaded["payload_sha256"] == created["payload_sha256"]
    assert loaded["policy_sha256"] == created["policy_sha256"]
    assert loaded["execution_authorized"] is False


def test_requester_cannot_approve_own_request(store):
    item = request(store)
    with pytest.raises(ApprovalConflict, match="own request"):
        store.decide(item["ticket"], reviewer="mcp-policy-client",
                     role="market_owner", decision="APPROVE")


def test_unauthorized_role_cannot_approve(store):
    item = request(store)
    with pytest.raises(ApprovalConflict, match="not authorized"):
        store.decide(item["ticket"], reviewer="reviewer-1",
                     role="viewer", decision="APPROVE")


def test_dual_approval_requires_two_distinct_reviewers(store):
    item = request(store, required=2)
    partial = store.decide(item["ticket"], reviewer="reviewer-1",
                           role="market_owner", decision="APPROVE")
    assert partial["status"] == "PENDING"
    assert partial["execution_authorized"] is False
    complete = store.decide(item["ticket"], reviewer="reviewer-2",
                            role="crm_ops_lead", decision="APPROVE")
    assert complete["status"] == "APPROVED"
    assert len(complete["decisions"]) == 2
    assert complete["execution_authorized"] is False


def test_same_reviewer_cannot_approve_twice(store):
    item = request(store, required=2)
    store.decide(item["ticket"], reviewer="reviewer-1",
                 role="market_owner", decision="APPROVE")
    with pytest.raises(ApprovalConflict, match="only once"):
        store.decide(item["ticket"], reviewer="reviewer-1",
                     role="market_owner", decision="APPROVE")


def test_rejection_is_terminal(store):
    item = request(store)
    rejected = store.decide(item["ticket"], reviewer="reviewer-1",
                            role="market_owner", decision="REJECT",
                            reason="Proof not signed")
    assert rejected["status"] == "REJECTED"
    with pytest.raises(ApprovalConflict, match="no longer pending"):
        store.decide(item["ticket"], reviewer="reviewer-2",
                     role="crm_ops_lead", decision="APPROVE")


def test_unknown_ticket_fails_closed(store):
    with pytest.raises(ApprovalNotFound):
        store.decide("APR-NOT-FOUND", reviewer="reviewer-1",
                     role="market_owner", decision="APPROVE")
