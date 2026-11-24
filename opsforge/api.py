"""Role-aware authenticated HTTP API for OPSFORGE specialist agents.

Run locally with OPSFORGE_API_TOKEN=<long-random-secret> python -m opsforge.api.
For multiple users, configure OPSFORGE_API_CREDENTIALS_JSON with SHA-256 token
hashes mapped to named roles; see docs/opsforge-api.md.

The service is advisory-only and never connects to or mutates production CRM.
"""

import hashlib
import hmac
import json
import os
import re
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from opsforge.agents.adobe_campaign_qa import AdobeCampaignQAAgent
from opsforge.agents.crm_operations import CRMOperationsAgent
from opsforge.agents.marketing_analytics import MarketingAnalyticsAgent
from opsforge.agents.registry import AgentRegistry
from opsforge.agents.research import ResearchAgent
from opsforge.api_audit import HashChainAuditLog
from opsforge.orchestrator import Orchestrator

MAX_BODY_BYTES = 64 * 1024
AGENT_NAMES = {
    "research",
    "crm_operations",
    "adobe_campaign_qa",
    "marketing_analytics",
}
ROLE_PERMISSIONS = {
    "analyst": frozenset({"research", "crm_operations", "marketing_analytics"}),
    "qa": frozenset({"adobe_campaign_qa"}),
    "operator": frozenset(AGENT_NAMES),
    "admin": frozenset(AGENT_NAMES),
}
GEMINI_ROLES = frozenset({"operator", "admin"})
_ACTOR_RE = re.compile(r"[A-Za-z0-9_.@ -]{1,64}")
_HASH_RE = re.compile(r"[a-f0-9]{64}")


