from __future__ import annotations

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from app.core.settings import get_settings
from app.mcp.registry import create_mcp_server


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "izmir-mcp"})


async def readyz(_request):
    return JSONResponse({"ok": True, "service": "izmir-mcp", "ready": True})


async def status(request):
    tools = await request.app.state.mcp_server.list_tools()
    settings = request.app.state.settings
    return JSONResponse(
        {
            "service": "izmir-mcp",
            "tools": [tool.name for tool in tools],
            "tool_count": len(tools),
            "limits": {
                "default_limit": settings.default_limit,
                "max_limit": settings.max_limit,
                "max_radius_m": settings.max_radius_m,
            },
            "upstream_health": "not_checked",
        }
    )


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/", status_code=308)


def create_app() -> Starlette:
    settings = get_settings()
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
    app.state.settings = settings
    app.state.mcp_server = mcp
    return app


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
