import re
import shutil
import subprocess

from pathlib import Path

import pytest


DASHBOARD = Path(__file__).parents[1] / "docs" / "opsforge" / "index.html"


def test_dashboard_exposes_all_agents_and_authenticated_api_mode():
    html = DASHBOARD.read_text(encoding="utf-8")
    for agent in ("research", "crm_operations", "adobe_campaign_qa", "marketing_analytics"):
        assert agent in html
    assert 'id="execution-mode"' in html
    assert 'id="api-token"' in html
    assert "Authorization" in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html


def test_dashboard_inline_javascript_is_syntax_valid(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed; JavaScript syntax check skipped.")
    html = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    assert scripts, "Dashboard must contain its self-contained application script."
    script_path = tmp_path / "dashboard.js"
    script_path.write_text("\n".join(scripts), encoding="utf-8")
    result = subprocess.run(
        [node, "--check", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
