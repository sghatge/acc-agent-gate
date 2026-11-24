"""OPSFORGE interactive governance lab — synthetic data only.

Run with: streamlit run streamlit_app.py
This UI is a local portfolio demonstration, not an authenticated production console.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

import streamlit as st

from acc_agent_gate import AgentGate, AuditLog, MockCampaignInstance, load_policy
from acc_agent_gate.approval_store import ApprovalError, PersistentApprovalStore
from acc_agent_gate.execution_authorizer import AuthorizationError, ExecutionAuthorizer

st.set_page_config(page_title="OPSFORGE | Governance Lab", page_icon="🛡️", layout="wide")

st.markdown(
    """
    <style>
    .block-container{padding-top:1.7rem;max-width:1500px}
    .hero{padding:1.25rem 1.4rem;border:1px solid rgba(120,150,200,.25);
          border-radius:16px;background:linear-gradient(120deg,rgba(34,67,110,.42),rgba(35,42,70,.18))}
    .hero h1{margin:0 0 .25rem;font-size:2rem}
    .muted{opacity:.72;font-size:.9rem}
    .stMetric{border:1px solid rgba(120,150,200,.2);padding:.75rem;border-radius:12px}
    </style>
    """,
    unsafe_allow_html=True,
)


def _initialize_demo() -> None:
    if "opsforge_demo_id" in st.session_state:
        return
    demo_id = secrets.token_hex(8)
    root = Path(os.getenv("ACC_GATE_DEMO_DATA_DIR", "var/streamlit-demo")) / demo_id
    root.mkdir(parents=True, exist_ok=True)
    gate = AgentGate(backend=MockCampaignInstance(), policy=load_policy(), audit=AuditLog())
    approvals = PersistentApprovalStore(root / "approvals.sqlite3")
    authorizer = ExecutionAuthorizer(
        gate=gate,
        approval_store=approvals,
        secret=secrets.token_urlsafe(48),
        replay_db=root / "execution-replay.sqlite3",
    )
    st.session_state["opsforge_demo_id"] = demo_id
    st.session_state["opsforge_gate"] = gate
    st.session_state["opsforge_approvals"] = approvals
    st.session_state["opsforge_authorizer"] = authorizer
    st.session_state["opsforge_permits"] = {}
    st.session_state["opsforge_executed"] = {}


_initialize_demo()
gate: AgentGate = st.session_state["opsforge_gate"]
approvals: PersistentApprovalStore = st.session_state["opsforge_approvals"]
authorizer: ExecutionAuthorizer = st.session_state["opsforge_authorizer"]
permits: dict[str, str] = st.session_state["opsforge_permits"]
deliveries = gate.backend.deliveries


def _campaign_label(delivery_id: str) -> str:
    delivery = gate.backend.get_delivery(delivery_id)
    return f"{delivery.id} · {delivery.market} · {delivery.target_count:,} recipients · {delivery.state}"


def _approval_label(item: dict[str, Any]) -> str:
    return f"{item['ticket']} · {item['campaign_id']} · {item['status']}"


def _request_approval(delivery_id: str) -> dict[str, Any]:
    outcome = gate.call(
        "delivery.send",
        {"delivery_id": delivery_id},
        agent="opsforge-streamlit-demo",
        intent="Human-operated synthetic governance demonstration",
    )
    decision = outcome["decision"]
    if decision["decision"] != "needs_approval":
        return {"created": False, "decision": decision["decision"],
                "reason": decision["reason"], "ticket": None}
    delivery = gate.backend.get_delivery(delivery_id)
    roles = gate.policy.get("tools", {}).get("delivery.send", {}).get("approver_roles", [])
    if not roles:
        return {"created": False, "decision": "block",
                "reason": "No authorized reviewer roles are configured; request failed closed.",
                "ticket": None}
    source_ticket = outcome["result"]["ticket"]
    audit_entry = gate.audit.entries[-1]
    item = approvals.create_request(
        source_ticket=source_ticket,
        campaign_id=delivery_id,
        requester="opsforge-streamlit-demo",
        payload={
            "delivery_id": delivery_id,
            "market": delivery.market,
            "target_count": delivery.target_count,
            "audit_fingerprint": audit_entry["hash"],
        },
        policy=gate.policy,
        approvals_required=decision["approvals_required"],
        allowed_roles=roles,
    )
    return {"created": True, "decision": "PENDING_HUMAN_APPROVAL",
            "reason": decision["reason"], "ticket": item["ticket"]}


def _show_json(data: Any) -> None:
    st.code(json.dumps(data, indent=2, ensure_ascii=False, default=str), language="json")


st.markdown(
    """
    <div class="hero">
      <div class="muted">OPSFORGE · ACC AGENT GATE · PHASES 1–5</div>
      <h1>🛡️ AI Governance Control Room</h1>
      <div class="muted">Deterministic policy → QA evidence → human review → signed permit → synthetic execution → audit</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.warning(
    "SYNTHETIC DEMO ONLY. This app uses fictional Campaign data and an in-process mock backend. "
    "It is not authenticated and must not be exposed as a production operator console. "
    "It cannot connect to or send through a real Adobe Campaign instance."
)

