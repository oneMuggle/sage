"""Validated, side-effect-free model catalog value contracts."""
from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StrictStr

from backend.compat.win7.pydantic_compat import field_validator

# -- Type aliases (cross-compat with Pydantic v1/v2) ----------------------
# On main (Pydantic v2), these were ``Annotated[T, AfterValidator(...)]``.
# On win7 (Pydantic v1), ``Annotated`` is not in ``typing`` (3.9+) and
# ``AfterValidator`` does not exist.  We use plain types + ``@field_validator``
# on each model so both runtimes validate identically.
NonblankString = StrictStr
PositiveInteger = int
NonnegativeInteger = int
UnitPrice = Decimal
UtcTimestamp = StrictStr


def _reject_bool(v: object) -> object:
    """Pydantic v1 accepts ``bool`` for ``int`` fields (bool is an int subclass).
    Pydantic v2's ``strict=True`` rejects it.  This helper bridges the gap so
    both runtimes behave identically."""
    if isinstance(v, bool):
        raise ValueError("value must not be a bool")
    return v


def _reject_bool_and_float(v: object) -> object:
    """Pydantic v1's ``strict=True`` on int fields accepts floats (truncates them)
    and strings (coerces them).  Pydantic v2 rejects both.  This helper bridges
    the gap so both runtimes validate identically."""
    if isinstance(v, bool):
        raise ValueError("value must not be a bool")
    if isinstance(v, float):
        raise ValueError("value must be an integer, not a float")
    if isinstance(v, str):
        raise ValueError("value must be an integer, not a string")
    return v


class CatalogValue(BaseModel):
    # v1 honors all of {extra, allow_mutation, json_encoders}.
    # v2 honors only extra (others emit deprecation warnings); the
    # explicit __hash__/__eq__ below cover v2 hashability since
    # frozen=True is v2-only and ignored here.
    class Config:
        extra = "forbid"
        allow_mutation = False
        json_encoders = {Decimal: str}

    def __hash__(self) -> int:
        """Make frozen models hashable (required for use as dict keys / in sets).
        Pydantic v2's ``frozen=True`` does this automatically; Pydantic v1 does not."""
        return hash(tuple(self.__dict__.get(k) for k in self.__fields__))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CatalogValue):
            return NotImplemented
        return type(self) is type(other) and self.__dict__ == other.__dict__


class ModelKey(CatalogValue):
    """Exact provider/model identity; no case or quantization normalization."""

    provider: NonblankString
    model_id: NonblankString

    @field_validator("provider", "model_id")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("value must not be blank")
        return v


class EndpointKey(CatalogValue):
    """The same model ID on different endpoints is a distinct identity."""

    endpoint_id: NonblankString
    model_id: NonblankString

    @field_validator("endpoint_id", "model_id")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("value must not be blank")
        return v


class Price(CatalogValue):
    """USD per million tokens. Pydantic serializes Decimal as JSON strings."""

    input_per_million: Optional[UnitPrice] = Field(None, ge=0)
    output_per_million: Optional[UnitPrice] = Field(None, ge=0)
    currency: Literal["USD"] = "USD"

    @field_validator("input_per_million", "output_per_million", mode="before")
    @classmethod
    def _no_bool_price(cls, v: object) -> object:
        if isinstance(v, bool):
            raise ValueError("value must not be a bool")
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise ValueError("value must be a finite number")
        return v


class ContextLimits(CatalogValue):
    native: Optional[PositiveInteger] = Field(None, strict=True, gt=0)
    service: Optional[PositiveInteger] = Field(None, strict=True, gt=0)

    @field_validator("native", "service", mode="before")
    @classmethod
    def _no_bool(cls, v: object) -> object:
        return _reject_bool_and_float(v)


