"""The gate: policy decision + controlled execution for every agent tool call."""
from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .analyzers import analyze_js, analyze_sql
from .audit import AuditLog
from .mock_instance import PII_FIELDS, MockCampaignInstance
from .qa import run_qa

WRITE_TOOLS = {"delivery.send", "workflow.control", "js.execute"}
RISK = {"allow": 5, "allow_masked": 20, "dry_run": 35, "needs_approval": 65, "block": 90}


@dataclass
class Decision:
    decision: str            # allow | allow_masked | dry_run | needs_approval | block
    rule: str
    reason: str
    risk: int
    approvals_required: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)
    safe_alternative: str | None = None


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else Path(__file__).resolve().parent.parent / "policy" / "default.yaml"
    return yaml.safe_load(Path(path).read_text())


def mask_value(field_name: str, value: Any) -> Any:
    if value is None:
        return None
    s = str(value)
    if field_name == "@email" and "@" in s:
        user, dom = s.split("@", 1)
        return f"{user[0]}***@{dom}"
    if field_name == "@mobilePhone":
        return s[:4] + " *** ****"
    if field_name == "@birthDate":
        return s[:4] + "-**-**"
    return s[0] + "***" if s else s


class AgentGate:
    """Sits between an AI agent (MCP client) and an Adobe Campaign backend."""

    def __init__(self, backend: MockCampaignInstance | None = None,
                 policy: dict[str, Any] | None = None,
                 audit: AuditLog | None = None,
                 clock: Any = None) -> None:
        self.backend = backend or MockCampaignInstance()
        self.policy = policy or load_policy()
        self.audit = audit or AuditLog()
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.pending: dict[str, dict[str, Any]] = {}
        self.write_calls = 0
        self._ticket = itertools.count(1)
        self.qa_cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ policy
    def evaluate(self, tool: str, args: dict[str, Any]) -> Decision:
        tools = self.policy.get("tools", {})
        if tool not in tools:
            return Decision("block", "fail_closed", f"Tool '{tool}' is not in the policy – fail closed", 95)

        cfg = tools[tool]
        if tool in WRITE_TOOLS and tool != "js.execute":
            if self.policy.get("kill_switch"):
                return Decision("block", "kill_switch", "Kill switch is ON – all writes halted", 99)
            limit = self.policy.get("session_limits", {}).get("max_write_calls", 5)
            if self.write_calls >= limit:
                return Decision("block", "session_write_limit",
                                f"Session already used {self.write_calls}/{limit} write calls", 85)

        handler = getattr(self, "_eval_" + tool.replace(".", "_"), None)
        if handler:
            return handler(args, cfg)
        mode = cfg.get("mode", "block")
        return Decision(mode, f"{tool}.mode", f"Policy mode for {tool} is '{mode}'", RISK.get(mode, 90))

    def _eval_query_run(self, args: dict[str, Any], cfg: dict[str, Any]) -> Decision:
        if "sql" in args:
            a = analyze_sql(args["sql"])
            if a.is_write and cfg.get("block_sql_writes", True):
                return Decision("block", "query.run.block_sql_writes",
                                f"Query tool used for a write: {a.summary()}", 95,
                                evidence={"sql": args["sql"]},
                                safe_alternative="Write the clean-up as a reviewed stage workflow; "
                                                 "agent can draft it, a human deploys it.")
        limit = self.policy.get("session_limits", {}).get("max_rows_per_query", 500)
        if int(args.get("limit", 100)) > limit:
            return Decision("block", "session_limits.max_rows_per_query",
                            f"Requested {args.get('limit')} rows; cap is {limit}", 70,
                            safe_alternative="Use an aggregate (group_by) instead of row-level export.")
        touched = set(args.get("select", [])) & PII_FIELDS
        if touched and cfg.get("mask_pii", True) and self.policy.get("data", {}).get("mask_pii", True):
            return Decision("allow_masked", "data.mask_pii",
                            f"PII fields masked before the agent sees them: {', '.join(sorted(touched))}", 20,
                            evidence={"masked_fields": sorted(touched)})
        return Decision("allow", "query.run.mode", "Read-only query within limits", 5)

    def _eval_delivery_send(self, args: dict[str, Any], cfg: dict[str, Any]) -> Decision:
        d = self.backend.get_delivery(args["delivery_id"])
        qa = run_qa(d, self.policy.get("qa", {}))
        self.qa_cache[d.id] = qa
        allowed = {"pass"} if cfg.get("require_qa", "pass") == "pass" else {"pass", "pass_with_warnings"}
        if qa["status"] not in allowed:
            fails = qa["blockers"] or qa["warnings"]
            return Decision("block", "delivery.send.require_qa",
                            f"QA {qa['status']}: {', '.join(fails)}", 92,
                            evidence={"qa": qa},
                            safe_alternative="Fix the listed checks, re-run delivery.qa, then request send.")
        n = 2 if d.target_count > cfg.get("dual_approval_over", 10**12) else 1
        return Decision("needs_approval", "delivery.send.approval",
                        f"QA {qa['status'].replace('_', ' ')}; {d.target_count:,} recipients in {d.market} – "
                        f"{'dual' if n == 2 else 'single'} human approval required", 65,
                        approvals_required=n, evidence={"qa": qa, "volume": d.target_count})

    def _eval_workflow_control(self, args: dict[str, Any], cfg: dict[str, Any]) -> Decision:
        wf = self.backend.workflows.get(args["workflow"])
        if wf is None:
            return Decision("block", "workflow.unknown", f"Unknown workflow {args['workflow']}", 80)
        if wf.critical and cfg.get("block_critical", True):
            return Decision("block", "workflow.control.block_critical",
                            f"{wf.internal_name} is a protected compliance workflow ({wf.label})", 98,
                            safe_alternative="Raise an incident to the platform owner; agents never touch it.")
        if wf.environment == "stage" and cfg.get("stage_environment") == "allow":
            return Decision("allow", "workflow.control.stage_environment", "Stage workflow – allowed", 15)
        return Decision("needs_approval", "workflow.control.mode",
                        f"'{args['action']}' on production workflow {wf.internal_name}", 70, approvals_required=1)

    def _eval_js_execute(self, args: dict[str, Any], cfg: dict[str, Any]) -> Decision:
        a = analyze_js(args["script"])
        blocked = a.categories & set(cfg.get("block_categories", []))
        if blocked:
            return Decision("block", "js.execute.block_categories",
                            f"Script performs {', '.join(sorted(blocked))}: {a.summary()}", 97,
                            evidence={"findings": [f.__dict__ for f in a.findings]},
                            safe_alternative="Express the intent as a query or a QA check; "
                                             "data changes go through a reviewed workflow.")
        return Decision(cfg.get("mode", "dry_run"), "js.execute.mode",
                        f"Analysed, not executed: {a.summary()}", 35,
                        evidence={"findings": [f.__dict__ for f in a.findings]})

    # --------------------------------------------------------------- execution
    def call(self, tool: str, args: dict[str, Any], agent: str = "agent", intent: str = "") -> dict[str, Any]:
        decision = self.evaluate(tool, args)
        result: Any = None
        ticket = None

        if decision.decision in ("allow", "allow_masked"):
            result = self._execute(tool, args, mask=decision.decision == "allow_masked")
        elif decision.decision == "dry_run":
            result = {"dry_run": True, "would_run": tool, "analysis": decision.evidence}
        elif decision.decision == "needs_approval":
            ticket = f"APR-{next(self._ticket):03d}"
            self.pending[ticket] = {"tool": tool, "args": args, "required": decision.approvals_required,
                                    "approvers": [], "agent": agent}
            result = {"status": "pending_approval", "ticket": ticket,
                      "approvals_required": decision.approvals_required}
        else:
            result = {"status": "blocked", "safe_alternative": decision.safe_alternative}

        entry = self.audit.append({
            "ts": self.clock(), "actor": agent, "type": "tool_call", "tool": tool,
            "intent": intent, "args": _redact_args(args), "decision": decision.decision,
            "rule": decision.rule, "reason": decision.reason, "risk": decision.risk,
            "ticket": ticket,
        })
        return {"decision": decision.__dict__, "result": result, "audit_seq": entry["seq"]}

    def approve(self, ticket: str, approver: str, role: str) -> dict[str, Any]:
        p = self.pending[ticket]
        roles = self.policy["tools"].get(p["tool"], {}).get("approver_roles")
        if roles and role not in roles:
            raise PermissionError(f"Role {role} cannot approve {p['tool']}")
        if approver in [a["approver"] for a in p["approvers"]]:
            raise PermissionError("Same person cannot approve twice")
        p["approvers"].append({"approver": approver, "role": role})
        done = len(p["approvers"]) >= p["required"]
        result = None
        if done:
            # re-evaluate at execution time – state may have changed since the request
            recheck = self.evaluate(p["tool"], p["args"])
            if recheck.decision == "block":
                result = {"status": "blocked_on_recheck", "reason": recheck.reason}
            else:
                result = self._execute(p["tool"], p["args"])
            del self.pending[ticket]
        self.audit.append({"ts": self.clock(), "actor": approver, "type": "approval", "ticket": ticket,
                           "role": role, "tool": p["tool"], "executed": done,
                           "decision": "approved" if done else "partial_approval",
                           "reason": f"{len(p['approvers'])}/{p['required']} approvals"})
        return {"ticket": ticket, "approvals": len(p["approvers"]), "required": p["required"],
                "executed": done, "result": result}

    def reject(self, ticket: str, approver: str, reason: str) -> dict[str, Any]:
        p = self.pending.pop(ticket)
        self.audit.append({"ts": self.clock(), "actor": approver, "type": "approval", "ticket": ticket,
                           "tool": p["tool"], "decision": "rejected", "reason": reason})
        return {"ticket": ticket, "status": "rejected", "reason": reason}

    def _execute(self, tool: str, args: dict[str, Any], mask: bool = False) -> Any:
        b = self.backend
        if tool == "campaign.discover":
            return b.discover()
        if tool == "schema.browse":
            return b.browse_schema(args["schema"])
        if tool == "query.run":
            if "sql" in args:
                return {"note": "raw read SQL not executed by mock", "sql": args["sql"]}
            res = b.query(args["schema"], args.get("select", []), args.get("where"),
                          args.get("group_by"), int(args.get("limit", 100)))
            if mask:
                res = copy.deepcopy(res)
                for row in res["rows"]:
                    for k in list(row):
                        if k in PII_FIELDS:
                            row[k] = mask_value(k, row[k])
            return res
        if tool == "delivery.qa":
            d = b.get_delivery(args["delivery_id"])
            qa = run_qa(d, self.policy.get("qa", {}))
            self.qa_cache[d.id] = qa
            return qa
        if tool == "delivery.send":
            self.write_calls += 1
            return b.send_delivery(args["delivery_id"])
        if tool == "workflow.control":
            self.write_calls += 1
            return b.control_workflow(args["workflow"], args["action"])
        if tool == "js.execute":
            self.write_calls += 1
            return b.execute_js(args["script"])
        raise KeyError(tool)


def _redact_args(args: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    if "script" in out and len(out["script"]) > 160:
        out["script"] = out["script"][:157] + "..."
    return out
