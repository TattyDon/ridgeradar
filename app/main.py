"""RidgeRadar FastAPI application.

Betfair Exchange market radar and exploitability scoring platform.
Shadow mode Phase 1 - measurement infrastructure only.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import competitions, config, health, markets, scores
from app.config import get_settings

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("starting_ridgeradar", version="0.1.0")
    yield
    logger.info("shutting_down_ridgeradar")


# Create FastAPI application
app = FastAPI(
    title="RidgeRadar",
    description="Betfair Exchange market radar and exploitability scoring platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
static_path = Path(__file__).parent / "ui" / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Setup Jinja2 templates
templates_path = Path(__file__).parent / "ui" / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# Include API routers
app.include_router(health.router)
app.include_router(markets.router)
app.include_router(scores.router)
app.include_router(competitions.router)
app.include_router(config.router)


# UI Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "title": "Dashboard"},
    )


@app.get("/radar", response_class=HTMLResponse)
async def radar(request: Request):
    """Market radar page."""
    return templates.TemplateResponse(
        "radar.html",
        {"request": request, "title": "Market Radar"},
    )


@app.get("/market/{market_id}", response_class=HTMLResponse)
async def market_detail(request: Request, market_id: int):
    """Market detail page."""
    return templates.TemplateResponse(
        "market_detail.html",
        {"request": request, "title": "Market Detail", "market_id": market_id},
    )


@app.get("/competitions", response_class=HTMLResponse)
async def competitions(request: Request):
    """Competitions list page."""
    return templates.TemplateResponse(
        "competitions.html",
        {"request": request, "title": "Competitions"},
    )


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler."""
    if request.url.path.startswith("/api/"):
        return {"detail": "Not found"}
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "title": "Not Found", "error": "Page not found"},
        status_code=404,
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    """Custom 500 handler."""
    logger.error("server_error", path=request.url.path, error=str(exc))
    if request.url.path.startswith("/api/"):
        return {"detail": "Internal server error"}
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "title": "Error", "error": "Internal server error"},
        status_code=500,
    )
