from __future__ import annotations

from backend.design.errors import (
    DesignError,
    DesignExportError,
    DesignGenerationError,
    DesignProjectNotFoundError,
    DesignSystemNotFoundError,
    DesignTemplateNotFoundError,
)


class TestDesignErrors:
    def test_base_error_is_exception(self):
        err = DesignError("test message")
        assert str(err) == "test message"
        assert isinstance(err, Exception)

    def test_system_not_found(self):
        err = DesignSystemNotFoundError("minimal")
        assert isinstance(err, DesignError)
        assert "minimal" in str(err)

    def test_template_not_found(self):
        err = DesignTemplateNotFoundError("landing-page")
        assert isinstance(err, DesignError)

    def test_generation_error(self):
        err = DesignGenerationError("LLM timeout")
        assert isinstance(err, DesignError)

    def test_export_error(self):
        err = DesignExportError("PDF render failed")
        assert isinstance(err, DesignError)

    def test_project_not_found(self):
        err = DesignProjectNotFoundError("proj-123")
        assert isinstance(err, DesignError)
