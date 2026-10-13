"""Tests for DesignTemplateRegistry."""
from __future__ import annotations

import pytest

from backend.design.errors import DesignTemplateNotFoundError
from backend.design.templates import DesignTemplateRegistry


class TestDesignTemplateRegistry:
    @pytest.fixture()
    def content_dir(self, tmp_path):
        """Create a minimal content directory with one template."""
        template_dir = tmp_path / "templates" / "prototype" / "test-page"
        template_dir.mkdir(parents=True)

        (template_dir / "SKILL.md").write_text(
            "---\nname: test-page\nkind: prototype\n"
            "description: A test page\n"
            "design_system_required: true\n---\n"
            "# Test Page\nCreate a simple test page."
        )
        (template_dir / "example.html").write_text(
            "<html><body>Example</body></html>"
        )

        return tmp_path

    def test_list_templates(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        templates = registry.list_templates()
        assert len(templates) == 1
        assert templates[0].id == "test-page"
        assert templates[0].kind == "prototype"

    def test_get_template(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        template = registry.get_template("test-page")
        assert template.id == "test-page"
        assert "Test Page" in template.skill_md

    def test_get_template_not_found(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        with pytest.raises(DesignTemplateNotFoundError):
            registry.get_template("nonexistent")

    def test_list_templates_by_kind(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        prototypes = registry.list_templates_by_kind("prototype")
        assert len(prototypes) == 1
        decks = registry.list_templates_by_kind("deck")
        assert len(decks) == 0

    def test_template_has_example_html(self, content_dir):
        registry = DesignTemplateRegistry(content_dir)
        template = registry.get_template("test-page")
        assert template.example_html is not None
        assert "Example" in template.example_html
