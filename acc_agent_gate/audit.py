"""Tamper-evident audit log.

Each entry stores the SHA-256 of the previous entry, so editing or deleting
any line breaks the chain from that point on. This gives compliance and
market owners a trustworthy record of everything an agent asked for and
what the gate decided – including what was blocked.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _digest(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.entries: list[dict[str, Any]] = []
        if self.path and self.path.exists():
            self.entries = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    @property
    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        entry = {"seq": len(self.entries) + 1, "prev": self.head, **record}
        entry["hash"] = _digest(entry)
        self.entries.append(entry)
        if self.path:
            with self.path.open("a") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    @staticmethod
    def verify(entries: list[dict[str, Any]]) -> dict[str, Any]:
        prev = GENESIS
        for e in entries:
            if e.get("prev") != prev or _digest(e) != e.get("hash"):
                return {"valid": False, "broken_at": e.get("seq"), "entries": len(entries)}
            prev = e["hash"]
        return {"valid": True, "broken_at": None, "entries": len(entries), "head": prev}
