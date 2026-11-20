import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import (
    agent_upload,
    audit,
    auth,
    backups,
    clients,
    dashboard,
    device_credentials,
    downloads,
    firmware,
    ftp_accounts,
    health,
    monitoring,
    server,
    system_users,
)
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.ratelimit import limiter

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("h2node_backup_api_started", frontend_origin=settings.frontend_origin)
    yield


app = FastAPI(
    title="H2NODE Backup API",
    version="0.1.0",
    docs_url=f"{settings.api_prefix}/docs" if settings.enable_docs else None,
    openapi_url=f"{settings.api_prefix}/openapi.json" if settings.enable_docs else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", uuid.uuid4().hex)
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        # COOKIE_SECURE=true é o próprio operador afirmando que o tráfego chega
        # via HTTPS (mesmo com TLS terminado num proxy externo).
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    # Lista explícita: com allow_credentials=True o navegador ignora curingas.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    max_age=600,
)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = jsonable_encoder(exc.errors())
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", [])[1:])
    detail = f"dados inválidos: {loc} — {first.get('msg', '')}" if loc else "dados inválidos"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": detail, "errors": errors},
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "erro interno"},
    )


_p = settings.api_prefix
for r in (
    health.router,
    auth.router,
    dashboard.router,
    clients.router,
    ftp_accounts.router,
    device_credentials.router,
    backups.router,
    server.router,
    audit.router,
    system_users.router,
    agent_upload.router,
    downloads.router,
    firmware.router,
    monitoring.router,
):
    app.include_router(r, prefix=_p)
