"""Pure catalog contracts: exact identity, independent inheritance and arithmetic."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.model_catalog.context import effective_window
from backend.model_catalog.pricing import estimate_basic
from backend.model_catalog.resolver import resolve_layers, resolve_model_key
from backend.model_catalog.schemas import ContextLimits, EndpointKey, LayerValues, ModelKey, Price


def test_fields_inherit_independently_and_keep_sources():
    user = LayerValues(
        limits=ContextLimits(native=32768),
        price=Price(input_per_million="0"), source="user_override", revision=1,
    )
    seed = LayerValues(
        limits=ContextLimits(native=4096, service=8192),
        price=Price(input_per_million="2", output_per_million="8"),
        source="seed", revision=9,
    )
    before = [item.model_dump() for item in [user, seed]]
    result = resolve_layers([user, seed])
    assert result.limits == ContextLimits(native=32768, service=8192)
    assert result.price == Price(input_per_million="0", output_per_million="8")
    assert result.provenance == {
        "limits.native": "user_override", "limits.service": "seed",
        "price.input_per_million": "user_override", "price.output_per_million": "seed",
    }
    assert effective_window(result.limits, True, 128000) == 8192
    assert [item.model_dump() for item in [user, seed]] == before
    assert resolve_layers([seed]).limits.native == 4096
    cleared = LayerValues(limits=ContextLimits(), price=Price(), source="user", revision=2)
    assert resolve_layers([cleared, seed]) == resolve_layers([seed])


def test_empty_layers_have_unknown_values_and_no_sources():
    result = resolve_layers([])
    assert result.limits == ContextLimits()
    assert result.price == Price()
    assert result.provenance == {}
    assert result.revision == 0


def test_identity_and_aliases_are_exact_not_fuzzy():
    key = ModelKey(provider="local", model_id="model:Q4")
    canonical = ModelKey(provider="vendor", model_id="model")
    aliases = {key: canonical}
    assert resolve_model_key(key, aliases) == canonical
    for other in [
        ModelKey(provider="local", model_id="model:Q8"),
        ModelKey(provider="local", model_id="Model:Q4"),
        ModelKey(provider="other", model_id="model:Q4"),
    ]:
        assert resolve_model_key(other, aliases) is other
    assert len({EndpointKey(endpoint_id="one", model_id="model"),
                EndpointKey(endpoint_id="two", model_id="model")}) == 2


@pytest.mark.parametrize(("schema", "field"), [
    (ModelKey, "provider"), (ModelKey, "model_id"),
    (EndpointKey, "endpoint_id"), (EndpointKey, "model_id"),
])
@pytest.mark.parametrize("bad", ["", "  ", True, 12, None])
def test_identity_requires_nonempty_strings(schema, field, bad):
    values = {"model_id": "model"}
    values["provider" if schema is ModelKey else "endpoint_id"] = "owner"
    values[field] = bad
    with pytest.raises(ValidationError):
        schema(**values)


@pytest.mark.parametrize("bad", [True, -1, 1.5, "1", None])
def test_revision_is_a_required_nonnegative_integer(bad):
    with pytest.raises(ValidationError):
        LayerValues(limits=ContextLimits(), price=Price(), source="seed", revision=bad)


@pytest.mark.parametrize("bad", ["", " ", True, None])
def test_source_is_required_and_nonblank(bad):
    with pytest.raises(ValidationError):
        LayerValues(limits=ContextLimits(), price=Price(), source=bad, revision=0)


@pytest.mark.parametrize("field", ["native", "service"])
@pytest.mark.parametrize("bad", [True, False, 0, -1, 1.5, 2.0, "4096", float("nan")])
def test_context_requires_strict_positive_integers(field, bad):
    with pytest.raises(ValidationError):
        ContextLimits(**{field: bad})


@pytest.mark.parametrize("field", ["input_per_million", "output_per_million"])
@pytest.mark.parametrize("bad", [True, False, "-0.01", "NaN", "Infinity", "-Infinity", float("nan")])
def test_price_rejects_invalid_values(field, bad):
    with pytest.raises(ValidationError):
        Price(**{field: bad})


def test_price_and_unknown():
    price = Price(input_per_million="2", output_per_million="8")
    assert estimate_basic(price, 1000, 500) == Decimal("0.006")
    assert estimate_basic(Price(), 1000, 500) is None
    assert estimate_basic(Price(input_per_million="0"), 0, 0) is None
    assert estimate_basic(Price(output_per_million="0"), 0, 0) is None
    assert estimate_basic(Price(input_per_million="0", output_per_million="0"), 1000, 500) == Decimal("0")


def test_price_json_preserves_decimal_strings_and_null():
    price = Price(input_per_million="0.12345678901234567890123456789")
    payload = json.loads(price.model_dump_json())
    assert payload == {"input_per_million": "0.12345678901234567890123456789",
                       "output_per_million": None, "currency": "USD"}
    assert Price.model_validate_json(price.model_dump_json()) == price
    with pytest.raises(ValidationError):
        Price(currency="CNY")


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "100", float("nan")])
@pytest.mark.parametrize("position", [0, 1])
def test_tokens_are_nonnegative_integers_even_if_price_unknown(bad, position):
    tokens = [0, 0]
    tokens[position] = bad
    with pytest.raises(ValueError, match="token counts"):
        estimate_basic(Price(), *tokens)


@pytest.mark.parametrize(("limits", "automatic", "fixed", "expected"), [
    (ContextLimits(), True, 128000, 4096),
    (ContextLimits(), False, 128000, 128000),
    (ContextLimits(native=32768), True, 1024, 32768),
    (ContextLimits(service=8192), True, 128000, 8192),
    (ContextLimits(native=32768, service=8192), True, 128000, 8192),
    (ContextLimits(native=32768, service=8192), False, 4096, 4096),
    (ContextLimits(native=32768, service=8192), False, 128000, 8192),
])
def test_effective_window(limits, automatic, fixed, expected):
    assert effective_window(limits, automatic, fixed) == expected


@pytest.mark.parametrize("bad", [True, False, 0, -1, 2.0, "4096", float("nan")])
def test_fixed_window_requires_positive_integer(bad):
    with pytest.raises(ValueError, match="fixed context window"):
        effective_window(ContextLimits(), False, bad)


@pytest.mark.parametrize("bad", [0, 1, "true", None])
def test_automatic_requires_boolean(bad):
    with pytest.raises(ValueError, match="automatic"):
        effective_window(ContextLimits(), bad, 4096)