with st.sidebar:
    st.subheader("Demo controls")
    st.caption(f"Session: {st.session_state['opsforge_demo_id']}")
    kill_switch = st.toggle(
        "Policy kill switch",
        value=bool(gate.policy.get("kill_switch", False)),
        help="When enabled, all write operations are blocked. Changing policy invalidates existing approvals and permits.",
    )
    gate.policy["kill_switch"] = kill_switch
    st.divider()
    st.caption("Environment")
    st.write("🟢 Synthetic Campaign v8")
    st.write("🔒 Local session state")
    st.write("🧾 Hash-chained in-memory audit")
    st.caption("Execution secret is generated per session and never displayed.")

all_requests = approvals.list_requests(status="ALL", limit=500)
pending_count = sum(x["status"] == "PENDING" for x in all_requests)
approved_count = sum(x["status"] == "APPROVED" for x in all_requests)
sent_count = len(gate.backend.sent_log)
blocked_count = sum(1 for x in gate.audit.entries if x.get("decision") == "block")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Campaigns", len(deliveries))
m2.metric("Pending reviews", pending_count)
m3.metric("Approved tickets", approved_count)
m4.metric("Synthetic sends", sent_count)
m5.metric("Blocked calls", blocked_count)

overview_tab, review_tab, execution_tab, audit_tab = st.tabs(
    ["1 · Campaign & QA", "2 · Human approvals", "3 · Execution control", "4 · Audit & AI explainer"]
)

with overview_tab:
    left, right = st.columns([1.05, 1])
    with left:
        st.subheader("Campaign inventory")
        inventory = [
            {"Campaign": d.id, "Market": d.market, "Recipients": d.target_count,
             "Scheduled local": d.scheduled_local, "State": d.state}
            for d in deliveries.values()
        ]
        st.dataframe(inventory, hide_index=True, use_container_width=True)
    with right:
        st.subheader("Pre-send QA")
        delivery_id = st.selectbox(
            "Select a synthetic campaign", list(deliveries),
            format_func=_campaign_label, key="qa_delivery",
        )
        if st.button("Run deterministic QA", type="primary", use_container_width=True):
            outcome = gate.call(
                "delivery.qa", {"delivery_id": delivery_id},
                agent="opsforge-streamlit-demo", intent="Human-operated QA preflight",
            )
            st.session_state["last_qa"] = outcome["result"]
            st.session_state["last_qa_campaign"] = delivery_id
        qa_result = st.session_state.get("last_qa")
        if qa_result and st.session_state.get("last_qa_campaign") == delivery_id:
            status = qa_result["status"].replace("_", " ").upper()
            message = f"QA {status} · {qa_result['passed']}/{qa_result['total']} checks passed"
            if qa_result["status"] == "fail":
                st.error(message)
            elif qa_result["status"] == "pass_with_warnings":
                st.warning(message)
            else:
                st.success(message)
            st.dataframe(qa_result["checks"], hide_index=True, use_container_width=True)
            with st.expander("Inspect QA evidence JSON"):
                _show_json(qa_result)
        if st.button("Request governed send review", use_container_width=True):
            try:
                result = _request_approval(delivery_id)
                st.session_state["last_request_result"] = result
            except Exception as exc:
                st.error(f"Request failed closed: {exc}")
            else:
                if result["created"]:
                    st.success(f"Human review ticket created: {result['ticket']}")
                else:
                    st.error(f"Request not queued · {result['decision']}: {result['reason']}")
        if st.session_state.get("last_request_result"):
            with st.expander("Last request result"):
                _show_json(st.session_state["last_request_result"])

    st.divider()
    st.subheader("Governance sequence")
    stages = st.columns(5)
    stage_data = [
        ("01 · Policy", "Fail-closed rules"),
        ("02 · QA", "Deterministic checks"),
        ("03 · Human review", "Role + separation of duties"),
        ("04 · Signed permit", "HMAC + expiry + replay guard"),
        ("05 · Mock execution", "Synthetic backend only"),
    ]
    for col, (heading, detail) in zip(stages, stage_data):
        with col:
            st.markdown(f"**{heading}**")
            st.caption(detail)

