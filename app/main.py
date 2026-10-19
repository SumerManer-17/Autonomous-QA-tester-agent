"""FastAPI application for the Autonomous QA Testing Agent.

Endpoints:
    GET /health
    GET /api/v1/runs
    POST /api/v1/runs
    GET /api/v1/runs/{run_id}
    GET /api/v1/runs/{run_id}/tests
    GET /api/v1/tests/{test_id}
    POST /api/v1/tests/{test_id}/rerun
    GET /api/v1/runs/{run_id}/bugs
    GET /api/v1/bugs/{bug_id}
    GET /api/v1/runs/{run_id}/artifacts
    GET /api/v1/artifacts/{rel_path:path}

Test execution is handled by a background task (no distributed job queue in
the MVP). Poll the run endpoint for status.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes  # noqa: F401  (ensures modules are imported)
from app.api.routes import artifacts, bugs, runs, tests
from app.core.config import settings
from app.core.logging import setup_logging
from app.repositories.database import init_db

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    init_db(settings.DATABASE_URL)
    for directory in (
        settings.ARTIFACTS_DIR,
        settings.SCREENSHOTS_DIR,
        settings.TRACES_DIR,
        settings.LOGS_DIR,
    ):
        import os

        os.makedirs(directory, exist_ok=True)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI-assisted autonomous QA testing system. "
        "Accepts a target URL and natural-language testing goal, explores the "
        "application, generates and executes Playwright tests, analyzes "
        "failures, and produces reproducible bug reports."
    ),
    contact={"name": "QA Engineering", "url": "https://example.local/qa"},
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    lifespan=lifespan,
)

# Versioned API.
app.include_router(runs.router, prefix="/api/v1")
app.include_router(tests.router, prefix="/api/v1")
app.include_router(bugs.router, prefix="/api/v1")
app.include_router(artifacts.router, prefix="/api/v1")

for _directory in (
    settings.ARTIFACTS_DIR,
    settings.SCREENSHOTS_DIR,
    settings.TRACES_DIR,
    settings.LOGS_DIR,
):
    os.makedirs(_directory, exist_ok=True)

# Artifact files (screenshots, logs, traces) served under /artifacts.
app.mount("/artifacts", StaticFiles(directory=settings.ARTIFACTS_DIR), name="artifacts")

# Dashboard static files.
app.mount("/dashboard/static", StaticFiles(directory="app/static"), name="dashboard-static")


@app.get("/health", tags=["health"])
async def health():
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "llm_mode": settings.LLM_MODE,
    }


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    from fastapi.responses import FileResponse

    return FileResponse("app/static/dashboard.html")
