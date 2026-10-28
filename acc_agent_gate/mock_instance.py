"""A synthetic Adobe Campaign Classic v8-style instance.

Nothing here comes from a real instance. Brand, markets, volumes and
content are invented so the gate can be demonstrated end to end without
touching production data. Swap this class for a real adapter (see
``backends.py``) to sit in front of a live Campaign MCP server.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any

BRAND = "Aurora Electronics"  # fictional

# Market reference data: locale formatting + legal footer requirement + quiet hours (local)
MARKETS: dict[str, dict[str, Any]] = {
    "HR": {"name": "Croatia", "lang": "hr", "tz_offset": 1, "currency": "EUR", "decimal": ",", "thousands": ".", "symbol_after": True},
    "SI": {"name": "Slovenia", "lang": "sl", "tz_offset": 1, "currency": "EUR", "decimal": ",", "thousands": ".", "symbol_after": True},
    "RS": {"name": "Serbia", "lang": "sr", "tz_offset": 1, "currency": "RSD", "decimal": ",", "thousands": ".", "symbol_after": True},
    "AT": {"name": "Austria", "lang": "de", "tz_offset": 1, "currency": "EUR", "decimal": ",", "thousands": ".", "symbol_after": False},
    "GR": {"name": "Greece", "lang": "el", "tz_offset": 2, "currency": "EUR", "decimal": ",", "thousands": ".", "symbol_after": True},
    "CY": {"name": "Cyprus", "lang": "el", "tz_offset": 2, "currency": "EUR", "decimal": ",", "thousands": ".", "symbol_after": True},
    "HU": {"name": "Hungary", "lang": "hu", "tz_offset": 1, "currency": "HUF", "decimal": ",", "thousands": " ", "symbol_after": True},
    "CZ": {"name": "Czechia", "lang": "cs", "tz_offset": 1, "currency": "CZK", "decimal": ",", "thousands": " ", "symbol_after": True},
}

PII_FIELDS = {"@email", "@mobilePhone", "@firstName", "@lastName", "@birthDate", "@address"}

SCHEMAS: dict[str, dict[str, Any]] = {
    "nms:recipient": {
        "label": "Recipients",
        "fields": ["@id", "@email", "@firstName", "@lastName", "@mobilePhone", "@birthDate",
                   "@country", "@language", "@blackListEmail", "@consentMarketing", "@lastOpen"],
        "pii": sorted(PII_FIELDS),
    },
    "nms:delivery": {
        "label": "Deliveries",
        "fields": ["@id", "@internalName", "@label", "@market", "@state", "@targetCount",
                   "@scheduledLocal", "@typology", "@proofSent", "@seedList"],
        "pii": [],
    },
    "xtk:workflow": {
        "label": "Workflows",
        "fields": ["@id", "@internalName", "@label", "@state", "@environment", "@critical"],
        "pii": [],
    },
    "nms:broadLogRcp": {
        "label": "Delivery logs",
        "fields": ["@id", "@delivery-id", "@recipient-id", "@status", "@eventDate"],
        "pii": [],
    },
}


def _fmt_price(value: float, m: dict[str, Any]) -> str:
    whole, frac = f"{value:,.2f}".split(".")
    whole = whole.replace(",", m["thousands"])
    num = f"{whole}{m['decimal']}{frac}"
    sym = {"EUR": "€", "RSD": "RSD", "HUF": "Ft", "CZK": "Kč"}[m["currency"]]
    return f"{num} {sym}" if m["symbol_after"] else f"{sym} {num}"


@dataclass
class Delivery:
    id: str
    internal_name: str
    market: str
    label: str
    subject: str
    preheader: str
    body: str
    target_count: int
    scheduled_local: str  # "YYYY-MM-DD HH:MM" in market local time
    typology: str = "TY_MARKETING_EU"
    proof_sent: bool = True
    seed_list: bool = True
    consent_filter: bool = True
    state: str = "ready"  # ready | sent | blocked


@dataclass
class Workflow:
    id: str
    internal_name: str
    label: str
    environment: str  # prod | stage
    critical: bool = False
    state: str = "idle"  # idle | started | paused | stopped


def _good_body(market: str, price: float) -> str:
    m = MARKETS[market]
    return (
        f"<h1>Black Friday</h1><p>Flagship foldable now {_fmt_price(price, m)}</p>"
        f"<a href='<%@ include view='MirrorPage' %>'>View online</a>"
        f"<footer>{BRAND} · Legal entity {market} · "
        f"<a href='<%@ include view='UnsubscriptionLink' %>'>Unsubscribe</a></footer>"
    )


@dataclass
class MockCampaignInstance:
    seed: int = 7
    deliveries: dict[str, Delivery] = field(default_factory=dict)
    workflows: dict[str, Workflow] = field(default_factory=dict)
    recipients: list[dict[str, Any]] = field(default_factory=list)
    sent_log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        rnd = random.Random(self.seed)
        first = ["Ana", "Marko", "Eleni", "Nikos", "Petra", "Luka", "Zsófia", "Jakub", "Maja", "Ivan"]
        last = ["Horvat", "Novak", "Papadopoulou", "Georgiou", "Kovač", "Nagy", "Dvořák", "Petrović"]
        for i in range(1, 2401):
            mk = rnd.choice(list(MARKETS))
            fn, ln = rnd.choice(first), rnd.choice(last)
            self.recipients.append({
                "@id": i, "@email": f"{fn.lower()}.{ln.lower()}{i}@example.test",
                "@firstName": fn, "@lastName": ln,
                "@mobilePhone": f"+3{rnd.randint(10, 99)} {rnd.randint(100, 999)} {rnd.randint(1000, 9999)}",
                "@birthDate": f"19{rnd.randint(55, 99)}-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}",
                "@country": mk, "@language": MARKETS[mk]["lang"],
                "@blackListEmail": rnd.random() < 0.06,
                "@consentMarketing": rnd.random() > 0.18,
                "@lastOpen": f"2026-{rnd.randint(1, 10):02d}-{rnd.randint(1, 28):02d}",
            })

        bf = "2026-11-27"
        specs = [
            # id, market, volume, local send time, defects
            ("DM_BF26_HR", "HR", 182_400, f"{bf} 10:00", {}),
            ("DM_BF26_SI", "SI", 64_900, f"{bf} 10:00", {"no_unsub": True}),
            ("DM_BF26_RS", "RS", 141_200, f"{bf} 11:00", {}),
            ("DM_BF26_AT", "AT", 298_700, f"{bf} 09:30", {"no_proof": True}),
            ("DM_BF26_GR", "GR", 356_100, f"{bf} 23:30", {"bad_price": True}),
            ("DM_BF26_CY", "CY", 38_400, f"{bf} 10:00", {}),
            ("DM_BF26_HU", "HU", 211_800, f"{bf} 10:00", {"no_consent_filter": True}),
            ("DM_BF26_CZ", "CZ", 247_300, f"{bf} 10:00", {"long_subject": True}),
        ]
        subjects = {
            "HR": "Black Friday: do -40% na odabrane uređaje",
            "SI": "Black Friday: do -40 % na izbrane naprave",
            "RS": "Black Friday: do -40% na izabrane uređaje",
            "AT": "Black Friday: bis zu -40 % auf ausgewählte Geräte",
            "GR": "Black Friday: έως -40% σε επιλεγμένες συσκευές",
            "CY": "Black Friday: έως -40% σε επιλεγμένες συσκευές",
            "HU": "Black Friday: akár -40% kiválasztott eszközökre",
            "CZ": "Black Friday: až -40 % na vybraná zařízení – jen do neděle, nenechte si ujít největší slevy roku",
        }
        prices = {"HR": 1299.0, "SI": 1299.0, "RS": 152999.0, "AT": 1349.0, "GR": 1299.0,
                  "CY": 1299.0, "HU": 529990.0, "CZ": 33990.0}
        for did, mk, vol, when, defects in specs:
            body = _good_body(mk, prices[mk])
            if defects.get("no_unsub"):
                body = body.replace("<a href='<%@ include view='UnsubscriptionLink' %>'>Unsubscribe</a>", "")
            if defects.get("bad_price"):
                body = body.replace(_fmt_price(prices[mk], MARKETS[mk]), "€1,299.00")
            self.deliveries[did] = Delivery(
                id=did, internal_name=did, market=mk,
                label=f"Black Friday 2026 – {MARKETS[mk]['name']}",
                subject=subjects[mk], preheader="Ponuda traje do nedjelje." if mk == "HR" else "Limited time.",
                body=body, target_count=vol, scheduled_local=when,
                proof_sent=not defects.get("no_proof"),
                consent_filter=not defects.get("no_consent_filter"),
            )

        for wf in [
            Workflow("WKF001", "WKF_BF26_Reminder", "BF26 – 48h reminder", "prod"),
            Workflow("WKF002", "WKF_GDPR_Purge", "GDPR erasure & purge", "prod", critical=True),
            Workflow("WKF003", "WKF_Unsub_Sync", "Unsubscribe sync to CRM", "prod", critical=True),
            Workflow("WKF004", "WKF_BF26_Reminder_STG", "BF26 reminder (stage)", "stage"),
        ]:
            self.workflows[wf.internal_name] = wf

    # ------------------------------------------------------------------ reads
    def discover(self) -> dict[str, Any]:
        return {
            "instance": "aurora-mkt-prod (synthetic)",
            "version": "Campaign v8 (mock)",
            "markets": {k: v["name"] for k, v in MARKETS.items()},
            "schemas": list(SCHEMAS),
            "deliveries": len(self.deliveries),
            "workflows": len(self.workflows),
        }

    def browse_schema(self, schema: str) -> dict[str, Any]:
        if schema not in SCHEMAS:
            raise KeyError(f"Unknown schema {schema}")
        return copy.deepcopy(SCHEMAS[schema])

    def query(self, schema: str, select: list[str], where: dict[str, Any] | None = None,
              group_by: str | None = None, limit: int = 100) -> dict[str, Any]:
        where = where or {}
        if schema == "nms:recipient":
            rows = [r for r in self.recipients if all(r.get(k) == v for k, v in where.items())]
        elif schema == "nms:delivery":
            rows = [{"@id": d.id, "@internalName": d.internal_name, "@market": d.market,
                     "@label": d.label, "@state": d.state, "@targetCount": d.target_count,
                     "@scheduledLocal": d.scheduled_local, "@typology": d.typology,
                     "@proofSent": d.proof_sent, "@seedList": d.seed_list}
                    for d in self.deliveries.values()]
            rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
        elif schema == "xtk:workflow":
            rows = [{"@id": w.id, "@internalName": w.internal_name, "@label": w.label,
                     "@state": w.state, "@environment": w.environment, "@critical": w.critical}
                    for w in self.workflows.values()]
        else:
            rows = []
        if group_by:
            counts: dict[Any, int] = {}
            for r in rows:
                counts[r.get(group_by)] = counts.get(r.get(group_by), 0) + 1
            return {"rows": [{group_by: k, "count": v} for k, v in sorted(counts.items(), key=str)],
                    "total": len(rows)}
        projected = [{k: r.get(k) for k in select} for r in rows[:limit]]
        return {"rows": projected, "total": len(rows), "returned": len(projected)}

    def get_delivery(self, delivery_id: str) -> Delivery:
        if delivery_id not in self.deliveries:
            raise KeyError(f"Unknown delivery {delivery_id}")
        return self.deliveries[delivery_id]

    # ----------------------------------------------------------------- writes
    def send_delivery(self, delivery_id: str) -> dict[str, Any]:
        d = self.get_delivery(delivery_id)
        d.state = "sent"
        rec = {"delivery": d.id, "market": d.market, "volume": d.target_count}
        self.sent_log.append(rec)
        return {"status": "sent", **rec}

    def control_workflow(self, name: str, action: str) -> dict[str, Any]:
        wf = self.workflows[name]
        wf.state = {"start": "started", "pause": "paused", "stop": "stopped", "restart": "started"}[action]
        return {"workflow": name, "state": wf.state}

    def execute_js(self, script: str) -> dict[str, Any]:
        # The mock never actually evaluates JS; it just acknowledges.
        return {"status": "executed (mock)", "chars": len(script)}
