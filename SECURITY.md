# Security Policy

## Supported versions

Security fixes are applied to the latest version on the default branch. This repository is an independent reference implementation and ships a synthetic Campaign backend; do not connect it to production systems without an independent security review.

## Reporting a vulnerability

Please do not disclose suspected vulnerabilities in public issues.

Report privately through GitHub's **Report a vulnerability** feature on this repository. Include:
- A concise description and potential impact.
- Reproduction steps or a proof of concept using synthetic data.
- The affected commit, version and environment.
- Any suggested mitigation.

Please allow a reasonable period for triage and remediation before public disclosure. Do not include real customer data, credentials, tokens or personal information in a report.

## Security design and fail-closed behavior

- Unknown tools and unrecognised actions must be denied by policy.
- A policy, validation, audit-integrity or authorization failure must not fall back to execution.
- An approval request is not an approval. Human approvals are deliberately outside the agent-callable MCP tools.
- Delivery QA must pass before a send can be considered for human approval.
- Policy checks must be repeated at the point of any separately implemented execution.
- Keep Campaign operator permissions as the outer security boundary; this gate is defence in depth, not a replacement for platform access controls.
- Keep secrets in environment variables or a managed secret store. Never commit credentials, tokens, production exports or customer data.
- MCP standard output is reserved for JSON-RPC protocol messages; diagnostic logs belong on standard error.

## Scope and limitations

The shipped backend and examples use synthetic data. The SQL/JavaScript analyzers are conservative pattern-based controls, not complete language parsers. The repository does not provide a production Adobe Campaign connector. Do not expose demo interfaces or unauthenticated local services as production operator consoles.
