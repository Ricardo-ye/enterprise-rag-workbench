from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base exception for errors safe to expose through the API."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ConfigurationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("configuration_error", message, status_code=500)


class ProviderError(AppError):
    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(
            "model_provider_error",
            message,
            status_code=502,
            details={"provider": provider},
        )


class KnowledgeValidationError(AppError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__("knowledge_validation_error", message, status_code=status_code)


class ResourceNotFoundError(AppError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            "resource_not_found",
            f"{resource} was not found",
            status_code=404,
            details={"resource": resource, "resource_id": resource_id},
        )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            },
        )
