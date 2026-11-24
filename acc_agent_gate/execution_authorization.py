"""Short-lived, single-use authorization evidence for reviewed ACC Gate requests.

This module deliberately does not execute Campaign actions. It issues and
consumes a signed authorization artifact only after revalidating the approval,
policy snapshot, audit chain, and current delivery QA state.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .approval_store import ApprovalNotFound, PersistentApprovalStore
from .audit import AuditLog
from .gate import AgentGate


class AuthorizationDenied(PermissionError):
    """Raised whenever authorization cannot be proven safely."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SingleUseAuthorizationService:
    """Issue and atomically consume HMAC-signed, single-use authorization tokens."""

    def __init__(
        self, approval_store: PersistentApprovalStore, gate: AgentGate,
        database: str | Path, signing_key: str | bytes, *,
        ttl_seconds: int = 120, clock: Callable[[], float] = time.time,
    ) -> None:
        key = signing_key.encode("utf-8") if isinstance(signing_key, str) else signing_key
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("Authorization signing key must contain at least 32 bytes.")
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 300:
            raise ValueError("Authorization TTL must be between 1 and 300 seconds.")
        self.approval_store = approval_store
        self.gate = gate
        self.database = str(database)
        self.signing_key = key
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout = 10000")
            yield db
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS authorization_tokens (
                    jti TEXT PRIMARY KEY,
                    ticket TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    policy_sha256 TEXT NOT NULL,
                    audit_fingerprint TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('issued', 'consumed')),
                    consumed_at INTEGER
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_authorization_ticket "
                "ON authorization_tokens(ticket, status)"
            )

    def _validate_approval(self, ticket: str) -> dict[str, Any]:
        try:
            approval = self.approval_store.get_request(ticket)
        except ApprovalNotFound as exc:
            raise AuthorizationDenied("Approval ticket does not exist.") from exc

        if approval.get("status") != "APPROVED":
            raise AuthorizationDenied("A fully approved request is required.")
        required = approval.get("approvals_required")
        decisions = approval.get("decisions", [])
        if not isinstance(required, int) or required not in (1, 2) or len(decisions) < required:
            raise AuthorizationDenied("Required distinct reviewer approvals are missing.")

        reviewers: set[str] = set()
        for decision in decisions:
            reviewer = decision.get("reviewer")
            if (
                decision.get("decision") != "APPROVE"
                or decision.get("role") not in approval.get("allowed_roles", [])
                or not isinstance(reviewer, str) or not reviewer
                or reviewer in reviewers or reviewer == approval.get("requester")
            ):
                raise AuthorizationDenied("Reviewer evidence is invalid.")
            reviewers.add(reviewer)

        payload = approval.get("payload")
        if not isinstance(payload, dict) or _sha256(payload) != approval.get("payload_sha256"):
            raise AuthorizationDenied("Approved payload digest does not match.")
        if _sha256(self.gate.policy) != approval.get("policy_sha256"):
            raise AuthorizationDenied("Policy changed after the approval request.")

        delivery_id = payload.get("delivery_id")
        fingerprint = payload.get("audit_fingerprint")
        if not isinstance(delivery_id, str) or not delivery_id:
            raise AuthorizationDenied("Approved delivery identifier is missing.")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise AuthorizationDenied("Original audit fingerprint is missing.")

        audit_check = AuditLog.verify(self.gate.audit.entries)
        if not audit_check.get("valid"):
            raise AuthorizationDenied("Audit chain integrity verification failed.")
        matching = [e for e in self.gate.audit.entries if e.get("hash") == fingerprint]
        if len(matching) != 1:
            raise AuthorizationDenied("Original request audit event cannot be verified.")
        original = matching[0]
        if (
            original.get("type") != "tool_call"
            or original.get("tool") != "delivery.send"
            or original.get("decision") != "needs_approval"
            or original.get("actor") != "mcp-policy-client"
        ):
            raise AuthorizationDenied("Audit fingerprint is not a valid send request.")

        try:
            delivery = self.gate.backend.get_delivery(delivery_id)
        except (KeyError, ValueError) as exc:
            raise AuthorizationDenied("Approved delivery no longer exists.") from exc
        if (
            payload.get("market") != delivery.market
            or payload.get("target_count") != delivery.target_count
            or delivery.state != "ready"
        ):
            raise AuthorizationDenied("Delivery details or state changed after approval.")

        current = self.gate.evaluate("delivery.send", {"delivery_id": delivery_id})
        if current.decision != "needs_approval" or current.approvals_required != required:
            raise AuthorizationDenied("Current policy or QA no longer permits the approved request.")
        return approval

    def _sign(self, claims: dict[str, Any]) -> str:
        encoded = _b64encode(_canonical_json(claims))
        signature = _b64encode(hmac.new(
            self.signing_key, encoded.encode("ascii"), hashlib.sha256
        ).digest())
        return encoded + "." + signature

    def _verify(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or len(token) > 4096 or token.count(".") != 1:
            raise AuthorizationDenied("Authorization token is malformed.")
        encoded, supplied = token.split(".", 1)
        expected = _b64encode(hmac.new(
            self.signing_key, encoded.encode("ascii"), hashlib.sha256
        ).digest())
        if not hmac.compare_digest(supplied, expected):
            raise AuthorizationDenied("Authorization token signature is invalid.")
        try:
            claims = json.loads(_b64decode(encoded).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorizationDenied("Authorization token payload is invalid.") from exc
        if not isinstance(claims, dict):
            raise AuthorizationDenied("Authorization token claims are invalid.")
        return claims

    def issue(self, ticket: str) -> str:
        approval = self._validate_approval(ticket)
        now = int(self.clock())
        claims = {
            "version": 1, "jti": secrets.token_urlsafe(24), "ticket": ticket,
            "payload_sha256": approval["payload_sha256"],
            "policy_sha256": approval["policy_sha256"],
            "audit_fingerprint": approval["payload"]["audit_fingerprint"],
            "issued_at": now, "expires_at": now + self.ttl_seconds,
        }
        token = self._sign(claims)
        with self._connect() as db:
            db.execute(
                """INSERT INTO authorization_tokens
                   (jti, ticket, payload_sha256, policy_sha256, audit_fingerprint,
                    expires_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'issued')""",
                (claims["jti"], ticket, claims["payload_sha256"], claims["policy_sha256"],
                 claims["audit_fingerprint"], claims["expires_at"]),
            )
        return token

    def consume(self, token: str) -> dict[str, Any]:
        claims = self._verify(token)
        expected_keys = {
            "version", "jti", "ticket", "payload_sha256", "policy_sha256",
            "audit_fingerprint", "issued_at", "expires_at",
        }
        if set(claims) != expected_keys or claims.get("version") != 1:
            raise AuthorizationDenied("Authorization token claims are incomplete.")
        now = int(self.clock())
        if (
            not isinstance(claims.get("expires_at"), int)
            or not isinstance(claims.get("issued_at"), int)
            or claims["issued_at"] > now or claims["expires_at"] <= now
            or claims["expires_at"] - claims["issued_at"] > self.ttl_seconds
        ):
            raise AuthorizationDenied("Authorization token has expired or is invalid.")

        approval = self._validate_approval(claims["ticket"])
        if (
            claims["payload_sha256"] != approval["payload_sha256"]
            or claims["policy_sha256"] != approval["policy_sha256"]
            or claims["audit_fingerprint"] != approval["payload"].get("audit_fingerprint")
        ):
            raise AuthorizationDenied("Authorization token no longer matches approved evidence.")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM authorization_tokens WHERE jti = ?", (claims["jti"],)
            ).fetchone()
            if (
                row is None or row["status"] != "issued"
                or row["ticket"] != claims["ticket"]
                or row["payload_sha256"] != claims["payload_sha256"]
                or row["policy_sha256"] != claims["policy_sha256"]
                or row["audit_fingerprint"] != claims["audit_fingerprint"]
                or row["expires_at"] != claims["expires_at"]
                or row["expires_at"] <= now
            ):
                db.rollback()
                raise AuthorizationDenied("Authorization token is unknown, expired, or already consumed.")
            db.execute(
                "UPDATE authorization_tokens SET status='consumed', consumed_at=? "
                "WHERE jti=? AND status='issued'", (now, claims["jti"])
            )
            db.commit()

        return {
            "authorized": True, "execution_performed": False,
            "ticket": claims["ticket"], "payload_sha256": claims["payload_sha256"],
            "policy_sha256": claims["policy_sha256"],
            "audit_fingerprint": claims["audit_fingerprint"],
            "expires_at": claims["expires_at"], "single_use": True,
        }
