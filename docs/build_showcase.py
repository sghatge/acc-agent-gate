"""Build docs/index.html: inject instance data, policy, the agent script and the audit chain
into docs/page.template.html. The page runs a JavaScript port of the gate in the browser."""
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acc_agent_gate import MockCampaignInstance, load_policy  # noqa: E402
from acc_agent_gate.mock_instance import MARKETS  # noqa: E402

scenario = json.loads((ROOT / "out" / "scenario.json").read_text())
entries = [json.loads(l) for l in (ROOT / "out" / "audit.jsonl").read_text().splitlines() if l.strip()]
inst = MockCampaignInstance()

counts: dict = {}
for r in inst.recipients:
    counts[r["@country"]] = counts.get(r["@country"], 0) + 1

data = {
    "meta": scenario["meta"],
    "markets": MARKETS,
    "deliveries": [asdict(d) for d in inst.deliveries.values()],
    "workflows": [asdict(w) for w in inst.workflows.values()],
    "recipients": {"total": len(inst.recipients), "by_country": counts},
    "policy": load_policy(),
    "script": [{k: s[k] for k in ("tool", "args", "intent", "phase")}
               for s in scenario["steps"] if s["actor"] == "agent"],
    "audit_entries": [{k: e.get(k) for k in ("seq", "tool", "decision", "prev", "hash")} for e in entries],
    "audit": scenario["audit"],
}
payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
html = (ROOT / "docs" / "page.template.html").read_text().replace("__DATA__", payload)
# Artifact version (the Claude artifact host adds its own document skeleton)
(ROOT / "out" / "artifact.html").write_text(html)

# GitHub Pages version: full document with link-preview metadata
SITE = "https://sghatge.github.io/acc-agent-gate/"
head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Interactive demo: an AI agent runs Black Friday across 8 EU markets in Adobe Campaign. Change the policy and watch what a governance gate stops.">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE}">
<meta property="og:title" content="I let an AI agent run Black Friday. It tried 9 risky things.">
<meta property="og:description" content="ACC Agent Gate: policy-as-code, pre-send QA, human approvals and a tamper-proof audit log for AI agents on Adobe Campaign. Interactive demo, synthetic data.">
<meta property="og:image" content="{SITE}og-black-friday.png">
<meta property="og:image:width" content="1080">
<meta property="og:image:height" content="1350">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{SITE}og-black-friday.png">
<style>:root{{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
"""
page = head + html.replace("<title>", "<title>", 1)
# move everything up to the end of the first <style> block into <head>
cut = page.index("</style>", page.index("<title>")) + len("</style>")
page = page[:cut] + "\n</head>\n<body>\n" + page[cut:] + "\n</body>\n</html>\n"
(ROOT / "docs" / "index.html").write_text(page)
print("docs/index.html", len(page), "bytes")
