"""Design studio module — HTML/CSS prototype and presentation generation."""

_PHASE_2_EXPORTS = {
    "DesignStudio": (".design_studio", "DesignStudio"),
    "DesignGenerator": (".generator", "DesignGenerator"),
    "DesignSystemRegistry": (".systems", "DesignSystemRegistry"),
    "DesignTemplateRegistry": (".templates", "DesignTemplateRegistry"),
}


def __getattr__(name: str):
    if name in _PHASE_2_EXPORTS:
        import importlib

        module_name, attr_name = _PHASE_2_EXPORTS[name]
        module = importlib.import_module(module_name, __package__)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
