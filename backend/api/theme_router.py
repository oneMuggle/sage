"""Theme REST API: 7 endpoints with unified ApiResponse envelope."""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Body, Depends
from pydantic import ValidationError

from backend.schemas.common import ApiError, ApiResponse
from backend.schemas.theme import ActiveTheme, ThemeCssPayload, ThemePreset
from backend.services.theme_storage import ThemeStorage

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton storage instance (overridden in tests via dependency)
_default_storage: ThemeStorage = None  # type: ignore[assignment]


def get_storage() -> ThemeStorage:
    """Dependency: return singleton ThemeStorage pointing at backend/data/themes/."""
    global _default_storage
    if _default_storage is None:
        # Subdir under backend/data/ to avoid colliding with the backend.data
        # Python package (which already holds *.py modules).
        data_dir = Path(__file__).parent.parent / "data" / "themes"
        _default_storage = ThemeStorage(data_dir)
    return _default_storage


# ---------- 16-var whitelist (mirror of frontend cssValidator) ----------

ALLOWED_CSS_VARS = frozenset(
    {
        "--color-bg",
        "--color-bg-secondary",
        "--color-bg-tertiary",
        "--color-fg",
        "--color-fg-secondary",
        "--color-fg-muted",
        "--color-border",
        "--color-border-strong",
        "--color-accent",
        "--color-accent-hover",
        "--color-success",
        "--color-warning",
        "--color-error",
        "--color-info",
        "--color-link",
        "--color-link-hover",
    }
)

FORBIDDEN_PATTERNS = [
    (r"@import", "CSS_INJECTION_FORBIDDEN: @import not allowed"),
    (r"expression\s*\(", "CSS_INJECTION_FORBIDDEN: expression() not allowed"),
    (r"behavior\s*:", "CSS_INJECTION_FORBIDDEN: behavior: not allowed"),
    (r"javascript:", "CSS_INJECTION_FORBIDDEN: javascript: URL not allowed"),
    (r"url\s*\(\s*['\"]?\s*https?:", "CSS_INJECTION_FORBIDDEN: external URL not allowed"),
    (r"url\s*\(\s*['\"]?\s*data:", "CSS_INJECTION_FORBIDDEN: data URL not allowed"),
    (r"-moz-binding", "CSS_INJECTION_FORBIDDEN: -moz-binding not allowed"),
    (r"@charset", "CSS_INJECTION_FORBIDDEN: @charset not allowed"),
]

MAX_LINE_LENGTH = 1000
MAX_TOTAL_LENGTH = 50_000


def _validate_css(css: str) -> dict:
    """Return {valid: bool, errors?: List[str]}."""
    errors: list[str] = []
    if len(css) > MAX_TOTAL_LENGTH:
        errors.append(f"CSS_TOO_LARGE: total length {len(css)} > {MAX_TOTAL_LENGTH}")
        return {"valid": False, "errors": errors}

    for i, line in enumerate(css.splitlines(), 1):
        if len(line) > MAX_LINE_LENGTH:
            errors.append(f"LINE_TOO_LONG: line {i} > {MAX_LINE_LENGTH} chars")
        for pattern, message in FORBIDDEN_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                errors.append(f"line {i}: {message}")

    # Whitelist check: extract --var: value; pairs
    var_decls = re.findall(r"(--[a-z0-9-]+)\s*:", css)
    for var in set(var_decls):
        if var not in ALLOWED_CSS_VARS:
            errors.append(f"VAR_NOT_ALLOWED: {var}")

    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True}


# ---------- endpoints ----------


@router.get("/list", response_model=ApiResponse[list[ThemePreset]])
def list_themes(storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.list())
    except OSError:
        logger.exception("themes.json read failed")
        return ApiError(error="主题存储读取失败", code="STORAGE_READ_FAILED")


@router.get("/get/{theme_id}", response_model=ApiResponse[ThemePreset])
def get_theme(theme_id: str, storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        preset = storage.get(theme_id)
        if not preset:
            return ApiError(error=f"Theme '{theme_id}' not found", code="THEME_NOT_FOUND")
        return ApiResponse(success=True, data=preset)
    except OSError:
        logger.exception("themes.json read failed")
        return ApiError(error="主题存储读取失败", code="STORAGE_READ_FAILED")


@router.post("/save", response_model=ApiResponse[ThemePreset])
def save_theme(
    preset: ThemePreset = Body(...),
    storage: ThemeStorage = Depends(get_storage),
) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.save(preset))
    except ValidationError as e:
        return ApiError(error=str(e), code="VALIDATION_ERROR")
    except ValueError as e:
        return ApiError(error=str(e), code="VALIDATION_ERROR")
    except OSError:
        logger.exception("themes.json write failed")
        return ApiError(error="主题存储写入失败", code="STORAGE_WRITE_FAILED")


@router.delete("/delete/{theme_id}", response_model=ApiResponse[dict])
def delete_theme(theme_id: str, storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        if storage.delete(theme_id):
            return ApiResponse(success=True, data={"deleted": theme_id})
        return ApiError(error=f"Theme '{theme_id}' not found", code="THEME_NOT_FOUND")
    except OSError:
        logger.exception("themes.json write failed")
        return ApiError(error="主题存储写入失败", code="STORAGE_WRITE_FAILED")


@router.get("/active", response_model=ApiResponse[ActiveTheme])
def get_active(storage: ThemeStorage = Depends(get_storage)) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.get_active())
    except OSError:
        logger.exception("active_theme.json read failed")
        return ApiError(error="活动主题读取失败", code="STORAGE_READ_FAILED")


@router.put("/active", response_model=ApiResponse[ActiveTheme])
def put_active(
    active: ActiveTheme = Body(...),
    storage: ThemeStorage = Depends(get_storage),
) -> ApiResponse:
    try:
        return ApiResponse(success=True, data=storage.save_active(active))
    except ValidationError as e:
        return ApiError(error=str(e), code="VALIDATION_ERROR")
    except ValueError as e:
        return ApiError(error=str(e), code="VALIDATION_ERROR")
    except OSError:
        logger.exception("active_theme.json write failed")
        return ApiError(error="活动主题写入失败", code="STORAGE_WRITE_FAILED")


@router.post("/validate", response_model=ApiResponse[dict])
def validate_css(payload: ThemeCssPayload = Body(...)) -> ApiResponse:
    """Validate raw CSS without saving. Returns {valid, errors?}."""
    return ApiResponse(success=True, data=_validate_css(payload.css))
