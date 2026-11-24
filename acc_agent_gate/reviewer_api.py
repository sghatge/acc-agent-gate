"""Authenticated human-review API for ACC Agent Gate.

This service records reviewer decisions in the durable approval ledger. It
never executes a Campaign action and never converts approval into execution
authorization.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .approval_store import (
    ApprovalConflict,
    ApprovalError,
    ApprovalNotFound,
    PersistentApprovalStore,
)

MAX_BODY_BYTES = 16 * 1024
ACTOR_RE = re.compile(r"[A-Za-z0-9_.@ -]{1,64}")
HASH_RE = re.compile(r"[a-f0-9]{64}")
TICKET_RE = re.compile(r"APR-[A-F0-9]{12}")


def token_sha256(token: str) -> str:
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("Reviewer tokens must contain at least 32 characters.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_reviewers(raw: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("At least one reviewer credential must be configured.")
    result: dict[str, dict[str, str]] = {}
    for digest, principal in raw.items():
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise ValueError("Reviewer credential keys must be lowercase SHA-256 hashes.")
        if not isinstance(principal, dict):
            raise ValueError("Reviewer credential entries must be objects.")
        reviewer, role = principal.get("reviewer"), principal.get("role")
        if not isinstance(reviewer, str) or not ACTOR_RE.fullmatch(reviewer):
            raise ValueError("Reviewer identity must be 1-64 safe characters.")
        if not isinstance(role, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", role):
            raise ValueError("Reviewer role is invalid.")
        result[digest] = {"reviewer": reviewer, "role": role}
    return result


def load_reviewers(
    *, token: str | None = None,
    credential_hashes: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    if credential_hashes is not None:
        return validate_reviewers(credential_hashes)
    configured = os.getenv("ACC_GATE_REVIEWER_CREDENTIALS_JSON")
    if configured:
        try:
            parsed = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ACC_GATE_REVIEWER_CREDENTIALS_JSON must be valid JSON.") from exc
        return validate_reviewers(parsed)
    supplied = token if token is not None else os.getenv("ACC_GATE_REVIEWER_TOKEN")
    if not isinstance(supplied, str) or len(supplied) < 32:
        raise RuntimeError(
            "Set ACC_GATE_REVIEWER_CREDENTIALS_JSON or ACC_GATE_REVIEWER_TOKEN "
            "(minimum 32 characters)."
        )
    return {
        token_sha256(supplied): {"reviewer": "local-reviewer", "role": "market_owner"}
    }


def create_server(
    host: str = "127.0.0.1",
    port: int = 8766,
    *,
    token: str | None = None,
    credential_hashes: dict[str, dict[str, str]] | None = None,
    approval_store: PersistentApprovalStore | None = None,
) -> ThreadingHTTPServer:
    credentials = load_reviewers(token=token, credential_hashes=credential_hashes)
    store = approval_store or PersistentApprovalStore(
        os.getenv("ACC_GATE_APPROVAL_DB", "approval_queue.sqlite3")
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "ACC-Gate-Reviewer"
        sys_version = ""

        def log_message(self, fmt: str, *args: Any) -> None:
            # Do not log request paths, bodies, identities or credentials.
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _principal(self) -> dict[str, str] | None:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return None
            digest = hashlib.sha256(header[7:].encode("utf-8")).hexdigest()
            for known, principal in credentials.items():
                if hmac.compare_digest(digest, known):
                    return principal
            return None

        def _body(self) -> dict[str, Any] | None:
            if self.headers.get("Content-Type", "").split(";")[0].lower() != "application/json":
                self._send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "application_json_required"})
                return None
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(HTTPStatus.BAD_REQUEST if length < 0 else HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                           {"error": "invalid_content_length"})
                return None
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return None
            if not isinstance(value, dict):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "json_object_required"})
                return None
            return value

        def do_GET(self) -> None:
            path = urlparse(self.path)
            if path.path == "/health":
                self._send(HTTPStatus.OK, {
                    "service": "acc-gate-reviewer-api",
                    "status": "healthy",
                    "execution_scope": "review_only",
                })
                return
            principal = self._principal()
            if principal is None:
                self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            role = principal["role"]
            match = re.fullmatch(r"/api/approvals/(APR-[A-F0-9]{12})", path.path)
            if match:
                try:
                    item = store.get_request(match.group(1))
                except ApprovalNotFound:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "approval_not_found"})
                    return
                if role not in item["allowed_roles"]:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "approval_not_found"})
                    return
                self._send(HTTPStatus.OK, item)
                return
            if path.path == "/api/approvals":
                query = parse_qs(path.query)
                status = query.get("status", ["PENDING"])[0].upper()
                try:
                    limit = int(query.get("limit", ["100"])[0])
                    items = store.list_requests(status=status, limit=limit)
                except (ValueError, ApprovalError):
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_query"})
                    return
                visible = [item for item in items if role in item["allowed_roles"]]
                self._send(HTTPStatus.OK, {
                    "items": visible,
                    "count": len(visible),
                    "execution_authorized": False,
                })
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:
            principal = self._principal()
            if principal is None:
                self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            match = re.fullmatch(
                r"/api/approvals/(APR-[A-F0-9]{12})/decision", urlparse(self.path).path
            )
            if not match:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            payload = self._body()
            if payload is None:
                return
            if set(payload) - {"decision", "reason"}:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "unexpected_fields"})
                return
            decision = payload.get("decision")
            reason = payload.get("reason", "")
            if not isinstance(decision, str) or decision.upper() not in {"APPROVE", "REJECT"}:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "decision_must_be_approve_or_reject"})
                return
            if not isinstance(reason, str) or len(reason) > 1000:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_reason"})
                return
            try:
                item = store.get_request(match.group(1))
                if principal["role"] not in item["allowed_roles"]:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "approval_not_found"})
                    return
                result = store.decide(
                    match.group(1),
                    reviewer=principal["reviewer"],
                    role=principal["role"],
                    decision=decision,
                    reason=reason,
                )
            except ApprovalNotFound:
                self._send(HTTPStatus.NOT_FOUND, {"error": "approval_not_found"})
                return
            except ApprovalConflict as exc:
                self._send(HTTPStatus.CONFLICT, {"error": "decision_conflict", "message": str(exc)})
                return
            except ApprovalError:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_decision"})
                return
            self._send(HTTPStatus.OK, {
                "approval": result,
                "execution_authorized": False,
                "message": "Reviewer decision recorded. Campaign execution was not performed.",
            })

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.getenv("ACC_GATE_REVIEWER_HOST", "127.0.0.1")
    port = int(os.getenv("ACC_GATE_REVIEWER_PORT", "8766"))
    server = create_server(host, port)
    print(f"ACC Gate reviewer API listening on http://{host}:{port}")
    print("Review-only service; configure TLS termination before remote access.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
