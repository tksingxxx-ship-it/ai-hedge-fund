"""FastAPI application. Serves the API and, when built, the web UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hedge_fund.tui.keys import apply_credentials

from office.api import register
from office.config import Config
from office.db import init_db, recover_inflight
from office.redact import install_redaction, redact
from office.secrets import load_into_environ
from office.security import install as install_guard

log = logging.getLogger("office")
DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    config: Config = app.state.config
    config.ensure_dirs()
    init_db(config)
    apply_credentials()
    loaded = load_into_environ(config.secrets_path)
    if loaded:
        log.info("loaded %s stored credential names", len(loaded))
    n = recover_inflight(config)
    if n:
        log.info("marked %s in-flight office rows after restart", n)
    yield


def create_app(config: Config | None = None) -> FastAPI:
    install_redaction()
    config = config or Config.from_env()
    app = FastAPI(title="AI Hedge Fund Virtual Office", version="0.1.0", lifespan=_lifespan)
    app.state.config = config
    if config.dev_cors:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, _exc: RequestValidationError):
        # Do not echo request bodies. They may contain credentials.
        return JSONResponse(status_code=422, content={
            "error": {"code": "invalid", "message": "Request rejected. Field values are not echoed."}
        })

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={
                "error": {"code": "http", "message": redact(str(exc.detail))}
            })
        log.exception("request failed")
        return JSONResponse(status_code=500, content={
            "error": {"code": "internal", "message": redact(str(exc))}
        })

    install_guard(app, config)
    register(app)
    if (DIST / "index.html").is_file():
        assets = DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        def index():
            return FileResponse(DIST / "index.html")

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (DIST / path).resolve()
            if not str(candidate).startswith(str(DIST.resolve())):
                raise HTTPException(404)
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(DIST / "index.html")

    return app