def token_sha256(token: str) -> str:
    """Return the SHA-256 hex digest used as a credential-map key."""
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("API tokens must contain at least 32 characters.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_credentials(
    credentials: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    if not isinstance(credentials, dict) or not credentials:
        raise RuntimeError("At least one OPSFORGE API credential must be configured.")
    validated: dict[str, dict[str, str]] = {}
    for digest, principal in credentials.items():
        if not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
            raise ValueError("Credential keys must be lowercase SHA-256 token hashes.")
        if not isinstance(principal, dict):
            raise ValueError("Each credential principal must be an object.")
        actor = principal.get("actor")
        role = principal.get("role")
        if not isinstance(actor, str) or not _ACTOR_RE.fullmatch(actor):
            raise ValueError("Credential actor must be 1-64 safe characters.")
        if not isinstance(role, str) or role not in ROLE_PERMISSIONS:
            raise ValueError(f"Unsupported OPSFORGE role: {role}")
        validated[digest] = {"actor": actor, "role": role}
    return validated


def load_credentials(
    *,
    token: str | None = None,
    credential_hashes: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    """Load hashed multi-user credentials or a single operator token fallback."""
    if credential_hashes is not None:
        return _validate_credentials(credential_hashes)

    configured = os.getenv("OPSFORGE_API_CREDENTIALS_JSON")
    if configured:
        try:
            parsed = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OPSFORGE_API_CREDENTIALS_JSON must be valid JSON.") from exc
        return _validate_credentials(parsed)

    api_token = token if token is not None else os.getenv("OPSFORGE_API_TOKEN")
    if not isinstance(api_token, str) or len(api_token) < 32:
        raise RuntimeError(
            "Set OPSFORGE_API_CREDENTIALS_JSON or OPSFORGE_API_TOKEN "
            "(minimum 32 characters)."
        )
    # Backward-compatible local single-credential mode. It has operator rights;
    # configure credential hashes for named per-user roles.
    return {
        token_sha256(api_token): {
            "actor": "local-operator",
            "role": "operator",
        }
    }


def build_orchestrator() -> Orchestrator:
    """Build the allow-listed registry used by the API."""
    registry = AgentRegistry()
    for agent in (
        ResearchAgent(),
        CRMOperationsAgent(),
        AdobeCampaignQAAgent(),
        MarketingAnalyticsAgent(),
    ):
        registry.register(agent)
    return Orchestrator(registry)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    token: str | None = None,
    credential_hashes: dict[str, dict[str, str]] | None = None,
    audit_path: str | None = None,
    enable_gemini: bool | None = None,
    allowed_origins: set[str] | None = None,
    orchestrator: Orchestrator | None = None,
) -> ThreadingHTTPServer:
    """Create the role-aware API; every execution route requires a bearer token."""
    credentials = load_credentials(token=token, credential_hashes=credential_hashes)
    gemini_enabled = (
        enable_gemini
        if enable_gemini is not None
        else os.getenv("OPSFORGE_ENABLE_GEMINI", "false").lower() == "true"
    )
    origins = (
        allowed_origins
        if allowed_origins is not None
        else {
            item.strip()
            for item in os.getenv("OPSFORGE_CORS_ORIGINS", "").split(",")
            if item.strip()
        }
    )
    log_path = audit_path or os.getenv(
        "OPSFORGE_AUDIT_PATH", "var/opsforge-api-audit.jsonl"
    )
    audit_log = HashChainAuditLog(log_path)
    agent_orchestrator = orchestrator or build_orchestrator()

    class Handler(BaseHTTPRequestHandler):
        server_version = "OPSFORGE-API"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            # Avoid writing request paths, payloads or credentials to stdout.
            return

        def _cors_headers(self) -> dict[str, str]:
            origin = self.headers.get("Origin", "")
            if origin and origin in origins:
                return {
                    "Access-Control-Allow-Origin": origin,
                    "Vary": "Origin",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                }
            return {}

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in self._cors_headers().items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            for key, value in self._cors_headers().items():
                self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if urlparse(self.path).path == "/health":
                self._send(
                    HTTPStatus.OK,
                    {
                        "service": "opsforge-api",
                        "status": "healthy",
                        "agents": sorted(AGENT_NAMES),
                        "roles": sorted(ROLE_PERMISSIONS),
                        "execution_scope": "advisory_only",
                    },
                )
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def _principal(self) -> dict[str, str] | None:
            supplied = self.headers.get("Authorization", "")
            if not supplied.startswith("Bearer "):
                return None
            candidate = supplied[7:]
            digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            for known_digest, principal in credentials.items():
                if hmac.compare_digest(digest, known_digest):
                    return principal
            return None

        def _audit(
            self,
            *,
            request_id: str,
            principal: dict[str, str],
            agent: str,
            status: int,
            outcome: str,
            task_bytes: bytes,
        ) -> bool:
            event = {
                "request_id": request_id,
                "actor": principal["actor"],
                "actor_verified": True,
                "role": principal["role"],
                "agent": agent,
                "http_status": status,
                "outcome": outcome,
                "task_sha256": hashlib.sha256(task_bytes).hexdigest(),
            }
            try:
                audit_log.append(event)
                return True
            except (OSError, ValueError, json.JSONDecodeError):
                return False

        def _audited_denial(
            self,
            *,
            request_id: str,
            principal: dict[str, str],
            agent: str,
            task_bytes: bytes,
            status: int,
            error: str,
            message: str,
        ) -> None:
            if not self._audit(
                request_id=request_id,
                principal=principal,
                agent=agent,
                status=int(status),
                outcome="permission_denied" if status == HTTPStatus.FORBIDDEN else "blocked",
                task_bytes=task_bytes,
            ):
                self._send(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "error": "audit_unavailable",
                        "message": "Denial event could not be persisted.",
                        "request_id": request_id,
                    },
                )
                return
            self._send(
                status,
                {"error": error, "message": message, "request_id": request_id},
            )

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            match = re.fullmatch(r"/api/agents/([a-z_]+)/run", path)
            if not match:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return

            request_id = str(uuid.uuid4())
            principal = self._principal()
            if principal is None:
                self._send(
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "unauthorized", "request_id": request_id},
                )
                return

            agent_name = match.group(1)
            if agent_name not in AGENT_NAMES:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    {"error": "unknown_agent", "request_id": request_id},
                )
                return

            content_type = self.headers.get("Content-Type", "").split(";")[0].lower()
            if content_type != "application/json":
                self._send(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    {"error": "application_json_required", "request_id": request_id},
                )
                return

            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > MAX_BODY_BYTES else HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_content_length", "request_id": request_id},
                )
                return

            task_bytes = self.rfile.read(length)
            try:
                task = json.loads(task_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_json", "request_id": request_id},
                )
                return
            if not isinstance(task, dict):
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "task_must_be_json_object", "request_id": request_id},
                )
                return

            if agent_name not in ROLE_PERMISSIONS[principal["role"]]:
                self._audited_denial(
                    request_id=request_id,
                    principal=principal,
                    agent=agent_name,
                    task_bytes=task_bytes,
                    status=HTTPStatus.FORBIDDEN,
                    error="role_not_authorized",
                    message=f"Role '{principal['role']}' cannot execute agent '{agent_name}'.",
                )
                return

            use_gemini = task.get("use_gemini", False)
            if not isinstance(use_gemini, bool):
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "use_gemini_must_be_boolean", "request_id": request_id},
                )
                return
            if use_gemini and principal["role"] not in GEMINI_ROLES:
                self._audited_denial(
                    request_id=request_id,
                    principal=principal,
                    agent=agent_name,
                    task_bytes=task_bytes,
                    status=HTTPStatus.FORBIDDEN,
                    error="gemini_role_not_authorized",
                    message="Gemini execution requires operator or admin role.",
                )
                return
            if use_gemini and not gemini_enabled:
                self._audited_denial(
                    request_id=request_id,
                    principal=principal,
                    agent=agent_name,
                    task_bytes=task_bytes,
                    status=HTTPStatus.FORBIDDEN,
                    error="gemini_execution_disabled",
                    message="Set OPSFORGE_ENABLE_GEMINI=true on the server to enable model execution.",
                )
                return

            try:
                result = agent_orchestrator.execute(agent_name, task)
                response = {
                    **result,
                    "request_id": request_id,
                    "authorization": {"role": principal["role"]},
                    "execution_scope": "advisory_only",
                }
                status = HTTPStatus.OK
                outcome = "completed"
            except ValueError as exc:
                response = {
                    "error": "invalid_task",
                    "message": str(exc),
                    "request_id": request_id,
                }
                status = HTTPStatus.BAD_REQUEST
                outcome = "rejected"
            except Exception as exc:
                # Keep implementation details and provider errors out of the API.
                response = {
                    "error": "agent_execution_failed",
                    "failure_type": type(exc).__name__,
                    "request_id": request_id,
                }
                status = HTTPStatus.BAD_GATEWAY
                outcome = "failed"

            if not self._audit(
                request_id=request_id,
                principal=principal,
                agent=agent_name,
                status=int(status),
                outcome=outcome,
                task_bytes=task_bytes,
            ):
                self._send(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "error": "audit_unavailable",
                        "message": "Execution result withheld because the audit event could not be persisted.",
                        "request_id": request_id,
                    },
                )
                return

            self._send(status, response)

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.getenv("OPSFORGE_API_HOST", "127.0.0.1")
    port = int(os.getenv("OPSFORGE_API_PORT", "8765"))
    server = create_server(host, port)
    print(f"OPSFORGE API listening on http://{host}:{port}")
    print("Execution requires bearer authentication; HTTPS should terminate at a trusted proxy.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
