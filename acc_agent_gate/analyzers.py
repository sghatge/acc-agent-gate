"""Static analysis of what an agent is trying to run.

These are deliberately conservative pattern checks, not parsers. The gate's
job is to fail closed: anything that *looks* like a write is treated as one
and escalated, and a human can always approve a false positive.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SQL_WRITE = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE)\b", re.I)

# Campaign server-side JS APIs that change data, send, or reach outside the instance.
JS_RULES: list[tuple[str, str, str]] = [
    (r"xtk\.session\.Write(Collection)?\s*\(", "write", "xtk.session.Write – bulk entity write"),
    (r"\bsqlExec\s*\(", "write", "sqlExec – raw SQL execution"),
    (r"\.(Delete|DeleteCollection)\s*\(", "write", "Delete call on entity"),
    (r"nms\.delivery\.(Start|Prepare|SubmitDelivery)|\bSubmitDelivery\s*\(", "send", "Starts or submits a delivery"),
    (r"xtk\.workflow\.(Start|Stop|Kill|PostEvent)", "workflow", "Controls a workflow"),
    (r"\bexecCommand\s*\(|\bxtk\.fileRes|\bFile\s*\(", "system", "Server command / file system access"),
    (r"\bHttpClientRequest\b|\bhttp(s)?://", "egress", "Outbound network call – possible data exfiltration"),
    (r"xtk\.operator|xtk\.opsecurity|setOption\s*\(", "admin", "Operator rights or instance options"),
]
JS_READ = re.compile(r"xtk\.queryDef\.create|\.ExecuteQuery\s*\(|logInfo\s*\(", re.I)


@dataclass
class Finding:
    kind: str
    detail: str


@dataclass
class Analysis:
    is_write: bool
    categories: set[str] = field(default_factory=set)
    findings: list[Finding] = field(default_factory=list)

    def summary(self) -> str:
        return "; ".join(f.detail for f in self.findings) or "read-only patterns only"


def analyze_sql(sql: str) -> Analysis:
    hits = sorted({m.group(1).upper() for m in SQL_WRITE.finditer(sql)})
    a = Analysis(is_write=bool(hits))
    if hits:
        a.categories.add("write")
        a.findings.append(Finding("write", f"SQL write keyword(s): {', '.join(hits)}"))
        if re.search(r"\b(DELETE|UPDATE)\b", sql, re.I) and not re.search(r"\bWHERE\b", sql, re.I):
            a.findings.append(Finding("write", "No WHERE clause – full-table change"))
    return a


def analyze_js(script: str) -> Analysis:
    a = Analysis(is_write=False)
    for pattern, kind, detail in JS_RULES:
        if re.search(pattern, script):
            a.categories.add(kind)
            a.findings.append(Finding(kind, detail))
    a.is_write = bool(a.categories)
    if not a.findings and JS_READ.search(script):
        a.findings.append(Finding("read", "queryDef read only"))
    return a
