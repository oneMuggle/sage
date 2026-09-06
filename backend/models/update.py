import re
from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field, validator


class FileMeta(BaseModel):
    """Metadata for a single update file (installer/binary)."""
    filename: str = Field(..., description="Filename without path")
    url: str = Field(..., description="HTTPS URL to download file")
    sha512: str = Field(..., description="SHA-512 hex digest for integrity check")
    size: int = Field(..., ge=0, description="File size in bytes")
    signature: Optional[str] = Field(None, description="Code signature (Authenticode/GPG)")

    @validator("url")
    def validate_https(cls, v: str) -> str:  # noqa: N805
        if not v.startswith("https://"):
            raise ValueError("File URL must use HTTPS")
        return v

    @validator("sha512")
    def validate_sha512(cls, v: str) -> str:  # noqa: N805
        if not re.match(r"^[a-f0-9]{128}$", v):
            raise ValueError("SHA-512 must be 128 hex characters")
        return v


class UpdateManifest(BaseModel):
    """Complete manifest for a single release version."""
    version: str = Field(..., description="Semantic version (e.g., 1.2.3)")
    channel: str = Field(..., description="Update channel: stable | beta | alpha")
    release_date: datetime = Field(..., description="ISO 8601 release timestamp")
    release_notes: str = Field(..., description="Markdown-formatted release notes")
    min_upgradable_version: str = Field(..., description="Minimum version that can upgrade to this")
    files: Dict[str, FileMeta] = Field(..., description="Platform-keyed file metadata")
    components: Dict[str, str] = Field(default_factory=dict, description="Component versions (future use)")

    @validator("version")
    def validate_semver(cls, v: str) -> str:  # noqa: N805
        if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", v):
            raise ValueError("Version must be semantic version")
        return v

    @validator("channel")
    def validate_channel(cls, v: str) -> str:  # noqa: N805
        if v not in ("stable", "beta", "alpha"):
            raise ValueError("Channel must be stable, beta, or alpha")
        return v
