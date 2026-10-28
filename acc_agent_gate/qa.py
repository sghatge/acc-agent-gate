"""Pre-send QA gate for a delivery.

Each check is small, deterministic and explainable, so a human approver can
see exactly why an agent's send was allowed or stopped. Checks encode the
kind of rules a multi-market CRM ops team applies by hand before every send.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .mock_instance import MARKETS, Delivery


@dataclass
class CheckResult:
    id: str
    label: str
    passed: bool
    severity: str  # blocker | warning
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _local_hour(d: Delivery) -> int:
    return int(d.scheduled_local.split(" ")[1].split(":")[0])


def check_unsubscribe(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    ok = "UnsubscriptionLink" in d.body
    return CheckResult("unsubscribe_link", "Unsubscribe link present", ok, "blocker",
                       "Found unsubscribe block" if ok else "No unsubscribe link in body – legal blocker in every EU market")


def check_legal_footer(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    ok = "<footer>" in d.body and f"Legal entity {d.market}" in d.body
    return CheckResult("legal_footer", "Market legal footer", ok, "blocker",
                       "Footer matches market entity" if ok else f"Footer missing or not localised for {d.market}")


_PRICE_RE = re.compile(r"(€\s?\d[\d.,\s]*\d|\d[\d.,\s]*\d\s?(€|RSD|Ft|Kč))")


def check_price_format(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    m = MARKETS[d.market]
    prices = [p[0].strip() for p in _PRICE_RE.findall(d.body)]
    bad = []
    for p in prices:
        digits = re.sub(r"[^\d.,]", "", p)
        # Locale expects decimal separator m['decimal']; a trailing ".dd" means English formatting slipped in
        if m["decimal"] == "," and re.search(r"\.\d{2}$", digits):
            bad.append(p)
        if not m["symbol_after"] and p.endswith("€"):
            bad.append(p)
        if m["symbol_after"] and p.startswith("€"):
            bad.append(p)
    ok = bool(prices) and not bad
    detail = (f"Prices match {m['name']} locale: {', '.join(prices)}" if ok
              else f"Price not in {m['name']} format: {', '.join(sorted(set(bad))) or 'none found'}")
    return CheckResult("price_locale", "Price & currency locale", ok, "blocker", detail)


def check_proof(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    return CheckResult("proof_sent", "Proof (BAT) sent & signed off", d.proof_sent, "blocker",
                       "Proof approved" if d.proof_sent else "No proof sent – market owner has not seen final render")


def check_seed(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    return CheckResult("seed_list", "Seed list attached", d.seed_list, "warning",
                       "Seed list attached" if d.seed_list else "No seed addresses – inbox monitoring blind")


def check_consent(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    return CheckResult("consent_filter", "Marketing-consent filter in target", d.consent_filter, "blocker",
                       "Target excludes recipients without marketing consent" if d.consent_filter
                       else "Target does not filter on marketing consent – GDPR exposure")


def check_quiet_hours(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    start, end = cfg.get("quiet_hours_local", [21, 8])
    h = _local_hour(d)
    in_quiet = h >= start or h < end
    return CheckResult("send_window", "Send time outside local quiet hours", not in_quiet, "blocker",
                       f"Scheduled {d.scheduled_local} local" + (" – inside quiet hours" if in_quiet else ""))


def check_subject(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    limit = cfg.get("subject_max_chars", 50)
    ok = len(d.subject) <= limit
    return CheckResult("subject_length", f"Subject ≤ {limit} chars", ok, "warning",
                       f"{len(d.subject)} chars" + ("" if ok else " – truncated on mobile and in AI inbox summaries"))


def check_typology(d: Delivery, cfg: dict[str, Any]) -> CheckResult:
    ok = d.typology.startswith("TY_MARKETING")
    return CheckResult("typology", "Marketing typology rules applied", ok, "blocker",
                       f"Typology {d.typology}")


CHECKS: list[Callable[[Delivery, dict[str, Any]], CheckResult]] = [
    check_unsubscribe, check_legal_footer, check_price_format, check_consent,
    check_proof, check_quiet_hours, check_typology, check_seed, check_subject,
]


def run_qa(d: Delivery, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or {}
    results = [c(d, cfg) for c in CHECKS]
    blockers = [r for r in results if not r.passed and r.severity == "blocker"]
    warnings = [r for r in results if not r.passed and r.severity == "warning"]
    return {
        "delivery": d.id,
        "market": d.market,
        "status": "fail" if blockers else ("pass_with_warnings" if warnings else "pass"),
        "passed": sum(r.passed for r in results),
        "total": len(results),
        "blockers": [r.id for r in blockers],
        "warnings": [r.id for r in warnings],
        "checks": [r.as_dict() for r in results],
    }
