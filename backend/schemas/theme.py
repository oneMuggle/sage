"""Theme domain models (pydantic 2.x compatible)."""

from pydantic import BaseModel, ConfigDict, Field


class ThemePreset(BaseModel):
    """A named theme preset - builtin or user-created."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9-]{1,32}$")
    name: str  # i18n key
    description: str  # i18n key
    cover: str | None = None
    css: str | None = None


class ThemeCssPayload(BaseModel):
    """Raw CSS string + parsed whitelisted variables."""

    model_config = ConfigDict(extra="forbid")

    css: str
    vars: dict[str, str] = {}  # 16-var whitelist, parsed separately by the API layer


class ActiveTheme(BaseModel):
    """Currently active theme: a preset + optional custom CSS overlay."""

    model_config = ConfigDict(extra="forbid")

    presetId: str
    customCss: str | None = None
