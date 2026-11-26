"""HTTP boundary regression tests for the OPSFORGE API."""

import http.client
import json
import threading

import pytest

from opsforge.api import MAX_BODY_BYTES, create_server, token_sha256

TOKEN = "test-token-that-is-long-enough-for-api-authentication"


@pytest.fixture
def api_server(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        credential_hashes={token_sha256(TOKEN): {"actor": "test-operator", "role": "operator"}},
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield host, port
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_health_response_has_security_headers(api_server):
    host, port = api_server
    connection = http.client.HTTPConnection(host, port, timeout=3)
    connection.request("GET", "/health")
    response = connection.getresponse()
    response.read()
    headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()

    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


def test_oversized_request_is_rejected_before_body_processing(api_server):
    host, port = api_server
    connection = http.client.HTTPConnection(host, port, timeout=3)
    body = b" " * (MAX_BODY_BYTES + 1)
    connection.request(
        "POST",
        "/api/agents/research/run",
        body=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()

    assert response.status == 413
    assert payload["error"] == "invalid_content_length"


@pytest.mark.parametrize("body", [b"[1, 2]", b"not-json"])
def test_non_object_or_invalid_json_is_rejected(api_server, body):
    host, port = api_server
    connection = http.client.HTTPConnection(host, port, timeout=3)
    connection.request(
        "POST",
        "/api/agents/research/run",
        body=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()

    assert response.status == 400
    assert payload["error"] in {"invalid_json", "task_must_be_json_object"}
