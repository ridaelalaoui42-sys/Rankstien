"""Standalone RankStein operator. No Odysseus or Next.js runtime required."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from backend.api.operator_auth import CSRF_TOKEN, require_local
from backend.api.operator_routes import setup_rankstein_routes

ASSETS = ROOT / "backend" / "static" / "operator"
app = FastAPI(title="RankStein Operator", version="1.0.0", docs_url=None, redoc_url=None)


@app.middleware("http")
async def local_access(request: Request, call_next):
    try:
        require_local(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    response.headers.update(
        {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        }
    )
    return response


@app.get("/health")
def health():
    return {"ok": True, "service": "rankstein-operator", "pid": os.getpid()}


@app.get("/api/operator/session")
def session():
    return {"csrf_token": CSRF_TOKEN}


@app.get("/")
@app.get("/rankstein")
@app.get("/mission-control")
def home():
    return RedirectResponse("/operator")


@app.get("/operator")
@app.get("/rankstein/operator")
def dashboard():
    return FileResponse(ASSETS / "index.html")


app.mount("/operator-assets", StaticFiles(directory=ASSETS), name="operator-assets")
app.include_router(setup_rankstein_routes())
