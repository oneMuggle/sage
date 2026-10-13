# backend/design/design_studio.py
"""Top-level design studio orchestrator."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.data.design_repo import DesignRepo
from backend.design.errors import DesignProjectNotFoundError
from backend.design.generator import DesignGenerator
from backend.design.models import DesignArtifact, DesignProject
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry


class DesignStudio:
    """Orchestrate design project lifecycle."""

    def __init__(
        self,
        repo: DesignRepo,
        generator: DesignGenerator,
        systems: DesignSystemRegistry,
        templates: DesignTemplateRegistry,
        workspace_dir: Path,
    ) -> None:
        self._repo = repo
        self._generator = generator
        self._systems = systems
        self._templates = templates
        self._workspace = workspace_dir

    def create_project(
        self,
        name: str,
        kind: str,
        system_id: str,
        template_id: str,
        brief: str,
    ) -> DesignProject:
        """Create a new design project."""
        self._systems.get_system(system_id)
        self._templates.get_template(template_id)

        now = datetime.now(timezone.utc)  # noqa: UP017
        return self._repo.create_project(
            id=str(uuid.uuid4()),
            name=name,
            kind=kind,
            system_id=system_id,
            template_id=template_id,
            brief=brief,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> DesignProject:
        """Get a project by ID."""
        return self._repo.get_project(project_id)

    def list_projects(
        self, kind: Optional[str] = None,
    ) -> list[DesignProject]:
        """List projects, optionally filtered by kind."""
        return self._repo.list_projects(kind=kind)

    def delete_project(self, project_id: str) -> None:
        """Delete a project."""
        self._repo.delete_project(project_id)

    async def generate(
        self, project_id: str, brief: Optional[str] = None,
    ) -> DesignArtifact:
        """Generate an artifact for a project, appending a new version."""
        project = self._repo.get_project(project_id)
        system = self._systems.get_system(project.system_id)
        template = self._templates.get_template(project.template_id)

        self._repo.update_project_status(project_id, "generating")

        try:
            use_brief = brief or project.brief
            result = await self._generator.generate(
                system, template, use_brief,
            )

            latest = self._repo.get_latest_artifact(project_id)
            new_version = latest.version + 1 if latest else 1
            artifact_id = str(uuid.uuid4())
            file_path = str(
                self._workspace / "design" / project_id
                / f"v{new_version}.html"
            )
            now = datetime.now(timezone.utc)  # noqa: UP017

            artifact = self._repo.create_artifact(
                id=artifact_id,
                project_id=project_id,
                version=new_version,
                html_content=result.bundled_html,
                title=result.parsed.title,
                file_path=file_path,
                kind="html",
                export_formats=["html"],
                source_prompt=result.source_prompt,
                created_at=now,
            )

            self._repo.update_project_status(project_id, "complete")
            return artifact

        except Exception:
            self._repo.update_project_status(project_id, "error")
            raise

    async def iterate(
        self, project_id: str, feedback: str,
    ) -> DesignArtifact:
        """Iterate on the latest artifact with user feedback."""
        project = self._repo.get_project(project_id)
        latest = self._repo.get_latest_artifact(project_id)
        if latest is None:
            raise DesignProjectNotFoundError(
                f"No artifacts for project {project_id}"
            )

        system = self._systems.get_system(project.system_id)
        template = self._templates.get_template(project.template_id)

        self._repo.update_project_status(project_id, "generating")

        try:
            result = await self._generator.generate(
                system, template, project.brief,
                iteration_context={
                    "current_html": latest.html_content,
                    "user_feedback": feedback,
                },
            )

            new_version = latest.version + 1
            artifact_id = str(uuid.uuid4())
            file_path = str(
                self._workspace / "design" / project_id
                / f"v{new_version}.html"
            )
            now = datetime.now(timezone.utc)  # noqa: UP017

            artifact = self._repo.create_artifact(
                id=artifact_id,
                project_id=project_id,
                version=new_version,
                html_content=result.bundled_html,
                title=result.parsed.title,
                file_path=file_path,
                kind="html",
                export_formats=["html"],
                source_prompt=result.source_prompt,
                created_at=now,
            )

            self._repo.update_project_status(project_id, "complete")
            return artifact

        except Exception:
            self._repo.update_project_status(project_id, "error")
            raise
