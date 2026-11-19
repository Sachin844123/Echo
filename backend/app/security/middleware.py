"""Reject untrusted requests before routing or reading request bodies."""

import logging
import secrets
import time
import uuid

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings


logger = logging.getLogger("echo.security")


class LocalSecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        if settings.session_token is None:
            raise ValueError("ECHO_SESSION_TOKEN is required")
        self.expected_token = settings.session_token.get_secret_value().encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        status = 500
        response_started = False
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope["headers"]:
            headers.setdefault(key.lower(), []).append(value)
        origins = headers.get(b"origin", [])
        valid_origin = len(origins) == 1 and origins[0].decode("latin-1") in self.settings.allowed_origins

        async def safe_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                response_headers = list(message.get("headers", []))
                response_headers.extend([
                    (b"x-request-id", request_id.encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"content-security-policy", b"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
                ])
                message = {**message, "headers": response_headers}
            await send(message)

        async def reject(code: int, detail: str):
            response_headers = {"WWW-Authenticate": "Bearer"} if code == 401 else {}
            if valid_origin:
                response_headers.update({"Access-Control-Allow-Origin": origins[0].decode("ascii"), "Vary": "Origin"})
            await JSONResponse({"detail": detail}, status_code=code, headers=response_headers)(scope, receive, safe_send)

        try:
            client = scope.get("client")
            if client is None or client[0] != "127.0.0.1":
                await reject(403, "Loopback clients only")
                return
            hosts = headers.get(b"host", [])
            if len(hosts) != 1 or hosts[0].decode("latin-1") not in self.settings.allowed_hosts:
                await reject(400, "Invalid host")
                return
            if origins and not valid_origin:
                await reject(403, "Origin not allowed")
                return
            # Browser preflight carries no bearer token. It exposes transport policy only;
            # CORSMiddleware handles it without invoking an API route.
            preflight = scope["method"] == "OPTIONS" and valid_origin and b"access-control-request-method" in headers
            # Only the non-sensitive, locally built shell/assets are public.
            # No API route, preview, imported file or token is served here.
            shell = scope["method"] in {"GET", "HEAD"} and (
                scope["path"] in {"/", "/favicon.svg"} or scope["path"].startswith("/assets/"))
            if not preflight and not shell:
                authorization = headers.get(b"authorization", [])
                if len(authorization) != 1 or len(authorization[0]) > 256:
                    await reject(401, "Valid session token required")
                    return
                scheme, separator, token = authorization[0].partition(b" ")
                if scheme.lower() != b"bearer" or not separator or not secrets.compare_digest(token, self.expected_token):
                    await reject(401, "Valid session token required")
                    return
            await self.app(scope, receive, safe_send)
        except Exception:
            logger.exception("request_failed", extra={"request_id": request_id})
            if response_started:
                raise
            await reject(500, "Internal server error")
        finally:
            logger.info("request_complete", extra={
                "request_id": request_id, "status_code": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            })
