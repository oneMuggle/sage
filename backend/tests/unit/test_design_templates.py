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

        # Decoy outside templates/ so traversal has a reachable target:
        # templates/prototype/../../OUTSIDE resolves here without the guard.
        outside = tmp_path / "OUTSIDE"
        outside.mkdir()
        (outside / "SKILL.md").write_text(
            "---\nname: pwned\nkind: prototype\n---\nSECRET\n"
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

    def test_get_template_missing_content_dir(self, tmp_path):
        """A missing templates/ dir raises the domain error, not FileNotFoundError."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        registry = DesignTemplateRegistry(empty_dir)
        with pytest.raises(DesignTemplateNotFoundError):
            registry.get_template("test-page")

    @pytest.mark.parametrize(
        "template_id", ["../secret", "../../OUTSIDE", "..", ".", "", "/etc"],
    )
    def test_get_template_rejects_non_bare_ids(self, content_dir, template_id):
        """Path-traversal and non-bare IDs must never escape the templates tree."""
        registry = DesignTemplateRegistry(content_dir)
        with pytest.raises(DesignTemplateNotFoundError):
            registry.get_template(template_id)

    def test_no_frontmatter_falls_back_to_dir_name(self, content_dir):
        """A SKILL.md with no frontmatter still resolves by directory name."""
        template_dir = content_dir / "templates" / "prototype" / "no-fm"
        template_dir.mkdir(parents=True)
        (template_dir / "SKILL.md").write_text("# No Frontmatter\nBody only.")

        registry = DesignTemplateRegistry(content_dir)
        template = registry.get_template("no-fm")
        assert template.id == "no-fm"
        assert template.name == "No Fm"
        # The listed ID must be resolvable by get_template (round-trip invariant).
        assert registry.get_template(template.id).id == "no-fm"

    def test_assets_collects_css_and_js(self, content_dir):
        """Only .css/.js under assets/ are collected, keyed by relative path."""
        assets_dir = content_dir / "templates" / "prototype" / "test-page" / "assets"
        assets_dir.mkdir()
        (assets_dir / "style.css").write_text(".a { color: red; }")
        (assets_dir / "app.js").write_text("console.log(1);")
        (assets_dir / "logo.png").write_text("not-a-real-png")

        registry = DesignTemplateRegistry(content_dir)
        template = registry.get_template("test-page")
        assert template.assets == {
            "assets/style.css": ".a { color: red; }",
            "assets/app.js": "console.log(1);",
        }
