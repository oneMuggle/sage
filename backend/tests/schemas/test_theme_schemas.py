"""Tests for theme pydantic models (2.x compatible)."""
import pytest
from pydantic import ValidationError

from backend.schemas.theme import ActiveTheme, ThemeCssPayload, ThemePreset

# --- ThemePreset ---

def test_theme_preset_minimal_required_fields():
    """ThemePreset requires only id/name/description."""
    p = ThemePreset(id="ocean", name="theme.presets.ocean.name", description="theme.presets.ocean.desc")
    assert p.id == "ocean"
    assert p.name == "theme.presets.ocean.name"
    assert p.cover is None
    assert p.css is None


def test_theme_preset_full_fields():
    """ThemePreset accepts cover and css as optional."""
    p = ThemePreset(
        id="light",
        name="n",
        description="d",
        cover="/assets/light.png",
        css=":root { --color-bg: #fff; }",
    )
    assert p.cover == "/assets/light.png"
    assert "--color-bg" in p.css


def test_theme_preset_id_must_match_pattern():
    """ThemePreset.id must be lowercase letters, digits, dashes; 1-32 chars."""
    with pytest.raises(ValidationError):
        ThemePreset(id="Light!", name="n", description="d")  # uppercase + bang rejected
    with pytest.raises(ValidationError):
        ThemePreset(id="a" * 33, name="n", description="d")  # too long
    # Valid edge cases:
    p = ThemePreset(id="a", name="n", description="d")  # 1 char
    assert p.id == "a"
    p2 = ThemePreset(id="my-theme-1", name="n", description="d")
    assert p2.id == "my-theme-1"


# --- ThemeCssPayload ---

def test_theme_css_payload_minimal():
    """ThemeCssPayload requires css string and vars dict."""
    p = ThemeCssPayload(css=":root {}", vars={"--color-bg": "#fff"})
    assert p.css == ":root {}"
    assert p.vars == {"--color-bg": "#fff"}


def test_theme_css_payload_empty_vars_allowed():
    """ThemeCssPayload.vars can be empty dict."""
    p = ThemeCssPayload(css="", vars={})
    assert p.vars == {}


# --- ActiveTheme ---

def test_active_theme_minimal():
    """ActiveTheme requires only presetId."""
    a = ActiveTheme(presetId="dark")
    assert a.presetId == "dark"
    assert a.customCss is None


def test_active_theme_with_custom_css():
    """ActiveTheme accepts customCss override."""
    a = ActiveTheme(presetId="ocean", customCss=":root { --color-bg: #001f3f; }")
    assert a.customCss.startswith(":root")
