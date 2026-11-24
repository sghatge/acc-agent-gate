"""Append-only, hash-chained audit events for the OPSFORGE API.

Only metadata and a SHA-256 digest of the submitted task are stored. Raw task
content, credentials and model responses are deliberately excluded.
"""

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

_GENESIS = "0" * 64


class HashChainAuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    @staticmethod
    def _canonical(event: dict[str, Any]) -> bytes:
        return json.dumps(
            event, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        """Append an event and return the stored record."""
        with self._lock:
            previous_hash = _GENESIS
            if self.path.exists() and self.path.stat().st_size:
                with self.path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        if line.strip():
                            previous_hash = json.loads(line)["hash"]

            record = dict(event)
            record["previous_hash"] = previous_hash
            record["hash"] = hashlib.sha256(self._canonical(record)).hexdigest()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
                stream.flush()
            return record


def verify_audit_log(path: str | Path) -> dict[str, Any]:
    """Verify sequence links and event hashes without modifying the file."""
    target = Path(path)
    previous_hash = _GENESIS
    entries = 0
    if not target.exists():
        return {"valid": True, "entries": 0, "last_hash": _GENESIS}

    with target.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                supplied_hash = record.pop("hash")
                linked_hash = record.get("previous_hash")
                if linked_hash != previous_hash:
                    return {
                        "valid": False,
                        "entries": entries,
                        "failed_line": line_number,
                        "reason": "previous_hash_mismatch",
                    }
                expected_hash = hashlib.sha256(
                    HashChainAuditLog._canonical(record)
                ).hexdigest()
                if supplied_hash != expected_hash:
                    return {
                        "valid": False,
                        "entries": entries,
                        "failed_line": line_number,
                        "reason": "event_hash_mismatch",
                    }
                previous_hash = supplied_hash
                entries += 1
            except (KeyError, json.JSONDecodeError, TypeError):
                return {
                    "valid": False,
                    "entries": entries,
                    "failed_line": line_number,
                    "reason": "malformed_record",
                }
    return {"valid": True, "entries": entries, "last_hash": previous_hash}
