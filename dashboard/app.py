"""FastAPI application factory, static assets, and scheduler lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers import SchedulerNotRunningError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from dashboard.routes import agents, applications, config_routes, jobs, ws
from scheduler.tasks import get_scheduler, reset_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background scheduler on boot."""

    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    yield
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    except (SchedulerNotRunningError, Exception):
        pass
    reset_scheduler()


def create_app() -> FastAPI:
    """Configure routes, CORS, and static files."""

    app = FastAPI(title="Ultra Job Agent", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    static_path = Path(__file__).parent / "static"
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    resumes_path = Path(__file__).resolve().parents[1] / "resumes"
    if resumes_path.exists():
        app.mount("/resumes", StaticFiles(directory=str(resumes_path)), name="resumes")

    app.include_router(jobs.router, prefix="/api")
    app.include_router(applications.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    app.include_router(config_routes.router, prefix="/api")
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(str(static_path / "index.html"))

    return app


app = create_app()
