import logging
import uuid
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException

from researchos.api.auth import router as auth_router
from researchos.api.documents import router as documents_router
from researchos.api.errors import ApiError
from researchos.api.health import router
from researchos.api.jobs import router as jobs_router
from researchos.api.papers import router as papers_router
from researchos.api.projects import router as projects_router
from researchos.api.providers import router as providers_router
from researchos.core.config import Settings
from researchos.infrastructure.database import build_engine
from researchos.services.health import HealthProbe, InfrastructureHealth

logger = logging.getLogger(__name__)


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "request_id": request_id, "details": {}}
        },
        headers={
            "X-Request-ID": request_id,
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def create_app(settings: Settings | None = None, probe: HealthProbe | None = None) -> FastAPI:
    config = settings or Settings()
    logging.basicConfig(level=config.log_level, format="%(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(config)
        broker = Redis.from_url(
            config.redis_url.get_secret_value(),
            socket_connect_timeout=config.health_timeout_seconds,
            socket_timeout=config.health_timeout_seconds,
        )
        app.state.engine = engine
        app.state.broker = broker
        app.state.settings = config
        if probe is None:
            app.state.health = InfrastructureHealth(engine, broker)
        else:
            app.state.health = probe
        try:
            yield
        finally:
            if broker is not None:
                broker.close()
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="ResearchOS API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    @app.middleware("http")
    async def request_metadata(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        if (
            request.method in {"POST", "PATCH", "PUT"}
            and request.url.path != "/api/v1/papers/upload"
        ):
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 16 * 1024:
                    return error_response(request, 413, "request_too_large", "Request is too large")
                body.extend(chunk)
            request._body = bytes(body)
        try:
            response = await call_next(request)
        except Exception as exc:
            # Catch before ServerErrorMiddleware re-raises and Uvicorn logs raw exception data.
            logger.error(
                "unhandled_request_error request_id=%s type=%s",
                request.state.request_id,
                type(exc).__name__,
            )
            response = error_response(
                request, 500, "internal_error", "An unexpected error occurred"
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        response = error_response(
            request,
            exc.status_code,
            exc.code if isinstance(exc, ApiError) else f"http_{exc.status_code}",
            exc.detail if isinstance(exc, ApiError) else HTTPStatus(exc.status_code).phrase,
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "validation_error", "Request validation failed")

    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, exc: OperationalError):
        return error_response(
            request, 503, "database_unavailable", "Database is temporarily unavailable"
        )

    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(papers_router)
    app.include_router(jobs_router)
    app.include_router(documents_router)
    app.include_router(providers_router)
    return app
