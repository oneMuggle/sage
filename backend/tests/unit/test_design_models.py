"""Tests for design studio Pydantic models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.design.models import (
    DesignArtifact,
    DesignExportRequest,
    DesignGenerateRequest,
    DesignIterateRequest,
    DesignProject,
    DesignSystem,
    DesignTemplate,
)


class TestDesignSystem:
    def test_valid_system(self):
        system = DesignSystem(
            id="minimal",
            name="Minimal",
            category="general",
            description="A minimal design system",
            design_md="# Minimal\n\nColors: black, white",
            tokens_css=":root { --bg: #fff; --fg: #000; }",
            design_tokens={"bg": {"value": "#fff", "type": "color"}},
            tags=["minimal", "clean"],
        )
        assert system.id == "minimal"
        assert len(system.tags) == 2

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DesignSystem(
                id="x",
                name="x",
                category="x",
                description="x",
                design_md="x",
                tokens_css="x",
                design_tokens={},
                tags=[],
                unknown_field="bad",
            )


class TestDesignTemplate:
    def test_valid_prototype_template(self):
        t = DesignTemplate(
            id="landing-page",
            name="Landing Page",
            kind="prototype",
            description="Product landing page",
            skill_md="# Landing Page\nGenerate a hero section...",
            example_html="<html>...</html>",
            assets={"base.css": "body { margin: 0; }"},
            design_system_required=True,
        )
        assert t.kind == "prototype"
        assert "base.css" in t.assets

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            DesignTemplate(
                id="x",
                name="x",
                kind="invalid_kind",
                description="x",
                skill_md="x",
                assets={},
                design_system_required=False,
            )


class TestDesignProject:
    def test_valid_project(self):
        now = datetime.now(timezone.utc)  # noqa: UP017
        p = DesignProject(
            id="proj-1",
            name="My Landing Page",
            kind="prototype",
            system_id="minimal",
            template_id="landing-page",
            brief="Create a SaaS landing page",
            status="draft",
            created_at=now,
            updated_at=now,
        )
        assert p.status == "draft"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            DesignProject(
                id="x",
                name="x",
                kind="prototype",
                system_id="x",
                template_id="x",
                brief="x",
                status="invalid_status",
                created_at=datetime.now(timezone.utc),  # noqa: UP017
                updated_at=datetime.now(timezone.utc),  # noqa: UP017
            )


class TestDesignArtifact:
    def test_valid_artifact(self):
        now = datetime.now(timezone.utc)  # noqa: UP017
        a = DesignArtifact(
            id="art-1",
            project_id="proj-1",
            version=1,
            html_content="<!DOCTYPE html><html></html>",
            css_injected=":root { --bg: #fff; }",
            title="My Page",
            file_path="design/proj-1/v1.html",
            kind="html",
            export_formats=["html", "pdf"],
            source_prompt="Generate a landing page...",
            created_at=now,
        )
        assert a.version == 1


class TestRequests:
    def test_generate_request(self):
        r = DesignGenerateRequest(
            project_id="proj-1",
            brief="Create a landing page",
            system_id="minimal",
            template_id="landing-page",
        )
        assert r.model_id is None

    def test_iterate_request(self):
        r = DesignIterateRequest(
            project_id="proj-1",
            feedback="Change the button color to blue",
        )
        assert r.feedback.startswith("Change")

    def test_export_request(self):
        r = DesignExportRequest(artifact_id="art-1", format="pdf")
        assert r.format == "pdf"

    def test_export_invalid_format(self):
        with pytest.raises(ValidationError):
            DesignExportRequest(artifact_id="art-1", format="docx")
