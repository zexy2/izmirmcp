from __future__ import annotations

import contextlib
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from app.core.abuse_guard import McpAbuseGuardMiddleware
from app.core.api_auth import ApiKeyAuthMiddleware, validate_api_keys
from app.core.cors import McpCorsMiddleware, validate_cors_origins
from app.core.http_logging import AccessLogMiddleware
from app.core.mcp_transport import McpJsonRpcGuard
from app.core.rate_limit import ClientRateLimiter, ConcurrencyLimiter
from app.core.loop_watchdog import start_watchdog, validate_watchdog_settings
from app.core.status import evaluate, public_readiness, source_cache_status
from app.core.tool_telemetry import tool_telemetry
from app.core.settings import Settings, get_settings
from app.mcp.registry import create_mcp_server

logger = logging.getLogger("izmir_mcp.security")

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class HostPolicyMiddleware:
    """Reject requests whose Host header is not allowlisted (DNS rebinding).

    With no allowlist configured the request passes; ``create_app`` warns once
    so existing deployments are not broken by an upgrade.
    """

    def __init__(self, app, *, allowed_hosts: tuple[str, ...]):
        self.app = app
        self.allowed = {host.lower() for host in allowed_hosts}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.allowed or "*" in self.allowed:
            await self.app(scope, receive, send)
            return
        host = ""
        for key, value in scope.get("headers", []):
            if key == b"host":
                host = value.decode("latin-1").strip().lower()
                break
        bare = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        bare = bare.strip("[]")
        if host in self.allowed or bare in self.allowed:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"ok": False, "error_code": "misdirected_request", "summary": "Unknown host."},
            status_code=421,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)


def check_exposure(settings: Settings) -> None:
    """Warn (or fail closed) when a public bind has no authentication."""
    public_bind = settings.host not in LOOPBACK_HOSTS
    if public_bind and not settings.mcp_api_keys:
        if settings.mcp_require_auth:
            raise RuntimeError(
                "IZMIR_MCP_REQUIRE_AUTH is set but IZMIR_MCP_API_KEYS is empty "
                f"while binding {settings.host}"
            )
        logger.warning(
            "izmir-mcp binds %s without IZMIR_MCP_API_KEYS: the MCP endpoint is "
            "unauthenticated. Set API keys or IZMIR_MCP_REQUIRE_AUTH=true.",
            settings.host,
        )
    elif settings.mcp_require_auth and not settings.mcp_api_keys:
        raise RuntimeError("IZMIR_MCP_REQUIRE_AUTH is set but IZMIR_MCP_API_KEYS is empty")
    if public_bind and not settings.mcp_allowed_hosts:
        logger.warning(
            "IZMIR_MCP_ALLOWED_HOSTS is not set; Host headers are not validated."
        )


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "izmir-mcp"})


async def readyz(request):
    """Local readiness: usable surface plus a usable local datastore.

    Upstream source health is deliberately not probed: a readiness probe must
    not fan out to third-party APIs, and their outage must not restart us. The
    detail text is omitted here because this endpoint stays unauthenticated.
    """
    settings = request.app.state.settings
    try:
        tools = await request.app.state.mcp_server.list_tools()
        tool_count = len(tools)
    except Exception:  # noqa: BLE001 - readiness must never raise
        tool_count = 0
    readiness = evaluate(settings, tool_count)
    payload = public_readiness(readiness)
    return JSONResponse(
        {"ok": readiness.ready, "service": "izmir-mcp", **payload},
        status_code=200 if readiness.ready else 503,
    )


