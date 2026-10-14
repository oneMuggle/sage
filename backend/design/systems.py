"""Design system registry — loads and manages DESIGN.md packages."""
from __future__ import annotations

import json
from pathlib import Path

from backend.design.errors import DesignSystemNotFoundError
from backend.design.models import DesignSystem


class DesignSystemRegistry:
    """Load and query design systems from a content directory."""

    def __init__(self, content_dir: Path) -> None:
        self._content_dir = content_dir
        self._systems_dir = content_dir / "systems"
        self._cache: dict[str, DesignSystem] = {}

    def list_systems(self) -> list[DesignSystem]:
        """List all available design systems."""
        if not self._systems_dir.exists():
            return []
        systems: list[DesignSystem] = []
        for system_dir in sorted(self._systems_dir.iterdir()):
            if system_dir.is_dir() and (system_dir / "manifest.json").exists():
                systems.append(self._load_system(system_dir))
        return systems

    def get_system(self, system_id: str) -> DesignSystem:
        """Get a design system by ID."""
        if system_id in self._cache:
            return self._cache[system_id]

        not_found = DesignSystemNotFoundError(
            f"Design system '{system_id}' not found"
        )
        if not self._systems_dir.exists():
            raise not_found
        if system_id != Path(system_id).name or system_id in (
            "", ".", "..",
        ):
            raise not_found

        system_dir = self._systems_dir / system_id
        if not system_dir.exists() or not (system_dir / "manifest.json").exists():
            raise not_found

        system = self._load_system(system_dir)
        self._cache[system_id] = system
        return system

    def search_systems(self, query: str) -> list[DesignSystem]:
        """Search design systems by name, description, or tags."""
        query_lower = query.lower()
        results: list[DesignSystem] = []
        for system in self.list_systems():
            if (
                query_lower in system.name.lower()
                or query_lower in system.description.lower()
                or query_lower in system.category.lower()
                or any(query_lower in tag.lower() for tag in system.tags)
            ):
                results.append(system)
        return results

    def _load_system(self, system_dir: Path) -> DesignSystem:
        """Load a design system from a directory."""
        manifest_path = system_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        design_md_path = system_dir / "DESIGN.md"
        design_md = (
            design_md_path.read_text(encoding="utf-8")
            if design_md_path.exists() else ""
        )

        tokens_css_path = system_dir / "tokens.css"
        tokens_css = (
            tokens_css_path.read_text(encoding="utf-8")
            if tokens_css_path.exists() else ""
        )

        tokens_json_path = system_dir / "design-tokens.json"
        design_tokens: dict = {}
        if tokens_json_path.exists():
            design_tokens = json.loads(
                tokens_json_path.read_text(encoding="utf-8")
            )

        return DesignSystem(
            id=manifest["id"],
            name=manifest["name"],
            category=manifest.get("category", "general"),
            description=manifest.get("description", ""),
            design_md=design_md,
            tokens_css=tokens_css,
            design_tokens=design_tokens,
            tags=manifest.get("tags", []),
        )
