"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .core.config import get_settings
from .infra.security import authenticate_request
from .routes import register_routes


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Local Deep Coding Agent Workbench", version="0.1.0")

    @app.middleware("http")
    async def workbench_auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)
        authorization = request.headers.get("authorization")
        try:
            request.state.auth_context = authenticate_request(authorization, get_settings())
        except HTTPException as exc:
            detail = exc.detail
            body = {"detail": detail} if isinstance(detail, str) else {"detail": str(detail)}
            return JSONResponse(status_code=exc.status_code, content=body)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_routes(app)
    return app
