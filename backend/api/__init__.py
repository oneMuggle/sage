"""API package - register all routers onto the FastAPI app."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.theme_router import router as theme_router
from backend.schemas.common import ApiError


def register_routers(app: FastAPI) -> None:
    """Mount all routers onto the FastAPI app.

    Also installs the unified-envelope validation error handler so that all
    pydantic ValidationError failures are returned at HTTP 200 with our
    ``{success:false, code:VALIDATION_ERROR, details}`` shape, instead of
    FastAPI's default 422 envelope (which the frontend would have to handle
    separately).
    """
    app.include_router(theme_router, prefix="/api/v1/theme")

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        err = ApiError(
            error="Validation failed",
            code="VALIDATION_ERROR",
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=200, content=err.model_dump())
