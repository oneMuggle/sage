"""Offline component packages for Sage (``.sagepkg``).

Public surface intentionally stays small: the CLI and Electron IPC both use
``ComponentService``, while the dataclasses carry the on-disk schema.
"""

from __future__ import annotations

from .errors import ComponentError
from .models import (
    ComponentFile,
    ComponentManifest,
    InstalledComponent,
    PackageScanResult,
)

__all__ = [
    "ComponentError",
    "ComponentFile",
    "ComponentManifest",
    "InstalledComponent",
    "PackageScanResult",
]
