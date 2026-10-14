"""Template registry — loads SKILL.md templates for design generation."""
from __future__ import annotations

import re
from pathlib import Path

from backend.design.errors import DesignTemplateNotFoundError
from backend.design.models import DesignTemplate


def _parse_skill_md(content: str) -> dict:
    """Parse YAML frontmatter from SKILL.md."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return {
            "skill_md": content,
            "name": "",
            "kind": "prototype",
            "description": "",
            "design_system_required": False,
        }

    frontmatter_str = match.group(1)
    body = match.group(2)

    fm: dict = {}
    for line in frontmatter_str.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value.lower() == "true":
                fm[key] = True
            elif value.lower() == "false":
                fm[key] = False
            else:
                fm[key] = value

    fm["skill_md"] = f"---\n{frontmatter_str}\n---\n{body}"
    return fm


class DesignTemplateRegistry:
    """Load and query design templates from a content directory."""

    def __init__(self, content_dir: Path) -> None:
        self._content_dir = content_dir
        self._templates_dir = content_dir / "templates"
        self._cache: dict[str, DesignTemplate] = {}

    def list_templates(self) -> list[DesignTemplate]:
        """List all available templates."""
        if not self._templates_dir.exists():
            return []
        templates: list[DesignTemplate] = []
        for kind_dir in sorted(self._templates_dir.iterdir()):
            if not kind_dir.is_dir():
                continue
            for template_dir in sorted(kind_dir.iterdir()):
                if (
                    template_dir.is_dir()
                    and (template_dir / "SKILL.md").exists()
                ):
                    templates.append(
                        self._load_template(template_dir, kind_dir.name)
                    )
        return templates

    def list_templates_by_kind(self, kind: str) -> list[DesignTemplate]:
        """List templates filtered by kind (prototype or deck)."""
        return [t for t in self.list_templates() if t.kind == kind]

    def get_template(self, template_id: str) -> DesignTemplate:
        """Get a template by ID."""
        if template_id in self._cache:
            return self._cache[template_id]

        not_found = DesignTemplateNotFoundError(
            f"Template '{template_id}' not found"
        )
        if not self._templates_dir.exists():
            raise not_found
        if template_id != Path(template_id).name or template_id in (
            "", ".", "..",
        ):
            raise not_found

        for kind_dir in self._templates_dir.iterdir():
            if not kind_dir.is_dir():
                continue
            template_dir = kind_dir / template_id
            if (
                template_dir.is_dir()
                and (template_dir / "SKILL.md").exists()
            ):
                template = self._load_template(template_dir, kind_dir.name)
                self._cache[template_id] = template
                return template

        raise not_found

    def _load_template(
        self, template_dir: Path, kind: str,
    ) -> DesignTemplate:
        """Load a template from a directory."""
        skill_content = (template_dir / "SKILL.md").read_text(
            encoding="utf-8"
        )
        parsed = _parse_skill_md(skill_content)

        example_path = template_dir / "example.html"
        example_html = (
            example_path.read_text(encoding="utf-8")
            if example_path.exists()
            else None
        )

        assets: dict[str, str] = {}
        assets_dir = template_dir / "assets"
        if assets_dir.exists():
            for asset_file in assets_dir.rglob("*"):
                if (
                    asset_file.is_file()
                    and asset_file.suffix in (".css", ".js")
                ):
                    rel_path = str(asset_file.relative_to(template_dir))
                    assets[rel_path] = asset_file.read_text(
                        encoding="utf-8"
                    )

        template_id = parsed.get("name") or template_dir.name

        return DesignTemplate(
            id=template_id,
            name=template_id.replace("-", " ").title(),
            kind=parsed.get("kind", kind),
            description=parsed.get("description", ""),
            skill_md=parsed["skill_md"],
            example_html=example_html,
            assets=assets,
            design_system_required=parsed.get(
                "design_system_required", False,
            ),
        )