class LayerValues(CatalogValue):
    limits: ContextLimits
    price: Price
    source: NonblankString
    revision: NonnegativeInteger = Field(..., strict=True, ge=0)

    @field_validator("source")
    @classmethod
    def _nonblank_source(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("value must not be blank")
        return v

    @field_validator("revision", mode="before")
    @classmethod
    def _no_bool_revision(cls, v: object) -> object:
        return _reject_bool_and_float(v)


def _validate_utc_timestamp(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value):
        raise ValueError("timestamp must be UTC RFC3339 ending in Z")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


class CandidateModel(CatalogValue):
    """Source-only candidate; endpoint credentials are deliberately not accepted."""

    model_key: ModelKey
    native: Optional[PositiveInteger] = Field(None, strict=True, gt=0)
    price: Price = Field(default_factory=Price)
    capabilities: Optional[Dict[str, bool]] = None
    architecture: Optional[NonblankString] = None
    quantization: Optional[NonblankString] = None
    source: NonblankString
    source_updated_at: Optional[UtcTimestamp] = None
    pricing_scope: NonblankString

    @field_validator("source", "pricing_scope")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("value must not be blank")
        return v

    @field_validator("architecture", "quantization")
    @classmethod
    def _nonblank_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not isinstance(v, str) or not v.strip()):
            raise ValueError("value must not be blank")
        return v

    @field_validator("source_updated_at")
    @classmethod
    def _validate_timestamp(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_utc_timestamp(v)
        return v

    @field_validator("native", mode="before")
    @classmethod
    def _no_bool_native(cls, v: object) -> object:
        return _reject_bool_and_float(v)


class EndpointPatch(CatalogValue):
    native: Optional[PositiveInteger] = Field(None, strict=True, gt=0)
    service: Optional[PositiveInteger] = Field(None, strict=True, gt=0)
    price: Price = Field(default_factory=Price)
    capabilities: Optional[Dict[str, bool]] = None
    architecture: Optional[NonblankString] = None
    quantization: Optional[NonblankString] = None

    @field_validator("architecture", "quantization")
    @classmethod
    def _nonblank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not isinstance(v, str) or not v.strip()):
            raise ValueError("value must not be blank")
        return v

    @field_validator("native", "service", mode="before")
    @classmethod
    def _no_bool_int(cls, v: object) -> object:
        return _reject_bool_and_float(v)


class OverrideRecord(CatalogValue):
    patch: EndpointPatch = Field(default_factory=EndpointPatch)
    revision: NonnegativeInteger = Field(0, strict=True, ge=0)

    @field_validator("revision", mode="before")
    @classmethod
    def _no_bool_revision(cls, v: object) -> object:
        return _reject_bool_and_float(v)


class ProbeRecord(CatalogValue):
    patch: EndpointPatch
    adapter: NonblankString
    status: Literal["success", "unsupported", "error"]
    observed_at: str
    error: Optional[str] = None
    base_url: Optional[str] = None  # endpoint URL at probe time; enables staleness detection

    @field_validator("adapter")
    @classmethod
    def _nonblank_adapter(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("value must not be blank")
        return v


class SnapshotDiff(CatalogValue):
    id: NonblankString
    base_revision: NonnegativeInteger = Field(..., strict=True, ge=0)
    before: Optional[CandidateModel]
    after: CandidateModel
    candidate: CandidateModel
    clear_fields: List[str]
    classification: Literal["new", "updated", "conflict", "unchanged"]
    status: Literal["pending", "applied", "ignored"]

    @field_validator("id")
    @classmethod
    def _nonblank_id(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("value must not be blank")
        return v

    @field_validator("base_revision", mode="before")
    @classmethod
    def _no_bool_base_rev(cls, v: object) -> object:
        return _reject_bool_and_float(v)


class EffectiveModel(CatalogValue):
    limits: ContextLimits
    price: Price
    provenance: Dict[str, str]
    revision: NonnegativeInteger = Field(0, strict=True, ge=0)

    @field_validator("revision", mode="before")
    @classmethod
    def _no_bool_revision(cls, v: object) -> object:
        return _reject_bool_and_float(v)
