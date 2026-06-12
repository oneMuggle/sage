"""Skill 出站适配器 (PR-7)。

- ``InprocSkillAdapter`` : 将进程内 ``backend.skills.registry.SkillRegistry``
  桥接为 ``SkillPort``,供路由层 / 未来的 ChatService 通过端口注入。
"""

from .inproc import InprocSkillAdapter

__all__ = ["InprocSkillAdapter"]
