import http.client
import json
import threading

import pytest

from opsforge.api import create_server, token_sha256
from opsforge.api_audit import verify_audit_log


TOKEN = "test-token-that-is-long-enough-for-api-authentication"


@pytest.fixture
def api_server(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        credential_hashes={token_sha256(TOKEN): {"actor": "test-operator", "role": "operator"}},
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
    assert "test-operator" in audit_text
    assert "qa-tester" not in audit_text
    assert "actor_verified" in audit_text
    assert "operator" in audit_text
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



def test_research_and_crm_routes_are_registered(api_server):
    research_status, research_body, _ = request(
        api_server,
        "POST",
        "/api/agents/research/run",
        {"question": "How should QA be governed?", "sources": ["internal SOP"]},
        token=TOKEN,
    )
    assert research_status == 200
    assert research_body["result"]["status"] == "draft"

    crm_status, crm_body, _ = request(
        api_server,
        "POST",
        "/api/agents/crm_operations/run",
        {"objective": "Improve campaign QA", "context": "Multi-market CRM operations"},
        token=TOKEN,
    )
    assert crm_status == 200
    assert crm_body["result"]["status"] == "draft"


def test_adobe_campaign_qa_route_returns_human_review_not_send_approval(api_server):
    delivery = {
        "id": "API_TEST_HR",
        "internal_name": "API_TEST_HR",
        "market": "HR",
        "label": "API QA sample",
        "subject": "Campaign preview",
        "preheader": "Sample preheader",
        "body": "<p>Price 1.234,00 €</p><footer>Legal entity HR</footer><a>UnsubscriptionLink</a>",
        "target_count": 1000,
        "scheduled_local": "2026-12-01 10:00",
        "typology": "TY_MARKETING_EU",
        "proof_sent": True,
        "seed_list": True,
        "consent_filter": True,
    }
    status, body, _ = request(
        api_server,
        "POST",
        "/api/agents/adobe_campaign_qa/run",
        {"delivery": delivery},
        token=TOKEN,
    )
    assert status == 200
    assert body["result"]["blockers"] == []
    assert body["result"]["send_recommendation"] == "eligible_for_human_review"
    assert body["execution_scope"] == "advisory_only"



def _start_role_server(tmp_path, credentials, enable_gemini=False):
    server = create_server(
        "127.0.0.1",
        0,
        credential_hashes=credentials,
        audit_path=str(tmp_path / "role-audit.jsonl"),
        enable_gemini=enable_gemini,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, (host, port, tmp_path / "role-audit.jsonl")


def test_analyst_role_can_run_analytics_but_not_campaign_qa(tmp_path):
    analyst_token = "analyst-token-that-is-long-enough-for-tests"
    credentials = {
        token_sha256(analyst_token): {"actor": "crm-analyst-01", "role": "analyst"}
    }
    server, thread, api = _start_role_server(tmp_path, credentials)
    try:
        allowed_status, allowed_body, _ = request(
            api,
            "POST",
            "/api/agents/marketing_analytics/run",
            {"campaigns": [{"name": "Email", "sends": 100, "delivered": 99}]},
            token=analyst_token,
        )
        assert allowed_status == 200
        assert allowed_body["authorization"]["role"] == "analyst"

        denied_status, denied_body, _ = request(
            api,
            "POST",
            "/api/agents/adobe_campaign_qa/run",
            {"delivery": {}},
            token=analyst_token,
        )
        assert denied_status == 403
        assert denied_body["error"] == "role_not_authorized"
        audit = api[2].read_text(encoding="utf-8")
        assert "crm-analyst-01" in audit
        assert "permission_denied" in audit
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_qa_role_is_limited_to_adobe_campaign_qa(tmp_path):
    qa_token = "qa-specialist-token-long-enough-for-tests"
    credentials = {
        token_sha256(qa_token): {"actor": "campaign-qa-02", "role": "qa"}
    }
    server, thread, api = _start_role_server(tmp_path, credentials)
    try:
        allowed_status, allowed_body, _ = request(
            api,
            "POST",
            "/api/agents/adobe_campaign_qa/run",
            {"delivery": {
                "id": "QA", "internal_name": "QA", "market": "HR",
                "label": "QA sample", "subject": "Sample subject",
                "preheader": "Preheader",
                "body": "<p>1.234,00 €</p><footer>Legal entity HR</footer><a>UnsubscriptionLink</a>",
                "target_count": 10, "scheduled_local": "2026-12-01 10:00",
                "typology": "TY_MARKETING_EU", "proof_sent": True,
                "seed_list": True, "consent_filter": True,
            }},
            token=qa_token,
        )
        assert allowed_status == 200
        assert allowed_body["authorization"]["role"] == "qa"

        denied_status, denied_body, _ = request(
            api,
            "POST",
            "/api/agents/marketing_analytics/run",
            {"campaigns": [{"name": "Email", "sends": 1, "delivered": 1}]},
            token=qa_token,
        )
        assert denied_status == 403
        assert denied_body["error"] == "role_not_authorized"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_analyst_cannot_request_gemini_even_when_server_enables_it(tmp_path):
    analyst_token = "analyst-gemini-token-long-enough-for-tests"
    credentials = {
        token_sha256(analyst_token): {"actor": "analyst-03", "role": "analyst"}
    }
    server, thread, api = _start_role_server(tmp_path, credentials, enable_gemini=True)
    try:
        status, body, _ = request(
            api,
            "POST",
            "/api/agents/research/run",
            {"question": "Research", "sources": ["reference"], "use_gemini": True},
            token=analyst_token,
        )
        assert status == 403
        assert body["error"] == "gemini_role_not_authorized"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_invalid_role_credential_configuration_is_rejected():
    with pytest.raises(ValueError, match="Unsupported OPSFORGE role"):
        create_server(
            credential_hashes={
                "a" * 64: {"actor": "unknown-role-user", "role": "superuser"}
            }
        )
