# Free deployment and demo runbook

This project can be demonstrated without provisioning paid infrastructure.

## Zero-cost public showcase

1. Keep the interactive browser showcase on GitHub Pages:
   https://sghatge.github.io/acc-agent-gate/
2. Use the existing Streamlit Community Cloud entry point for the Python demo:
   https://share.streamlit.io/deploy?repository=sghatge%2Facc-agent-gate&branch=main&mainModule=streamlit_app.py
3. Select the public repository, `main` branch and `streamlit_app.py` entry point.
4. Keep all demo records synthetic. Do not add production Campaign credentials,
   recipient data, or API tokens to the public app.
5. Verify the deployed app from the Community Cloud workspace and review its
   logs if startup fails.

Streamlit Community Cloud currently describes its service as free. Apps with
no traffic for 12 hours are put to sleep and wake when a visitor requests them.
Resource limits apply and can change. See the official documentation:
https://docs.streamlit.io/deploy/streamlit-community-cloud

## What is not part of the free path

The optional authenticated OPSFORGE HTTP API blueprint in `render.yaml`
uses a persistent disk and a paid Render service plan, as documented in
`docs/opsforge-hosted-deployment.md`. Do not deploy that blueprint when the
budget is zero.

The GitHub Pages showcase and the Streamlit demo are demonstrations, not a
production identity, audit-retention, or Campaign integration environment.
The API should remain local for development unless an approved hosting budget,
identity layer, persistent audit retention, and security review are available.

## Release smoke checklist

- [ ] GitHub Actions CI passes on Python 3.11 and 3.12.
- [ ] GitHub Pages showcase loads.
- [ ] Streamlit app starts and renders the synthetic demo.
- [ ] No secrets or production data are present in repository history.
- [ ] Human approval and execution boundaries remain visible in the demo.
