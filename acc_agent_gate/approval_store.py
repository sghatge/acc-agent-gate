"""Durable, fail-closed human approval ledger for ACC Agent Gate.

This ledger records reviewer decisions only. It deliberately does not execute
Campaign actions or mint execution credentials.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ApprovalError(ValueError):
    """Base error for invalid approval operations."""


class ApprovalNotFound(ApprovalError):
    pass


class ApprovalConflict(ApprovalError):
    pass


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PersistentApprovalStore:
    """SQLite-backed approval ledger with transactional reviewer decisions."""

    def __init__(self, path: str | Path = "approval_queue.sqlite3", *, clock=None):
        self.path = str(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA busy_timeout = 10000")
            yield db
        finally:
            db.close()

    def _initialize(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    ticket TEXT PRIMARY KEY,
                    source_ticket TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    requester TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    policy_sha256 TEXT NOT NULL,
                    approvals_required INTEGER NOT NULL CHECK (approvals_required IN (1, 2)),
                    allowed_roles_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approval_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket TEXT NOT NULL REFERENCES approval_requests(ticket),
                    reviewer TEXT NOT NULL,
                    role TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(ticket, reviewer)
                );
                CREATE INDEX IF NOT EXISTS idx_approval_status_created
                    ON approval_requests(status, created_at);
            """)

    def create_request(
        self, *, source_ticket: str, campaign_id: str, requester: str,
        payload: dict[str, Any], policy: dict[str, Any], approvals_required: int,
        allowed_roles: list[str],
    ) -> dict[str, Any]:
        if approvals_required not in (1, 2):
            raise ApprovalError("Approvals required must be one or two.")
        if not source_ticket or not campaign_id or not requester:
            raise ApprovalError("Source ticket, campaign ID and requester are required.")
        if not allowed_roles or any(not isinstance(x, str) or not x for x in allowed_roles):
            raise ApprovalError("At least one valid reviewer role is required.")
        ticket = "APR-" + uuid.uuid4().hex[:12].upper()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        policy_hash = _canonical_digest(policy)
        now = self.clock()
        with self._connect() as db:
            db.execute(
                """INSERT INTO approval_requests
                (ticket, source_ticket, campaign_id, requester, payload_json,
                 payload_sha256, policy_sha256, approvals_required,
                 allowed_roles_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
                (ticket, source_ticket, campaign_id, requester, payload_json,
                 payload_hash, policy_hash, approvals_required,
                 json.dumps(sorted(set(allowed_roles))), now, now),
            )
        return self.get_request(ticket)

    def get_request(self, ticket: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM approval_requests WHERE ticket=?", (ticket,)).fetchone()
            if row is None:
                raise ApprovalNotFound("Approval ticket not found.")
            decisions = db.execute(
                """SELECT reviewer, role, decision, reason, created_at
                   FROM approval_decisions WHERE ticket=? ORDER BY id""", (ticket,)
            ).fetchall()
        return self._serialize(row, decisions)

    def list_requests(self, *, status: str = "PENDING", limit: int = 100) -> list[dict[str, Any]]:
        if status not in {"PENDING", "APPROVED", "REJECTED", "ALL"}:
            raise ApprovalError("Unsupported approval status.")
        if not 1 <= limit <= 500:
            raise ApprovalError("Limit must be between 1 and 500.")
        with self._connect() as db:
            if status == "ALL":
                rows = db.execute(
                    "SELECT * FROM approval_requests ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM approval_requests WHERE status=? ORDER BY created_at LIMIT ?",
                    (status, limit),
                ).fetchall()
            result = []
            for row in rows:
                decisions = db.execute(
                    """SELECT reviewer, role, decision, reason, created_at
                       FROM approval_decisions WHERE ticket=? ORDER BY id""",
                    (row["ticket"],),
                ).fetchall()
                result.append(self._serialize(row, decisions))
            return result

    def decide(self, ticket: str, *, reviewer: str, role: str,
               decision: str, reason: str = "") -> dict[str, Any]:
        decision = decision.upper()
        if decision not in {"APPROVE", "REJECT"}:
            raise ApprovalError("Decision must be APPROVE or REJECT.")
        if not reviewer or not role or len(reason) > 1000:
            raise ApprovalError("Reviewer and role are required; reason is limited to 1000 characters.")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM approval_requests WHERE ticket=?", (ticket,)).fetchone()
            if row is None:
                raise ApprovalNotFound("Approval ticket not found.")
            if row["status"] != "PENDING":
                raise ApprovalConflict("Approval request is no longer pending.")
            if reviewer == row["requester"]:
                raise ApprovalConflict("Requester cannot approve their own request.")
            allowed_roles = json.loads(row["allowed_roles_json"])
            if role not in allowed_roles:
                raise ApprovalConflict("Reviewer role is not authorized for this request.")
            prior = db.execute(
                "SELECT 1 FROM approval_decisions WHERE ticket=? AND reviewer=?",
                (ticket, reviewer),
            ).fetchone()
            if prior:
                raise ApprovalConflict("A reviewer may decide a ticket only once.")
            db.execute(
                """INSERT INTO approval_decisions
                   (ticket, reviewer, role, decision, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ticket, reviewer, role, decision, reason, now),
            )
            if decision == "REJECT":
                status = "REJECTED"
            else:
                count = db.execute(
                    "SELECT COUNT(*) FROM approval_decisions WHERE ticket=? AND decision='APPROVE'",
                    (ticket,),
                ).fetchone()[0]
                status = "APPROVED" if count >= row["approvals_required"] else "PENDING"
            db.execute(
                "UPDATE approval_requests SET status=?, updated_at=? WHERE ticket=?",
                (status, now, ticket),
            )
            db.commit()
        return self.get_request(ticket)

    @staticmethod
    def _serialize(row, decisions):
        return {
            "ticket": row["ticket"],
            "source_ticket": row["source_ticket"],
            "campaign_id": row["campaign_id"],
            "requester": row["requester"],
            "payload": json.loads(row["payload_json"]),
            "payload_sha256": row["payload_sha256"],
            "policy_sha256": row["policy_sha256"],
            "approvals_required": row["approvals_required"],
            "allowed_roles": json.loads(row["allowed_roles_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "decisions": [dict(item) for item in decisions],
            "execution_authorized": False,
        }