async def status(request):
    tools = await request.app.state.mcp_server.list_tools()
    settings: Settings = request.app.state.settings
    return JSONResponse(
        {
            "service": "izmir-mcp",
            "tools": [tool.name for tool in tools],
            "tool_count": len(tools),
            "limits": {
                "default_limit": settings.default_limit,
                "max_limit": settings.max_limit,
                "max_radius_m": settings.max_radius_m,
                "max_body_bytes": settings.client_max_body_bytes,
            },
            # Configuration summary, not raw endpoints: /status is reachable
            # without a key when auth is off, so it must not hand out the exact
            # upstream URLs a scraper could use.
            "configuration": {
                "auth": "enabled" if settings.mcp_api_keys else "disabled",
                "quota_enforced": bool(settings.mcp_api_keys and settings.api_key_daily_quota),
                "cors_origins": len(settings.mcp_cors_allowed_origins),
            },
            "rate_limit": request.app.state.rate_limiter.snapshot(),
            "concurrency": request.app.state.concurrency_limiter.snapshot(),
            "readiness": evaluate(settings, len(tools)).as_dict(),
            "tools_telemetry": tool_telemetry().snapshot(),
            "source_cache": source_cache_status(),
            "auth": "enabled" if settings.mcp_api_keys else "disabled",
            "quota": {
                "daily_per_key": settings.api_key_daily_quota,
                "enforced": bool(settings.mcp_api_keys and settings.api_key_daily_quota),
            },
            "upstream_health": "not_checked",
        }
    )


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/", status_code=308)


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or get_settings()
    validate_api_keys(settings.mcp_api_keys)
    validate_cors_origins(settings.mcp_cors_allowed_origins)
    check_exposure(settings)
    validate_watchdog_settings(settings)
    mcp = create_mcp_server(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        watchdog = start_watchdog(settings)
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            if watchdog is not None:
                watchdog.stop()

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Route("/status", status, methods=["GET"]),
            Route("/mcp", mcp_redirect, methods=["GET", "POST", "HEAD", "OPTIONS"]),
            Mount(
                "/mcp",
                app=mcp.streamable_http_app(
                    host=settings.host,
                    streamable_http_path="/",
                    stateless_http=True,
                    json_response=True,
                    max_request_body_size=settings.mcp_max_body_bytes,
                ),
            ),
        ],
        lifespan=lifespan,
    )

    rate_limiter = ClientRateLimiter(
        capacity=settings.client_rate_limit_capacity,
        refill_per_second=settings.client_rate_limit_refill_per_second,
        max_clients=settings.client_rate_limit_max_clients,
    )
    concurrency_limiter = ConcurrencyLimiter(
        max_concurrent=settings.client_max_concurrent_requests
    )

    # Innermost first: guard before any MCP work, then auth, then origin policy,
    # with access logging and CORS headers on the outermost response path.
    # Innermost: a malformed JSON-RPC envelope is answered with -32600/-32700
    # instead of reaching the SDK's generic failure path.
    app.add_middleware(McpJsonRpcGuard, max_body_bytes=settings.client_max_body_bytes)
    app.add_middleware(
        McpAbuseGuardMiddleware,
        max_body_bytes=settings.client_max_body_bytes,
        rate_limiter=rate_limiter,
        concurrency_limiter=concurrency_limiter,
    )
    app.add_middleware(
        ApiKeyAuthMiddleware,
        keys=settings.mcp_api_keys,
        quota_path=settings.database_path,
        daily_quota=settings.api_key_daily_quota,
    )
    app.add_middleware(HostPolicyMiddleware, allowed_hosts=settings.mcp_allowed_hosts)
    app.add_middleware(AccessLogMiddleware, enabled=settings.access_log_enabled)

    app.state.settings = settings
    app.state.mcp_server = mcp
    app.state.rate_limiter = rate_limiter
    app.state.concurrency_limiter = concurrency_limiter

    # CORS must wrap the whole stack so error responses still carry the headers.
    return McpCorsApplication(
        routes=app.routes,
        lifespan_app=app,
        allowed_origins=settings.mcp_cors_allowed_origins,
    )


class McpCorsApplication(Starlette):
    """Starlette app whose outermost layer enforces the browser Origin policy.

    The inner app is constructed separately so the Origin guard can wrap its
    fully-built middleware stack, including the SDK's own error middleware.
    """

    def __init__(self, *, routes, lifespan_app: Starlette, allowed_origins):
        super().__init__(routes=routes, lifespan=lifespan_app.router.lifespan_context)
        self._inner = lifespan_app
        self._allowed_origins = tuple(allowed_origins)
        # Share state so ``request.app.state`` resolves the same objects.
        self.state._state.update(lifespan_app.state._state)

    def build_middleware_stack(self):
        return McpCorsMiddleware(
            self._inner.build_middleware_stack(),
            allowed_origins=self._allowed_origins,
        )


app = create_app()


def run() -> None:
    """Console entry point (``izmir-mcp``).

    No argument (or ``http``) serves streamable HTTP, as before. ``stdio`` runs
    the stdio transport, so ``uvx izmir-mcp stdio`` works for registry clients
    that launch the package's default script.
    """
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "http"
    if mode == "stdio":
        from app.stdio import main as stdio_main

        stdio_main()
        return
    if mode != "http":
        raise SystemExit("usage: izmir-mcp [http|stdio]")
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    run()
