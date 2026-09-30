import logging
import re
import time
from collections.abc import Iterable
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from enterprise_rag.core.config import Settings
from enterprise_rag.core.security import FixedWindowRateLimiter, valid_api_key
from enterprise_rag.observability.metrics import MetricsRegistry

logger = logging.getLogger("enterprise_rag.request")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def install_request_middleware(
    app: FastAPI,
    settings: Settings,
    metrics: MetricsRegistry,
) -> None:
    raw_api_key = settings.api_key.get_secret_value() if settings.api_key else ""
    expected_api_key = raw_api_key or None
    rate_limiter = FixedWindowRateLimiter(settings.rate_limit_requests_per_minute)

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming_id = request.headers.get("X-Request-ID", "")
        request_id = incoming_id if _REQUEST_ID_PATTERN.fullmatch(incoming_id) else uuid4().hex
        request.state.request_id = request_id
        started_at = time.perf_counter()

        if not _is_public_path(request.url.path):
            if not valid_api_key(expected_api_key, request.headers.get("X-API-Key")):
                early_response = JSONResponse(
                    status_code=401,
                    content={"error": {"code": "unauthorized", "message": "Invalid API key"}},
                )
                return _complete_request(
                    request, early_response, request_id, started_at, metrics, app
                )
            client_host = request.client.host if request.client else "unknown"
            allowed, retry_after = rate_limiter.allow(client_host)
            if not allowed:
                early_response = JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limit_exceeded",
                            "message": "Request rate limit exceeded",
                        }
                    },
                    headers={"Retry-After": str(retry_after)},
                )
                return _complete_request(
                    request, early_response, request_id, started_at, metrics, app
                )

        try:
            response = await call_next(request)
        except Exception:
            duration_seconds = time.perf_counter() - started_at
            metrics.record_http(
                request.method,
                _route_template(request, app),
                500,
                duration_seconds,
            )
            logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_seconds * 1000, 2),
                },
            )
            raise
        return _complete_request(request, response, request_id, started_at, metrics, app)


def _complete_request(
    request: Request,
    response: Response,
    request_id: str,
    started_at: float,
    metrics: MetricsRegistry,
    app: FastAPI,
) -> Response:
    duration_seconds = time.perf_counter() - started_at
    duration_ms = round(duration_seconds * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
        "img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'"
    )
    metrics.record_http(
        request.method,
        _route_template(request, app),
        response.status_code,
        duration_seconds,
    )
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


def _route_template(request: Request, app: FastAPI) -> str:
    for route in app.routes:
        for candidate in _effective_routes(route):
            path_regex = getattr(candidate, "path_regex", None)
            if path_regex is not None and path_regex.fullmatch(request.url.path):
                path = getattr(candidate, "path", None)
                if path:
                    return str(path)
    return "unmatched"


def _is_public_path(path: str) -> bool:
    return path in {"/", "/ui", "/health", "/health/live", "/health/ready"} or (
        path.startswith("/assets/")
    )


def _effective_routes(route: Any) -> Iterable[Any]:
    contexts = getattr(route, "effective_route_contexts", None)
    if callable(contexts):
        return cast(Iterable[Any], contexts())
    return (route,)
