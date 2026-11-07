"""Origin and header checks for mutating requests.

Browsers send Origin on cross-site posts. A foreign origin is rejected.
Mutating calls also need X-Office-Request, which a plain HTML form cannot set.
If the process is bound off loopback, OFFICE_ALLOW_REMOTE and a long
OFFICE_API_TOKEN are required, and every mutating call must send that token.
The token is never written to a log line here.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from office.config import Config

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def bind_error(config: Config) -> str | None:
    if loopback(config.host):
        return None
    if not config.allow_remote or len(config.api_token) < 16:
        return (
            f"Refusing to bind {config.host}. Set OFFICE_ALLOW_REMOTE=1 and "
            "OFFICE_API_TOKEN to at least 16 characters, or bind 127.0.0.1."
        )
    return None


def allowed_origins(config: Config) -> set[str]:
    port = config.port
    origins = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    }
    if config.dev_cors:
        origins.update({"http://127.0.0.1:5173", "http://localhost:5173"})
    return origins


def install(app: FastAPI, config: Config) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method in _MUTATING and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins(config):
                return JSONResponse(status_code=403, content={
                    "error": {"code": "origin", "message": "This origin cannot change office state."}
                })
            if request.headers.get("x-office-request") != "1":
                return JSONResponse(status_code=403, content={
                    "error": {"code": "csrf", "message": "Missing X-Office-Request header."}
                })
            if config.api_token:
                expected = f"Bearer {config.api_token}"
                if request.headers.get("authorization") != expected:
                    return JSONResponse(status_code=401, content={
                        "error": {"code": "unauthorized", "message": "API token required."}
                    })
        return await call_next(request)
