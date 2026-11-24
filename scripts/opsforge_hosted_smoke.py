#!/usr/bin/env python3
"""No-dependency smoke test for a deployed OPSFORGE advisory API.

Usage:
  OPSFORGE_API_URL=https://service.example.com python scripts/opsforge_hosted_smoke.py
  OPSFORGE_API_URL=https://service.example.com OPSFORGE_API_TOKEN=... python scripts/opsforge_hosted_smoke.py

Without a token, checks public health and verifies that protected execution
rejects an unauthenticated request. With a token, also runs one harmless,
synthetic research task. The token is never printed.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXPECTED_AGENTS = {
    "research",
    "crm_operations",
    "adobe_campaign_qa",
    "marketing_analytics",
}


def request_json(url: str, *, method: str = "GET", payload: dict | None = None,
                 token: str | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=15)
    except HTTPError as exc:
        response = exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach API endpoint: {exc.reason}") from exc
    try:
        raw = response.read(128 * 1024)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        return response.status, body if isinstance(body, dict) else {}
    finally:
        response.close()


def main() -> int:
    origin = os.getenv("OPSFORGE_API_URL", "").strip().rstrip("/")
    token = os.getenv("OPSFORGE_API_TOKEN", "")
    local_http = origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")
    if not origin.startswith("https://") and not local_http:
        print("FAIL: OPSFORGE_API_URL must use HTTPS (HTTP is allowed only for localhost).")
        return 2
    if token and len(token) < 32:
        print("FAIL: OPSFORGE_API_TOKEN must contain at least 32 characters.")
        return 2

    failures = 0

    def check(label: str, passed: bool, detail: str) -> None:
        nonlocal failures
        print(f"{'PASS' if passed else 'FAIL'}: {label} — {detail}")
        failures += int(not passed)

    try:
        status, health = request_json(f"{origin}/health")
        check(
            "Public health",
            status == 200 and health.get("status") == "healthy",
            f"HTTP {status}; service={health.get('service', 'unknown')}",
        )
        check(
            "Advisory-only boundary",
            health.get("execution_scope") == "advisory_only",
            f"execution_scope={health.get('execution_scope', 'missing')}",
        )
        check(
            "Agent allow-list",
            set(health.get("agents", [])) == EXPECTED_AGENTS,
            f"{len(health.get('agents', []))} agents advertised",
        )

        task = {"question": "Describe the purpose of a campaign QA checklist using synthetic examples."}
        unauth_status, unauth_body = request_json(
            f"{origin}/api/agents/research/run", method="POST", payload=task
        )
        check(
            "Unauthenticated execution denied",
            unauth_status == 401 and unauth_body.get("error") == "unauthorized",
            f"HTTP {unauth_status}",
        )

        if token:
            auth_status, auth_body = request_json(
                f"{origin}/api/agents/research/run",
                method="POST",
                payload=task,
                token=token,
            )
            authorization = auth_body.get("authorization", {})
            check(
                "Authenticated synthetic research",
                auth_status == 200 and bool(auth_body.get("request_id")),
                f"HTTP {auth_status}; request_id={'present' if auth_body.get('request_id') else 'missing'}",
            )
            check(
                "Server-derived role and advisory boundary",
                bool(authorization.get("role"))
                and auth_body.get("execution_scope") == "advisory_only",
                f"role={authorization.get('role', 'missing')}; scope={auth_body.get('execution_scope', 'missing')}",
            )
        else:
            print("SKIP: Authenticated request — set OPSFORGE_API_TOKEN to run the synthetic authenticated check.")

    except (RuntimeError, TimeoutError, OSError) as exc:
        print(f"FAIL: Smoke test could not complete — {exc}")
        return 1

    if failures:
        print(f"\nResult: {failures} check(s) failed.")
        return 1
    print("\nResult: all applicable OPSFORGE API smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
