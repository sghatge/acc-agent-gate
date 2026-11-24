import http.client
import json
import threading

import pytest

from opsforge.api import create_server
from opsforge.api_audit import verify_audit_log


TOKEN = "test-token-that-is-long-enough-for-api-authentication"


@pytest.fixture
def api_server(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        token=TOKEN,
        audit_path=str(tmp_path / "audit.jsonl"),
        allowed_origins={"https://sghatge.github.io"},
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield host, port, tmp_path / "audit.jsonl"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(api_server, method, path, payload=None, token=None, headers=None):
    host, port, _ = api_server
    connection = http.client.HTTPConnection(host, port, timeout=3)
    body = None if payload is None else json.dumps(payload)
    request_headers = dict(headers or {})
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    connection.request(method, path, body=body, headers=request_headers)
    response = connection.getresponse()
    result = json.loads(response.read().decode("utf-8"))
    status = response.status
    response_headers = dict(response.getheaders())
    connection.close()
    return status, result, response_headers


def test_health_is_public_and_describes_scope(api_server):
    status, body, _ = request(api_server, "GET", "/health")
    assert status == 200
    assert body["status"] == "healthy"
    assert body["execution_scope"] == "advisory_only"
    assert "marketing_analytics" in body["agents"]


def test_agent_execution_requires_bearer_token(api_server):
    status, body, _ = request(
        api_server,
        "POST",
        "/api/agents/marketing_analytics/run",
        {"campaigns": [{"name": "Launch", "sends": 100, "delivered": 98}]},
    )
    assert status == 401
    assert body["error"] == "unauthorized"


def test_marketing_analytics_executes_and_writes_metadata_audit(api_server):
    task = {"campaigns": [{"name": "Launch", "sends": 100, "delivered": 98, "opens": 50, "clicks": 10}]}
    status, body, _ = request(
        api_server,
        "POST",
        "/api/agents/marketing_analytics/run",
        task,
        token=TOKEN,
        headers={"X-OPSFORGE-Actor": "qa-tester"},
    )
    assert status == 200
    assert body["agent"] == "marketing_analytics"
    assert body["result"]["overall"]["delivery_rate_pct"] == 98.0
    assert body["execution_scope"] == "advisory_only"

    audit_path = api_server[2]
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "qa-tester" in audit_text
    assert "actor_label_verified" in audit_text
    assert "Launch" not in audit_text
    assert verify_audit_log(audit_path)["valid"] is True


def test_invalid_task_returns_400_and_is_audited(api_server):
    status, body, _ = request(
        api_server,
        "POST",
        "/api/agents/research/run",
        {"question": "", "sources": []},
        token=TOKEN,
    )
    assert status == 400
    assert body["error"] == "invalid_task"
    assert verify_audit_log(api_server[2])["entries"] == 1


def test_gemini_is_disabled_by_default(api_server):
    status, body, _ = request(
        api_server,
        "POST",
        "/api/agents/research/run",
        {"question": "Research", "sources": ["internal"], "use_gemini": True},
        token=TOKEN,
    )
    assert status == 403
    assert body["error"] == "gemini_execution_disabled"


def test_unknown_agent_and_route_are_rejected(api_server):
    status, body, _ = request(
        api_server,
        "POST",
        "/api/agents/unknown/run",
        {},
        token=TOKEN,
    )
    assert status == 404
    assert body["error"] == "unknown_agent"


def test_non_json_payload_is_rejected(api_server):
    host, port, _ = api_server
    connection = http.client.HTTPConnection(host, port, timeout=3)
    connection.request(
        "POST",
        "/api/agents/research/run",
        body="{}",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "text/plain"},
    )
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    connection.close()
    assert response.status == 415
    assert body["error"] == "application_json_required"


def test_audit_chain_detects_tampering(tmp_path):
    from opsforge.api_audit import HashChainAuditLog

    path = tmp_path / "audit.jsonl"
    log = HashChainAuditLog(path)
    log.append({"request_id": "one", "outcome": "completed"})
    log.append({"request_id": "two", "outcome": "rejected"})
    assert verify_audit_log(path)["valid"] is True

    records = path.read_text(encoding="utf-8").replace('"rejected"', '"completed"')
    path.write_text(records, encoding="utf-8")
    result = verify_audit_log(path)
    assert result["valid"] is False
    assert result["failed_line"] == 2


def test_server_refuses_short_or_missing_token():
    with pytest.raises(RuntimeError, match="OPSFORGE_API_TOKEN"):
        create_server(token="too-short")



def test_corrupted_existing_audit_chain_withholds_execution_response(api_server):
    api_server[2].write_text("not-json\\n", encoding="utf-8")
    status, body, _ = request(
        api_server,
        "POST",
        "/api/agents/marketing_analytics/run",
        {"campaigns": [{"name": "Launch", "sends": 10, "delivered": 10}]},
        token=TOKEN,
    )
    assert status == 503
    assert body["error"] == "audit_unavailable"
    assert verify_audit_log(api_server[2])["valid"] is False


def test_cors_is_exact_origin_allow_list(api_server):
    status, _, headers = request(
        api_server,
        "GET",
        "/health",
        headers={"Origin": "https://sghatge.github.io"},
    )
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "https://sghatge.github.io"
    _, _, rejected_headers = request(
        api_server,
        "GET",
        "/health",
        headers={"Origin": "https://untrusted.example"},
    )
    assert "Access-Control-Allow-Origin" not in rejected_headers
