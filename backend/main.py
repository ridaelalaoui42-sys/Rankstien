"""RankStein — Enterprise AI SEO Platform
FastAPI application entry point with lifespan, middleware, and routing.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from backend.core import database as db
from backend.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger("rankstein")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown."""
    settings = get_settings()
    await db.get_db()
    logger.info("Database initialized at %s", settings.db_file)
    logger.info("RankStein API ready on %s:%s", settings.host, settings.port)
    yield
    await db.close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="RankStein API", description="Enterprise AI SEO Platform", version="2.0.0", lifespan=lifespan
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-RankStein-Key"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' http://localhost:* https:;"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# Static files
(Path(__file__).resolve().parent.parent.parent / "data" / "images").mkdir(parents=True, exist_ok=True)
app.mount(
    "/images",
    StaticFiles(directory=str(Path(__file__).resolve().parent.parent.parent / "data" / "images")),
    name="images",
)

# API routes
from backend.api.routes import router as api_router

app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("backend.main:app", host=s.host, port=s.port, reload=s.debug_mode, log_level=s.log_level)
