"""Skill 出站适配器 (PR-7)。

- ``InprocSkillAdapter`` : 将进程内 ``backend.skills.registry.SkillRegistry``
  桥接为 ``SkillPort``,供路由层 / 未来的 ChatService 通过端口注入。
- ``PersonaLoader`` / ``PersonaManifest`` : Persona 声明式 Markdown manifest
  加载器 (A5, 来自 OpenWorker), 支持启动扫描 + 热加载。
"""

from .inproc import InprocSkillAdapter
from .persona_loader import (
    PersonaLoader,
    PersonaManifest,
    PersonaManifestError,
    SyncResult,
    load_manifest_file,
    parse_manifest,
)

__all__ = [
    "InprocSkillAdapter",
    "PersonaLoader",
    "PersonaManifest",
    "PersonaManifestError",
    "SyncResult",
    "load_manifest_file",
    "parse_manifest",
]
