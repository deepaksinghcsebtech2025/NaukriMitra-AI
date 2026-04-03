"""FastAPI application factory, static assets, and scheduler lifespan."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers import SchedulerNotRunningError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from core.startup import validate_environment
from dashboard.routes import (
    agents,
    analytics,
    applications,
    auth_routes,
    config_routes,
    jobs,
    linkedin_routes,
    resume_routes,
    track,
    ws,
)
from scheduler.tasks import get_scheduler, reset_scheduler

# Cache startup report so /health can return it
_startup_report: dict = {}


def _make_exception_handler(loop: asyncio.AbstractEventLoop):
    """Return an asyncio exception handler that silences APScheduler double-shutdown noise."""

    def handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, SchedulerNotRunningError):
            return  # APScheduler shutdown was already called; ignore the callback
        loop.default_exception_handler(context)

    return handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup checks and start background scheduler."""

    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_make_exception_handler(loop))

    global _startup_report
    _startup_report = validate_environment()

    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    try:
        yield
    except asyncio.CancelledError:
        pass  # Second Ctrl+C — exit cleanly without traceback
    finally:
        try:
            if scheduler.running:
                scheduler.shutdown(wait=False)
        except (SchedulerNotRunningError, Exception):
            pass
        reset_scheduler()


def create_app() -> FastAPI:
    """Configure routes, CORS, and static files."""

    app = FastAPI(title="Ultra Job Agent", version="2.0.0", lifespan=lifespan)
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

    # Auth routes (no /api prefix — /api/auth/login etc.)
    app.include_router(auth_routes.router, prefix="/api")
    # Core API routes
    app.include_router(jobs.router, prefix="/api")
    app.include_router(applications.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    app.include_router(config_routes.router, prefix="/api")
    app.include_router(analytics.router, prefix="/api")
    app.include_router(resume_routes.router, prefix="/api")
    app.include_router(linkedin_routes.router, prefix="/api")
    app.include_router(track.router, prefix="/api")
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict:
        """Detailed health check with service status."""
        from core.database import get_db_client

        db = get_db_client()
        db_status = "ok"
        if not db._configured:
            db_status = "not_configured"
        elif db._unreachable:
            db_status = "unreachable"

        return {
            "status": "ok",
            "version": "2.0.0",
            "database": db_status,
            "services": _startup_report,
        }

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(str(static_path / "index.html"))

    return app


app = create_app()
