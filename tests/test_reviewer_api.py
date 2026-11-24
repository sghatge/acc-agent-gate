import json
import threading
import urllib.error
import urllib.request

import pytest

from acc_agent_gate.approval_store import PersistentApprovalStore
from acc_agent_gate.reviewer_api import create_server, token_sha256


@pytest.fixture
def api(tmp_path):
    store = PersistentApprovalStore(tmp_path / "approval.sqlite3")
    item = store.create_request(
        source_ticket="APR-SOURCE",
        campaign_id="DM_BF26_HR",
        requester="mcp-policy-client",
        payload={"delivery_id": "DM_BF26_HR", "target_count": 10000},
        policy={"version": 1},
        approvals_required=1,
        allowed_roles=["market_owner"],
    )
    token = "reviewer-secret-token-value-with-at-least-32-chars"
    credentials = {
        token_sha256(token): {"reviewer": "market-owner-01", "role": "market_owner"}
    }
    server = create_server(
        host="127.0.0.1", port=0, credential_hashes=credentials, approval_store=store
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, item, token, store
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def call(server, path, token=None, method="GET", body=None):
    url = f"http://127.0.0.1:{server.server_port}{path}"
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health_is_public_but_reports_review_only(api):
    server, _, _, _ = api
    status, body = call(server, "/health")
    assert status == 200
    assert body["execution_scope"] == "review_only"


def test_approval_list_requires_authentication(api):
    server, _, _, _ = api
    status, body = call(server, "/api/approvals")
    assert status == 401
    assert body["error"] == "unauthorized"


def test_authenticated_reviewer_can_list_only_role_eligible_requests(api):
    server, item, token, _ = api
    status, body = call(server, "/api/approvals", token)
    assert status == 200
    assert body["count"] == 1
    assert body["items"][0]["ticket"] == item["ticket"]
    assert body["execution_authorized"] is False


def test_authenticated_decision_uses_server_side_reviewer_identity(api):
    server, item, token, store = api
    status, body = call(
        server, f"/api/approvals/{item['ticket']}/decision", token,
        method="POST", body={"decision": "APPROVE", "reason": "QA evidence reviewed"},
    )
    assert status == 200
    assert body["execution_authorized"] is False
    record = store.get_request(item["ticket"])
    assert record["status"] == "APPROVED"
    assert record["decisions"][0]["reviewer"] == "market-owner-01"
    assert record["decisions"][0]["role"] == "market_owner"


def test_client_cannot_override_reviewer_identity_or_role(api):
    server, item, token, store = api
    status, body = call(
        server, f"/api/approvals/{item['ticket']}/decision", token,
        method="POST",
        body={"decision": "APPROVE", "reviewer": "admin", "role": "admin"},
    )
    assert status == 400
    assert body["error"] == "unexpected_fields"
    assert store.get_request(item["ticket"])["status"] == "PENDING"


def test_invalid_decision_is_rejected(api):
    server, item, token, store = api
    status, _ = call(
        server, f"/api/approvals/{item['ticket']}/decision", token,
        method="POST", body={"decision": "EXECUTE"},
    )
    assert status == 400
    assert store.get_request(item["ticket"])["status"] == "PENDING"


def test_unauthorized_role_cannot_view_ticket(api):
    server, item, _, store = api
    other_token = "second-reviewer-secret-value-with-at-least-32-chars"
    server.server_close()
    server.shutdown()
    # Replace fixture server with one whose identity has a non-eligible role.
    credentials = {
        token_sha256(other_token): {"reviewer": "viewer-01", "role": "viewer"}
    }
    replacement = create_server(
        host="127.0.0.1", port=0, credential_hashes=credentials, approval_store=store
    )
    thread = threading.Thread(target=replacement.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = call(replacement, f"/api/approvals/{item['ticket']}", other_token)
        assert status == 404
        assert body["error"] == "approval_not_found"
    finally:
        replacement.shutdown()
        replacement.server_close()
        thread.join(timeout=2)
