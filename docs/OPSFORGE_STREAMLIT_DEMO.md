# Phase 5 — OPSFORGE Streamlit Governance Control Room

Phase 5 adds a hands-on Streamlit interface for the complete synthetic
ACC Agent Gate lifecycle:

1. Select a campaign and run deterministic pre-send QA.
2. Request a governed send; eligible requests are persisted in the approval
   ledger, while QA/policy blockers fail closed.
3. Review the ticket using the configured reviewer roles and separation-of-
   duties rules.
4. Issue a short-lived HMAC-signed execution permit from the separate operator
   panel.
5. Consume the permit once and execute only against the synthetic Campaign
   backend.
6. Inspect the hash-chained audit trail and optionally ask Gemini to explain
   the supplied evidence.

## Run locally

Python 3.11 is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit (normally
`http://localhost:8501`).

## Suggested walkthrough

- Start with `DM_BF26_HR`: QA should pass and the approval threshold is one.
- Create a review request and approve it as `market_owner` or
  `crm_ops_lead`, using a reviewer ID different from the requester.
- Issue a permit, then consume it. The mock delivery state changes to sent.
- Try to reuse the same permit; replay protection rejects it.
- Try `DM_BF26_SI`, `DM_BF26_AT`, `DM_BF26_GR` or
  `DM_BF26_HU` to see QA blockers.
- Try `DM_BF26_CZ` to see a warning-only QA case and dual-approval threshold.
- Toggle the policy kill switch after approval or permit issuance; revalidation
  should fail closed.

## Optional Gemini explainer

Set `GEMINI_API_KEY` on the Streamlit server to enable the optional explainer
in the Audit tab. Gemini receives a compact evidence snapshot and can only
explain it. It is not permitted to decide policy, approve a request, mint a
permit or execute an action. The governance workflow works without Gemini.

## Security and deployment boundary

- This is an unauthenticated local portfolio demo. Do not expose it as a
  production operator console or put it on a public network without adding
  authentication, authorization, CSRF/session protections, TLS, rate limits,
  secret management and an operational security review.
- Every campaign, recipient and delivery is synthetic. The only send target
  is the bundled `MockCampaignInstance`.
- The app generates an ephemeral signing secret per Streamlit session. It is
  never displayed and is not shared with an AI agent.
- Approval and replay SQLite files are isolated by a random demo session ID
  under `var/streamlit-demo`. The gate and audit log live in Streamlit session
  memory. This is a demo lifecycle, not a durable production deployment.
- The reviewer form accepts a typed reviewer label for demonstration. Use the
  separate authenticated Reviewer API for server-derived identity in a
  controlled deployment.
- The Gemini explainer is optional and advisory. The deterministic gate,
  approval ledger and execution authorizer remain authoritative.
- No production Adobe Campaign or Salesforce connector is included.

This Streamlit app demonstrates the governance control flow. It does not
replace the MCP policy server, authenticated reviewer service or deployment
hardening required for enterprise use.