with review_tab:
    st.subheader("Human approval inbox")
    st.caption("Reviewer identity and role are entered only for this local demo. The production reviewer API derives them from server-side credentials.")
    request_items = approvals.list_requests(status="ALL", limit=500)
    if not request_items:
        st.info("No approval tickets yet. Create one from Campaign & QA.")
    else:
        selected_ticket = st.selectbox(
            "Select an approval ticket", [x["ticket"] for x in request_items],
            format_func=lambda ticket: _approval_label(approvals.get_request(ticket)),
        )
        selected = approvals.get_request(selected_ticket)
        a, b, c = st.columns(3)
        a.metric("Status", selected["status"])
        b.metric("Required approvals", selected["approvals_required"])
        c.metric("Recorded decisions", len(selected["decisions"]))
        st.write(f"**Campaign:** {selected['campaign_id']} · **Requester:** {selected['requester']}")
        st.write(f"**Allowed roles:** {', '.join(selected['allowed_roles'])}")
        if selected["decisions"]:
            st.dataframe(selected["decisions"], hide_index=True, use_container_width=True)
        if selected["status"] == "PENDING":
            with st.form("review_decision_form"):
                reviewer = st.text_input("Reviewer identifier", placeholder="e.g. market-owner-01")
                role = st.selectbox("Reviewer role", selected["allowed_roles"])
                decision = st.radio("Decision", ["APPROVE", "REJECT"], horizontal=True)
                reason = st.text_area("Review rationale", max_chars=1000)
                submitted = st.form_submit_button("Record human decision", type="primary")
            if submitted:
                try:
                    updated = approvals.decide(
                        selected_ticket, reviewer=reviewer.strip(), role=role,
                        decision=decision, reason=reason.strip(),
                    )
                except (ApprovalError, ValueError) as exc:
                    st.error(f"Decision rejected: {exc}")
                else:
                    st.success(f"Decision recorded. Ticket status: {updated['status']}")
                    st.rerun()
        elif selected["status"] == "APPROVED":
            st.success("Required human approvals are complete. This is review evidence, not execution authorization.")
        else:
            st.error("This request was rejected and cannot be reopened.")

