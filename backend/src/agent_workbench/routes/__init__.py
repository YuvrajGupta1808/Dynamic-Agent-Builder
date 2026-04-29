"""HTTP route registration."""

from fastapi import FastAPI

from . import config, files, health, runs, sessions, workspaces


def register_routes(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(config.router)
    app.include_router(workspaces.router)
    app.include_router(sessions.router)
    app.include_router(files.router)
    app.include_router(runs.router)
