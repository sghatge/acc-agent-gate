"""Human side of the gate: review pending approvals and verify the audit chain.

    python -m acc_agent_gate.cli verify audit.jsonl
    python -m acc_agent_gate.cli show audit.jsonl
"""
from __future__ import annotations

import json
import sys

from .audit import AuditLog

ICON = {"allow": "✅", "allow_masked": "🟦", "dry_run": "🧪", "needs_approval": "⏸️ ", "block": "⛔",
        "approved": "👤", "partial_approval": "👤", "rejected": "✋"}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in {"verify", "show"}:
        print(__doc__)
        return 2
    log = AuditLog(argv[1])
    if argv[0] == "verify":
        res = AuditLog.verify(log.entries)
        print(json.dumps(res, indent=2))
        return 0 if res["valid"] else 1
    for e in log.entries:
        print(f"{e['seq']:>3} {ICON.get(e['decision'], '•')} {e.get('tool', ''):<18} "
              f"{e['decision']:<16} {e.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
