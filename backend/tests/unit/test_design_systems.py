"""Tests for DesignSystemRegistry."""
from __future__ import annotations

import json

import pytest

from backend.design.errors import DesignSystemNotFoundError
from backend.design.systems import DesignSystemRegistry


class TestDesignSystemRegistry:
    @pytest.fixture()
    def content_dir(self, tmp_path):
        """Create a minimal content directory with one design system."""
        systems_dir = tmp_path / "systems" / "test-system"
        systems_dir.mkdir(parents=True)

        (systems_dir / "DESIGN.md").write_text(
            "# Test System\n\nA test design system."
        )
        (systems_dir / "tokens.css").write_text(
            ":root { --bg: #fff; --fg: #000; }"
        )
        (systems_dir / "manifest.json").write_text(json.dumps({
            "id": "test-system",
            "name": "Test System",
            "category": "general",
            "description": "A test design system for unit tests",
            "tags": ["test", "minimal"],
        }))

        return tmp_path

    def test_list_systems(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        systems = registry.list_systems()
        assert len(systems) == 1
        assert systems[0].id == "test-system"
        assert systems[0].name == "Test System"

    def test_get_system(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        system = registry.get_system("test-system")
        assert system.id == "test-system"
        assert "Test System" in system.design_md
        assert "--bg: #fff" in system.tokens_css

    def test_get_system_not_found(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        with pytest.raises(DesignSystemNotFoundError):
            registry.get_system("nonexistent")

    def test_search_systems(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        results = registry.search_systems("test")
        assert len(results) == 1

    def test_search_systems_no_match(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        results = registry.search_systems("quantum")
        assert len(results) == 0

    def test_get_system_includes_tags(self, content_dir):
        registry = DesignSystemRegistry(content_dir)
        system = registry.get_system("test-system")
        assert "test" in system.tags
        assert "minimal" in system.tags

    def test_get_system_missing_content_dir(self, tmp_path):
        """A missing systems/ dir raises the domain error, not FileNotFoundError."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        registry = DesignSystemRegistry(empty_dir)
        with pytest.raises(DesignSystemNotFoundError):
            registry.get_system("test-system")

    @pytest.mark.parametrize(
        "system_id", ["../secret", "../../OUTSIDE", "..", ".", "", "/etc"],
    )
    def test_get_system_rejects_non_bare_ids(self, content_dir, system_id):
        """Path-traversal and non-bare IDs must never escape the systems tree."""
        registry = DesignSystemRegistry(content_dir)
        with pytest.raises(DesignSystemNotFoundError):
            registry.get_system(system_id)
