"""Validated, side-effect-free model catalog value contracts."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr
from typing_extensions import Annotated  # py38: typing.Annotated 是 3.9+


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


NonblankString = Annotated[StrictStr, AfterValidator(_nonblank)]
PositiveInteger = Annotated[int, Field(strict=True, gt=0)]
NonnegativeInteger = Annotated[int, Field(strict=True, ge=0)]
UnitPrice = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class CatalogValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


class ModelKey(CatalogValue):
    """Exact provider/model identity; no case or quantization normalization."""

    provider: NonblankString
    model_id: NonblankString


class EndpointKey(CatalogValue):
    """The same model ID on different endpoints is a distinct identity."""

    endpoint_id: NonblankString
    model_id: NonblankString


class Price(CatalogValue):
    """USD per million tokens. Pydantic serializes Decimal as JSON strings."""

    input_per_million: Optional[UnitPrice] = None
    output_per_million: Optional[UnitPrice] = None
    currency: Literal["USD"] = "USD"


class ContextLimits(CatalogValue):
    native: Optional[PositiveInteger] = None
    service: Optional[PositiveInteger] = None


class LayerValues(CatalogValue):
    limits: ContextLimits
    price: Price
    source: NonblankString
    revision: NonnegativeInteger


def _utc_timestamp(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value):
        raise ValueError("timestamp must be UTC RFC3339 ending in Z")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


UtcTimestamp = Annotated[StrictStr, AfterValidator(_utc_timestamp)]


class CandidateModel(CatalogValue):
    """Source-only candidate; endpoint credentials are deliberately not accepted."""

    model_key: ModelKey
    native: Optional[PositiveInteger] = None
    price: Price = Field(default_factory=Price)
    capabilities: Optional[Dict[str, bool]] = None
    architecture: Optional[NonblankString] = None
    quantization: Optional[NonblankString] = None
    source: NonblankString
    source_updated_at: Optional[UtcTimestamp] = None
    pricing_scope: NonblankString


class EndpointPatch(CatalogValue):
    native: Optional[PositiveInteger] = None
    service: Optional[PositiveInteger] = None
    price: Price = Field(default_factory=Price)
    capabilities: Optional[Dict[str, bool]] = None
    architecture: Optional[NonblankString] = None
    quantization: Optional[NonblankString] = None


class OverrideRecord(CatalogValue):
    patch: EndpointPatch = Field(default_factory=EndpointPatch)
    revision: NonnegativeInteger = 0


class ProbeRecord(CatalogValue):
    patch: EndpointPatch
    adapter: NonblankString
    status: Literal["success", "unsupported", "error"]
    observed_at: str
    error: Optional[str] = None
    base_url: Optional[str] = None  # endpoint URL at probe time; enables staleness detection


class SnapshotDiff(CatalogValue):
    id: str
    base_revision: NonnegativeInteger
    before: Optional[CandidateModel]
    after: CandidateModel
    candidate: CandidateModel
    clear_fields: List[str]
    classification: Literal["new", "updated", "conflict", "unchanged"]
    status: Literal["pending", "applied", "ignored"]


class EffectiveModel(CatalogValue):
    limits: ContextLimits
    price: Price
    provenance: Dict[str, str]
    revision: NonnegativeInteger = 0
