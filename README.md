# ACC Agent Gate

**[⚡ OPSFORGE Unified Agent Workspace](https://sghatge.github.io/acc-agent-gate/opsforge/)** · explore Research, CRM Operations, Adobe Campaign QA and Marketing Analytics in one interactive synthetic-data showcase.

**[▶ Interactive governance demo](https://sghatge.github.io/acc-agent-gate/)** · change the policy and watch an AI agent's Black Friday session re-run live.

**A governance layer between AI agents and Adobe Campaign.**

Adobe's CX Enterprise agentic tools now list Campaign Classic capabilities that include instance discovery, schema browsing, query execution, workflow control and SOAP/JS execution, reached through CX Enterprise Coworker rather than a standalone endpoint [1][2]. That is a big productivity unlock. It also means an eager agent is a few calls away from a full-table `DELETE`, a send without an unsubscribe link, or pausing your GDPR purge.

ACC Agent Gate sits in the middle. Every tool call is checked against a written policy before it reaches Campaign:

| Decision | What happens | Example |
|---|---|---|
| ✅ `allow` | Runs | Schema browse, aggregate audience count |
| 🟦 `allow_masked` | Runs, PII masked before the agent sees it | Sample of recipient rows |
| 🧪 `dry_run` | Analysed and explained, never executed | Read-only server-side JS |
| ⏸️ `needs_approval` | Queued for one or two humans, re-checked at execution | Delivery send, prod workflow start |
| ⛔ `block` | Stopped, with a safe alternative | SQL writes, QA failures, compliance workflows, data egress |

Everything, including what was blocked, goes into a **hash-chained audit log** that fails verification if any entry is edited or deleted.

## What the demo shows

`scenarios/black_friday_session.py` replays a realistic agent session across 8 EU markets on a **synthetic** instance (fictional brand, invented data):

- 28 agent calls → 12 allowed, 1 masked, 1 dry-run, 5 sent for approval, 9 blocked
- 4 sends approved and executed (609,300 recipients); 931,500 held back by QA
- Defects caught before send: missing unsubscribe link (SI), no proof sign-off (AT), English price format plus a 23:30 send time (GR), no consent filter (HU)
- Agent attempts blocked: `DELETE` via the query tool, a 50,000-row PII export, pausing the GDPR purge, bulk consent overwrite via `xtk.session.Write`, an outbound HTTP "backup" of the audience
- Audit chain verifies; editing one "block" to "allow" is detected

## Interactive showcase

`docs/index.html` is a self-contained page (GitHub Pages ready) that runs a JavaScript port of the gate in the browser:

- **Policy lab**: toggle any rule or pick a preset (Recommended, Humans only, Agent autopilot, Lockdown) and the 28-call session re-runs live, showing defective sends, PII exposure and destructive actions
- **Playground**: submit your own SQL, server-side JS, sends or workflow actions; approve them in an inbox with role checks and dual sign-off; each decision is SHA-256 chained in the browser
- **QA board**: apply fixes to failing checks and watch outcomes change
- **Audit log**: forge any entry and see where verification breaks
- **Policy file**: YAML that follows the lab, with your changes highlighted

Rebuild it with `python docs/build_showcase.py` after running the scenario.

## Quick start

```bash
pip install -r requirements.txt
python scenarios/black_friday_session.py      # writes out/scenario.json + out/audit.jsonl
python -m acc_agent_gate.cli show out/audit.jsonl
python -m acc_agent_gate.cli verify out/audit.jsonl
python -m pytest -q                           # complete test suite
```

### Deploy the OPSFORGE API

See the [hosted deployment runbook](docs/opsforge-hosted-deployment.md) and the root-level `render.yaml` blueprint for a repeatable HTTPS deployment of the authenticated API. The hosted API is separate from the GitHub Pages dashboard and requires platform secrets plus persistent audit storage.

### Run it as an MCP server

```bash
python -m acc_agent_gate.server               # stdio
```

```json
{ "mcpServers": { "acc-agent-gate": { "command": "python", "args": ["-m", "acc_agent_gate.server"] } } }
```

The agent gets `campaign_discover`, `schema_browse`, `query_run`, `delivery_qa`, `delivery_send`, `workflow_control` and `js_execute`. Approvals are **not** exposed as tools. An agent can ask, but only a human can say yes.

## Design principles

1. **Fail closed.** A tool not named in the policy is blocked.
2. **Policy is a file, not a prompt.** `policy/default.yaml` is reviewed like code. Prompts can be talked around; a YAML gate cannot.
3. **Treat anything that looks like a write as a write.** The analyzers use conservative pattern matching. A false positive costs one human click; a false negative costs a market.
4. **Re-check at execution time.** If a proof is withdrawn while a send waits for approval, the approved send is still blocked.
5. **Separation of duties.** Role-checked approvers, dual approval above a volume threshold, and no one approves twice.
6. **Evidence over trust.** Every decision carries the rule ID, the reason and a risk score, and is chained in the audit log.

## Pre-send QA checks

Unsubscribe link · market legal footer · price and currency locale · marketing-consent filter · proof sign-off · local quiet hours · marketing typology · seed list · subject length ≤ 50 chars (warning). Each check maps to Adobe's own guidance in the sources below.

## Repo layout

```
acc_agent_gate/
  gate.py           policy evaluation + controlled execution + approvals
  analyzers.py      SQL / server-side JS risk analysis
  qa.py             pre-send QA checks
  audit.py          hash-chained audit log
  mock_instance.py  synthetic Campaign instance (8 markets, deliveries, workflows, 2,400 recipients)
  server.py         MCP server exposing gated tools
  cli.py            show / verify the audit log
policy/default.yaml
scenarios/black_friday_session.py
tests/test_gate.py
```

## Going from mock to a real instance

`MockCampaignInstance` is the only backend shipped. To front a real instance, implement the same methods (`discover`, `browse_schema`, `query`, `get_delivery`, `send_delivery`, `control_workflow`, `execute_js`) as an adapter over Campaign's SOAP API, or over whatever agent access Adobe exposes for your instance, using an operator whose operator groups and named rights grant only what the gate allows [6]. Keep the operator's own rights as the outer boundary. The gate is defence in depth, not a replacement for Campaign security.

## Limitations

- The analyzers are pattern-based, not full SQL/JS parsers. They are tuned to over-block.
- The mock never evaluates JavaScript.
- Approvals are in-process. Production use needs a persistent queue and an identity provider.

## Sources (Adobe Experience League, 2026)

| # | Page | Used for | Last updated |
|---|---|---|---|
| 1 | [MCP Servers – Adobe CX Enterprise](https://experienceleague.adobe.com/en/docs/cx-enterprise-agentic-tools/using/tools/mcp-servers) | Campaign Classic capabilities exposed to agents (query, workflow control, SOAP/JS); access depends on entitlements and user permissions | 16 Sep 2026 |
| 2 | [Adobe CX Enterprise Coworker overview](https://experienceleague.adobe.com/en/docs/cx-enterprise-coworker/content/home) | Agent experience; approvals and governance defined per customer; roles set in Admin Console | 27 Oct 2026 |
| 3 | [Delivery best practices – check before sending](https://experienceleague.adobe.com/en/docs/campaign-classic/using/sending-messages/key-steps-when-creating-a-delivery/delivery-bestpractices/check-before-sending) | Proofs, working opt-out link, subject ≤ 50 chars, deduplicated target, validation | 5 Oct 2026 |
| 4 | [Preview and test your email (Campaign v8)](https://experienceleague.adobe.com/en/docs/campaign/campaign-v8/send/validate/preview-and-proof) | Proof sign-off check | — |
| 5 | [About seed addresses](https://experienceleague.adobe.com/en/docs/campaign-classic/using/sending-messages/using-seed-addresses/about-seed-addresses) | Seed list check | — |
| 6 | [Get started with permissions (Campaign v8)](https://experienceleague.adobe.com/en/docs/campaign/campaign-v8/permissions/gs-permissions) | Operator groups and named rights as the outer boundary | 5 Oct 2026 |
| 7 | [Work with business rules (typologies)](https://experienceleague.adobe.com/en/docs/campaign-web/v8/conf/typologies) | Typology check | — |
| 8 | [Manage subscriptions and unsubscriptions (Campaign v8)](https://experienceleague.adobe.com/nl/docs/campaign/campaign-v8/audience/subscriptions) | Unsubscribe link check | — |
| 9 | [Manage Privacy requests in Campaign](https://experienceleague.adobe.com/en/docs/campaign/campaign-v8/privacy/privacy) | Why privacy and erasure workflows are protected | — |

Note: source [1] lists Campaign Classic with no direct endpoint and does not state which of its capabilities are read-only. This project assumes the worst case and gates every write-capable action.

## Disclaimer

Independent project. Not affiliated with or endorsed by Adobe. All data, brands and deliveries are synthetic.

MIT licensed · Built by Sangram Ghatge


## OPSFORGE API service

The four OPSFORGE agents can be invoked through an optional bearer-authenticated HTTP API with role-based permissions for analysts, QA specialists, operators and admins. The unified dashboard includes an explicit API mode for connecting to a self-hosted service, and a non-root Docker image is provided for deployment. See [API setup, RBAC, container deployment, security and endpoint documentation](docs/opsforge-api.md).

## OPSFORGE Gemini provider

The OPSFORGE Research Agent can use the Google Gen AI SDK through
`opsforge.providers.gemini.GeminiProvider`.

### Configuration

Set the API key as an environment variable; do not commit it to Git:

```bash
# macOS / Linux
export GEMINI_API_KEY="your-google-ai-studio-api-key"

# PowerShell
$env:GEMINI_API_KEY = "your-google-ai-studio-api-key"
```

Optional model override:

```bash
# Default: gemini-3.8-flash
$env:GEMINI_MODEL = "gemini-3.8-flash"
```

The provider also accepts `GOOGLE_API_KEY` and the legacy
`GEMINI_API_1` variable for backward compatibility. Prefer
`GEMINI_API_KEY` for new setups.

### Verify the connection

Install dependencies and run the live smoke test:

```bash
pip install -r requirements.txt
python scripts/gemini_smoke_test.py
```

The smoke test sends one short request, confirms a known response token,
and never prints the API key. A successful response proves API connectivity;
it does not by itself validate agent quality or production readiness.

### Offline tests

```bash
python -m pytest -q tests/test_gemini_provider.py tests/test_opsforge_agents.py
```

These tests mock the Google client and do not require an API key or network access.


### Model profiles

Use Flash for the default cost-efficient agent path:

```powershell
$env:GEMINI_MODEL = "gemini-3.8-flash"
```

For a Pro-class reasoning profile, set the model explicitly to the
currently available Pro model enabled for your Google AI Studio project:

```powershell
$env:GEMINI_MODEL = "gemini-3.1-pro-preview"
```

Model availability and billing depend on the Google API project and region.
A Gemini app subscription does not automatically provide Gemini Developer API
credits; verify API access and billing separately in Google AI Studio.


## OPSFORGE CRM Operations Agent

The `crm_operations` agent converts supplied operating context into an
evidence-conscious CRM improvement plan. It is advisory-only: it does not
connect to or change Adobe Campaign, Salesforce, or other production systems.

### Example

```python
from opsforge.agents.crm_operations import CRMOperationsAgent
from opsforge.agents.registry import AgentRegistry
from opsforge.orchestrator import Orchestrator
from opsforge.providers.gemini import GeminiProvider

registry = AgentRegistry()
registry.register(CRMOperationsAgent(provider=GeminiProvider()))
orchestrator = Orchestrator(registry)

result = orchestrator.execute(
    "crm_operations",
    {
        "objective": "Reduce pre-send campaign QA defects",
        "context": {
            "platform": "Adobe Campaign Classic",
            "current_process": "Manual pre-send checks",
            "known_constraints": ["No production changes"],
        },
        "constraints": ["Use existing team capacity"],
        "use_gemini": True,
    },
)
print(result["result"]["report"])
```

The generated advisory covers current-state assessment, prioritised
recommendations, a 30/60/90-day roadmap, KPIs, risks and evidence gaps.
Input context is treated as unverified; the agent must label assumptions
and must not invent performance figures or claim that actions were executed.

### Test

```bash
python -m pytest -q tests/test_crm_operations_agent.py
```


## OPSFORGE Adobe Campaign QA Agent

The `adobe_campaign_qa` agent runs deterministic pre-send checks using the
same QA rules as ACC Agent Gate. It checks unsubscribe links, market legal
footers, price/currency locale, consent filtering, proof sign-off, local quiet
hours, marketing typology, seed-list presence and subject length.

The input is an explicit delivery evidence object; the agent does not query
Adobe Campaign or infer missing facts. Blockers produce a `hold`
recommendation. A clean result is only eligible for human review—it is not
send approval and does not execute a delivery.

### Example

```python
from opsforge.agents.adobe_campaign_qa import AdobeCampaignQAAgent

agent = AdobeCampaignQAAgent()
result = agent.run({
    "delivery": {
        "id": "DM_TEST_HR",
        "internal_name": "DM_TEST_HR",
        "market": "HR",
        "label": "Test campaign Croatia",
        "subject": "Test campaign",
        "preheader": "A short preheader",
        "body": "<footer>Legal entity HR ... UnsubscriptionLink ...</footer>",
        "target_count": 12000,
        "scheduled_local": "2026-11-24 10:00",
        "typology": "TY_MARKETING_EU",
        "proof_sent": True,
        "seed_list": True,
        "consent_filter": True,
    }
})
print(result["status"], result["blockers"])
```

Set `use_gemini=True` to add remediation guidance. Gemini can explain fixes,
but deterministic check results remain authoritative and cannot be overridden
by generated text.

### Test

```bash
python -m pytest -q tests/test_adobe_campaign_qa_agent.py
```


## OPSFORGE Marketing Analytics Agent

The `marketing_analytics` agent calculates campaign-level and aggregate
CRM performance from supplied metrics. It reports delivery rate, bounce
rate, open rate, click-through rate, click-to-open rate, conversion rate,
revenue per 1,000 sends, CTR rankings and configurable bounce-rate alerts.

### Input contract

Provide one record per campaign with a unique `name` and numeric metrics:
`sends`, `delivered`, `opens`, `clicks`, `conversions`, `bounces`,
and optional `revenue`. Missing metrics default to zero. Counts must be
non-negative and internally consistent. Open and click counts are treated
as unique counts for rate calculations. Revenue uses the currency unit
supplied by the caller; currency conversion is not performed.

### Example

```python
from opsforge.agents.marketing_analytics import MarketingAnalyticsAgent

agent = MarketingAnalyticsAgent()
result = agent.run({
    "period": "Jan-Aug 2026",
    "bounce_rate_threshold_pct": 1.5,
    "campaigns": [
        {
            "name": "Flagship launch",
            "sends": 10000,
            "delivered": 9800,
            "opens": 4900,
            "clicks": 980,
            "conversions": 98,
            "bounces": 200,
            "revenue": 250000,
        }
    ],
})
print(result["overall"])
print(result["insights"])
```

Optionally provide `baseline_campaigns` to calculate absolute KPI deltas
against a comparison period. Rate deltas are percentage-point changes;
volume and revenue deltas are raw differences. Set `use_gemini=True` for
a narrative interpretation. Deterministic calculations remain authoritative;
Gemini must not invent metrics or causal explanations.

### Metric definitions

- Delivery rate = delivered / sends × 100
- Bounce rate = bounces / sends × 100
- Open rate = unique opens / delivered × 100
- Click-through rate = unique clicks / delivered × 100
- Click-to-open rate = unique clicks / unique opens × 100
- Conversion rate = conversions / clicks × 100
- Revenue per 1,000 sends = revenue / sends × 1,000

A zero denominator returns `null`, not a fabricated zero rate.

### Test

```bash
python -m pytest -q tests/test_marketing_analytics_agent.py
```


## Typed MCP Policy Server

A typed MCP entry point exposes the deterministic gate as structured
campaign-governance tools. Eligible send requests are also recorded in a
SQLite-backed approval ledger with payload and policy fingerprints, role
constraints, self-approval prevention and distinct-reviewer dual approval.
The ledger is review evidence only: approval does not authorize or execute a
Campaign send. See [Phase 2 architecture and security boundary](docs/MCP_POLICY_SERVER.md).

Available tools:

- `campaign_preflight_check` — deterministic QA with APPROVE/BLOCK evidence.
- `campaign_request_execution` — queues eligible sends for human approval;
  it never approves or executes a campaign.
- `audit_chain_verify` — verifies the hash-chained audit history.

Run it with `python -m acc_agent_gate.policy_server`. See
[Phase 1 architecture, tool contracts and security boundaries](docs/MCP_POLICY_SERVER.md).


## Authenticated Human Reviewer API

A separate review-only HTTP service lets authorized human reviewers inspect
role-eligible tickets and record APPROVE/REJECT decisions. Reviewer identity
and role are derived from server-side hashed bearer credentials; the service
does not accept client-supplied identities and does not execute campaigns.

- Start: `python -m acc_agent_gate.reviewer_api`
- Configure: `ACC_GATE_REVIEWER_CREDENTIALS_JSON` and
  `ACC_GATE_APPROVAL_DB`
- API setup and security boundary: [Reviewer API documentation](docs/REVIEWER_API.md)

An approved ledger record is not execution authorization. Put any remote
deployment behind HTTPS, rate limiting and managed secrets.

## Phase 4 — Signed Execution Authorization

The separate execution-authorization library adds short-lived HMAC-signed,
single-use permits bound to the approved payload, policy digest, audit
fingerprint and distinct human approvers. It re-runs QA/policy checks at
issuance and consumption and persists consumed JTIs to prevent replay.

- Reference implementation: `acc_agent_gate.execution_authorizer.ExecutionAuthorizer`
- Documentation and integration boundary: [Signed Execution Authorization](docs/EXECUTION_AUTHORIZATION.md)
- Tests: `tests/test_execution_authorizer.py`

This is a synthetic-backend reference implementation only. No production
Adobe Campaign connector or agent-callable execution tool is provided.
