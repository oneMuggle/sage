# backend/design/design_studio.py
"""Top-level design studio orchestrator."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from backend.data.design_repo import DesignRepo
from backend.design.async_bridge import run_sync
from backend.design.craft_loader import CraftRuleRegistry
from backend.design.errors import (
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateKindMismatchError,
    DesignTemplateNotFoundError,
)
from backend.design.generator import DesignGenerator
from backend.design.lint import DesignLinter
from backend.design.messages_store import IterationMessage, MessageStore
from backend.design.models import (
    DesignArtifact,
    DesignProject,
    DesignSystem,
    DesignTemplate,
)
from backend.design.systems import DesignSystemRegistry
from backend.design.templates import DesignTemplateRegistry
from backend.design.tweaks_store import ProjectTweaks, TweaksStore

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_IDS = ("minimal", "corporate")
_DEFAULT_TEMPLATE_IDS = {
    "deck": ("pitch-deck", "weekly-report"),
    "prototype": ("landing-page", "dashboard", "pricing", "docs-page"),
}


def _derive_project_name(brief: str) -> str:
    """From the brief's first non-empty line, capped at 24 chars."""
    for line in (brief or "").splitlines():
        cleaned = line.strip().lstrip("#-*> ").strip()
        if cleaned:
            return cleaned[:24]
    return "Untitled design"


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
        self._messages = MessageStore(workspace_dir / "design")
        self._tweaks = TweaksStore(workspace_dir / "design")
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

    def _default_system_id(self) -> str:
        """Pick the preferred built-in system, else the first available."""
        available = {s.id for s in self._systems.list_systems()}
        if not available:
            raise DesignSystemNotFoundError("No design systems are available")
        for candidate in _DEFAULT_SYSTEM_IDS:
            if candidate in available:
                return candidate
        return sorted(available)[0]

    def _default_template_id(self, kind: str) -> str:
        """Pick a preferred template for the kind, else the first available."""
        available = [t.id for t in self._templates.list_templates_by_kind(kind)]
        if not available:
            raise DesignTemplateNotFoundError(
                f"No templates are available for kind '{kind}'"
            )
        for candidate in _DEFAULT_TEMPLATE_IDS.get(kind, ()):
            if candidate in available:
                return candidate
        return available[0]

    def create_project(
        self,
        name: Optional[str] = None,
        kind: str = "deck",
        system_id: Optional[str] = None,
        template_id: Optional[str] = None,
        brief: str = "",
    ) -> DesignProject:
        """Create a new design project.

        ``system_id``, ``template_id`` and ``name`` are optional: when
        omitted they are resolved to server-side defaults so the caller can
        create a project from a single brief.
        """
        resolved_system = system_id or self._default_system_id()
        resolved_template = template_id or self._default_template_id(kind)
        resolved_name = (name or "").strip() or _derive_project_name(brief)

        self._systems.get_system(resolved_system)
        self._resolve_template_for_kind(resolved_template, kind)

        now = datetime.now(timezone.utc)  # noqa: UP017
        return self._repo.create_project(
            id=str(uuid.uuid4()),
            name=resolved_name,
            kind=kind,
            system_id=resolved_system,
            template_id=resolved_template,
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

    def list_artifacts(self, project_id: str) -> List[DesignArtifact]:
        """List all artifact versions of a project, oldest first."""
        self._repo.get_project(project_id)
        return self._repo.list_artifacts(project_id)

    def get_artifact(self, artifact_id: str) -> DesignArtifact:
        """Fetch one artifact (including HTML content) by ID."""
        return self._repo.get_artifact(artifact_id)

    def list_messages(self, project_id: str) -> List[IterationMessage]:
        """List persisted iteration messages for a project."""
        self._repo.get_project(project_id)
        return self._messages.list(project_id)

    def get_tweaks(self, project_id: str) -> ProjectTweaks:
        """Read tweaks for a project; returns empty defaults when absent."""
        self._repo.get_project(project_id)
        return self._tweaks.get(project_id) or ProjectTweaks()

    def update_tweaks(
        self,
        project_id: str,
        *,
        accent: Optional[str] = None,
        radius: Optional[float] = None,
        font_size: Optional[float] = None,
        density: Optional[float] = None,
    ) -> ProjectTweaks:
        """Merge partial tweaks into the project's tweaks file."""
        self._repo.get_project(project_id)
        return self._tweaks.update(
            project_id,
            accent=accent,
            radius=radius,
            font_size=font_size,
            density=density,
        )

    def _record_message(
        self,
        project_id: str,
        role: str,
        content: str,
        *,
        artifact_id: Optional[str] = None,
        artifact_version: Optional[int] = None,
    ) -> None:
        """Best-effort message persistence — never fails generation."""
        try:
            self._messages.append(
                project_id, role, content,
                artifact_id=artifact_id,
                artifact_version=artifact_version,
            )
        except Exception:
            logger.warning(
                "Failed to persist design message for project %s",
                project_id,
                exc_info=True,
            )

    def restore_artifact(
        self, project_id: str, artifact_id: str,
    ) -> DesignArtifact:
        """Append a copy of an old artifact as a new version (no LLM call)."""
        self._repo.get_project(project_id)
        source = self._repo.get_artifact(artifact_id)
        if source.project_id != project_id:
            raise DesignProjectNotFoundError(
                f"Artifact {artifact_id} does not belong to project "
                f"{project_id}"
            )
        return self.add_artifact(
            project_id, source.html_content,
            title=source.title, kind=source.kind,
        )

    def add_artifact(
        self,
        project_id: str,
        html_content: str,
        *,
        title: Optional[str] = None,
        kind: str = "html",
        export_formats: Optional[list] = None,
    ) -> DesignArtifact:
        """Append a new artifact version without calling the LLM.

        Used by post-processing steps (chart embedding) that mutate an
        existing artifact's HTML and must keep version history honest.
        """
        project = self._repo.get_project(project_id)
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
                title=title or (latest.title if latest else project.name),
                file_path=file_path,
                kind=kind,
                export_formats=export_formats or ["html"],
                source_prompt=latest.source_prompt if latest else "",
                created_at=now,
            )

        self._repo.update_project_status(project_id, "complete")
        return artifact

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
            self._record_message(
                project_id, "assistant", artifact.title,
                artifact_id=artifact.id,
                artifact_version=artifact.version,
            )
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
        self._record_message(project_id, "user", feedback)

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
            self._record_message(
                project_id, "assistant", artifact.title,
                artifact_id=artifact.id,
                artifact_version=artifact.version,
            )
            return artifact

        except asyncio.CancelledError:
            self._repo.update_project_status(project_id, "error")
            raise
        except Exception:
            self._repo.update_project_status(project_id, "error")
            raise
