"""Design studio exception hierarchy."""

from __future__ import annotations


class DesignError(Exception):
    """Base exception for all design studio errors."""


class DesignSystemNotFoundError(DesignError):
    """Raised when a design system ID is not found in the registry."""


class DesignTemplateNotFoundError(DesignError):
    """Raised when a template ID is not found in the registry."""


class DesignTemplateKindMismatchError(DesignError):
    """Raised when a template's kind does not match the requested project kind."""


class DesignGenerationError(DesignError):
    """Raised when LLM generation fails or produces unparseable output."""


class DesignExportError(DesignError):
    """Raised when export to PDF/PPTX/ZIP fails."""


class DesignProjectNotFoundError(DesignError):
    """Raised when a design project ID is not found."""