with execution_tab:
    st.subheader("Execution authorization")
    st.info(
        "Only this separate operator-controlled demo panel can request a permit. "
        "No MCP tool or AI agent can issue or consume execution permits."
    )
    approved_items = approvals.list_requests(status="APPROVED", limit=500)
    if not approved_items:
        st.info("No fully approved tickets are available.")
    else:
        approved_ticket = st.selectbox(
            "Approved ticket", [x["ticket"] for x in approved_items],
            format_func=lambda ticket: _approval_label(approvals.get_request(ticket)),
        )
        ttl = st.slider("Permit lifetime (seconds)", min_value=30, max_value=300, value=120, step=30)
        if st.button("Issue signed execution permit", type="primary"):
            try:
                token = authorizer.issue(approved_ticket, ttl_seconds=ttl)
            except (AuthorizationError, ApprovalError, KeyError, ValueError) as exc:
                st.error(f"Permit issuance denied: {exc}")
            else:
                permits[approved_ticket] = token
                st.session_state["opsforge_permits"] = permits
                st.success("Permit issued and bound to current approval, policy, campaign and audit evidence.")
        token = permits.get(approved_ticket)
        if token:
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            st.code(f"Permit fingerprint: {token_hash[:16]}…{token_hash[-8:]}")
            st.caption("The bearer token itself is not displayed.")
            if approved_ticket in st.session_state["opsforge_executed"]:
                st.success("This ticket has already been executed in this demo session.")
                _show_json(st.session_state["opsforge_executed"][approved_ticket])
            elif st.button("Consume permit & execute synthetic send"):
                try:
                    result = authorizer.execute(token)
                except (AuthorizationError, ApprovalError, KeyError, ValueError) as exc:
                    st.error(f"Execution denied: {exc}")
                else:
                    st.session_state["opsforge_executed"][approved_ticket] = result
                    st.success("Synthetic execution completed. The permit is now consumed.")
                    _show_json(result)
                    st.rerun()
        st.caption("Replay protection is persisted in this session's SQLite database. A consumed or expired permit cannot be reused.")

with audit_tab:
    st.subheader("Tamper-evident audit trail")
    verification = AuditLog.verify(gate.audit.entries)
    if verification["valid"]:
        st.success(f"Audit chain valid · {verification['entries']} entries")
    else:
        st.error(f"Audit chain invalid at sequence {verification.get('broken_at')}")
    st.write(f"**Chain head:** {verification.get('head', '')}")
    if gate.audit.entries:
        st.dataframe(
            [
                {"Seq": entry.get("seq"), "Actor": entry.get("actor"),
                 "Action": entry.get("tool") or entry.get("type"),
                 "Decision": entry.get("decision") or entry.get("type"),
                 "Ticket": entry.get("ticket"), "Hash": entry.get("hash", "")[:16] + "…"}
                for entry in gate.audit.entries
            ],
            hide_index=True, use_container_width=True,
        )
        with st.expander("Inspect complete audit JSON"):
            _show_json(gate.audit.entries)
    else:
        st.info("No events yet. Run QA or request a governed send.")

    st.divider()
    st.subheader("Optional Gemini evidence explainer")
    st.caption("Gemini may explain supplied evidence in plain language. It cannot change policy, approve tickets, issue permits or execute actions.")
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_1"):
        question = st.text_area(
            "What would you like explained?",
            value="Explain the current approval and audit posture. Highlight blockers and the next safe human action.",
            height=90,
        )
        if st.button("Explain with Gemini"):
            try:
                from opsforge.providers.gemini import GeminiProvider
                context = {
                    "policy_kill_switch": gate.policy.get("kill_switch"),
                    "requests": [
                        {"ticket": item["ticket"], "campaign_id": item["campaign_id"],
                         "status": item["status"], "approvals_required": item["approvals_required"],
                         "decisions": item["decisions"]}
                        for item in all_requests
                    ],
                    "audit_verification": verification,
                    "synthetic_sends": gate.backend.sent_log,
                }
                prompt = (
                    "You are an explanatory assistant for a synthetic CRM governance demo. "
                    "Explain only the supplied evidence. Never claim to have approved or executed anything. "
                    "Do not recommend bypassing QA, human approval, role checks, policy or audit controls. "
                    "The deterministic policy engine is authoritative; you are not a decision-maker.\n\n"
                    f"User question: {question[:2000]}\n\nEvidence JSON:\n"
                    f"{json.dumps(context, ensure_ascii=False, default=str)}"
                )
                answer = GeminiProvider().generate_text(prompt)
                st.markdown(answer)
            except Exception as exc:
                st.error(f"Gemini explanation unavailable: {exc}")
    else:
        st.info("Add GEMINI_API_KEY to the server environment to enable the optional explanation panel. The governance demo works without Gemini.")

st.divider()
st.caption(
    "OPSFORGE Phase 5 · Local portfolio demo · Synthetic data · No production CRM connector · "
    "Policy and human controls remain authoritative."
)
