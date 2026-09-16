from typing import List, Mapping

"""Resolve caller-filtered layers; this module does not select price scopes."""


from .schemas import ContextLimits, EffectiveModel, LayerValues, ModelKey, Price

_FIELDS = (
    ("limits", "native"),
    ("limits", "service"),
    ("price", "input_per_million"),
    ("price", "output_per_million"),
)


def resolve_model_key(key: ModelKey, aliases: Mapping[ModelKey, ModelKey]) -> ModelKey:
    """Resolve one explicitly declared alias, without fuzzy or recursive lookup."""
    return aliases.get(key, key)


def resolve_layers(layers: List[LayerValues]) -> EffectiveModel:
    """First non-null value wins per field; list order, not revision, is priority.

    The repository must filter identity and quotation scope before calling.
    Provenance uses dotted field paths and the winning layer's source.
    """
    values = {}
    provenance = {}
    for group, field in _FIELDS:
        for layer in layers:
            value = getattr(getattr(layer, group), field)
            if value is not None:
                values[field] = value
                provenance[f"{group}.{field}"] = layer.source
                break
    revision = next(
        (layer.revision for layer in layers if layer.source == "user_override"),
        0,
    )
    return EffectiveModel(
        limits=ContextLimits(native=values.get("native"), service=values.get("service")),
        price=Price(
            input_per_million=values.get("input_per_million"),
            output_per_million=values.get("output_per_million"),
        ),
        provenance=provenance,
        revision=revision,
    )
