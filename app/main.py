from __future__ import annotations

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from app.core.abuse_guard import McpAbuseGuardMiddleware
from app.core.api_auth import ApiKeyAuthMiddleware, validate_api_keys
from app.core.cors import McpCorsMiddleware, validate_cors_origins
from app.core.http_logging import AccessLogMiddleware
from app.core.rate_limit import ClientRateLimiter, ConcurrencyLimiter
from app.core.settings import Settings, get_settings
from app.mcp.registry import create_mcp_server


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "izmir-mcp"})


async def readyz(request):
    """Local readiness only: the tool surface built and the process is serving.

    Upstream source health is deliberately not probed here; a readiness check
    must not fan out to third-party APIs on every probe.
    """
    try:
        tools = await request.app.state.mcp_server.list_tools()
        tool_check = "ok" if tools else "empty"
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        tools = []
        tool_check = f"error:{type(exc).__name__}"
    ready = bool(tools)
    return JSONResponse(
        {
            "ok": ready,
            "service": "izmir-mcp",
            "ready": ready,
            "upstream_health": "not_checked",
            "checks": {
                "tool_surface": tool_check,
                "tool_count": len(tools),
            },
        },
        status_code=200 if ready else 503,
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
            "rate_limit": request.app.state.rate_limiter.snapshot(),
            "concurrency": request.app.state.concurrency_limiter.snapshot(),
            "auth": "enabled" if settings.mcp_api_keys else "disabled",
            "upstream_health": "not_checked",
        }
    )


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/", status_code=308)


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or get_settings()
    validate_api_keys(settings.mcp_api_keys)
    validate_cors_origins(settings.mcp_cors_allowed_origins)
    mcp = create_mcp_server(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

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
    app.add_middleware(
        McpAbuseGuardMiddleware,
        max_body_bytes=settings.client_max_body_bytes,
        rate_limiter=rate_limiter,
        concurrency_limiter=concurrency_limiter,
    )
    app.add_middleware(ApiKeyAuthMiddleware, keys=settings.mcp_api_keys)
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


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
