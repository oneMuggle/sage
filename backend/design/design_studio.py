# backend/design/design_studio.py
"""Top-level design studio orchestrator."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.data.design_repo import DesignRepo
from backend.design.async_bridge import run_sync
from backend.design.craft_loader import CraftRuleRegistry
from backend.design.errors import (
    DesignProjectNotFoundError,
    DesignTemplateKindMismatchError,
)
from backend.design.generator import DesignGenerator
from backend.design.lint import DesignLinter
from backend.design.models import (
    DesignArtifact,
    DesignProject,
    DesignSystem,
    DesignTemplate,
)
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry

logger = logging.getLogger(__name__)


class DesignStudio:
    """Orchestrate design project lifecycle."""

    def __init__(
        self,
        repo: DesignRepo,
        generator: DesignGenerator,
        systems: DesignSystemRegistry,
        templates: DesignTemplateRegistry,
        workspace_dir: Path,
        craft_rules: Optional[CraftRuleRegistry] = None,
        lint_retry: bool = True,
    ) -> None:
        self._repo = repo
        self._generator = generator
        self._systems = systems
        self._templates = templates
        self._workspace = workspace_dir
        self._craft_rules = craft_rules
        self._lint_retry = lint_retry
        self._version_lock = threading.Lock()

    def _craft_for(self, template: DesignTemplate) -> Optional[list]:
        """Craft rules applicable to a template, or None when no registry."""
        if self._craft_rules is None:
            return None
        return self._craft_rules.rules_for_kind(template.kind)

    def _resolve_template_for_kind(
        self, template_id: str, kind: str,
    ) -> DesignTemplate:
        """Resolve a template and assert its kind matches the requested kind.

        The check is repeated at every resolution point (create and generate)
        because the project row may predate the template, and a template's
        frontmatter may be edited on disk after a project was created.
        """
        template = self._templates.get_template(template_id)
        if template.kind != kind:
            raise DesignTemplateKindMismatchError(
                f"Template '{template_id}' has kind '{template.kind}', "
                f"but kind '{kind}' was requested. Pick a template whose "
                f"kind matches, or change kind to '{template.kind}'."
            )
        return template

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
        self._resolve_template_for_kind(template_id, kind)

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

    def list_systems(self) -> list[DesignSystem]:
        """List all available design systems."""
        return self._systems.list_systems()

    def list_templates(
        self, kind: Optional[str] = None,
    ) -> list[DesignTemplate]:
        """List available design templates, optionally filtered by kind."""
        if kind:
            return self._templates.list_templates_by_kind(kind)
        return self._templates.list_templates()

    def get_latest_artifact(self, project_id: str) -> Optional[DesignArtifact]:
        """Return the newest artifact of a project, or None when none exist."""
        return self._repo.get_latest_artifact(project_id)

    def delete_project(self, project_id: str) -> None:
        """Delete a project."""
        self._repo.delete_project(project_id)

    async def _apply_lint(
        self,
        html: str,
        *,
        system: DesignSystem,
        template: DesignTemplate,
        project_id: str,
        brief: Optional[str],
        base_context: Optional[dict] = None,
        label: str = "generate",
    ) -> str:
        """Lint generated HTML, auto-fix safe issues, and retry once on P0.

        The retry is skipped when ``lint_retry`` is disabled or when the
        first pass is already clean. On retry the lint feedback is appended
        to the iteration context so the model can address the specific
        anti-patterns instead of regenerating blindly.
        """
        linter = DesignLinter()
        report = linter.lint(html)

        if not report.ok:
            logger.info(
                "Design lint found %d error(s), %d warning(s) for project %s (%s)",
                report.error_count,
                report.warning_count,
                project_id,
                label,
            )
            html = linter.auto_fix(html, report.issues)
            report = linter.lint(html)

        if self._lint_retry and not report.ok:
            feedback = linter.generate_feedback(report)
            context = dict(base_context or {})
            prior_feedback = context.get("user_feedback")
            context["current_html"] = html
            context["user_feedback"] = (
                f"{prior_feedback}\n\n{feedback}"
                if prior_feedback else feedback
            )
            logger.info(
                "Retrying design generation with lint feedback for project %s (%s)",
                project_id,
                label,
            )
            caller_loop = asyncio.get_event_loop()
            retry_result = await caller_loop.run_in_executor(
                None,
                lambda: run_sync(
                    self._generator.generate(
                        system, template, brief or "",
                        iteration_context=context,
                        craft_rules=self._craft_for(template),
                    ),
                ),
            )
            retry_html = retry_result.bundled_html
            retry_report = linter.lint(retry_html)
            if retry_report.error_count < report.error_count:
                retry_html = linter.auto_fix(retry_html, retry_report.issues)
                retry_report = linter.lint(retry_html)
                if retry_report.error_count < report.error_count:
                    html, report = retry_html, retry_report

        if report.warning_count > 0:
            logger.debug(
                "Design lint warnings for project %s (%s): %s",
                project_id,
                label,
                report.to_dict(),
            )
        return html

    async def generate(
        self, project_id: str, brief: Optional[str] = None,
    ) -> DesignArtifact:
        """Generate an artifact for a project, appending a new version."""
        project = self._repo.get_project(project_id)
        system = self._systems.get_system(project.system_id)
        template = self._resolve_template_for_kind(
            project.template_id, project.kind,
        )

        self._repo.update_project_status(project_id, "generating")

        try:
            use_brief = brief or project.brief

            # C1: delegate LLM call to bridge loop so the cached
            # httpx.AsyncClient always runs on its owning loop.
            caller_loop = asyncio.get_event_loop()
            result = await caller_loop.run_in_executor(
                None,
                lambda: run_sync(
                    self._generator.generate(
                        system, template, use_brief,
                        craft_rules=self._craft_for(template),
                    ),
                ),
            )

            # C3: yield to let a pending cancellation propagate before
            # the sync artifact write (prevents ghost artifacts).
            await asyncio.sleep(0)

            # M2-4: lint + auto-fix + optional one-shot retry on P0
            html_content = await self._apply_lint(
                result.bundled_html,
                system=system,
                template=template,
                project_id=project_id,
                brief=use_brief,
                label="generate",
            )

            # C2: hold the version lock across read + insert so two
            # concurrent callers cannot compute the same version number.
            with self._version_lock:
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
                    html_content=html_content,
                    title=result.parsed.title,
                    file_path=file_path,
                    kind="html",
                    export_formats=["html"],
                    source_prompt=result.source_prompt,
                    created_at=now,
                )

            self._repo.update_project_status(project_id, "complete")
            return artifact

        except asyncio.CancelledError:
            self._repo.update_project_status(project_id, "error")
            raise
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
        template = self._resolve_template_for_kind(
            project.template_id, project.kind,
        )

        self._repo.update_project_status(project_id, "generating")

        try:
            # C1: delegate LLM call to bridge loop.
            caller_loop = asyncio.get_event_loop()
            result = await caller_loop.run_in_executor(
                None,
                lambda: run_sync(
                    self._generator.generate(
                        system, template, project.brief,
                        iteration_context={
                            "current_html": latest.html_content,
                            "user_feedback": feedback,
                        },
                        craft_rules=self._craft_for(template),
                    ),
                ),
            )

            # C3: yield to let pending cancellation propagate.
            await asyncio.sleep(0)

            # M2-4: lint + auto-fix + optional one-shot retry on P0
            html_content = await self._apply_lint(
                result.bundled_html,
                system=system,
                template=template,
                project_id=project_id,
                brief=project.brief,
                base_context={
                    "current_html": latest.html_content,
                    "user_feedback": feedback,
                },
                label="iterate",
            )

            # C2: re-read latest inside lock for safe version assignment.
            with self._version_lock:
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
                    html_content=html_content,
                    title=result.parsed.title,
                    file_path=file_path,
                    kind="html",
                    export_formats=["html"],
                    source_prompt=result.source_prompt,
                    created_at=now,
                )

            self._repo.update_project_status(project_id, "complete")
            return artifact

        except asyncio.CancelledError:
            self._repo.update_project_status(project_id, "error")
            raise
        except Exception:
            self._repo.update_project_status(project_id, "error")
            raise
