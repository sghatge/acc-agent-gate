import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acc_agent_gate import AgentGate, AuditLog, MockCampaignInstance, load_policy  # noqa: E402
from acc_agent_gate.analyzers import analyze_js, analyze_sql  # noqa: E402


@pytest.fixture
def gate():
    return AgentGate(MockCampaignInstance(), load_policy(), AuditLog())


def test_unknown_tool_fails_closed(gate):
    assert gate.call("recipient.delete_all", {})["decision"]["decision"] == "block"


def test_pii_is_masked(gate):
    res = gate.call("query.run", {"schema": "nms:recipient", "select": ["@email", "@country"], "limit": 3})
    assert res["decision"]["decision"] == "allow_masked"
    for row in res["result"]["rows"]:
        assert "***@" in row["@email"]


@pytest.mark.parametrize("sql", ["DELETE FROM NmsRecipient", "update NmsRecipient set x=1",
                                 "DROP TABLE NmsDelivery", "insert into t values (1)"])
def test_sql_writes_blocked(gate, sql):
    assert gate.call("query.run", {"sql": sql})["decision"]["decision"] == "block"


def test_row_cap(gate):
    res = gate.call("query.run", {"schema": "nms:recipient", "select": ["@country"], "limit": 10_000})
    assert res["decision"]["decision"] == "block"


def test_send_blocked_when_qa_fails(gate):
    res = gate.call("delivery.send", {"delivery_id": "DM_BF26_SI"})
    assert res["decision"]["decision"] == "block"
    assert gate.backend.deliveries["DM_BF26_SI"].state == "ready"


def test_send_needs_approval_then_executes(gate):
    res = gate.call("delivery.send", {"delivery_id": "DM_BF26_HR"})
    assert res["decision"]["decision"] == "needs_approval"
    assert gate.backend.deliveries["DM_BF26_HR"].state == "ready"  # nothing sent yet
    out = gate.approve(res["result"]["ticket"], "owner.hr", "market_owner")
    assert out["executed"] and gate.backend.deliveries["DM_BF26_HR"].state == "sent"


def test_dual_approval_and_no_self_double_approval(gate):
    res = gate.call("delivery.send", {"delivery_id": "DM_BF26_CZ"})
    t = res["result"]["ticket"]
    assert res["decision"]["approvals_required"] == 2
    gate.approve(t, "owner.cz", "market_owner")
    with pytest.raises(PermissionError):
        gate.approve(t, "owner.cz", "market_owner")
    assert gate.approve(t, "ops.lead", "crm_ops_lead")["executed"]


def test_wrong_role_cannot_approve(gate):
    t = gate.call("delivery.send", {"delivery_id": "DM_BF26_HR"})["result"]["ticket"]
    with pytest.raises(PermissionError):
        gate.approve(t, "intern", "viewer")


def test_recheck_at_execution_time(gate):
    t = gate.call("delivery.send", {"delivery_id": "DM_BF26_HR"})["result"]["ticket"]
    gate.backend.deliveries["DM_BF26_HR"].proof_sent = False  # something changed while waiting
    out = gate.approve(t, "owner.hr", "market_owner")
    assert out["result"]["status"] == "blocked_on_recheck"
    assert gate.backend.deliveries["DM_BF26_HR"].state == "ready"


def test_critical_workflow_blocked(gate):
    assert gate.call("workflow.control", {"workflow": "WKF_GDPR_Purge", "action": "pause"}
                     )["decision"]["decision"] == "block"


def test_kill_switch_blocks_writes_not_reads():
    pol = copy.deepcopy(load_policy())
    pol["kill_switch"] = True
    g = AgentGate(MockCampaignInstance(), pol, AuditLog())
    assert g.call("campaign.discover", {})["decision"]["decision"] == "allow"
    assert g.call("delivery.send", {"delivery_id": "DM_BF26_HR"})["decision"]["rule"] == "kill_switch"


def test_session_write_limit():
    pol = copy.deepcopy(load_policy())
    pol["session_limits"]["max_write_calls"] = 1
    g = AgentGate(MockCampaignInstance(), pol, AuditLog())
    g.call("workflow.control", {"workflow": "WKF_BF26_Reminder_STG", "action": "start"})
    res = g.call("workflow.control", {"workflow": "WKF_BF26_Reminder_STG", "action": "stop"})
    assert res["decision"]["rule"] == "session_write_limit"


@pytest.mark.parametrize("script,expected", [
    ("xtk.session.Write(<recipient/>)", "write"),
    ("sqlExec('delete from x')", "write"),
    ("new HttpClientRequest('https://x.test')", "egress"),
    ("nms.delivery.Start(123)", "send"),
    ("execCommand('ls')", "system"),
])
def test_js_analyzer(script, expected):
    assert expected in analyze_js(script).categories


def test_read_only_js_is_dry_run(gate):
    res = gate.call("js.execute", {"script": "xtk.queryDef.create(<queryDef/>).ExecuteQuery()"})
    assert res["decision"]["decision"] == "dry_run"
    assert gate.write_calls == 0


def test_sql_no_where_flagged():
    assert any("No WHERE" in f.detail for f in analyze_sql("DELETE FROM NmsRecipient").findings)


def test_audit_chain_detects_tampering(gate):
    gate.call("campaign.discover", {})
    gate.call("query.run", {"sql": "DELETE FROM x"})
    gate.call("campaign.discover", {})
    assert AuditLog.verify(gate.audit.entries)["valid"]
    forged = copy.deepcopy(gate.audit.entries)
    forged[1]["decision"] = "allow"
    assert AuditLog.verify(forged) == {"valid": False, "broken_at": 2, "entries": 3}
    assert not AuditLog.verify(gate.audit.entries[:1] + gate.audit.entries[2:])["valid"]  # deletion


def test_qa_catches_each_seeded_defect():
    from acc_agent_gate.qa import run_qa
    inst, cfg = MockCampaignInstance(), load_policy()["qa"]
    expect = {"DM_BF26_SI": "unsubscribe_link", "DM_BF26_AT": "proof_sent", "DM_BF26_GR": "price_locale",
              "DM_BF26_HU": "consent_filter"}
    for did, check in expect.items():
        assert check in run_qa(inst.deliveries[did], cfg)["blockers"]
    assert run_qa(inst.deliveries["DM_BF26_HR"], cfg)["status"] == "pass"
    assert run_qa(inst.deliveries["DM_BF26_CZ"], cfg)["warnings"] == ["subject_length"]
