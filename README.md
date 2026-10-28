# ACC Agent Gate

**[▶ Interactive demo](https://sghatge.github.io/acc-agent-gate/)** · change the policy and watch an AI agent's Black Friday session re-run live.

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
python -m pytest -q                           # 24 tests
```

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
