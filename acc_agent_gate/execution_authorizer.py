"""Signed, short-lived, single-use authorization for synthetic Campaign execution.

Human approval is necessary but not sufficient. This module revalidates the
approved request against current policy, current delivery state, QA and the
tamper-evident audit chain both when issuing and consuming an authorization.
It deliberately has no production Campaign connector or agent-facing MCP tool.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .approval_store import PersistentApprovalStore
from .audit import AuditLog


class AuthorizationError(ValueError):
    """Authorization failed closed."""


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class ExecutionAuthorizer:
    """Issues and consumes signed execution permits for a single synthetic send."""

    def __init__(
        self,
        *,
        gate: Any,
        approval_store: PersistentApprovalStore,
        secret: str | bytes,
        replay_db: str | Path,
        clock=None,
        max_ttl_seconds: int = 300,
    ) -> None:
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("Execution signing secret must be at least 32 bytes.")
        if not 1 <= max_ttl_seconds <= 300:
            raise ValueError("Maximum token lifetime must be between 1 and 300 seconds.")
        self.gate = gate
        self.approvals = approval_store
        self.key = key
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_ttl_seconds = max_ttl_seconds
        self.replay_db = str(replay_db)
        if self.replay_db != ":memory:":
            Path(self.replay_db).parent.mkdir(parents=True, exist_ok=True)
        self._initialize_replay_db()

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _initialize_replay_db(self) -> None:
        with sqlite3.connect(self.replay_db) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS consumed_authorizations (
                    jti TEXT PRIMARY KEY,
                    ticket TEXT NOT NULL,
                    token_sha256 TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
            """)

    def _assert_unconsumed(self, jti: str) -> None:
        with sqlite3.connect(self.replay_db) as db:
            row = db.execute(
                "SELECT 1 FROM consumed_authorizations WHERE jti=?", (jti,)
            ).fetchone()
        if row:
            raise AuthorizationError("Execution permit has already been consumed.")

    def _approval_evidence(self, ticket: str) -> dict[str, Any]:
        item = self.approvals.get_request(ticket)
        if item["status"] != "APPROVED":
            raise AuthorizationError("Approval ticket is not fully approved.")
        decisions = item["decisions"]
        if len(decisions) < item["approvals_required"]:
            raise AuthorizationError("Required distinct human approvals are missing.")
        reviewers = [d["reviewer"] for d in decisions]
        if len(set(reviewers)) != len(reviewers):
            raise AuthorizationError("Approver identities are not distinct.")
        allowed = set(item["allowed_roles"])
        if any(d["decision"] != "APPROVE" or d["role"] not in allowed for d in decisions):
            raise AuthorizationError("Approval evidence contains an invalid decision or role.")
        if any(d["reviewer"] == item["requester"] for d in decisions):
            raise AuthorizationError("Requester cannot authorize their own execution.")
        return item

    def _revalidate(self, item: dict[str, Any]) -> dict[str, Any]:
        if _canonical_sha256(self.gate.policy) != item["policy_sha256"]:
            raise AuthorizationError("Policy changed after approval; request a new review.")
        integrity = AuditLog.verify(self.gate.audit.entries)
        if not integrity["valid"]:
            raise AuthorizationError("Audit chain integrity check failed.")
        fingerprint = item["payload"].get("audit_fingerprint")
        source = next((e for e in self.gate.audit.entries if e.get("hash") == fingerprint), None)
        if not source or source.get("tool") != "delivery.send" or source.get("decision") != "needs_approval":
            raise AuthorizationError("Original send request is not present in the verified audit chain.")
        if source.get("ticket") != item["source_ticket"]:
            raise AuthorizationError("Audit evidence does not match the approval ticket.")

        delivery_id = item["campaign_id"]
        delivery = self.gate.backend.get_delivery(delivery_id)
        snapshot = item["payload"]
        if delivery.id != snapshot.get("delivery_id") or delivery.market != snapshot.get("market"):
            raise AuthorizationError("Campaign identity or market changed after approval.")
        if delivery.target_count != snapshot.get("target_count"):
            raise AuthorizationError("Campaign audience size changed after approval.")
        if delivery.state != "ready":
            raise AuthorizationError("Campaign is no longer in a sendable ready state.")

        decision = self.gate.evaluate("delivery.send", {"delivery_id": delivery_id})
        if decision.decision != "needs_approval":
            raise AuthorizationError(f"Current policy blocks execution: {decision.reason}")
        if decision.approvals_required != item["approvals_required"]:
            raise AuthorizationError("Current approval threshold differs from the approved request.")
        return {
            "delivery_id": delivery_id,
            "payload_sha256": item["payload_sha256"],
            "policy_sha256": item["policy_sha256"],
            "audit_fingerprint": fingerprint,
            "approvers": [
                {"reviewer": d["reviewer"], "role": d["role"]}
                for d in decisions_sorted(item["decisions"])
            ],
        }

    def issue(self, ticket: str, *, ttl_seconds: int = 120) -> str:
        """Issue a permit after checking approval and current execution conditions."""
        if not 1 <= ttl_seconds <= self.max_ttl_seconds:
            raise AuthorizationError(f"Token lifetime must be 1-{self.max_ttl_seconds} seconds.")
        item = self._approval_evidence(ticket)
        binding = self._revalidate(item)
        now = int(self._now().timestamp())
        payload = {
            "v": 1,
            "iss": "acc-agent-gate",
            "aud": "synthetic-campaign-executor",
            "ticket": ticket,
            **binding,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": secrets.token_urlsafe(24),
        }
        body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = _b64(hmac.new(self.key, body.encode("ascii"), hashlib.sha256).digest())
        self.gate.audit.append({
            "ts": self._now().isoformat(), "actor": "execution-authorizer",
            "type": "execution_permit_issued", "ticket": ticket,
            "jti": payload["jti"], "expires_at": payload["exp"],
            "execution_authorized": True,
        })
        return body + "." + signature

    def execute(self, token: str) -> dict[str, Any]:
        """Consume a permit once, revalidate all bindings, then execute mock send."""
        payload = self._decode_and_verify(token)
        now = int(self._now().timestamp())
        if payload["exp"] <= now or payload["iat"] > now + 30:
            raise AuthorizationError("Execution permit is expired or not yet valid.")
        if payload["exp"] - payload["iat"] > self.max_ttl_seconds:
            raise AuthorizationError("Execution permit lifetime exceeds the configured maximum.")

        self._assert_unconsumed(payload["jti"])
        item = self._approval_evidence(payload["ticket"])
        binding = self._revalidate(item)
        for key in ("delivery_id", "payload_sha256", "policy_sha256", "audit_fingerprint", "approvers"):
            if payload.get(key) != binding[key]:
                raise AuthorizationError(f"Execution permit binding mismatch: {key}.")

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        try:
            with sqlite3.connect(self.replay_db, timeout=10, isolation_level=None) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO consumed_authorizations(jti,ticket,token_sha256,consumed_at) VALUES(?,?,?,?)",
                    (payload["jti"], payload["ticket"], token_hash, self._now().isoformat()),
                )
                db.commit()
        except sqlite3.IntegrityError as exc:
            raise AuthorizationError("Execution permit has already been consumed.") from exc

        # Revalidate immediately before the side effect; fail closed if state changed.
        item = self._approval_evidence(payload["ticket"])
        self._revalidate(item)
        result = self.gate._execute("delivery.send", {"delivery_id": payload["delivery_id"]})
        self.gate.audit.append({
            "ts": self._now().isoformat(), "actor": "synthetic-execution-service",
            "type": "execution_performed", "ticket": payload["ticket"],
            "jti": payload["jti"], "result": result, "execution_authorized": True,
        })
        return {
            "ticket": payload["ticket"],
            "execution_authorized": True,
            "result": result,
            "permit_consumed": True,
        }

    def _decode_and_verify(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or token.count(".") != 1 or len(token) > 8192:
            raise AuthorizationError("Malformed execution permit.")
        body, supplied = token.split(".", 1)
        expected = _b64(hmac.new(self.key, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise AuthorizationError("Execution permit signature is invalid.")
        try:
            payload = json.loads(_unb64(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorizationError("Execution permit payload is invalid.") from exc
        required = {
            "v", "iss", "aud", "ticket", "delivery_id", "payload_sha256",
            "policy_sha256", "audit_fingerprint", "approvers", "iat", "exp", "jti",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise AuthorizationError("Execution permit schema is invalid.")
        if payload["v"] != 1 or payload["iss"] != "acc-agent-gate" or payload["aud"] != "synthetic-campaign-executor":
            raise AuthorizationError("Execution permit issuer, audience or version is invalid.")
        return payload


def decisions_sorted(decisions: list[dict[str, Any]]) -> list[dict[str, str]]:
    return sorted(
        [{"reviewer": d["reviewer"], "role": d["role"]} for d in decisions],
        key=lambda item: (item["reviewer"], item["role"]),
    )
